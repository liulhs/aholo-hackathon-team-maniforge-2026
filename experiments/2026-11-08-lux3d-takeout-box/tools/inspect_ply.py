"""Summarize and render a 3D Gaussian PLY. Usage: inspect_ply.py <file.ply> <out.png>"""
import sys

import numpy as np
from PIL import Image

SH_C0 = 0.28209479177387814
RES = 620


def load(path):
    raw = open(path, "rb").read()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    lines = raw[:end].split(b"\n")
    props = [line.split()[-1].decode() for line in lines if line.startswith(b"property")]
    count = int([line for line in lines if line.startswith(b"element vertex")][0].split()[-1])
    arr = np.frombuffer(raw, "<f4", count * len(props), end).reshape(count, len(props))
    return {p: arr[:, i] for i, p in enumerate(props)}, len(raw)


def main():
    col, size = load(sys.argv[1])
    xyz = np.stack([col["x"], col["y"], col["z"]], 1).astype(np.float64)
    rgb = np.clip(0.5 + SH_C0 * np.stack([col["f_dc_0"], col["f_dc_1"], col["f_dc_2"]], 1), 0, 1)
    opacity = 1 / (1 + np.exp(-col["opacity"]))
    scale = np.exp(np.stack([col["scale_0"], col["scale_1"], col["scale_2"]], 1))
    print({
        "gaussians": len(xyz), "bytes": size, "fields": list(col),
        "bbox_m": np.round(np.ptp(xyz, 0), 4).tolist(),
        "center": np.round((xyz.max(0) + xyz.min(0)) / 2, 4).tolist(),
        "scale_median_mm": np.round(np.median(scale, 0) * 1000, 3).tolist(),
        "opacity_median": round(float(np.median(opacity)), 3),
        "opacity_lt_0.1_share": round(float((opacity < 0.1).mean()), 3),
    })
    keep = opacity > 0.05
    u, v, depth = xyz[keep, 0], xyz[keep, 1], xyz[keep, 2]
    px = ((u - u.min()) / max(np.ptp(u), np.ptp(v)) * (RES - 20) + 10).astype(int)
    py = ((v.max() - v) / max(np.ptp(u), np.ptp(v)) * (RES - 20) + 10).astype(int)
    order = np.argsort(depth)
    img = np.ones((RES, RES, 3))
    img[py[order], px[order]] = rgb[keep][order]
    Image.fromarray((img * 255).astype(np.uint8)).save(sys.argv[2])


if __name__ == "__main__":
    main()
