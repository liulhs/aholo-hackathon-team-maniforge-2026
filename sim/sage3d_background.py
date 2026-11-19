"""Cut a SAGE-3D / InteriorGS room into a Gaussian-splat background for the web demo.

Input: one scene of the SAGE-3D_InteriorGS_usdz dataset (Manycore / SpatialVerse, CC-BY-NC-4.0,
https://huggingface.co/datasets/spatialverse/SAGE-3D_InteriorGS_usdz). Each .usdz holds a NVIDIA
3DGRUT .nurec file: gzip + msgpack, float16 arrays of Gaussian positions, rotations (w, x, y, z),
log scales, opacity logits, SH colour (features_albedo = degree 0, features_specular = degrees 1-3).
Positions are in InteriorGS's frame: metres, x right, y back, z up, floor at z ~ 0.

The background is visual only: the robot's physics scene is unchanged. The room is moved so that
`--spot` (a free patch of floor in room coordinates) lies under the sim table's centre, the floor at
the sim floor (z = -TABLE_HEIGHT_M), and turned by `--yaw-deg` about z. Splats farther than
`--radius` from the spot, near-transparent ones and stray ones below the floor are dropped, and only
the degree-0 colour is kept (size). Output: a standard 3DGS PLY in the sim frame, which
@playcanvas/splat-transform then packs into the .sog the page loads:

    python sim/sage3d_background.py data/sage3d/839920.usdz --spot 1.3 -3.6 --yaw-deg 139.5 --out data/sage3d/restaurant_839920.ply
    cd web && npx splat-transform ../data/sage3d/restaurant_839920.ply public/background/restaurant_839920.sog
"""

import argparse
import gzip
import zipfile
from pathlib import Path

import msgpack
import numpy as np

from simple_table import TABLE_CENTER_X_M, TABLE_HEIGHT_M

PREFIX = ".gaussians_nodes.gaussians."
FLOOR_SLACK_M = 0.3  # keep splats down to this far below the room's floor (z = 0)


def read_nurec(usdz: Path) -> dict[str, np.ndarray]:
    with zipfile.ZipFile(usdz) as z:
        name = next(n for n in z.namelist() if n.endswith(".nurec"))
        state = msgpack.unpackb(gzip.decompress(z.read(name)), raw=False, strict_map_key=False)["nre_data"]["state_dict"]
    out = {}
    for field in ("positions", "rotations", "scales", "densities", "features_albedo"):
        key = PREFIX + field
        out[field] = np.frombuffer(state[key], dtype=np.float16).reshape(state[key + ".shape"]).astype(np.float32)
    return out


def yaw_quaternion(yaw: float) -> np.ndarray:
    return np.array([np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)], np.float32)


def quat_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a * b for one quaternion a and rows b, both (w, x, y, z)."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b.T
    return np.stack([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ], axis=1)


def place(g: dict[str, np.ndarray], spot: np.ndarray, yaw: float, radius: float, min_opacity: float, max_z: float) -> dict[str, np.ndarray]:
    p = g["positions"]
    opacity = 1 / (1 + np.exp(-g["densities"][:, 0]))
    keep = (np.hypot(p[:, 0] - spot[0], p[:, 1] - spot[1]) < radius) & (p[:, 2] > -FLOOR_SLACK_M) & (p[:, 2] < max_z) & (opacity > min_opacity)
    c, s = np.cos(yaw), np.sin(yaw)
    rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float32)
    local = p[keep] - np.array([spot[0], spot[1], 0], np.float32)
    moved = np.einsum("ij,nj->ni", rot, local) + np.array([TABLE_CENTER_X_M, 0, -TABLE_HEIGHT_M], np.float32)
    q = g["rotations"][keep]
    q = quat_multiply(yaw_quaternion(yaw), q / np.linalg.norm(q, axis=1, keepdims=True))
    return {"positions": moved, "rotations": q, "scales": g["scales"][keep], "densities": g["densities"][keep], "features_albedo": g["features_albedo"][keep]}


def write_ply(g: dict[str, np.ndarray], path: Path) -> None:
    names = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    columns = np.concatenate([g["positions"], g["features_albedo"], g["densities"], g["scales"], g["rotations"]], axis=1).astype("<f4")
    header = "ply\nformat binary_little_endian 1.0\n" f"element vertex {len(columns)}\n" + "".join(f"property float {n}\n" for n in names) + "end_header\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(header.encode("ascii"))
        f.write(columns.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("usdz", type=Path)
    parser.add_argument("--spot", type=float, nargs=2, required=True, metavar=("X", "Y"), help="free floor in room coordinates (m) that goes under the sim table")
    parser.add_argument("--yaw-deg", type=float, default=0.0, help="turn the room about z by this much")
    parser.add_argument("--radius", type=float, default=6.0, help="keep splats within this distance of the spot (m)")
    parser.add_argument("--max-z", type=float, default=3.4, help="drop splats above this height in the room (m)")
    parser.add_argument("--min-opacity", type=float, default=0.05)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    g = read_nurec(args.usdz)
    placed = place(g, np.array(args.spot, np.float32), np.radians(args.yaw_deg), args.radius, args.min_opacity, args.max_z)
    write_ply(placed, args.out)
    print(f"{len(g['positions'])} splats in the room, {len(placed['positions'])} kept -> {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
