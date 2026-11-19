"""Images for the web page's Lux3D carousel: each object's Lux3D input images and three MuJoCo
renders of the model it produced.

    .venv/bin/python sim/build_lux3d_gallery.py

Reads the converted models in sim/models/objects/<name>/ (sim/prep_object.py, not in git) and the
inputs in experiments/. Writes web/public/media/lux3d/<name>/input-<k>.webp and view-<k>.webp.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import mujoco
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
OBJECTS_DIR = REPO / "sim" / "models" / "objects"
OUT_DIR = REPO / "web" / "public" / "media" / "lux3d"
LUX3D_1118 = REPO / "experiments" / "2026-11-18-lux3d-objects" / "input"
LUX3D_1108 = REPO / "experiments" / "2026-11-08-lux3d-takeout-box" / "input"

INPUT_PX = 240  # shown at ~80-120 css px, 2x for retina
VIEW_PX = 520
RENDER_PX = 1040  # rendered at 2x, then downsampled: MuJoCo's own antialiasing is light
BACKGROUND = (0.937, 0.953, 0.965)  # matches the slide's plate in story.css
AZIMUTHS = (55.0, 0.0, 235.0)  # front three-quarter, side, back three-quarter (models face -y: azimuth 90 is front)
ELEVATION = -14.0
FRAME_DISTANCE = 1.35  # x the bounding-box diagonal, so tall figures and near-cubes both fit with a margin
WEBP_QUALITY = 82


@dataclass(frozen=True)
class Gallery:
    inputs: tuple[Path, ...]  # in the order they were given to Lux3D; the first is the main image


def views(folder: str) -> tuple[Path, ...]:
    return tuple(sorted((LUX3D_1118 / folder).glob("*.png")))


GALLERIES: dict[str, Gallery] = {
    "takeout_box": Gallery((LUX3D_1108 / "takeout_box_input.png",)),
    "labubu": Gallery((LUX3D_1118 / "labubu_original_v3.png", *views("labubu_views"))),
    "twinkle_devil": Gallery(views("twinkle_devil_views")),
    "airpods": Gallery((LUX3D_1118 / "airpods_pro3_open.png", *views("airpods_pro3_open_views"))),
    "aholo_mascot": Gallery((LUX3D_1118 / "aholo_mascot.png", *views("aholo_mascot_views"))),
    "tamagotchi": Gallery((LUX3D_1118 / "tamagotchi.png", *views("tamagotchi_views"))),
    "insta360_x5": Gallery(views("insta360_x5_views")),
    "insta360_go3s": Gallery((LUX3D_1118 / "insta360_go3s.png", *views("insta360_go3s_views"))),
}


def square_on_white(path: Path, size: int) -> Image.Image:
    """Fit an input image into a white square (inputs mix transparent and coloured backgrounds)."""
    image = Image.open(path).convert("RGBA")
    image.thumbnail((size, size), Image.LANCZOS)
    plate = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    plate.alpha_composite(image, ((size - image.width) // 2, (size - image.height) // 2))
    return plate.convert("RGB")


def scene_xml(folder: Path) -> str:
    r, g, b = BACKGROUND
    return f"""<mujoco><compiler meshdir="{folder}" texturedir="{folder}"/>
    <visual><global offwidth="{RENDER_PX}" offheight="{RENDER_PX}"/><quality shadowsize="4096"/>
      <headlight ambient="0.5 0.5 0.5" diffuse="0.45 0.45 0.45" specular="0.05 0.05 0.05"/></visual>
    <asset><texture type="skybox" builtin="flat" rgb1="{r} {g} {b}" rgb2="{r} {g} {b}" width="8" height="8"/>
      <texture type="2d" name="t" file="texture.png"/><material name="m" texture="t" specular="0.15"/>
      <mesh name="v" file="visual.obj"/></asset>
    <worldbody><light pos="0.4 -0.5 0.9" dir="-0.4 0.5 -0.9" directional="true" diffuse="0.55 0.55 0.55"/>
      <geom type="mesh" mesh="v" material="m"/></worldbody></mujoco>"""


def render_views(name: str) -> list[Image.Image]:
    folder = OBJECTS_DIR / name
    size = json.loads((folder / "meta.json").read_text())["size_m"]
    model = mujoco.MjModel.from_xml_string(scene_xml(folder))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    camera = mujoco.MjvCamera()
    camera.lookat[:] = [0.0, 0.0, size[2] / 2]
    camera.distance = math.dist((0, 0, 0), size) * FRAME_DISTANCE
    camera.elevation = ELEVATION
    images = []
    with mujoco.Renderer(model, RENDER_PX, RENDER_PX) as renderer:
        for azimuth in AZIMUTHS:
            camera.azimuth = azimuth
            renderer.update_scene(data, camera)
            images.append(Image.fromarray(renderer.render()).resize((VIEW_PX, VIEW_PX), Image.LANCZOS))
    return images


def main() -> int:
    missing = [name for name in GALLERIES if not (OBJECTS_DIR / name / "visual.obj").exists()]
    missing += [str(p) for g in GALLERIES.values() for p in g.inputs if not p.exists()]
    if missing:
        print("missing (run sim/prep_object.py --all first):", *missing, sep="\n  ", file=sys.stderr)
        return 1
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    for name, gallery in GALLERIES.items():
        out = OUT_DIR / name
        out.mkdir(parents=True)
        for k, path in enumerate(gallery.inputs, start=1):
            square_on_white(path, INPUT_PX).save(out / f"input-{k}.webp", quality=WEBP_QUALITY)
        for k, image in enumerate(render_views(name), start=1):
            image.save(out / f"view-{k}.webp", quality=WEBP_QUALITY)
        print(f"{name}: {len(gallery.inputs)} inputs, {len(AZIMUTHS)} views")
    return 0


if __name__ == "__main__":
    sys.exit(main())
