"""Merge per-object lift demos into one LeRobot dataset without images, for a policy that sees no camera.

Reads data/so101_table_lift_<object> (written by record.py) and writes a dataset holding only
the arm's joint angles, the object's state (position, orientation, size) and the action.
Every recorded episode is used by default. Episodes in which the object leaned past 37 degrees
while still on the table are listed in meta/sources.json; `--drop-tipped` leaves them out. Most
such tilts are the object pivoting as the gripper pinches it, a fraction of a second before the
lift (thin objects such as the Tamagotchi), not a knock-over.

    source .venv/bin/activate
    python sim/build_state_dataset.py                                   # every recorded object -> data/so101_state_all
    python sim/build_state_dataset.py --objects labubu --name labubu    # one object
    python sim/build_state_dataset.py --per-object 20 --name all_20     # first 20 episodes of each
    python sim/build_state_dataset.py --object-position com --name all8_com   # position = centre of mass

meta/sources.json in the output says which episodes of which object went in.
"""

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

import lift_scene as scene
from record import FPS, OBJECT_STATE_KEY, REPO, default_root, task_text
from so101_mapping import JOINT_NAMES

STATE_KEY, ACTION_KEY = "observation.state", "action"
COLUMNS = ["episode_index", "frame_index", STATE_KEY, OBJECT_STATE_KEY, ACTION_KEY]
ON_TABLE_M = 0.01  # the object's centre has risen less than this: it is still on the table
MIN_UPRIGHT = 0.8  # cosine of the tilt (37 degrees) beyond which an object on the table counts as tipped


def recorded_objects() -> list[str]:
    return [name for name in scene.OBJECTS if (default_root(name) / "meta" / "info.json").exists()]


def load_episodes(root: Path) -> dict[int, pd.DataFrame]:
    files = sorted((root / "data").glob("*/*.parquet"))
    if not files:
        raise SystemExit(f"No data in {root}")
    try:
        frames = pd.concat(pd.read_parquet(f, columns=COLUMNS) for f in files)
    except OSError as error:  # a parquet file without its footer: record.py is still writing it
        raise SystemExit(f"{root} cannot be read; if it is being recorded, close the recording window first. ({error})") from error
    return {int(index): group.sort_values("frame_index") for index, group in frames.groupby("episode_index")}


def tipped_on_table(object_states: np.ndarray) -> bool:
    """True if the object leaned past MIN_UPRIGHT before it was lifted."""
    up_z = np.cross(object_states[:, 3:6], object_states[:, 6:9])[:, 2]
    on_table = object_states[:, 2] - object_states[0, 2] < ON_TABLE_M
    return bool((up_z[on_table] < MIN_UPRIGHT).any())


def object_com_offset(object_name: str) -> np.ndarray:
    """The object's centre of mass in its body frame (MuJoCo's body ipos), from its training scene."""
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(scene.write_scene(object_name)))
    return model.body(scene.OBJECT_BODY).ipos.copy()


def with_com_position(object_states: np.ndarray, com_offset: np.ndarray) -> np.ndarray:
    """object_state rows with the position (bottom-centre point) replaced by the centre of mass:
    origin + R @ ipos, R from the stored rotation columns (equals data.xipos after mj_forward to 1e-16 m;
    right after mj_step xipos is a substep old, so sim/evaluate.py and the page use this formula too)."""
    c0, c1 = object_states[:, 3:6], object_states[:, 6:9]
    rotation = np.stack([c0, c1, np.cross(c0, c1)], axis=2)  # columns: body x, y, z in world
    out = object_states.copy()
    out[:, 0:3] = object_states[:, 0:3] + np.einsum("nij,j->ni", rotation, com_offset)
    return out


def features() -> dict:
    joint = {"dtype": "float32", "shape": (len(JOINT_NAMES),), "names": list(JOINT_NAMES)}
    object_state = {"dtype": "float32", "shape": (scene.OBJECT_STATE_SIZE,), "names": None}
    return {STATE_KEY: joint, OBJECT_STATE_KEY: object_state, ACTION_KEY: joint}


def build(objects: list[str], out: Path, name: str, per_object: int | None, drop_tipped: bool, position: str = "origin") -> dict:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    shutil.rmtree(out, ignore_errors=True)
    dataset = LeRobotDataset.create(f"maniforge/so101_state_{name}", fps=FPS, features=features(), root=out, robot_type="so101_sim", use_videos=False)
    sources = {}
    for object_name in objects:
        episodes = load_episodes(default_root(object_name))
        com_offset = object_com_offset(object_name) if position == "com" else None
        kept, tipped = [], []
        for index, frames in episodes.items():
            object_states = np.stack(frames[OBJECT_STATE_KEY].to_numpy())
            if tipped_on_table(object_states):
                tipped.append(index)
                if drop_tipped:
                    continue
            if per_object is not None and len(kept) >= per_object:
                continue
            given = with_com_position(object_states.astype(np.float64), com_offset) if com_offset is not None else object_states
            for state, object_state, action in zip(frames[STATE_KEY], given, frames[ACTION_KEY]):
                dataset.add_frame(
                    {
                        STATE_KEY: np.asarray(state, dtype=np.float32),
                        OBJECT_STATE_KEY: object_state.astype(np.float32),
                        ACTION_KEY: np.asarray(action, dtype=np.float32),
                        "task": task_text(object_name),
                    }
                )
            dataset.save_episode(parallel_encoding=False)
            kept.append(index)
        sources[object_name] = {"recorded": len(episodes), "used": kept, "tipped_on_table": tipped}
    dataset.finalize()
    (out / "meta" / "sources.json").write_text(json.dumps(sources, indent=2))
    note = {"origin": "the object's bottom-centre point (body origin), lift_scene.object_state",
            "com": "the object's centre of mass in world coordinates (data.xipos)"}[position]
    (out / "meta" / "object_position.json").write_text(json.dumps({"object_position": position, "note": f"observation.environment_state[0:3] is {note}"}, indent=2))
    return sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--objects", nargs="+", default=None, choices=list(scene.OBJECTS), help="default: every recorded object")
    parser.add_argument("--name", default="all", help="output is data/so101_state_<name>")
    parser.add_argument("--per-object", type=int, default=None, help="use at most this many episodes of each object")
    parser.add_argument("--object-position", choices=["origin", "com"], default="origin",
                        help="position given to the policy: bottom-centre point (as recorded) or centre of mass")
    parser.add_argument("--drop-tipped", action="store_true", help="leave out episodes where the object leaned past 37 degrees on the table")
    args = parser.parse_args()

    objects = args.objects or recorded_objects()
    if not objects:
        raise SystemExit("Nothing recorded yet (data/so101_table_lift_<object>).")
    out = REPO / "data" / f"so101_state_{args.name}"
    sources = build(objects, out, args.name, args.per_object, args.drop_tipped, args.object_position)
    for object_name, source in sources.items():
        print(f"{object_name}: used {len(source['used'])} of {source['recorded']}, tipped on the table: {source['tipped_on_table']}")
    print(f"Dataset: {out}")


if __name__ == "__main__":
    main()
