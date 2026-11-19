"""Inspect a GLB's real geometry and textures. Usage: inspect_glb.py <file.glb> <out_dir>"""
import io
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import ConvexHull

COMPONENT_DTYPE = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
WELD_TOLERANCE_M = 1e-6


def parse_glb(path):
    data = Path(path).read_bytes()
    _, _, total = struct.unpack("<4sII", data[:12])
    if total != len(data):
        raise ValueError(f"GLB length {total} does not match file size {len(data)}")
    json_len = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20:20 + json_len])
    bin_start = 20 + json_len + 8
    return doc, data[bin_start:]


def read_accessor(doc, blob, index):
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    width = TYPE_WIDTH[acc["type"]]
    out = np.frombuffer(blob, COMPONENT_DTYPE[acc["componentType"]], acc["count"] * width, start)
    return out.reshape(-1, width) if width > 1 else out


def read_image(doc, blob, index):
    view = doc["bufferViews"][doc["images"][index]["bufferView"]]
    start = view.get("byteOffset", 0)
    return Image.open(io.BytesIO(blob[start:start + view["byteLength"]]))


def weld(pos, tol=WELD_TOLERANCE_M):
    keys = np.round(pos / tol).astype(np.int64)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    return inverse.ravel()


def topology(faces, n_verts):
    directed = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    undirected = np.sort(directed, axis=1)
    _, edge_counts = np.unique(undirected, axis=0, return_counts=True)
    _, directed_counts = np.unique(directed, axis=0, return_counts=True)
    used = np.unique(faces)
    graph = coo_matrix(
        (np.ones(len(directed)), (directed[:, 0], directed[:, 1])), shape=(n_verts, n_verts)
    )
    _, labels = connected_components(graph, directed=False)
    used_labels = labels[used]
    comp_ids, _ = np.unique(used_labels, return_counts=True)
    return {
        "verts_used": int(len(used)),
        "edges": int(len(edge_counts)),
        "boundary_edges": int((edge_counts == 1).sum()),
        "manifold_edges": int((edge_counts == 2).sum()),
        "nonmanifold_edges": int((edge_counts > 2).sum()),
        "misoriented_directed_edges": int((directed_counts > 1).sum()),
        "components": int(len(comp_ids)),
        "euler_V-E+F": int(len(used) - len(edge_counts) + len(faces)),
    }, labels


def signed_volume(pos, faces):
    a, b, c = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    return float(np.einsum("ij,ij->", a, np.cross(b, c)) / 6.0)


def report_geometry(doc, blob):
    prim = doc["meshes"][0]["primitives"][0]
    pos = read_accessor(doc, blob, prim["attributes"]["POSITION"]).astype(np.float64)
    nrm = read_accessor(doc, blob, prim["attributes"]["NORMAL"]).astype(np.float64) if "NORMAL" in prim["attributes"] else None
    uv = read_accessor(doc, blob, prim["attributes"]["TEXCOORD_0"]).astype(np.float64) if "TEXCOORD_0" in prim["attributes"] else None
    faces = read_accessor(doc, blob, prim["indices"]).astype(np.int64).reshape(-1, 3)

    print("\n[raw]", topology(faces, len(pos))[0])
    ids = weld(pos)
    welded = ids[faces]
    n_welded = int(ids.max()) + 1
    rep = np.zeros((n_welded, 3))
    rep[ids] = pos

    cross = np.cross(rep[welded[:, 1]] - rep[welded[:, 0]], rep[welded[:, 2]] - rep[welded[:, 0]])
    areas = np.linalg.norm(cross, axis=1) / 2
    collapsed = (
        (welded[:, 0] == welded[:, 1]) | (welded[:, 1] == welded[:, 2]) | (welded[:, 0] == welded[:, 2])
    )
    _, dup_counts = np.unique(np.sort(welded, axis=1), axis=0, return_counts=True)
    print("[faces]", {
        "total": int(len(faces)),
        "collapsed_after_weld": int(collapsed.sum()),
        "near_zero_area": int((areas < 1e-14).sum()),
        "duplicate_extra": int((dup_counts - 1).sum()),
    })

    clean = welded[~collapsed]
    topo, labels = topology(clean, n_welded)
    print("[welded]", topo)
    print("[welded] watertight:", topo["boundary_edges"] == 0 and topo["nonmanifold_edges"] == 0,
          "| consistent winding:", topo["misoriented_directed_edges"] == 0)

    face_labels = labels[clean[:, 0]]
    comp_ids, comp_faces = np.unique(face_labels, return_counts=True)
    print("[components by face count, top 10]")
    for k in np.argsort(-comp_faces)[:10]:
        sel = clean[face_labels == comp_ids[k]]
        pts = rep[np.unique(sel)]
        print(f"  faces={comp_faces[k]:7d} size_m={np.round(np.ptp(pts, axis=0), 4).tolist()} signed_vol_m3={signed_volume(rep, sel):.7f}")

    used = np.unique(clean)
    size = np.ptp(rep[used], axis=0)
    hull = ConvexHull(rep[used])
    volume = signed_volume(rep, clean)
    print("[shape]", {
        "bbox_m": np.round(size, 4).tolist(),
        "bbox_volume_m3": round(float(np.prod(size)), 7),
        "surface_area_m2": round(float(areas[~collapsed].sum()), 5),
        "signed_volume_m3": round(volume, 7),
        "hull_volume_m3": round(float(hull.volume), 7),
        "hull_vertices": int(len(hull.vertices)),
        "volume_over_hull": round(abs(volume) / hull.volume, 3),
        "edge_len_median_mm": round(float(np.median(np.linalg.norm(
            rep[clean[:, 0]] - rep[clean[:, 1]], axis=1))) * 1000, 3),
    })
    if nrm is not None:
        norm_len = np.linalg.norm(nrm, axis=1)
        print("[normals] zero-length:", int((norm_len < 0.5).sum()))
    if uv is not None:
        print("[uv]", {"min": np.round(uv.min(axis=0), 4).tolist(), "max": np.round(uv.max(axis=0), 4).tolist()})
    ymin = rep[used, 1].min()
    low = rep[used][rep[used, 1] < ymin + 0.002][:, [0, 2]]
    if len(low) >= 3:
        print("[bottom] support polygon within 2mm: area_cm2", round(ConvexHull(low).volume * 1e4, 2),
              "x/z extent cm", np.round(np.ptp(low, axis=0) * 100, 2).tolist())
    return pos, uv, faces


