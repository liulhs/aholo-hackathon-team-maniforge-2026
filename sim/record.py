"""Record lift demos of one object: the real SO-101 drives the sim arm, episodes go into a LeRobot dataset.

    source .venv/bin/activate
    mjpython sim/record.py                               # the takeout box, into data/so101_table_lift_takeout_box
    mjpython sim/record.py --object labubu --episodes 40  # another object, stop after 40 saved episodes

Each object gets its own dataset (data/so101_table_lift_<object>); `--object` takes a name
from prep_object.OBJECTS. To switch objects, close the window (or let --episodes end the run)
and start again with another --object. Running the same object again appends to its dataset.

In the MuJoCo window:
    Enter       start recording this episode (move the arm to a start pose first)
    Backspace   throw this episode away and put the object somewhere new

An episode saves itself once the object is held 5 cm up for 1 s, and is thrown away after
--max-seconds. Only successful episodes are kept. Close the window to stop; the dataset is
finalized on exit.

Each frame stores, at FPS: both camera images, the sim joint angles (observation.state) and
the target joint angles read from the real arm (action), all in radians, joint order as in
so101_mapping.JOINT_NAMES. `observation.environment_state` is the object's position, orientation
and size (lift_scene.object_state), so a policy can be trained without the camera images.
`sim.state` holds MuJoCo's full integration state per frame, so an episode replays exactly
(replay.py, and later the browser); meta/sim.json says how. Don't drag the arm or box with the
mouse in the viewer while recording: that force is not recorded.
"""

import argparse
import json
import time
from enum import Enum
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np

import lift_scene as scene
from so101_mapping import JOINT_NAMES, readings_to_joint_rad
from teleop import DEFAULT_ARM_ID, DEFAULT_PORT, SimArm, connect_arm

REPO = Path(__file__).resolve().parent.parent
DATASET_PREFIX = "so101_table_lift"
FPS = 20
DEFAULT_MAX_SECONDS = 40.0
KEY_ENTER, KEY_BACKSPACE = 257, 259
IMAGE_KEYS = {"front": "observation.images.front", "wrist_cam": "observation.images.wrist"}
OBJECT_STATE_KEY = "observation.environment_state"
SIM_STATE_KEY = "sim.state"  # not an "observation.*" key, so policies never see it
SIM_STATE_SPEC = mujoco.mjtState.mjSTATE_INTEGRATION


def steps_per_frame(model: mujoco.MjModel) -> int:
    return max(1, round(1.0 / FPS / model.opt.timestep))


def default_root(object_name: str) -> Path:
    return REPO / "data" / f"{DATASET_PREFIX}_{object_name}"


def repo_id(object_name: str) -> str:
    return f"maniforge/{DATASET_PREFIX}_{object_name}"


def task_text(object_name: str) -> str:
    return f"Pick up the {object_name} and hold it up."


class Phase(Enum):
    READY = "READY - move arm to start pose, press Enter"
    RECORDING = "RECORDING - lift the object 5 cm, hold 1 s"


def features(state_size: int) -> dict:
    joint = {"dtype": "float32", "shape": (len(JOINT_NAMES),), "names": list(JOINT_NAMES)}
    image = {"dtype": "video", "shape": (scene.CAMERA_HEIGHT, scene.CAMERA_WIDTH, 3), "names": ["height", "width", "channels"]}
    sim_state = {"dtype": "float64", "shape": (state_size,), "names": None}
    object_state = {"dtype": "float32", "shape": (scene.OBJECT_STATE_SIZE,), "names": None}
    return {
        "observation.state": joint,
        OBJECT_STATE_KEY: object_state,
        "action": joint,
        SIM_STATE_KEY: sim_state,
        **{key: image for key in IMAGE_KEYS.values()},
    }


