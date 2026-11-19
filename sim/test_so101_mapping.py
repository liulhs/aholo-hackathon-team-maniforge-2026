import math
from pathlib import Path

import pytest

from so101_mapping import JOINT_NAMES, JointMap, gripper_to_deg, readings_to_joint_rad

MODEL = Path(__file__).parent / "models" / "so101" / "scene.xml"


def reading(**overrides: float) -> dict[str, float]:
    base = {f"{name}.pos": 0.0 for name in JOINT_NAMES}
    base.update({f"{name}.pos": value for name, value in overrides.items()})
    return base


def test_middle_pose_maps_to_model_zero():
    angles = readings_to_joint_rad(reading(gripper=100 * 10 / 110))
    assert all(abs(angle) < 1e-9 for angle in angles.values())


def test_body_joint_degrees_become_radians():
    angles = readings_to_joint_rad(reading(elbow_flex=90.0, shoulder_pan=-45.0))
    assert angles["elbow_flex"] == pytest.approx(math.pi / 2)
    assert angles["shoulder_pan"] == pytest.approx(-math.pi / 4)


def test_gripper_spans_model_range():
    assert gripper_to_deg(0.0) == pytest.approx(-10.0)
    assert gripper_to_deg(100.0) == pytest.approx(100.0)


def test_sign_and_offset_corrections_apply():
    joint_map = {name: JointMap() for name in JOINT_NAMES[:-1]}
    joint_map["wrist_flex"] = JointMap(sign=-1.0, offset_deg=5.0)
    angles = readings_to_joint_rad(reading(wrist_flex=30.0), joint_map)
    assert angles["wrist_flex"] == pytest.approx(math.radians(-25.0))


def test_missing_joint_raises():
    partial = reading()
    del partial["gripper.pos"]
    with pytest.raises(KeyError, match="gripper"):
        readings_to_joint_rad(partial)


@pytest.mark.skipif(not MODEL.exists(), reason="run sim/fetch_models.sh first")
def test_model_has_one_position_actuator_per_joint():
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(str(MODEL))
    for name in JOINT_NAMES:
        actuator = model.actuator(name)
        assert model.joint(int(actuator.trnid[0])).name == name


NOCAM = MODEL.parent / "scene_nocam.xml"


@pytest.mark.skipif(not NOCAM.exists(), reason="run sim/fetch_models.sh first")
def test_nocam_model_has_no_camera_mount_geoms():
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(str(NOCAM))
    mount = model.body("camera_mount").id
    assert not any(model.geom_bodyid[g] == mount for g in range(model.ngeom))
