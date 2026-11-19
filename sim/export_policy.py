"""Export a trained state-only ACT policy to ONNX for the browser demo, and check it matches PyTorch.

policy.onnx takes the raw numbers the sim gives (joint angles in rad, lift_scene.object_state) and
returns raw target joint angles in rad: LeRobot's saved normaliser and unnormaliser are baked into
the graph. policy.json says how to call it, including the temporal-ensemble rule to port to
JavaScript. After exporting, onnxruntime and PyTorch are run on frames of the training dataset
and the largest difference is printed, with the onnxruntime CPU time per call.

    source .venv/bin/activate
    python sim/export_policy.py outputs/act_state_envnorm/checkpoints/030000/pretrained_model --out-dir web/public/policy
    python sim/export_policy.py <pretrained_model> --out-dir <dir> --eval outputs/eval/envnorm_30k_te.json   # record eval results in policy.json
    python sim/export_policy.py <pretrained_model> --out-dir <dir> --check-frames 0   # skip the check
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

from build_state_dataset import ACTION_KEY, STATE_KEY
from evaluate import dataset_object_position
from record import FPS, OBJECT_STATE_KEY, REPO
from so101_mapping import JOINT_NAMES

OPSET = 17  # onnxruntime-web 1.31 runs it
INPUT_NAMES = ("state", "env_state")
OUTPUT_NAME = "actions"
TEMPORAL_ENSEMBLE_COEFF = 0.01  # what the evaluations used (ACT paper default)
DEFAULT_CHECK_FRAMES = 512
MAX_CHECK_DIFF_RAD = 1e-4
LATENCY_CALLS = 200

CONTROL_LOOP = (
    "As sim/evaluate.py: every frame read the 6 joint qpos and object_state, run the model, temporal-ensemble the chunk, "
    "write each joint's action, clipped to actuator_ctrlrange, to that joint's position-actuator ctrl (teleop.SimArm.command), "
    "then mj_step round(1 / fps / opt.timestep) times."
)
ENSEMBLE_STEPS = [
    "Precompute w[i] = exp(-coeff * i) and W[i] = w[0] + ... + w[i] for i = 0 .. chunk_size-1 (C = chunk_size).",
    "Keep two buffers, empty at the start of every episode (reset): avg, a list of 6-number actions, and count, a list of integers of the same length.",
    "Every frame (20 Hz) run the model on the current observation; it returns a chunk a[0..C-1] for this frame and the next C-1 frames.",
    "If avg is empty: avg = copy of a[0..C-1], count = [1] * C.",
    "Otherwise avg and count have length C-1. For k = 0 .. C-2: n = count[k]; "
    "avg[k] = (avg[k] * W[n-1] + a[k] * w[n]) / W[n]; count[k] = min(n + 1, C). "
    "Then append a[C-1] to avg and 1 to count (length C again).",
    "Pop the front: the action to send this frame is avg[0]; set avg = avg[1..], count = count[1..].",
]
ENSEMBLE_RESULT = (
    "The action sent at frame t is the weighted mean of every prediction made for frame t: sum_j w[j] * p_j / sum_j w[j], "
    "where p_0 is the oldest such prediction (made C-1 frames ago, or the first frame's chunk), p_1 the next oldest, and so on; "
    "with coeff 0.01 older predictions weigh slightly more. n never exceeds C-1 when it indexes w, so the min() never bites. "
    "LeRobot does this in float32 (ACTTemporalEnsembler in lerobot/policies/act/modeling_act.py)."
)


class BakedPolicy(nn.Module):
    """Raw observation in, raw action chunk out: LeRobot's normaliser, ACT and unnormaliser in one module."""

    def __init__(self, policy: nn.Module, normalizer, unnormalizer) -> None:
        super().__init__()
        self.policy, self.normalizer, self.unnormalizer = policy, normalizer, unnormalizer

    def forward(self, state: torch.Tensor, env_state: torch.Tensor) -> torch.Tensor:
        # LeRobot's own transform code, traced with the saved statistics as constants.
        batch = {
            key: self.normalizer._apply_transform(value, key, self.normalizer.features[key].type)
            for key, value in ((STATE_KEY, state), (OBJECT_STATE_KEY, env_state))
        }
        actions = self.policy.predict_action_chunk(batch)  # eval mode: VAE latent is zeros
        return self.unnormalizer._apply_transform(actions, ACTION_KEY, self.unnormalizer.features[ACTION_KEY].type, inverse=True)


