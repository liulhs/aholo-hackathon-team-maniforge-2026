"""Map a calibrated SO-101 arm's LeRobot readings to Menagerie SO-101 joint angles.

Both sides share one zero: Menagerie's model comes from `so101_new_calib`, whose zero pose is
the "middle of range" pose LeRobot's calibration homes to. So a body joint is the same angle on
both sides, up to a per-joint sign and offset kept in JOINT_MAP for corrections found by moving
the real arm. The gripper reads 0 (closed) to 100 (open) in LeRobot and is an angle in the model;
it is mapped linearly onto the model's gripper range, as LeIsaac does.
"""

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class JointMap:
    sign: float = 1.0
    offset_deg: float = 0.0


BODY_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
GRIPPER = "gripper"
JOINT_NAMES = (*BODY_JOINTS, GRIPPER)

# Corrections per body joint, found by moving the real arm and watching the model.
JOINT_MAP: Mapping[str, JointMap] = MappingProxyType({name: JointMap() for name in BODY_JOINTS})

GRIPPER_READING_RANGE = (0.0, 100.0)  # LeRobot RANGE_0_100: closed .. open
GRIPPER_MODEL_RANGE_DEG = (-10.0, 100.0)  # Menagerie gripper joint range


def gripper_to_deg(reading: float) -> float:
    lo, hi = GRIPPER_READING_RANGE
    model_lo, model_hi = GRIPPER_MODEL_RANGE_DEG
    fraction = (reading - lo) / (hi - lo)
    return model_lo + fraction * (model_hi - model_lo)


def readings_to_joint_rad(
    action: Mapping[str, float], joint_map: Mapping[str, JointMap] = JOINT_MAP
) -> dict[str, float]:
    """`SO101Leader.get_action()` output ({"<joint>.pos": value}) -> {joint: radians} for the model."""
    missing = [name for name in JOINT_NAMES if f"{name}.pos" not in action]
    if missing:
        raise KeyError(f"Arm reading lacks joints: {missing}")
    angles = {}
    for name in BODY_JOINTS:
        correction = joint_map[name]
        degrees = correction.sign * action[f"{name}.pos"] + correction.offset_deg
        angles[name] = math.radians(degrees)
    angles[GRIPPER] = math.radians(gripper_to_deg(action[f"{GRIPPER}.pos"]))
    return angles


def clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)
