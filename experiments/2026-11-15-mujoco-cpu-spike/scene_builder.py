"""Builds an MJCF scene: Menagerie SO-101 + one Lux3D object as a free body."""
from pathlib import Path

MODEL_DIR = Path(__file__).parent / "models" / "so101"

OBJECT_MASS_KG = 0.03
OBJECT_FRICTION = "0.8 0.005 0.0001"
OBJECT_PRIORITY = 0  # Menagerie gripper geoms use priority=1 friction=1, which overrides ours unless >1
OBJECT_POS = (0.22, 0.02, 0.03)  # spawn slightly above the floor; it settles

SCENE_TEMPLATE = """<mujoco model="so101_lux3d">
  <include file="so101.xml"/>
  <visual>
    <headlight diffuse="0.6 0.6 0.6" ambient="0.3 0.3 0.3" specular="0 0 0"/>
    <global azimuth="130" elevation="-25" offwidth="960" offheight="720"/>
  </visual>
  <asset>
    <texture type="skybox" builtin="gradient" rgb1="0.3 0.5 0.7" rgb2="0 0 0" width="512" height="3072"/>
    <texture type="2d" name="groundplane" builtin="checker" mark="edge" rgb1="0.2 0.3 0.4"
      rgb2="0.1 0.2 0.3" markrgb="0.8 0.8 0.8" width="300" height="300"/>
    <material name="groundplane" texture="groundplane" texuniform="true" texrepeat="5 5" reflectance="0.2"/>
    <mesh name="lux3d_obj" file="{mesh_file}"/>
  </asset>
  <worldbody>
    <light pos="0 0 3.5" dir="0 0 -1" directional="true"/>
    <geom name="floor" size="0 0 0.05" type="plane" material="groundplane"/>
    <body name="lux3d_obj" pos="{px} {py} {pz}">
      <freejoint name="lux3d_free"/>
      <!-- MuJoCo collides mesh geoms through their convex hull (computed at compile time). -->
      <geom name="lux3d_obj" type="mesh" mesh="lux3d_obj" mass="{mass}" friction="{friction}"
        condim="4" priority="{priority}" rgba="0.85 0.75 0.55 1"/>
    </body>
  </worldbody>
</mujoco>
"""


def write_scene(mesh_file: str, out_name: str) -> Path:
    """Write the scene next to so101.xml so its relative meshdir resolves."""
    px, py, pz = OBJECT_POS
    xml = SCENE_TEMPLATE.format(
        mesh_file=mesh_file, px=px, py=py, pz=pz, mass=OBJECT_MASS_KG, friction=OBJECT_FRICTION, priority=OBJECT_PRIORITY
    )
    out = MODEL_DIR / out_name
    out.write_text(xml)
    return out