def load_policy(path: Path):
    """The ACT policy (CPU, eval mode) and its saved pre/post-processors, loaded as evaluate.py does."""
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    policy = ACTPolicy.from_pretrained(path)
    policy.to("cpu").eval()
    on_cpu = {"device_processor": {"device": "cpu"}}
    preprocess, postprocess = make_pre_post_processors(
        policy.config, pretrained_path=path, preprocessor_overrides=on_cpu, postprocessor_overrides=on_cpu
    )
    return policy, preprocess, postprocess


def find_step(pipeline, class_name: str):
    """The one step of a processor pipeline with this class name."""
    steps = [step for step in pipeline.steps if type(step).__name__ == class_name]
    if len(steps) != 1:
        raise SystemExit(f"Expected one {class_name} in {pipeline.name}, found {len(steps)}")
    return steps[0]


def export_onnx(policy, preprocess, postprocess, out: Path) -> None:
    """Trace the baked policy to a single-file ONNX graph."""
    baked = BakedPolicy(policy, find_step(preprocess, "NormalizerProcessorStep"), find_step(postprocess, "UnnormalizerProcessorStep")).eval()
    example = (torch.zeros(1, len(JOINT_NAMES)), torch.zeros(1, policy.config.env_state_feature.shape[0]))
    with torch.no_grad():
        torch.onnx.export(
            baked, example, str(out), input_names=list(INPUT_NAMES), output_names=[OUTPUT_NAME],
            opset_version=OPSET, do_constant_folding=True, dynamo=False,
        )
    import onnx

    onnx.checker.check_model(str(out), full_check=True)


def torch_chunk(policy, preprocess, postprocess, state: np.ndarray, env_state: np.ndarray) -> np.ndarray:
    """The raw action chunk the PyTorch pipeline (as evaluate.py runs it) predicts for one frame."""
    observation = {STATE_KEY: torch.from_numpy(state), OBJECT_STATE_KEY: torch.from_numpy(env_state)}
    with torch.inference_mode():
        return postprocess(policy.predict_action_chunk(preprocess(observation))).numpy()