def sim_meta(model: mujoco.MjModel, steps_per_frame: int, object_name: str) -> dict:
    """What a replay needs to rebuild each frame from `sim.state` (see replay.py)."""
    object_adr = scene.object_qpos_adr(model)
    return {
        "scene_xml": scene.scene_path(object_name).name,
        "mujoco_version": mujoco.__version__,
        "state_spec": "mjSTATE_INTEGRATION",
        "state_size": mujoco.mj_stateSize(model, SIM_STATE_SPEC),
        "timestep": model.opt.timestep,
        "steps_per_frame": steps_per_frame,
        "nq": model.nq,
        "nv": model.nv,
        "nu": model.nu,
        "object": object_name,
        "object_state": "position xyz (m), rotation matrix columns 1 and 2, bounding-box size xyz (m)",
        "play_area_x_m": list(scene.SPAWN_X_M),
        "play_area_y_m": list(scene.SPAWN_Y_M),
        "object_qpos_slice": [object_adr, object_adr + 7],
        "note": "sim.state at frame t is taken after ctrl is set for frame t, before stepping. "
        "Replay: mj_setState(frame 0), then per frame mj_step steps_per_frame times; ctrl stays as set.",
    }


def open_dataset(root: Path, model: mujoco.MjModel, steps_per_frame: int, object_name: str):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    meta_path = root / "meta" / "sim.json"
    if (root / "meta" / "info.json").exists():
        recorded = json.loads(meta_path.read_text())
        current = sim_meta(model, steps_per_frame, object_name)
        changed = {k for k in ("object", "state_size", "timestep", "steps_per_frame", "nq", "nv") if recorded.get(k) != current[k]}
        if changed:
            raise SystemExit(f"Scene changed since {root} was recorded ({sorted(changed)}); record into a new --root.")
        return LeRobotDataset.resume(repo_id(object_name), root=root)
    root.parent.mkdir(parents=True, exist_ok=True)
    state_size = mujoco.mj_stateSize(model, SIM_STATE_SPEC)
    dataset = LeRobotDataset.create(
        repo_id(object_name), fps=FPS, features=features(state_size), root=root, robot_type="so101_sim", use_videos=True
    )
    meta_path.write_text(json.dumps(sim_meta(model, steps_per_frame, object_name), indent=2))
    scene_xml = scene.scene_path(object_name)
    (root / "meta" / scene_xml.name).write_text(scene_xml.read_text())
    return dataset


