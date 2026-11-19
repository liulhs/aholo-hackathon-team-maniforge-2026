"""Let a trained state-only policy pick up objects on its own in MuJoCo and count how often it succeeds.

Each trial: the object goes to a random spot of the play area (same sampling as record.py), the
arm starts from the first frame of a random training episode, and the policy drives the arm at
20 Hz from the joint angles and the object's state. Success is the recorder's rule: the object
held 5 cm up for 1 s. No window, no camera images.

Like every recorded episode, a trial starts with the object resting upright where it was put
and the arm clear of it. A draw where the start pose touches the object, or the object moves
while settling, is redrawn (the count is printed), so every model sees the same set of trials.

    source .venv/bin/activate
    python sim/evaluate.py outputs/act_state_all/checkpoints/last/pretrained_model
    python sim/evaluate.py <pretrained_model> --objects labubu --trials 100 --n-action-steps 10
    python sim/evaluate.py <pretrained_model> --temporal-ensemble 0.01   # predict every frame, average overlapping chunks

Writes eval.json (every trial) next to the model unless --out says otherwise.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import mujoco
import numpy as np
import pandas as pd
import torch

import lift_scene as scene
from build_state_dataset import MIN_UPRIGHT, STATE_KEY, with_com_position
from record import FPS, OBJECT_STATE_KEY, REPO, steps_per_frame
from so101_mapping import JOINT_NAMES
from teleop import SimArm

DEFAULT_TRIALS = 50
DEFAULT_MAX_SECONDS = 20.0  # demos take 4-9 s
SETTLE_FRAMES = 10  # the object drops 5 mm onto the table before the policy starts
SETTLED_SHIFT_M = 0.003  # a trial starts only if settling moved the object less than this
SETTLED_UPRIGHT = 0.99
MAX_REDRAWS = 50


@dataclass(frozen=True)
class Trial:
    object_name: str
    x: float
    y: float
    yaw: float
    success: bool
    seconds: float  # when it succeeded, or the time limit
    max_lift_m: float  # highest the object's base got (a tumbling object also raises it a few cm)
    knocked_over_at: float | None  # first time (s) the object leaned past 37 degrees while on the table
    in_air_at_success: bool | None  # at the success moment nothing but the arm touched the object
    tipped: bool  # the object ended up leaning more than 37 degrees
    start_index: int  # which training episode's first frame the arm started from


class Policy:
    """A trained LeRobot policy with its normalisation, called one frame at a time."""

    def __init__(self, path: Path, device: str, n_action_steps: int | None, temporal_ensemble: float | None) -> None:
        from lerobot.policies.act.modeling_act import ACTPolicy, ACTTemporalEnsembler
        from lerobot.policies.factory import make_pre_post_processors

        self.policy = ACTPolicy.from_pretrained(path)
        self.policy.to(device).eval()
        config = self.policy.config
        if temporal_ensemble is not None:
            config.temporal_ensemble_coeff, config.n_action_steps = temporal_ensemble, 1
            self.policy.temporal_ensembler = ACTTemporalEnsembler(temporal_ensemble, config.chunk_size)
        elif n_action_steps is not None:
            if not 1 <= n_action_steps <= config.chunk_size:
                raise SystemExit(f"--n-action-steps must be 1-{config.chunk_size} (the trained chunk size)")
            config.n_action_steps = n_action_steps
        on_device = {"device_processor": {"device": device}}
        self.preprocess, self.postprocess = make_pre_post_processors(
            self.policy.config, pretrained_path=path, preprocessor_overrides=on_device, postprocessor_overrides=on_device
        )

    def reset(self) -> None:
        self.policy.reset()

    def act(self, joint_rad: np.ndarray, object_state: np.ndarray) -> dict[str, float]:
        observation = {
            STATE_KEY: torch.from_numpy(joint_rad.astype(np.float32)),
            OBJECT_STATE_KEY: torch.from_numpy(object_state.astype(np.float32)),
        }
        with torch.inference_mode():
            action = self.postprocess(self.policy.select_action(self.preprocess(observation)))
        return dict(zip(JOINT_NAMES, action.squeeze(0).cpu().numpy().tolist()))


def start_poses(dataset_root: Path) -> np.ndarray:
    """Joint angles at the first frame of every episode of the training dataset."""
    files = sorted((dataset_root / "data").glob("*/*.parquet"))
    if not files:
        raise SystemExit(f"No data in {dataset_root} (needed for the arm's start poses; pass --starts)")
    frames = pd.concat(pd.read_parquet(f, columns=["frame_index", STATE_KEY]) for f in files)
    return np.stack(frames.loc[frames["frame_index"] == 0, STATE_KEY].to_numpy())


def trained_objects(dataset_root: Path) -> list[str]:
    """The objects in a dataset written by build_state_dataset.py."""
    sources = dataset_root / "meta" / "sources.json"
    if not sources.exists():
        raise SystemExit(f"{sources} is missing; name the objects with --objects")
    return list(json.loads(sources.read_text()))


def upright(state: np.ndarray) -> float:
    """z of the object's up axis in the world: 1 standing, 0 on its side."""
    return float(np.cross(state[3:6], state[6:9])[2])


