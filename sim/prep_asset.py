"""Turn a downloaded 3D model (glTF/GLB/OBJ) into a MuJoCo-ready desk prop.

Output in sim/models/props/<name>/ (not committed):
    part_<i>.obj        visual meshes with UVs, one per material
    part_<i>.png        base-colour texture of that part, when it has one
    collision.obj       convex hull of the whole model
    meta.json           parts (texture or rgba), size in metres, source and licence
    preview.png         four MuJoCo renders next to a 10 cm cube, proving it loads

The model is rotated to Z-up, scaled uniformly so one dimension has its real-world size, centred
in x/y and set down on z=0. Meshes keep their UVs, so nothing is decimated here: pick sources
under FACE_BUDGET triangles, or simplify first with a UV-preserving tool (e.g. gltfpack -si).

    python -I sim/prep_asset.py mug raw/mug.glb --height 0.095 \\
        --source-url https://... --license CC0 --author "..."
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh

PROPS_DIR = Path(__file__).resolve().parent / "models" / "props"
FACE_BUDGET = 60_000
Y_UP_TO_Z_UP = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
AXES = {"x": 0, "y": 1, "z": 2}


def load_parts(path: Path) -> list[trimesh.Trimesh]:
    scene = trimesh.load(str(path), force="scene")
    parts = [m for m in scene.dump(concatenate=False) if isinstance(m, trimesh.Trimesh) and len(m.faces) > 0]
    if not parts:
        raise ValueError(f"No triangle meshes in {path}")
    return parts


def part_look(mesh: trimesh.Trimesh):
    """(texture image or None, rgba) for one part."""
    material = getattr(mesh.visual, "material", None)
    image = getattr(material, "baseColorTexture", None) if material is not None else None
    if image is None and material is not None:
        image = getattr(material, "image", None)
    has_uv = getattr(mesh.visual, "uv", None) is not None
    factor = getattr(material, "baseColorFactor", None) if material is not None else None
    if factor is None and material is not None:
        factor = getattr(material, "main_color", None)
    if factor is None and mesh.visual.kind in ("vertex", "face"):
        factor = np.asarray(mesh.visual.vertex_colors).mean(axis=0)
    rgba = [0.7, 0.7, 0.7, 1.0] if factor is None else (np.asarray(factor, dtype=float) / (255.0 if np.max(factor) > 1 else 1.0)).tolist()
    rgba = (rgba + [1.0])[:4]
    return (image if has_uv else None), rgba


def write_obj(path: Path, mesh: trimesh.Trimesh, with_uv: bool) -> None:
    lines = [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in mesh.vertices]
    if with_uv:
        lines += [f"vt {u:.6f} {v:.6f}" for u, v in np.asarray(mesh.visual.uv)]
        lines += [f"f {a}/{a} {b}/{b} {c}/{c}" for a, b, c in mesh.faces + 1]
    else:
        lines += [f"f {a} {b} {c}" for a, b, c in mesh.faces + 1]
    path.write_text("\n".join(lines) + "\n")


def normalize(parts: list[trimesh.Trimesh], up: str, yaw_deg: float, target_m: float, target_axis: str) -> np.ndarray:
    """Transform all parts in place; returns the final size (x, y, z) in metres."""
    for part in parts:
        if up == "y":
            part.apply_transform(Y_UP_TO_Z_UP)
        if yaw_deg:
            part.apply_transform(trimesh.transformations.rotation_matrix(np.radians(yaw_deg), [0, 0, 1]))
    bounds = np.array([[p.bounds[0] for p in parts], [p.bounds[1] for p in parts]])
    low, high = bounds[0].min(axis=0), bounds[1].max(axis=0)
    size = high - low
    current = size.max() if target_axis == "longest" else size[AXES[target_axis]]
    scale = target_m / current
    shift = -np.array([(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]])
    for part in parts:
        part.apply_translation(shift)
        part.apply_scale(scale)
    return size * scale


def export(name: str, parts: list[trimesh.Trimesh], size: np.ndarray, info: dict) -> Path:
    out = PROPS_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    meta_parts = []
    for i, part in enumerate(parts):
        image, rgba = part_look(part)
        entry = {"obj": f"part_{i}.obj", "faces": int(len(part.faces)), "rgba": [round(float(c), 4) for c in rgba]}
        write_obj(out / entry["obj"], part, with_uv=image is not None)
        if image is not None:
            entry["texture"] = f"part_{i}.png"
            image.convert("RGB").save(out / entry["texture"])
        meta_parts.append(entry)
    hull = trimesh.util.concatenate([trimesh.Trimesh(p.vertices, p.faces, process=False) for p in parts]).convex_hull
    hull.export(out / "collision.obj")
    total = sum(p["faces"] for p in meta_parts)
    meta = {"name": name, "size_m": [round(float(v), 4) for v in size], "faces": total, "parts": meta_parts, **info}
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    if total > FACE_BUDGET:
        print(f"WARNING: {total} faces is over the {FACE_BUDGET} budget; simplify the source first", file=sys.stderr)
    return out


def prop_xml(name: str, meta: dict, rel_dir: str, tex_dir: str | None = None, solid: bool = True) -> tuple[str, str]:
    """(asset XML, geom XML for inside a <body>) for one prop.

    Mesh files are looked up under `rel_dir`, textures under `tex_dir` (MuJoCo resolves the two
    against different base directories). `solid=False` leaves out the collision hull.
    """
    tex_dir = rel_dir if tex_dir is None else tex_dir
    assets, geoms = [], []
    for i, part in enumerate(meta["parts"]):
        key = f"{name}_{i}"
        assets.append(f'<mesh name="{key}" file="{rel_dir}/{name}/{part["obj"]}"/>')
        if "texture" in part:
            assets.append(f'<texture type="2d" name="{key}" file="{tex_dir}/{name}/{part["texture"]}"/>')
            assets.append(f'<material name="{key}" texture="{key}" specular="0.15" shininess="0.3"/>')
        else:
            rgba = " ".join(str(c) for c in part["rgba"])
            assets.append(f'<material name="{key}" rgba="{rgba}" specular="0.15" shininess="0.3"/>')
        geoms.append(f'<geom type="mesh" mesh="{key}" material="{key}" group="2" contype="0" conaffinity="0" mass="0"/>')
    if solid:
        assets.append(f'<mesh name="{name}_collision" file="{rel_dir}/{name}/collision.obj"/>')
        geoms.append(f'<geom name="prop_{name}" type="mesh" mesh="{name}_collision" group="3" rgba="1 1 1 0"/>')
    return "\n    ".join(assets), "\n      ".join(geoms)


def render_preview(name: str) -> None:
    import mujoco
    from PIL import Image

    out = PROPS_DIR / name
    meta = json.loads((out / "meta.json").read_text())
    assets, geoms = prop_xml(name, meta, str(PROPS_DIR))
    reach = max(meta["size_m"])
    xml = f"""<mujoco><visual><global offwidth="1280" offheight="960"/><headlight ambient="0.5 0.5 0.5"/></visual>
    <asset>{assets}</asset><worldbody><light pos="1 -1 2" dir="-1 1 -2" directional="true"/>
    <geom type="plane" size="3 3 0.1" rgba="0.8 0.8 0.8 1"/>
    <geom type="box" size="0.05 0.05 0.05" pos="{reach / 2 + 0.12} 0 0.05" rgba="0.9 0.2 0.2 1"/>
    <body>{geoms}</body></worldbody></mujoco>"""
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, 480, 640)
    camera = mujoco.MjvCamera()
    camera.lookat[:] = [0, 0, meta["size_m"][2] / 2]
    camera.distance, camera.elevation = max(0.5, reach * 2.6), -22
    sheet = Image.new("RGB", (1280, 960))
    for i, azimuth in enumerate((0, 90, 180, 270)):  # azimuth 0 looks along +x, 90 along +y
        camera.azimuth = azimuth
        renderer.update_scene(data, camera)
        sheet.paste(Image.fromarray(renderer.render()), ((i % 2) * 640, (i // 2) * 480))
    sheet.save(out / "preview.png")
    renderer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="prop name, [a-z0-9_]")
    parser.add_argument("source", type=Path)
    size = parser.add_mutually_exclusive_group(required=True)
    size.add_argument("--height", type=float, help="real height in metres")
    size.add_argument("--width-x", type=float, help="real size along x in metres (after yaw)")
    size.add_argument("--width-y", type=float, help="real size along y in metres (after yaw)")
    size.add_argument("--longest", type=float, help="real size of the longest side in metres")
    parser.add_argument("--up", choices=("y", "z"), default="y", help="up axis of the source (glTF is y)")
    parser.add_argument("--yaw", type=float, default=0.0, help="degrees about the up axis, applied after up-conversion")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--author", required=True)
    args = parser.parse_args()

    if args.height:
        target, axis = args.height, "z"
    elif args.width_x:
        target, axis = args.width_x, "x"
    elif args.width_y:
        target, axis = args.width_y, "y"
    else:
        target, axis = args.longest, "longest"
    parts = load_parts(args.source)
    size_m = normalize(parts, args.up, args.yaw, target, axis)
    info = {"source_url": args.source_url, "license": args.license, "author": args.author, "source_file": args.source.name}
    out = export(args.name, parts, size_m, info)
    render_preview(args.name)
    print(f"{args.name}: size {np.round(size_m, 3).tolist()} m, {sum(len(p.faces) for p in parts)} faces, {len(parts)} parts -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
