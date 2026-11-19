"""Headless check that a LeIsaac task loads and the Lux3D box rests on the table.

Run on the GPU instance (lives in ~/cogway/tools/, NOT next to ~/cogway/leisaac: Python would
otherwise import the repo root folder as the `leisaac` package):
    python ~/cogway/tools/smoke_test.py --task LeIsaac-SO101-LiftTakeoutBox-v0 --headless --enable_cameras

Writes ~/cogway/out/<task>_front.png and ~/cogway/out/<task>_result.json. Kit can swallow Python
exceptions and still exit 0, so callers must read the result file instead of the exit code.
"""
import argparse
import json
import sys
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser()
parser.add_argument("--task", default="LeIsaac-SO101-LiftTakeoutBox-v0")
parser.add_argument("--object", default="takeout_box", help="scene entity name of the object to check")
parser.add_argument("--settle_steps", type=int, default=240, help="physics steps to let the object settle")
parser.add_argument("--out_dir", default=str(Path.home() / "cogway" / "out"))
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
simulation_app = AppLauncher(vars(args)).app

import gymnasium as gym  # noqa: E402
import leisaac.tasks  # noqa: E402,F401  registers LeIsaac tasks, including lift_takeout_box
from isaaclab_tasks.utils import parse_env_cfg  # noqa: E402
from PIL import Image  # noqa: E402

TABLE_TOP_Z = 0.041
REST_TOLERANCE_M = 0.01


def main() -> int:
    env_cfg = parse_env_cfg(args.task, device=args.device, num_envs=1)
    # LeIsaac fills the arm/gripper action terms only once a teleop device is chosen
    # (teleop_se3_agent.py does the same before gym.make).
    env_cfg.use_teleop_device("keyboard")
    env = gym.make(args.task, cfg=env_cfg).unwrapped
    env.reset()
    obj = env.scene[args.object]
    start = obj.data.root_pos_w[0].tolist()
    dt = env.sim.get_physics_dt()
    for _ in range(args.settle_steps):
        env.sim.step(render=False)
        env.scene.update(dt)
    end = obj.data.root_pos_w[0].tolist()
    env.sim.render()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if "front" in env.scene.keys():
        env.scene["front"].update(dt, force_recompute=True)
        rgb = env.scene["front"].data.output["rgb"][0].cpu().numpy()
        Image.fromarray(rgb[..., :3]).save(out_dir / f"{args.task}_front.png")
    resting_z = end[2] - env.scene.env_origins[0, 2].item()
    settled = abs(resting_z - TABLE_TOP_Z) < REST_TOLERANCE_M
    print(f"[smoke] task={args.task} object={args.object}")
    print(f"[smoke] start_pos={[round(v, 4) for v in start]} end_pos={[round(v, 4) for v in end]}")
    print(f"[smoke] bottom_z={resting_z:.4f} table_top={TABLE_TOP_Z} settled={settled}")
    print(f"[smoke] image={out_dir / f'{args.task}_front.png'}")
    (out_dir / f"{args.task}_result.json").write_text(json.dumps({
        "task": args.task, "object": args.object, "start_pos": start, "end_pos": end,
        "bottom_z": resting_z, "table_top_z": TABLE_TOP_Z, "settled": settled,
    }, indent=1))
    env.close()
    return 0 if settled else 1


if __name__ == "__main__":
    code = main()
    simulation_app.close()
    sys.exit(code)
