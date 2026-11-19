"""Convert a Lux3D raw_mesh.glb (Y-up glTF) into MuJoCo-ready meshes.

Uniform-scales so the widest side == TARGET_MAX_EXTENT, rotates Y-up -> Z-up,
centers the bounding box at the origin, and exports a full-res STL plus a
decimated OBJ (for browser use).
"""
import sys
from pathlib import Path

import numpy as np
import trimesh

TARGET_MAX_EXTENT = 0.05  # m, SO-101 jaw opening is ~6-7 cm
DECIMATE_FACES = 4000


def load_single_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(str(path))
    return loaded.to_mesh() if isinstance(loaded, trimesh.Scene) else loaded


def normalize(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    out = mesh.copy()
    out.apply_scale(TARGET_MAX_EXTENT / out.extents.max())
    # glTF is Y-up; MuJoCo is Z-up. +90 deg about X maps +Y -> +Z.
    out.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    out.apply_translation(-out.bounds.mean(axis=0))
    return out


def main() -> None:
    src = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh = normalize(load_single_mesh(src))
    mesh.export(out_dir / "box_full.stl")  # NOTE: MuJoCo STL decoder caps at 200k faces
    mesh.export(out_dir / "box_full.obj")
    small = mesh.simplify_quadric_decimation(face_count=DECIMATE_FACES)
    small.export(out_dir / "box_small.obj")
    hull = mesh.convex_hull
    print(f"faces full={len(mesh.faces)} small={len(small.faces)} hull={len(hull.faces)}")
    print(f"extents (x,y,z) m = {np.round(mesh.extents, 4).tolist()}")
    print(f"watertight={mesh.is_watertight} volume={mesh.volume:.3e} m^3 hull_volume={hull.volume:.3e}")


if __name__ == "__main__":
    main()