def object_contact_bodies(model: mujoco.MjModel, data: mujoco.MjData) -> set[int]:
    """Ids of the bodies the object touches; 0 is the world (table and floor)."""
    object_body = model.body(scene.OBJECT_BODY).id
    touching = set()
    for contact in data.contact[: data.ncon]:
        pair = (int(model.geom_bodyid[contact.geom1]), int(model.geom_bodyid[contact.geom2]))
        if object_body in pair:
            touching.add(pair[1] if pair[0] == object_body else pair[0])
    return touching


def arm_touches_object(model: mujoco.MjModel, data: mujoco.MjData) -> bool:
    return bool(object_contact_bodies(model, data) - {0})


def set_up_trial(model, data, arm: SimArm, pose: scene.ObjectPose, start: np.ndarray) -> bool:
    """Arm at `start`, object settled at `pose`. False if they touch or the object did not stay put."""
    mujoco.mj_resetData(model, data)
    arm.place(dict(zip(JOINT_NAMES, start.tolist())))
    scene.place_object(model, data, pose)
    if arm_touches_object(model, data):
        return False
    for _ in range(SETTLE_FRAMES * steps_per_frame(model)):
        mujoco.mj_step(model, data)
    state = scene.object_state(model, data)
    settled = np.hypot(state[0] - pose.x, state[1] - pose.y) < SETTLED_SHIFT_M and upright(state) > SETTLED_UPRIGHT
    return settled and not arm_touches_object(model, data)


def observed_object_state(model: mujoco.MjModel, data: mujoco.MjData, position: str) -> np.ndarray:
    """What the policy is given: lift_scene.object_state, with the position replaced by the centre of
    mass when the policy was trained on a dataset built with build_state_dataset.py --object-position com."""
    state = scene.object_state(model, data)
    if position == "com":  # from the current qpos, as the training data was built (data.xipos lags a substep after mj_step)
        state = with_com_position(state[None].astype(np.float64), model.body(scene.OBJECT_BODY).ipos)[0].astype(np.float32)
    return state


def run_trial(model, data, arm: SimArm, policy: Policy, object_name: str, pose: scene.ObjectPose, start_index: int, max_frames: int, position: str = "origin") -> Trial:
    """The policy's attempt from the state set_up_trial left."""
    substeps = steps_per_frame(model)
    policy.reset()
    tracker, max_lift, success, frame = scene.SuccessTracker(), 0.0, False, 0
    knocked_over_at, in_air = None, None
    for frame in range(max_frames):
        joint_rad = np.array([data.qpos[arm.qpos_adr[name]] for name in JOINT_NAMES])
        arm.command(policy.act(joint_rad, observed_object_state(model, data, position)))
        for _ in range(substeps):
            mujoco.mj_step(model, data)
        lift = scene.object_lift_m(model, data)
        max_lift = max(max_lift, lift)
        on_table = 0 in object_contact_bodies(model, data)
        if knocked_over_at is None and on_table and upright(scene.object_state(model, data)) < MIN_UPRIGHT:
            knocked_over_at = (frame + 1) / FPS
        if tracker.update(lift, data.time):
            success, in_air = True, not on_table
            break
    tipped = upright(scene.object_state(model, data)) < MIN_UPRIGHT
    return Trial(object_name, pose.x, pose.y, pose.yaw, success, (frame + 1) / FPS, max_lift, knocked_over_at, in_air, tipped, start_index)


