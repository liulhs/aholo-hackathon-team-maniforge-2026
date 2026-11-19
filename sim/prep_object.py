"""Turn one Lux3D object into MuJoCo assets: a textured visual mesh and a collision mesh.

For any object in the lift task: uniform scale so the wider horizontal side is
`--grip-width` (what the gripper has to span), glTF Y-up -> MuJoCo Z-up, centred in x/y, bottom
on z=0. The visual keeps its UVs and base-colour texture; MuJoCo collides through the convex
hull of the collision mesh.

Input folder: Lux3D `textured.glb` (looks) and, when there is one, `raw_mesh.glb` (closed mesh,
for collision; without it the textured mesh is used, which is fine for a convex hull).
Output in sim/models/objects/<name>/ (not committed): visual.obj, texture.png, collision.obj,
meta.json (size in metres, face counts, source) and preview.png (four MuJoCo renders).

OBJECTS lists the objects of the lift task. `--all` converts every one of them (run by
fetch_models.sh); a single name with a folder converts something else for a quick look.

    python sim/prep_object.py --all
    python sim/prep_object.py tryout experiments/some-folder --grip-width 0.045
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

REPO = Path(__file__).resolve().parent.parent
OBJECTS_DIR = Path(__file__).resolve().parent / "models" / "objects"
LUX3D_2026_11_18 = "experiments/2026-11-18-lux3d-objects"


@dataclass(frozen=True)
class ObjectSpec:
    """One graspable object. Mass is an assumption, not a measurement."""

    source: str  # folder with the Lux3D output, relative to the repo root
    grip_width_m: float  # its longer horizontal side after scaling; the shorter one must fit the 6-7 cm jaw
    mass_kg: float
    label: str  # shown to people
    lay_flat: bool = False  # rest on its back, front facing up (for things that do not stand)


OBJECTS = {
    "takeout_box": ObjectSpec("experiments/2026-11-08-lux3d-takeout-box/g1_standard", 0.050, 0.03, "外卖盒"),
    "labubu": ObjectSpec(f"{LUX3D_2026_11_18}/labubu_mv", 0.045, 0.04, "Labubu"),
    "twinkle_devil": ObjectSpec(f"{LUX3D_2026_11_18}/twinkle_devil_mv", 0.055, 0.04, "星星人"),
    "airpods": ObjectSpec(f"{LUX3D_2026_11_18}/airpods_open_mv", 0.055, 0.05, "AirPods"),
    "aholo_mascot": ObjectSpec(f"{LUX3D_2026_11_18}/aholo_mascot_mv", 0.050, 0.04, "Aholo 吉祥物"),
    "tamagotchi": ObjectSpec(f"{LUX3D_2026_11_18}/tamagotchi_mv", 0.045, 0.04, "拓麻歌子"),
    "insta360_x5": ObjectSpec(f"{LUX3D_2026_11_18}/insta360_x5_mv", 0.036, 0.06, "Insta360 X5"),
    "insta360_go3s": ObjectSpec(f"{LUX3D_2026_11_18}/insta360_go3s_mv", 0.036, 0.04, "Insta360 GO 3S"),
}
BASE_SLICE = 0.08
Y_UP_TO_Z_UP = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
FRONT_TO_TOP = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])  # the front (-y) turns to face +z


def load_single_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(str(path))
    return loaded.to_mesh() if isinstance(loaded, trimesh.Scene) else loaded


def placement(reference: trimesh.Trimesh, grip_width_m: float, lay_flat: bool = False) -> np.ndarray:
    """4x4 transform that sets `reference` on z=0 (upright, or on its back), centred, with its wider
    horizontal side scaled to grip_width_m."""
    orient = FRONT_TO_TOP @ Y_UP_TO_Z_UP if lay_flat else Y_UP_TO_Z_UP
    oriented = reference.copy()
    oriented.apply_transform(orient)
    low, high = oriented.bounds
    scale = grip_width_m / max(high[0] - low[0], high[1] - low[1])
    shift = trimesh.transformations.translation_matrix([-(low[0] + high[0]) / 2, -(low[1] + high[1]) / 2, -low[2]])
    return trimesh.transformations.scale_matrix(scale) @ shift @ orient


def write_obj_with_uv(path: Path, vertices: np.ndarray, uv: np.ndarray, faces: np.ndarray) -> None:
    """Minimal OBJ: one UV per vertex, faces as v/vt (trimesh drops UVs when told to skip the .mtl)."""
    lines = [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in vertices]
    lines += [f"vt {u:.6f} {v:.6f}" for u, v in uv]
    lines += [f"f {a}/{a} {b}/{b} {c}/{c}" for a, b, c in faces + 1]
    path.write_text("\n".join(lines) + "\n")


def flat_bottomed(hull: trimesh.Trimesh) -> trimesh.Trimesh:
    """The hull with its lowest BASE_SLICE pressed flat onto z=min, so a rounded bottom (the AirPods
    case) rests on a face instead of rocking on a point. Changes the shape by a few millimetres."""
    vertices = hull.vertices.copy()
    floor = vertices[:, 2].min()
    vertices[vertices[:, 2] <= floor + BASE_SLICE * np.ptp(vertices[:, 2]), 2] = floor
    return trimesh.Trimesh(vertices).convex_hull


def convert(name: str, source: Path, grip_width_m: float, lay_flat: bool = False) -> dict:
    out = OBJECTS_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    visual = load_single_mesh(source / "textured.glb")
    raw = source / "raw_mesh.glb"  # closed mesh from the web task record; not always available
    collision = load_single_mesh(raw if raw.exists() else source / "textured.glb")
    image = getattr(visual.visual.material, "baseColorTexture", None) or getattr(visual.visual.material, "image", None)
    if image is None or visual.visual.uv is None:
        raise ValueError(f"{source / 'textured.glb'} has no base-colour texture or UVs")
    transform = placement(visual, grip_width_m, lay_flat)  # both meshes share one transform, so they stay aligned
    visual.apply_transform(transform)
    collision.apply_transform(transform)
    image.convert("RGB").save(out / "texture.png")
    write_obj_with_uv(out / "visual.obj", visual.vertices, np.asarray(visual.visual.uv), visual.faces)
    hull = flat_bottomed(collision.convex_hull)  # MuJoCo collides through the hull anyway
    hull.export(out / "collision.obj")
    meta = {
        "name": name,
        "source": str(source),
        "size_m": [round(float(v), 4) for v in visual.extents],
        "visual_faces": int(len(visual.faces)),
        "texture_px": list(image.size),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def render_preview(name: str) -> None:
    import mujoco
    from PIL import Image

    out = OBJECTS_DIR / name
    size = json.loads((out / "meta.json").read_text())["size_m"]
    xml = f"""<mujoco><compiler meshdir="{out}" texturedir="{out}"/>
    <visual><global offwidth="1280" offheight="960"/><headlight ambient="0.55 0.55 0.55" diffuse="0.5 0.5 0.5"/></visual>
    <asset><texture type="skybox" builtin="gradient" rgb1="0.95 0.95 0.95" rgb2="0.8 0.8 0.8" width="32" height="192"/>
      <texture type="2d" name="t" file="texture.png"/><material name="m" texture="t" specular="0.1"/>
      <mesh name="v" file="visual.obj"/><mesh name="c" file="collision.obj"/></asset>
    <worldbody><light pos="0.3 -0.3 0.6" dir="-0.3 0.3 -1" directional="true"/>
      <geom type="plane" size="1 1 0.1" rgba="0.82 0.82 0.80 1"/>
      <geom type="box" size="0.025 0.025 0.025" pos="{size[0] / 2 + 0.05} 0 0.025" rgba="0.9 0.2 0.2 1"/>
      <geom type="mesh" mesh="v" material="m"/>
      <geom type="mesh" mesh="c" pos="{-size[0] - 0.03} 0 0" rgba="0.3 0.6 0.9 0.6"/>
    </worldbody></mujoco>"""
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, 480, 640)
    camera = mujoco.MjvCamera()
    camera.lookat[:] = [0, 0, size[2] / 2]
    camera.lookat[0] = -size[0] / 4
    camera.distance, camera.elevation = max(size) * 2.6 + 0.08, -18
    sheet = Image.new("RGB", (1280, 960))
    for i, azimuth in enumerate((90, 180, 270, 0)):  # front, right, back, left of a model that faces -y
        camera.azimuth = azimuth
        renderer.update_scene(data, camera)
        sheet.paste(Image.fromarray(renderer.render()), ((i % 2) * 640, (i // 2) * 480))
    sheet.save(out / "preview.png")
    renderer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", nargs="?", help="object name, [a-z0-9_]")
    parser.add_argument("source", nargs="?", type=Path, help="folder with Lux3D textured.glb and raw_mesh.glb")
    parser.add_argument("--grip-width", type=float, default=0.05, help="wider horizontal side in metres (jaw opens 6-7 cm)")
    parser.add_argument("--all", action="store_true", help="convert every object in OBJECTS")
    args = parser.parse_args()
    if args.all:
        jobs = [(name, REPO / spec.source, spec.grip_width_m, spec.lay_flat) for name, spec in OBJECTS.items()]
    elif args.name and args.source:
        jobs = [(args.name, args.source, args.grip_width, False)]
    else:
        parser.error("give --all, or a name and a source folder")
    for name, source, grip_width, lay_flat in jobs:
        if not (source / "textured.glb").exists():
            print(f"SKIPPED {name}: {source / 'textured.glb'} is missing (Lux3D output is not in git)", file=sys.stderr)
            continue
        meta = convert(name, source, grip_width, lay_flat)
        render_preview(name)
        print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