def sample_frames(dataset_root: Path, count: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """`count` random (state, env_state) frames of a dataset; unreadable parquet files are skipped."""
    tables = []
    for path in sorted((dataset_root / "data").glob("*/*.parquet")):
        try:
            tables.append(pd.read_parquet(path, columns=[STATE_KEY, OBJECT_STATE_KEY]))
        except Exception as error:  # a file still being written
            print(f"Skipping {path}: {error}")
    if not tables:
        raise SystemExit(f"No readable frames in {dataset_root}")
    frames = pd.concat(tables, ignore_index=True)
    rows = np.random.default_rng(seed).choice(len(frames), size=min(count, len(frames)), replace=False)
    states = np.stack(frames[STATE_KEY].to_numpy()[rows]).astype(np.float32)
    env_states = np.stack(frames[OBJECT_STATE_KEY].to_numpy()[rows]).astype(np.float32)
    return states, env_states


def ort_session(path: Path, threads: int):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def check_against_torch(onnx_path: Path, policy, preprocess, postprocess, dataset_root: Path, count: int) -> float:
    """Largest |onnxruntime - PyTorch| over the action chunks of `count` dataset frames, in rad."""
    session = ort_session(onnx_path, threads=1)
    states, env_states = sample_frames(dataset_root, count, seed=0)
    worst = 0.0
    for state, env_state in zip(states, env_states):
        feeds = dict(zip(INPUT_NAMES, (state[None], env_state[None])))
        ours = session.run([OUTPUT_NAME], feeds)[0]
        reference = torch_chunk(policy, preprocess, postprocess, state, env_state)
        worst = max(worst, float(np.abs(ours - reference).max()))
    print(f"onnxruntime vs PyTorch on {len(states)} frames of {dataset_root}: max |diff| {worst:.2e} rad")
    return worst


def time_calls(onnx_path: Path, threads: int) -> float:
    """Median onnxruntime CPU time per call, in ms."""
    session = ort_session(onnx_path, threads)
    feeds = dict(zip(INPUT_NAMES, (np.zeros((1, len(JOINT_NAMES)), np.float32), np.zeros((1, 12), np.float32))))
    for _ in range(10):
        session.run([OUTPUT_NAME], feeds)
    times = []
    for _ in range(LATENCY_CALLS):
        start = time.perf_counter()
        session.run([OUTPUT_NAME], feeds)
        times.append(time.perf_counter() - start)
    return 1000 * float(np.median(times))


def eval_summary(path: Path) -> dict:
    """An evaluate.py results file reduced to lifted/trials per object."""
    results = json.loads(path.read_text())
    lifted, trials = Counter(), Counter()
    for trial in results["trials"]:
        trials[trial["object_name"]] += 1
        lifted[trial["object_name"]] += bool(trial["success"])
    summary = {key: value for key, value in results.items() if key != "trials"}
    return {
        **summary,
        "file": str(path),
        "lifted": sum(lifted.values()),
        "trials": sum(trials.values()),
        "per_object": {name: f"{lifted[name]}/{trials[name]}" for name in trials},
    }


def relative(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)


def describe(policy, policy_dir: Path, train_root: Path, evals: list[Path]) -> dict:
    """Everything the browser needs to call policy.onnx, as policy.json."""
    config = policy.config
    chunk, env_size = config.chunk_size, config.env_state_feature.shape[0]
    sources = train_root / "meta" / "sources.json"
    return {
        "source_checkpoint": relative(policy_dir),
        "training_dataset": relative(train_root),
        "objects": list(json.loads(sources.read_text())) if sources.exists() else None,
        # env_state[0:3]: "origin" = the object's bottom-centre point, "com" = its centre of mass (build_state_dataset.py --object-position)
        "object_position": dataset_object_position(train_root),
        "fps": FPS,
        "chunk_size": chunk,
        "joint_names": list(JOINT_NAMES),
        "inputs": {
            INPUT_NAMES[0]: {"dtype": "float32", "shape": [1, len(JOINT_NAMES)], "meaning": "joint angles in rad, order joint_names (sim qpos)"},
            INPUT_NAMES[1]: {
                "dtype": "float32",
                "shape": [1, env_size],
                "meaning": "lift_scene.object_state: object position xyz (m, world), rotation-matrix column 0 (3), column 1 (3), bounding-box size xyz (m)",
            },
        },
        "outputs": {
            OUTPUT_NAME: {
                "dtype": "float32",
                "shape": [1, chunk, len(JOINT_NAMES)],
                "meaning": "target joint angles in rad for this frame and the next chunk_size-1 frames, order joint_names",
            }
        },
        "normalization": "baked into the graph (LeRobot MEAN_STD stats of the training dataset); feed raw values",
        "control_loop": CONTROL_LOOP,
        "opset": OPSET,
        "temporal_ensemble_coeff": TEMPORAL_ENSEMBLE_COEFF,
        "temporal_ensemble": {"steps": ENSEMBLE_STEPS, "result": ENSEMBLE_RESULT},
        "evaluations": [eval_summary(path) for path in evals],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("policy", type=Path, help="a checkpoint's pretrained_model directory")
    parser.add_argument("--out-dir", type=Path, required=True, help="where policy.onnx and policy.json go")
    parser.add_argument("--eval", type=Path, nargs="*", default=[], help="evaluate.py results files to summarise in policy.json")
    parser.add_argument("--check-frames", type=int, default=DEFAULT_CHECK_FRAMES, help="dataset frames to compare onnxruntime with PyTorch on (0: skip)")
    parser.add_argument("--check-dataset", type=Path, default=None, help="default: the training dataset")
    args = parser.parse_args()

    train_root = Path(json.loads((args.policy / "train_config.json").read_text())["dataset"]["root"])
    train_root = train_root if train_root.is_absolute() else REPO / train_root
    policy, preprocess, postprocess = load_policy(args.policy)
    if policy.config.image_features or policy.config.env_state_feature is None:
        raise SystemExit("Only state-only ACT policies (joint angles + environment state, no images) can be exported")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = args.out_dir / "policy.onnx"
    export_onnx(policy, preprocess, postprocess, onnx_path)
    print(f"Wrote {onnx_path} ({onnx_path.stat().st_size / 1e6:.1f} MB, opset {OPSET})")
    info = describe(policy, args.policy, train_root, args.eval)
    (args.out_dir / "policy.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"Wrote {args.out_dir / 'policy.json'}")

    for threads in (1, 4):
        print(f"onnxruntime CPU, {threads} thread(s): {time_calls(onnx_path, threads):.2f} ms per call (median of {LATENCY_CALLS})")
    if args.check_frames > 0:
        worst = check_against_torch(onnx_path, policy, preprocess, postprocess, args.check_dataset or train_root, args.check_frames)
        if worst >= MAX_CHECK_DIFF_RAD:
            raise SystemExit(f"Mismatch: {worst:.2e} rad >= {MAX_CHECK_DIFF_RAD:.0e}")


if __name__ == "__main__":
    main()