def report_textures(doc, blob, out_dir):
    if not doc.get("images"):
        print("\n[textures] none")
        return None
    base = read_image(doc, blob, 0).convert("RGBA")
    base_arr = np.asarray(base)
    print("\n[baseColor]", base.size, "alpha<255 share:", round(float((base_arr[..., 3] < 255).mean()), 4))
    if len(doc["images"]) > 1:
        mr = np.asarray(read_image(doc, blob, 1).convert("RGB")) / 255
        print("[metalRough] G_roughness mean", round(float(mr[..., 1].mean()), 3), "| B_metallic mean", round(float(mr[..., 2].mean()), 3))
    base.convert("RGB").resize((800, 800)).save(out_dir / "basecolor_small.png")
    return base_arr[..., :3] / 255.0


def render(pos, uv, faces, tex, axes, flip, res=620):
    u, v = pos[:, axes[0]] * flip[0], pos[:, axes[1]] * flip[1]
    depth = pos[:, axes[2]] * flip[2]
    scale = (res - 20) / max(np.ptp(u), np.ptp(v))
    px = (u - u.min()) * scale + 10
    py = (v.max() - v) * scale + 10
    zbuf = np.full((res, res), -np.inf)
    img = np.ones((res, res, 3))
    light = np.array([0.3, 0.5, 0.81])
    for tri in faces:
        x, y, z = px[tri], py[tri], depth[tri]
        area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
        if abs(area) < 1e-9:
            continue
        x0, x1 = int(max(x.min(), 0)), int(min(np.ceil(x.max()), res - 1))
        y0, y1 = int(max(y.min(), 0)), int(min(np.ceil(y.max()), res - 1))
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        b1 = ((gx - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (gy - y[0])) / area
        b2 = ((x[1] - x[0]) * (gy - y[0]) - (gx - x[0]) * (y[1] - y[0])) / area
        b0 = 1 - b1 - b2
        inside = (b0 >= -0.02) & (b1 >= -0.02) & (b2 >= -0.02)
        if not inside.any():
            continue
        zs = b0 * z[0] + b1 * z[1] + b2 * z[2]
        visible = inside & (zs > zbuf[gy, gx])
        if not visible.any():
            continue
        p = np.stack([u[tri], v[tri], z], axis=1)
        normal = np.cross(p[1] - p[0], p[2] - p[0])
        normal = normal / max(np.linalg.norm(normal), 1e-20)
        shade = 0.55 + 0.45 * abs(float(normal @ light))
        yy, xx = gy[visible], gx[visible]
        zbuf[yy, xx] = zs[visible]
        if tex is None or uv is None:
            img[yy, xx] = np.array([0.8, 0.8, 0.8]) * shade
            continue
        h, w = tex.shape[:2]
        tu = b0 * uv[tri[0], 0] + b1 * uv[tri[1], 0] + b2 * uv[tri[2], 0]
        tv = b0 * uv[tri[0], 1] + b1 * uv[tri[1], 1] + b2 * uv[tri[2], 1]
        img[yy, xx] = tex[(tv[visible] * h).astype(int) % h, (tu[visible] * w).astype(int) % w] * shade
    return Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))


def main():
    glb_path, out_dir = sys.argv[1], Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    doc, blob = parse_glb(glb_path)
    pos, uv, faces = report_geometry(doc, blob)
    tex = report_textures(doc, blob, out_dir)
    views = [((0, 1, 2), (1, 1, 1)), ((0, 1, 2), (-1, 1, -1)), ((2, 1, 0), (-1, 1, 1)), ((0, 2, 1), (1, -1, 1))]
    sheet = Image.new("RGB", (620 * 4, 620), "white")
    for i, (axes, flip) in enumerate(views):
        sheet.paste(render(pos, uv, faces, tex, axes, flip), (620 * i, 0))
    sheet.save(out_dir / "views_front_back_side_top.png")
    print("\nrendered:", out_dir / "views_front_back_side_top.png")


if __name__ == "__main__":
    main()
