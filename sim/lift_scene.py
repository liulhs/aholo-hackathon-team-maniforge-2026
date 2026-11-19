"""Lift task on a table: Menagerie SO-101 (no camera mount) + one Lux3D object at a time.

The arm is clamped to the edge of a small table whose top is the z=0 plane, so poses and the
lift check read the same as on a floor. The table, its clamps and the mat that marks where the
object may be placed are drawn by simple_table.py.

The objects are listed in prep_object.OBJECTS and converted by prep_object.py: each looks like
its Lux3D `textured.glb` and collides through a convex hull. Its body frame is the centre of its
footprint, on the table (z=0 when it stands). Each episode drops the object at a random spot
and yaw on the mat. The task succeeds once the object is LIFT_SUCCESS_M above the table and
stays there for HOLD_SUCCESS_S.

Physics values are assumptions, not measurements: mass per object (prep_object.OBJECTS),
spread evenly through the collision hull, and friction 0.8. Objects only have to stand where
they are placed; nothing keeps them up if the gripper knocks them (tall ones fall easily). `priority=2` makes the object's friction win over the Menagerie gripper pads
(priority 1), and since priority also hands over condim and solref, the gripper's tuned values
are restated here (2026-11-15 spike).
"""

from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np

import simple_table
from prep_object import OBJECTS, OBJECTS_DIR

SIM_DIR = Path(__file__).parent
ROBOT_DIR = SIM_DIR / "models" / "so101"
OBJECTS_FROM_MESHDIR = "../../objects"  # meshes resolve from models/so101/assets (so101 meshdir)
OBJECTS_FROM_MODEL = "../objects"  # textures resolve from models/so101 (no texturedir)

DEFAULT_OBJECT = "takeout_box"
OBJECT_BODY = "object"  # body and free joint; the same in every scene, so the state layout never changes
OBJECT_FRICTION = "0.8 0.005 0.0001"
OBJECT_STATE_SIZE = 12
SPAWN_X_M = simple_table.PLAY_AREA_X_M
SPAWN_Y_M = simple_table.PLAY_AREA_Y_M
SPAWN_DROP_M = 0.005
LIFT_SUCCESS_M = 0.05
HOLD_SUCCESS_S = 1.0

CAMERA_WIDTH, CAMERA_HEIGHT = 320, 240
FRONT_CAMERA_POS = np.array([0.60, -0.46, 0.40])  # across the table's front corner
FRONT_CAMERA_LOOKAT = np.array([0.17, 0.0, 0.06])
FRONT_CAMERA_FOVY = 55
CAMERAS = ("front", "wrist_cam")

SCENE_XML = """<mujoco model="so101_table_lift">
  <include file="so101_nocam.xml"/>
  <visual>
    <headlight diffuse="0.25 0.25 0.25" ambient="0.42 0.41 0.40" specular="0 0 0"/>
    <global azimuth="160" elevation="-25" offwidth="1280" offheight="720"/>
    <quality shadowsize="4096"/>
  </visual>
  <asset>
    {table_assets}
    <texture type="2d" name="object_texture" file="{tex_dir}/texture.png"/>
    <material name="object_material" texture="object_texture" specular="0.1" shininess="0.1"/>
    <mesh name="object_visual" file="{mesh_dir}/visual.obj"/>
    <mesh name="object_collision" file="{mesh_dir}/collision.obj"/>
  </asset>
  <worldbody>
    {lights}
    {room}
    <camera name="front" pos="{cam_pos}" xyaxes="{cam_xyaxes}" fovy="{cam_fovy}"/>
    <body name="object" pos="0.2 0 0">
      <freejoint name="object"/>
      <geom name="object_visual" type="mesh" mesh="object_visual" material="object_material" group="2"
        contype="0" conaffinity="0" mass="0"/>
      <geom name="object_collision" type="mesh" mesh="object_collision" group="3" mass="{mass}"
        friction="{friction}" priority="2" condim="6" solref="0.01 1" rgba="1 1 1 0"/>
    </body>
  </worldbody>
</mujoco>
"""


def look_at_xyaxes(pos: np.ndarray, target: np.ndarray) -> str:
    """MuJoCo camera xyaxes for a camera at `pos` looking at `target`, with world Z up."""
    forward = (target - pos) / np.linalg.norm(target - pos)
    x_axis = np.cross(forward, [0.0, 0.0, 1.0])
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(x_axis, forward)
    return " ".join(f"{v:.5f}" for v in (*x_axis, *y_axis))


def scene_path(object_name: str) -> Path:
    return ROBOT_DIR / f"scene_table_{object_name}.xml"


def available_objects() -> list[str]:
    """Objects that are listed and have been converted on this machine."""
    return [name for name in OBJECTS if (OBJECTS_DIR / name / "visual.obj").exists()]


