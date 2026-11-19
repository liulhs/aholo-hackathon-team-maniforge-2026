"""Replay recorded episodes by re-simulating them from the saved MuJoCo state, and check they match.

Each frame's `sim.state` (mjSTATE_INTEGRATION) includes the ctrl applied over that frame. Replay
sets frame 0's state, then for every frame re-applies its ctrl and steps; the resulting state is
compared with the recorded next frame. A bitwise match means the recording fully describes the
episode, so it can be replayed elsewhere (the browser) or re-rendered from new viewpoints.

    source .venv/bin/activate
    python sim/replay.py                                    # verify every takeout-box episode
    python sim/replay.py --object labubu                     # another object's dataset
    python sim/replay.py --episode 3 --video out.mp4         # also render a replay video
"""

import argparse
import json
import sys
from pathlib import Path

import mujoco
import numpy as np
import pandas as pd

import lift_scene as scene
from record import SIM_STATE_KEY, SIM_STATE_SPEC, default_root

VIDEO_SIZE = (720, 1280)  # height, width
VIDEO_LOOKAT = (0.18, 0.0, 0.03)
VIDEO_DISTANCE, VIDEO_AZIMUTH, VIDEO_ELEVATION = 0.95, 125.0, -26.0


def load_episodes(root: Path) -> dict[int, np.ndarray]:
    files = sorted((root / "data").glob("*/*.parquet"))
    if not files:
        raise SystemExit(f"No data in {root}")
    frames = pd.concat(pd.read_parquet(f, columns=["episode_index", "frame_index", SIM_STATE_KEY]) for f in files)
    episodes = {}
    for index, group in frames.groupby("episode_index"):
        ordered = group.sort_values("frame_index")
        episodes[int(index)] = np.stack(ordered[SIM_STATE_KEY].to_numpy())
    return episodes


def replay(model: mujoco.MjModel, data: mujoco.MjData, states: np.ndarray, steps_per_frame: int, on_frame=None):
    """Re-simulate one episode; returns the largest |replayed - recorded| state difference."""
    recorded = mujoco.MjData(model)  # unpacks each recorded state to read its ctrl
    current = np.empty(states.shape[1])
    worst = 0.0
    mujoco.mj_setState(model, data, states[0], SIM_STATE_SPEC)
    for t in range(len(states)):
        if t > 0:
            mujoco.mj_setState(model, recorded, states[t], SIM_STATE_SPEC)
            data.ctrl[:] = recorded.ctrl  # the command the operator gave for frame t
            mujoco.mj_getState(model, data, current, SIM_STATE_SPEC)
            worst = max(worst, float(np.max(np.abs(current - states[t]))))
        if on_frame is not None:
            on_frame(data)
        for _ in range(steps_per_frame):
            mujoco.mj_step(model, data)
    return worst


def render_video(model: mujoco.MjModel, data: mujoco.MjData, states: np.ndarray, steps_per_frame: int, fps: int, out: Path) -> None:
    import av

    renderer = mujoco.Renderer(model, *VIDEO_SIZE)
    camera = mujoco.MjvCamera()
    camera.lookat[:] = VIDEO_LOOKAT
    camera.distance, camera.azimuth, camera.elevation = VIDEO_DISTANCE, VIDEO_AZIMUTH, VIDEO_ELEVATION
    with av.open(str(out), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.height, stream.width = VIDEO_SIZE
        stream.pix_fmt = "yuv420p"

        def write(frame_data: mujoco.MjData) -> None:
            renderer.update_scene(frame_data, camera)
            frame = av.VideoFrame.from_ndarray(renderer.render(), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)

        replay(model, data, states, steps_per_frame, on_frame=write)
        for packet in stream.encode():
            container.mux(packet)
    renderer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--object", default=scene.DEFAULT_OBJECT, choices=list(scene.OBJECTS))
    parser.add_argument("--root", type=Path, default=None, help="dataset directory (default: that object's)")
    parser.add_argument("--episode", type=int, default=None, help="only this episode")
    parser.add_argument("--video", type=Path, default=None, help="render the replay to this mp4 (needs --episode)")
    args = parser.parse_args()

    root = args.root or default_root(args.object)
    meta = json.loads((root / "meta" / "sim.json").read_text())
    fps = json.loads((root / "meta" / "info.json").read_text())["fps"]
    model, data = scene.load(meta["object"])  # the dataset says which object it holds
    if mujoco.mj_stateSize(model, SIM_STATE_SPEC) != meta["state_size"]:
        raise SystemExit("Current scene differs from the recorded one (state size); cannot replay.")
    episodes = load_episodes(root)
    chosen = [args.episode] if args.episode is not None else sorted(episodes)

    mismatched = 0
    for index in chosen:
        worst = replay(model, data, episodes[index], meta["steps_per_frame"])
        status = "exact" if worst == 0.0 else f"max diff {worst:.3g}"
        mismatched += worst != 0.0
        print(f"episode {index:3d}: {len(episodes[index]):4d} frames, {status}")
    if args.video is not None:
        if args.episode is None:
            raise SystemExit("--video needs --episode")
        render_video(model, data, episodes[args.episode], meta["steps_per_frame"], fps, args.video)
        print(f"video: {args.video}")
    print(f"{len(chosen) - mismatched}/{len(chosen)} episodes replay exactly")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