class Session:
    """Episode state machine around one MuJoCo scene and one dataset."""

    def __init__(
        self, model, data, dataset, read_target, seed: int, max_seconds: float, object_name: str, target_episodes: int | None = None
    ) -> None:
        self.model, self.data = model, data
        self.task = task_text(object_name)
        self.progress_label = object_name + ("" if target_episodes is None else f"   target {target_episodes}")
        self.arm = SimArm(self.model, self.data)
        self.cameras = scene.Cameras(self.model)
        self.dataset, self.read_target = dataset, read_target
        self.rng = np.random.default_rng(seed)
        self.max_frames = int(max_seconds * FPS)
        self.steps_per_frame = steps_per_frame(self.model)
        self.state_buf = np.empty(mujoco.mj_stateSize(self.model, SIM_STATE_SPEC))
        self.saved = dataset.meta.total_episodes
        self.pending_key: int | None = None
        self.message = ""
        self.new_episode()

    def on_key(self, keycode: int) -> None:
        if keycode in (KEY_ENTER, KEY_BACKSPACE):
            self.pending_key = keycode

    def new_episode(self) -> None:
        self.phase, self.frames, self.success = Phase.READY, 0, scene.SuccessTracker()
        self.arm.place(self.read_target())
        scene.place_object(self.model, self.data, scene.random_object_pose(self.rng))

    def discard(self, why: str) -> None:
        if self.frames:
            self.dataset.clear_episode_buffer()
        self.message = f"discarded: {why}"
        self.new_episode()

    def handle_key(self) -> None:
        key, self.pending_key = self.pending_key, None
        if key == KEY_ENTER and self.phase is Phase.READY:
            self.phase, self.message = Phase.RECORDING, ""
        elif key == KEY_BACKSPACE:
            self.discard("Backspace")

    def tick(self) -> None:
        if self.pending_key is not None:
            self.handle_key()
        target = self.read_target()
        self.arm.command(target)  # sets ctrl only; the state stays this frame's observation
        if self.phase is Phase.RECORDING:
            self.record_frame(target)
        for _ in range(self.steps_per_frame):
            mujoco.mj_step(self.model, self.data)
        if self.phase is Phase.RECORDING:
            self.check_end()

    def record_frame(self, target: dict[str, float]) -> None:
        images = self.cameras.render(self.data)
        mujoco.mj_getState(self.model, self.data, self.state_buf, SIM_STATE_SPEC)
        frame = {
            "observation.state": np.array([self.data.qpos[self.arm.qpos_adr[n]] for n in JOINT_NAMES], dtype=np.float32),
            OBJECT_STATE_KEY: scene.object_state(self.model, self.data),
            "action": np.array([target[n] for n in JOINT_NAMES], dtype=np.float32),
            "task": self.task,
            SIM_STATE_KEY: self.state_buf.copy(),
            **{key: images[cam] for cam, key in IMAGE_KEYS.items()},
        }
        self.dataset.add_frame(frame)
        self.frames += 1

    def check_end(self) -> None:
        if self.success.update(scene.object_lift_m(self.model, self.data), self.data.time):
            self.dataset.save_episode(parallel_encoding=False)  # no worker process: safe under mjpython
            self.saved += 1
            self.message = f"saved episode {self.saved} ({self.frames / FPS:.1f} s)"
            self.new_episode()
        elif self.frames >= self.max_frames:
            self.discard(f"no lift within {self.max_frames / FPS:.0f} s")

    def overlay(self) -> list[tuple]:
        lift_cm = scene.object_lift_m(self.model, self.data) * 100
        status = f"{self.progress_label}\n{self.phase.value}\nsaved {self.saved}   frames {self.frames}   lift {lift_cm:4.1f} cm"
        if self.message:
            status += f"\n{self.message}"
        return [(mujoco.mjtFontScale.mjFONTSCALE_150, mujoco.mjtGridPos.mjGRID_TOPLEFT, status, None)]


def run(session: Session, target_episodes: int | None) -> None:
    period = 1.0 / FPS
    with mujoco.viewer.launch_passive(session.model, session.data, key_callback=session.on_key) as viewer:
        while viewer.is_running():
            start = time.monotonic()
            with viewer.lock():
                session.tick()
            viewer.set_texts(session.overlay())
            viewer.sync()
            if target_episodes is not None and session.saved >= target_episodes:
                break
            late = time.monotonic() - start - period
            if late < 0:
                time.sleep(-late)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--object", default=scene.DEFAULT_OBJECT, choices=list(scene.OBJECTS), help="what to pick up")
    parser.add_argument("--root", type=Path, default=None, help="dataset directory (default: data/so101_table_lift_<object>)")
    parser.add_argument("--episodes", type=int, default=None, help="stop once the dataset holds this many")
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    parser.add_argument("--seed", type=int, default=None, help="object placement seed (default: random)")
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--id", default=DEFAULT_ARM_ID)
    args = parser.parse_args()

    root = args.root or default_root(args.object)
    model, data = scene.load(args.object)
    real_arm = connect_arm(args.port, args.id)
    dataset = open_dataset(root, model, steps_per_frame(model), args.object)
    session = None
    try:
        read_target = lambda: readings_to_joint_rad(real_arm.get_action())  # noqa: E731
        session = Session(model, data, dataset, read_target, args.seed, args.max_seconds, args.object, args.episodes)
        run(session, args.episodes)
    except KeyboardInterrupt:
        pass
    finally:
        if session is not None and session.frames:
            dataset.clear_episode_buffer()  # an unfinished episode is never kept
        dataset.finalize()
        real_arm.disconnect()
        print(f"Dataset: {root} ({dataset.meta.total_episodes} episodes)")

if __name__ == "__main__":
    main()