def write_scene(object_name: str = DEFAULT_OBJECT) -> Path:
    if object_name not in OBJECTS:
        raise ValueError(f"Unknown object '{object_name}'. Known: {', '.join(OBJECTS)}")
    for needed in (ROBOT_DIR / "so101_nocam.xml", OBJECTS_DIR / object_name / "visual.obj"):
        if not needed.exists():
            raise FileNotFoundError(f"{needed} missing. Run: bash sim/fetch_models.sh")
    simple_table.write_textures()
    path = scene_path(object_name)
    xml = (
        SCENE_XML.format(
            mesh_dir=f"{OBJECTS_FROM_MESHDIR}/{object_name}",
            tex_dir=f"{OBJECTS_FROM_MODEL}/{object_name}",
            cam_pos=" ".join(f"{v:.3f}" for v in FRONT_CAMERA_POS),
            cam_xyaxes=look_at_xyaxes(FRONT_CAMERA_POS, FRONT_CAMERA_LOOKAT),
            cam_fovy=FRONT_CAMERA_FOVY,
            table_assets=simple_table.assets_xml(),
            lights=simple_table.LIGHTS_XML,
            room=simple_table.room_xml(),
            mass=OBJECTS[object_name].mass_kg,
            friction=OBJECT_FRICTION,
        )
    )
    simple_table.write_if_changed(path, xml.encode())
    return path


def load(object_name: str = DEFAULT_OBJECT) -> tuple[mujoco.MjModel, mujoco.MjData]:
    model = mujoco.MjModel.from_xml_path(str(write_scene(object_name)))
    return model, mujoco.MjData(model)


@dataclass(frozen=True)
class ObjectPose:
    x: float
    y: float
    yaw: float


def random_object_pose(rng: np.random.Generator) -> ObjectPose:
    return ObjectPose(x=rng.uniform(*SPAWN_X_M), y=rng.uniform(*SPAWN_Y_M), yaw=rng.uniform(-np.pi, np.pi))


def object_qpos_adr(model: mujoco.MjModel) -> int:
    return int(model.joint(OBJECT_BODY).qposadr[0])


def place_object(model: mujoco.MjModel, data: mujoco.MjData, pose: ObjectPose) -> None:
    adr = object_qpos_adr(model)
    vadr = int(model.joint(OBJECT_BODY).dofadr[0])
    data.qpos[adr : adr + 3] = (pose.x, pose.y, SPAWN_DROP_M)
    data.qpos[adr + 3 : adr + 7] = (np.cos(pose.yaw / 2), 0.0, 0.0, np.sin(pose.yaw / 2))
    data.qvel[vadr : vadr + 6] = 0.0
    mujoco.mj_forward(model, data)


def object_lift_m(model: mujoco.MjModel, data: mujoco.MjData) -> float:
    """Height of the object's footprint centre above the table."""
    return float(data.qpos[object_qpos_adr(model) + 2])


def object_size_m(model: mujoco.MjModel) -> np.ndarray:
    """Bounding-box size (x, y, z) of the object's collision mesh in the object's body frame."""
    geom = model.geom("object_collision").id
    mesh = model.geom_dataid[geom]
    vertices = model.mesh_vert[model.mesh_vertadr[mesh] : model.mesh_vertadr[mesh] + model.mesh_vertnum[mesh]]
    rotation = np.empty(9)  # MuJoCo re-centres and re-orients meshes; geom_pos/quat undo that
    mujoco.mju_quat2Mat(rotation, model.geom_quat[geom])
    # einsum, not @: numpy's matmul raises spurious overflow warnings here on Apple's Accelerate
    in_body = np.einsum("ij,kj->ik", vertices, rotation.reshape(3, 3)) + model.geom_pos[geom]
    return in_body.max(axis=0) - in_body.min(axis=0)


def object_state(model: mujoco.MjModel, data: mujoco.MjData) -> np.ndarray:
    """What a policy without cameras is told about the object, OBJECT_STATE_SIZE numbers:
    position (3, metres), the first two columns of its rotation matrix (6; no jump at +-180
    degrees, unlike yaw or a quaternion), and its bounding-box size (3, metres)."""
    adr = object_qpos_adr(model)  # read from qpos: always current, no mj_forward needed
    rotation = np.empty(9)
    mujoco.mju_quat2Mat(rotation, data.qpos[adr + 3 : adr + 7])
    rotation = rotation.reshape(3, 3)
    position = data.qpos[adr : adr + 3]
    return np.concatenate([position, rotation[:, 0], rotation[:, 1], object_size_m(model)]).astype(np.float32)


class SuccessTracker:
    """Object held at least LIFT_SUCCESS_M up for HOLD_SUCCESS_S of sim time."""

    def __init__(self) -> None:
        self.lifted_since: float | None = None

    def update(self, lift_m: float, sim_time: float) -> bool:
        if lift_m < LIFT_SUCCESS_M:
            self.lifted_since = None
            return False
        if self.lifted_since is None:
            self.lifted_since = sim_time
        return sim_time - self.lifted_since >= HOLD_SUCCESS_S


class Cameras:
    """Offscreen RGB renders of the named cameras."""

    def __init__(self, model: mujoco.MjModel) -> None:
        self.renderer = mujoco.Renderer(model, CAMERA_HEIGHT, CAMERA_WIDTH)

    def render(self, data: mujoco.MjData) -> dict[str, np.ndarray]:
        images = {}
        for name in CAMERAS:
            self.renderer.update_scene(data, camera=name)
            images[name] = self.renderer.render().copy()
        return images

    def close(self) -> None:
        self.renderer.close()