def dataset_object_position(root: Path) -> str:
    """"com" if build_state_dataset.py wrote the dataset with --object-position com, else "origin"."""
    if not root.is_dir():
        raise SystemExit(f"Training dataset {root} not found; cannot tell which object position the policy expects.")
    meta = root / "meta" / "object_position.json"
    return json.loads(meta.read_text())["object_position"] if meta.exists() else "origin"


def evaluate(policy: Policy, objects: list[str], starts: np.ndarray, trials: int, seed: int, max_seconds: float, position: str = "origin") -> list[Trial]:
    results = []
    for object_name in objects:
        model, data = scene.load(object_name)
        arm = SimArm(model, data)
        rng = np.random.default_rng(seed)  # same seed for every object and model: comparable trials
        redraws = 0
        for _ in range(trials):
            for _ in range(MAX_REDRAWS):
                pose, start_index = scene.random_object_pose(rng), int(rng.integers(len(starts)))
                if set_up_trial(model, data, arm, pose, starts[start_index]):
                    break
                redraws += 1
            else:
                raise SystemExit(f"{object_name}: no clear start in {MAX_REDRAWS} draws")
            results.append(run_trial(model, data, arm, policy, object_name, pose, start_index, int(max_seconds * FPS), position))
        done = [t for t in results if t.object_name == object_name]
        wins = [t for t in done if t.success]
        fails = [t for t in done if not t.success]
        seconds = f", median {np.median([t.seconds for t in wins]):.1f} s" if wins else ""
        knocked = [t for t in fails if t.knocked_over_at is not None]
        early = sum(t.knocked_over_at <= 1.0 for t in knocked)
        not_in_air = sum(not t.in_air_at_success for t in wins)
        print(
            f"{object_name}: {len(wins)}/{len(done)} lifted{seconds}"
            + (f" ({not_in_air} still touching the table!)" if not_in_air else "")
            + f"; of {len(fails)} failures, {len(knocked)} knocked it over on the table ({early} within 1 s); "
            f"{redraws} start draws redone",
            flush=True,
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("policy", type=Path, help="a checkpoint's pretrained_model directory")
    parser.add_argument("--objects", nargs="+", default=None, choices=list(scene.OBJECTS), help="default: the objects it was trained on")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS, help="per object")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    parser.add_argument("--n-action-steps", type=int, default=None, help="actions run per prediction (default: as trained)")
    parser.add_argument("--temporal-ensemble", type=float, default=None, metavar="COEFF", help="predict every frame and average overlapping chunks (ACT paper: 0.01)")
    parser.add_argument("--starts", type=Path, default=None, help="dataset to take the arm's start poses from (default: the training dataset; give the same one to compare models)")
    parser.add_argument("--object-position", choices=["auto", "origin", "com"], default="auto",
                        help="position the policy is given: the object's bottom-centre point or its centre of mass (auto: as its training dataset)")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out", type=Path, default=None, help="where to write every trial (default: <policy>/eval.json)")
    args = parser.parse_args()

    train_config = json.loads((args.policy / "train_config.json").read_text())
    train_root = Path(train_config["dataset"]["root"])
    train_root = train_root if train_root.is_absolute() else REPO / train_root
    objects = args.objects or trained_objects(train_root)
    starts = start_poses(args.starts or train_root)
    position = args.object_position
    if position == "auto":
        position = dataset_object_position(train_root)
    policy = Policy(args.policy, args.device, args.n_action_steps, args.temporal_ensemble)
    results = evaluate(policy, objects, starts, args.trials, args.seed, args.max_seconds, position)
    wins = sum(t.success for t in results)
    print(f"Total: {wins}/{len(results)} lifted ({100 * wins / len(results):.0f}%)")
    out = args.out or args.policy / "eval.json"
    config = policy.policy.config
    summary = {
        "policy": str(args.policy),
        "seed": args.seed,
        "starts": str(args.starts or train_root),
        "n_action_steps": config.n_action_steps,
        "temporal_ensemble": config.temporal_ensemble_coeff,
        "object_position": position,
    }
    out.write_text(json.dumps({**summary, "trials": [asdict(t) for t in results]}, indent=2))
    print(f"Trials: {out}")


if __name__ == "__main__":
    main()
