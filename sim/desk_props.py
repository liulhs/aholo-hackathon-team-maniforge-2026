"""A real desk around the cobot, built from downloaded 3D models (see ASSETS.md for sources).

World frame: the desk top is the z=0 plane; the arm base sits at the origin on the desk's left
short edge and reaches along +x; the person sits on the -y side; the wall is on the +y side.
Every model comes from sim/models/props/<name>/ (made by prep_asset.py from a downloaded file,
front facing -y) and is placed by LAYOUT. Props are static. All of them stay outside WORKSPACE,
the rectangle the arm works in, so they never decide whether a grasp succeeds.

Physics for the desk top is one flat invisible box ("table"); the desk model is looks only.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

from prep_asset import PROPS_DIR, prop_xml

GENERATED_DIR = Path(__file__).parent / "models" / "desk"
GENERATED_FROM_MODEL = "../desk"  # textures resolve from models/so101
PROPS_FROM_MESHDIR = "../../props"  # meshes resolve from models/so101/assets
PROPS_FROM_MODEL = "../props"

DESK_TOP_HALF_X_M, DESK_TOP_HALF_Y_M = 0.5195, 0.3213  # flat part of the desk model's top
DESK_LEFT_EDGE_X_M = -0.075  # the arm base stands just inside this edge
DESK_CENTER_X_M = DESK_LEFT_EDGE_X_M + DESK_TOP_HALF_X_M
WALL_Y_M = 0.385

# Props keep clear of this rectangle (x range, |y| limit): box spawn area plus the arm's sweep.
WORKSPACE_X_M = (0.0, 0.34)
WORKSPACE_HALF_Y_M = 0.15

TEXTURE_SIZE = 512
FLOOR_TONES = ((0.42, 0.31, 0.22), (0.28, 0.20, 0.14))


@dataclass(frozen=True)
class Placement:
    name: str
    x: float
    y: float
    z: float = 0.0
    yaw_deg: float = 0.0
    solid: bool = True


LAYOUT = (
    Placement("desk", DESK_CENTER_X_M, 0.0, z=-0.74, solid=False),
    Placement("monitor", 0.70, 0.20),
    Placement("keyboard", 0.70, -0.14),
    Placement("mug", 0.42, -0.24, yaw_deg=25),
    Placement("books", 0.10, -0.25, yaw_deg=3),
    Placement("headphones", 0.10, -0.25, z=0.0837, yaw_deg=-20),
    Placement("desk_lamp", 0.26, 0.26, yaw_deg=90),  # head points +x, along the wall
    Placement("plant", 0.0, 0.25),
    Placement("chair", 0.72, -0.78, z=-0.74, yaw_deg=165, solid=False),
)

ASSETS_XML = """
    <texture type="skybox" builtin="gradient" rgb1="0.93 0.93 0.90" rgb2="0.75 0.77 0.80" width="64" height="384"/>
    <texture type="2d" name="floor_wood" file="{generated}/floor_wood.png"/>
    <material name="floor_wood" texture="floor_wood" texuniform="true" texrepeat="1.2 1.2" specular="0.1"/>
    <material name="wall" rgba="0.80 0.82 0.80 1" specular="0"/>
"""

LIGHTS_XML = """
    <light name="window" pos="1.4 -1.2 1.6" dir="-0.6 0.55 -1" directional="true"
      diffuse="0.75 0.72 0.66" specular="0.2 0.2 0.2" castshadow="true"/>
    <light name="fill" pos="-0.6 -0.9 1.2" dir="0.5 0.5 -1" directional="true"
      diffuse="0.22 0.24 0.28" specular="0 0 0" castshadow="false"/>
"""


def floor_texture(seed: int = 2) -> Image.Image:
    """Wood-grain floor (the one generated surface; everything on and around the desk is a model)."""
    rng = np.random.default_rng(seed)
    grain = gaussian_filter(rng.standard_normal((TEXTURE_SIZE, TEXTURE_SIZE)), sigma=(1.2, 40), mode="wrap")
    waves = gaussian_filter(rng.standard_normal((TEXTURE_SIZE, TEXTURE_SIZE)), sigma=(14, 90), mode="wrap")
    mix = 0.5 + 0.5 * np.tanh(0.45 * grain / grain.std() + 0.35 * waves / waves.std())
    mix[(np.arange(TEXTURE_SIZE) % (TEXTURE_SIZE // 4)) < 2, :] += 0.25  # plank seams
    mix = np.clip(mix, 0, 1)[..., None]
    light, dark = (np.array(tone) for tone in FLOOR_TONES)
    return Image.fromarray(((light * (1 - mix) + dark * mix) * 255).astype(np.uint8))


def write_textures() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    floor_texture().save(GENERATED_DIR / "floor_wood.png")


def load_meta(name: str) -> dict:
    path = PROPS_DIR / name / "meta.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: the '{name}' model has not been downloaded and converted (prep_asset.py)")
    return json.loads(path.read_text())


def room_xml() -> str:
    return "\n    ".join(
        [
            # "table" is the surface the arm base and the box stand on; the desk model is drawn over it.
            f'<geom name="table" type="box" size="{DESK_TOP_HALF_X_M} {DESK_TOP_HALF_Y_M} 0.012" '
            f'pos="{DESK_CENTER_X_M} 0 -0.012" group="3" rgba="1 1 1 0"/>',
            '<geom name="floor" type="plane" size="4 4 0.05" pos="0 0 -0.74" material="floor_wood"/>',
            f'<geom name="wall" type="box" size="4 0.01 1.4" pos="0 {WALL_Y_M + 0.01} 0.4" material="wall"/>',
        ]
    )


def assets_and_bodies() -> tuple[str, str]:
    assets = [ASSETS_XML.format(generated=GENERATED_FROM_MODEL)]
    bodies = []
    for i, place in enumerate(LAYOUT):
        prop_assets, geoms = prop_xml(place.name, load_meta(place.name), PROPS_FROM_MESHDIR, PROPS_FROM_MODEL, place.solid)
        assets.append(prop_assets)
        bodies.append(
            f'<body name="prop_{place.name}" pos="{place.x} {place.y} {place.z}" euler="0 0 {np.radians(place.yaw_deg):.4f}">\n'
            f"      {geoms}\n    </body>"
        )
    return "\n    ".join(assets), "\n    ".join(bodies)


def credits_markdown() -> str:
    rows = ["| 物品 | 作者 | 许可 | 来源 |", "| --- | --- | --- | --- |"]
    for name in dict.fromkeys(place.name for place in LAYOUT):
        meta = load_meta(name)
        rows.append(f"| {name} | {meta['author']} | {meta['license']} | {meta['source_url']} |")
    return "\n".join(rows)
