"""Images for the web page's "import into physics" carousel: each object standing in the grasp
scene, the arm in its start pose, seen from the web demo's default angle but closer in.

    .venv/bin/python sim/build_scene_gallery.py

Builds each scene with sim/lift_scene.py (needs the converted models, sim/prep_object.py --all),
lets the object settle, and writes web/public/media/scene/<name>.webp.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import mujoco
from PIL import Image

import lift_scene
from prep_object import OBJECTS

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "web" / "public" / "media" / "scene"
MANIFEST = REPO / "web" / "public" / "scenes" / "manifest.json"

WIDTH, HEIGHT = 1280, 720  # the scene's offscreen buffer size
OUT_WIDTH = 1120
POSE = lift_scene.ObjectPose(x=0.235, y=0.0, yaw=math.radians(38))  # mat centre, front (-y) turned to the camera
LOOK_AT = (0.19, 0.0, 0.07)
AZIMUTH, ELEVATION, DISTANCE = 132.0, -24.0, 0.42  # web/src/render/sceneView.ts WIDE_VIEW, nearer
SETTLE_S = 0.5
WEBP_QUALITY = 80


def render(name: str, start_pose: list[float], joint_names: list[str]) -> Image.Image:
    model, data = lift_scene.load(name)
    for joint, angle in zip(joint_names, start_pose):
        data.qpos[model.joint(joint).qposadr[0]] = angle
        data.ctrl[model.actuator(joint).id] = angle
    lift_scene.place_object(model, data, POSE)
    for _ in range(round(SETTLE_S / model.opt.timestep)):
        mujoco.mj_step(model, data)
    with mujoco.Renderer(model, HEIGHT, WIDTH) as renderer:
        camera = mujoco.MjvCamera()
        camera.lookat[:] = LOOK_AT
        camera.azimuth, camera.elevation, camera.distance = AZIMUTH, ELEVATION, DISTANCE
        renderer.update_scene(data, camera)
        frame = Image.fromarray(renderer.render())
    return frame.resize((OUT_WIDTH, round(OUT_WIDTH * HEIGHT / WIDTH)), Image.LANCZOS)


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    for name in OBJECTS:
        render(name, manifest["start_pose_rad"], manifest["joint_names"]).save(OUT_DIR / f"{name}.webp", quality=WEBP_QUALITY)
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
