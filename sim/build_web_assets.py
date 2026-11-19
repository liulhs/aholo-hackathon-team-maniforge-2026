"""Build what the web demo loads: one compiled MuJoCo model (.mjb.gz) per object, a manifest and thumbnails.

Each web scene is the training scene (lift_scene.scene_path, read, never rewritten) with lighter
looks only: the object's visual mesh decimated to at most MAX_VISUAL_FACES faces with its UVs
kept, its texture shrunk to at most MAX_TEXTURE_PX, and the arm's visual-only meshes (no geom
that collides uses them) decimated to about ARM_VISUAL_FACES faces in all. Collision meshes,
masses, joints, actuators and options are untouched. The decimated assets and a readable copy
of the web scene go to --build-dir (sim/models/web/<object>/ and sim/models/web/arm/, not in
git); the page's files go to --out-dir: <object>.mjb.gz (gzip of the .mjb, unpacked by the
page), thumbs/<object>.png and manifest.json (constants and addresses the page needs).

`--verify` then proves the .mjb physics equals the training scene's: no model field outside
looks (meshes, textures, BVHs, and the rows of the visual-only geoms whose mesh was lightened)
may differ, every recorded episode of the object (data/so101_table_lift_<object>) must replay
bit for bit on the .mjb, and every object also runs recorded arm commands in both models side
by side (max state difference).

    source .venv/bin/activate
    OMP_NUM_THREADS=4 python sim/build_web_assets.py --out-dir web/public/scenes --verify
    python sim/build_web_assets.py --objects labubu airpods --out-dir web/public/scenes
    python sim/build_web_assets.py --out-dir web/public/scenes --no-build --verify   # check what is there

Needs pymeshlab (arm decimation; fast_simplification stalls at about a third of these CAD
meshes' faces): uv pip install --python .venv/bin/python pymeshlab==2025.7.post1
"""

import argparse
import contextlib
import gzip
import json
import os
import sys
from pathlib import Path

import fast_simplification
import mujoco
import numpy as np
import pandas as pd
import trimesh
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

import lift_scene as scene
from build_state_dataset import MIN_UPRIGHT, ON_TABLE_M, STATE_KEY
from prep_object import OBJECTS, OBJECTS_DIR, write_obj_with_uv
from record import FPS, SIM_STATE_KEY, SIM_STATE_SPEC, default_root, steps_per_frame
from so101_mapping import JOINT_NAMES

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_DIR = scene.SIM_DIR / "models" / "web"
STATE_DATASET = REPO / "data" / "so101_state_all8"  # the trained policy's dataset: start poses, trained objects
MAX_VISUAL_FACES = 30_000  # 20k was tried: no loss on labubu, visible facets on the airpods
MAX_TEXTURE_PX = 1024
ARM_DIR = "arm"  # under --build-dir: the decimated arm meshes, shared by every scene
ARM_VISUAL_FACES = 60_000  # all arm visual-only meshes together (336k in Menagerie's STLs)
ARM_MIN_FACES = 1_500  # no arm mesh goes below this; smaller ones (the 1,254-face mounting plate) stay as they are
ARM_FIXED_FACES = {"base_so101_v2": 4_700}  # its waffle grid turns to facets at the even share (~1,700)
ARM_QUALITY_THR = 0.8  # meshlab's penalty on thin triangles; 0.3 left dark slivers around the servo horn's holes
MJB_SUFFIX = ".mjb.gz"
GZIP_LEVEL = 9
KEEPOUT_PAD_M = 0.01  # start_pose_keepout = blocked box grown by this (real overlaps reach ~1 cm past the grid)
THUMB_PX, THUMB_SUPERSAMPLE = 320, 3
THUMB_AZIMUTH, THUMB_ELEVATION = 70.0, -18.0  # front-right three-quarter view of a model facing -y
THUMB_MARGIN = 1.05  # camera distance over the one that just fits the bounding sphere
THUMB_BACKGROUND = (0.94, 0.94, 0.93)  # also what bleeds into the anti-aliased edge
CLEARANCE_STEP_M = 0.01  # start-pose check: objects on a 1 cm grid over the play area
CLEARANCE_YAWS_DEG = (0, 45, 90, 135)
SCRIPTED_EPISODES = 5  # recorded command sequences run side by side in both models
SCRIPTED_SOURCE = "labubu"  # whose recorded commands drive objects without their own dataset
FULL_STATE = mujoco.mjtState.mjSTATE_FULLPHYSICS


# ---------------------------------------------------------------- decimation keeping UVs


def uv_charts(faces: np.ndarray, vertex_count: int) -> np.ndarray:
    """Connected-component label per vertex. The mesh is split at UV seams, so a component is one UV chart."""
    edges = faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(vertex_count, vertex_count))
    return connected_components(graph, directed=False)[1]


def corner_uvs(
    points: np.ndarray, out_faces: np.ndarray, cluster: np.ndarray, vertices: np.ndarray, uv: np.ndarray, faces: np.ndarray, weld: np.ndarray
) -> tuple[np.ndarray, int]:
    """UV for every corner of every decimated face, all three from one chart of the original mesh.

    `points`/`out_faces` are the decimated mesh, `cluster` maps each welded vertex to the
    decimated vertex it collapsed into, `weld` each original vertex to its welded one. The
    face's chart is that of the original face nearest its centroid. A corner's UV comes from
    projecting its position onto the original faces of that chart around the vertices that
    collapsed into it; a corner whose collapsed vertices never touched that chart (a face that
    straddles a seam; 1-6% of corners) is projected onto the chart's nearby faces instead.
    Returns the UVs (3 per face, face order) and how many corners took that fallback.
    """
    chart = uv_charts(faces, len(vertices))[faces[:, 0]]
    chart_count = int(chart.max()) + 1
    corner_out = cluster[weld[faces]]  # decimated vertex each original corner collapsed into
    pairs = np.unique(np.column_stack([corner_out.ravel(), np.repeat(np.arange(len(faces)), 3)]), axis=0)
    triangles = vertices[faces[pairs[:, 1]]]
    nearest = trimesh.triangles.closest_point(triangles, points[pairs[:, 0]])
    distance = np.linalg.norm(nearest - points[pairs[:, 0]], axis=1)
    key = pairs[:, 0] * chart_count + chart[pairs[:, 1]]
    order = np.lexsort((distance, key))
    keys, first = np.unique(key[order], return_index=True)
    best = order[first]  # per (decimated vertex, chart): the closest original face and point
    bary = trimesh.triangles.points_to_barycentric(triangles[best], nearest[best])
    key_uv = np.einsum("ni,nij->nj", bary, uv[faces[pairs[best, 1]]])

    tree = cKDTree(vertices[faces].mean(axis=1))  # original face centroids
    face_chart = chart[tree.query(points[out_faces].mean(axis=1))[1]]
    wanted = out_faces * chart_count + face_chart[:, None]
    slot = np.minimum(np.searchsorted(keys, wanted), len(keys) - 1)
    found = keys[slot] == wanted
    result = key_uv[slot]
    missing = np.argwhere(~found)
    for face, corner in missing:
        result[face, corner] = project_into_chart(points[out_faces[face, corner]], face_chart[face], tree, chart, vertices, uv, faces)
    return result.reshape(-1, 2), len(missing)


def project_into_chart(
    point: np.ndarray, chart_id: int, tree: cKDTree, chart: np.ndarray, vertices: np.ndarray, uv: np.ndarray, faces: np.ndarray, neighbours: int = 64
) -> np.ndarray:
    """UV of the closest point to `point` on the original faces of one chart, searched among the
    `neighbours` faces nearest it (all of the chart's faces if none of those is in the chart)."""
    candidates = tree.query(point, k=neighbours)[1]
    candidates = candidates[chart[candidates] == chart_id]
    if not len(candidates):
        candidates = np.flatnonzero(chart == chart_id)
    triangles = vertices[faces[candidates]]
    nearest = trimesh.triangles.closest_point(triangles, np.repeat(point[None], len(candidates), axis=0))
    pick = int(np.argmin(np.linalg.norm(nearest - point, axis=1)))
    bary = trimesh.triangles.points_to_barycentric(triangles[pick : pick + 1], nearest[pick : pick + 1])[0]
    return bary @ uv[faces[candidates[pick]]]


def decimate_textured(vertices: np.ndarray, uv: np.ndarray, faces: np.ndarray, max_faces: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Quadric decimation that keeps the texture mapping.

    Lux3D meshes are split at UV seams (1,300-5,400 charts, 25-80 thousand seam edges), so
    decimating them as they are either tears the seams open or, with seam edges kept, cannot
    get near max_faces. Instead the seams are welded, the welded surface is decimated (fast_simplification, which also tells
    which original vertices collapsed into each new one), and UVs are looked up again on the
    original mesh (corner_uvs). Returns vertices, uv (one per vertex), faces, and the number of
    corners that needed the fallback projection.
    """
    welded, weld = np.unique(vertices, axis=0, return_inverse=True)
    weld = weld.ravel()
    welded_faces = weld[faces]
    solid = (welded_faces[:, 0] != welded_faces[:, 1]) & (welded_faces[:, 1] != welded_faces[:, 2]) & (welded_faces[:, 0] != welded_faces[:, 2])
    _, _, collapses = fast_simplification.simplify(welded, welded_faces[solid], target_count=max_faces, return_collapses=True)
    points, out_faces, cluster = fast_simplification.replay_simplification(welded, welded_faces[solid], collapses)
    corner_uv, fallbacks = corner_uvs(points, out_faces, cluster, vertices, uv, faces, weld)
    corners = np.column_stack([out_faces.ravel(), corner_uv])
    unique, inverse = np.unique(corners, axis=0, return_inverse=True)  # split again where UVs differ
    return points[unique[:, 0].astype(int)], unique[:, 1:], inverse.reshape(-1, 3), fallbacks


def light_object_assets(name: str, out: Path) -> dict:
    """Decimated visual.obj and shrunk texture.png of one object, written to `out`."""
    out.mkdir(parents=True, exist_ok=True)
    source = trimesh.load(OBJECTS_DIR / name / "visual.obj", process=False)
    vertices, faces = np.asarray(source.vertices), np.asarray(source.faces)
    uv = np.asarray(source.visual.uv)
    fallbacks = 0
    if len(faces) > MAX_VISUAL_FACES:
        vertices, uv, faces, fallbacks = decimate_textured(vertices, uv, faces, MAX_VISUAL_FACES)
    write_obj_with_uv(out / "visual.obj", vertices, uv, faces)
    texture = Image.open(OBJECTS_DIR / name / "texture.png").convert("RGB")
    source_px = texture.size
    if max(texture.size) > MAX_TEXTURE_PX:
        scale = MAX_TEXTURE_PX / max(texture.size)
        texture = texture.resize((round(texture.width * scale), round(texture.height * scale)), Image.Resampling.LANCZOS)
    texture.save(out / "texture.png")
    return {
        "visual_faces": len(faces),
        "visual_faces_source": len(source.faces),
        "uv_fallback_corners": fallbacks,
        "texture_px": list(texture.size),
        "texture_px_source": list(source_px),
        "bounds_m": [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
    }


# ---------------------------------------------------------------- arm visual meshes


def visual_only_meshes(model: mujoco.MjModel) -> list[int]:
    """Meshes that no colliding geom (contype or conaffinity set) uses; unused meshes included."""
    colliding = {
        int(model.geom_dataid[g])
        for g in range(model.ngeom)
        if model.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH and (model.geom_contype[g] or model.geom_conaffinity[g])
    }
    return [m for m in range(model.nmesh) if m not in colliding]


def arm_visual_meshes(model: mujoco.MjModel) -> list[str]:
    """Names of the arm's visual-only meshes: the visual-only ones that are not the object's."""
    return [model.mesh(m).name for m in visual_only_meshes(model) if not model.mesh(m).name.startswith("object_")]


def light_arm_meshes(out: Path) -> dict:
    """Decimate every arm visual-only mesh to about ARM_VISUAL_FACES faces in all and write them to
    `out` as STL: ARM_FIXED_FACES ones to their own count, those of at most ARM_MIN_FACES kept as
    they are, the rest to one shared fraction (at least ARM_MIN_FACES each). MuJoCo computes their normals
    on load, as it does for the original STLs, so shading works the same way. The arm is the same
    in every scene; the default object's scene names the meshes. Returns faces before/after and
    the two-sided Hausdorff distance to the original surface per mesh."""
    import pymeshlab  # only the build needs it

    spec = mujoco.MjSpec.from_file(str(scene.scene_path(scene.DEFAULT_OBJECT)))
    model = spec.compile()
    names = arm_visual_meshes(model)
    sizes = {n: int(model.mesh(n).facenum[0]) for n in names}
    fixed = {n: min(s, ARM_FIXED_FACES.get(n, s)) for n, s in sizes.items() if n in ARM_FIXED_FACES or s <= ARM_MIN_FACES}
    ratio = (ARM_VISUAL_FACES - sum(fixed.values())) / sum(s for n, s in sizes.items() if n not in fixed)
    out.mkdir(parents=True, exist_ok=True)
    info = {}
    for name in names:
        source = trimesh.load(scene.ROBOT_DIR / spec.compiler.meshdir / spec.mesh(name).file, process=True)  # welds facet corners
        meshes = pymeshlab.MeshSet()
        meshes.add_mesh(pymeshlab.Mesh(np.asarray(source.vertices, dtype=np.float64), np.asarray(source.faces)))
        target = fixed.get(name, max(ARM_MIN_FACES, round(len(source.faces) * ratio)))
        if target < len(source.faces):
            meshes.meshing_decimation_quadric_edge_collapse(
                targetfacenum=target, preservenormal=True, preservetopology=True, planarquadric=True,
                optimalplacement=True, qualitythr=ARM_QUALITY_THR,
            )
            meshes.meshing_remove_unreferenced_vertices()
        light = meshes.current_mesh()
        trimesh.Trimesh(light.vertex_matrix(), light.face_matrix(), process=False).export(out / f"{name}.stl")
        meshes.add_mesh(pymeshlab.Mesh(np.asarray(source.vertices, dtype=np.float64), np.asarray(source.faces)))
        there = meshes.get_hausdorff_distance(sampledmesh=0, targetmesh=1, samplenum=20_000)
        back = meshes.get_hausdorff_distance(sampledmesh=1, targetmesh=0, samplenum=20_000)
        info[name] = {
            "faces_source": len(source.faces),
            "faces": int(light.face_number()),
            "hausdorff_max_mm": round(1000 * max(there["max"], back["max"]), 3),
            "hausdorff_mean_mm": round(1000 * max(there["mean"], back["mean"]), 4),
        }
    (out / "info.json").write_text(json.dumps(info, indent=2))
    before, after = sum(v["faces_source"] for v in info.values()), sum(v["faces"] for v in info.values())
    worst = max(v["hausdorff_max_mm"] for v in info.values())
    print(f"arm visual meshes: {len(info)}, {before} -> {after} faces, max surface deviation {worst} mm", flush=True)
    return info


# ---------------------------------------------------------------- web scene, compiled


def compile_web_scene(name: str, build: Path, arm: Path) -> mujoco.MjModel:
    """The training scene with the object's visual mesh and texture and the arm's visual-only
    meshes (decimated into `arm` by light_arm_meshes) swapped for the light ones.

    Compiled from the repo root with relative paths, so the file paths MuJoCo stores in the
    model (model.paths, saved into the .mjb) hold no home directory. A copy of the scene for
    reading is written to build/scene.xml.
    """
    train = mujoco.MjModel.from_xml_path(str(scene.scene_path(name)))
    arm_meshes = arm_visual_meshes(train)
    missing = [n for n in arm_meshes if not (arm / f"{n}.stl").exists()]
    if missing:
        raise SystemExit(f"{name}: no decimated arm mesh for {missing} in {arm}")
    spec = mujoco.MjSpec.from_file(str(scene.scene_path(name)))
    meshdir = scene.ROBOT_DIR / spec.compiler.meshdir
    spec.mesh("object_visual").file = os.path.relpath(build / "visual.obj", meshdir)
    for mesh in arm_meshes:
        spec.mesh(mesh).file = os.path.relpath(arm / f"{mesh}.stl", meshdir)
    spec.texture("object_texture").file = os.path.relpath(build / "texture.png", scene.ROBOT_DIR)  # no texturedir
    with contextlib.chdir(REPO):
        spec.modelfiledir = str(scene.ROBOT_DIR.relative_to(REPO)) + "/"
        model = spec.compile()
        copy = spec.copy()
    restore_derived_sizes(model, train)
    copy.compiler.meshdir = str(scene.ROBOT_DIR / spec.compiler.meshdir)
    copy.compiler.texturedir = str(scene.ROBOT_DIR)
    copy.modelfiledir = str(build) + "/"
    warning = "<!-- For reading only. MjSpec.to_xml rounds numbers (inertias to 6 digits), so this file does not\n" \
        "     compile to the same physics; the .mjb was compiled from the spec (sim/build_web_assets.py). -->\n"
    (build / "scene.xml").write_text(warning + copy.to_xml())
    return model


def restore_derived_sizes(web: mujoco.MjModel, train: mujoco.MjModel) -> None:
    """Copy the training model's length scales the compiler derives from geom sizes, the visual
    mesh's included: dof_length (the object's rotational dofs, about 0.1% off) and stat.meansize.
    The physics did not change without this (replays were exact), but now every field outside
    meshes, textures and BVHs equals the training model's, whatever MuJoCo uses them for."""
    web.dof_length[:] = train.dof_length
    web.stat.meansize = train.stat.meansize


def scene_file(out_dir: Path, name: str) -> Path:
    return out_dir / f"{name}{MJB_SUFFIX}"


def save_scene(model: mujoco.MjModel, path: Path) -> int:
    """Write the model as a gzipped .mjb (no timestamp in the header, so a rebuild of the same
    model gives the same bytes); returns the uncompressed size."""
    raw = np.empty(mujoco.mj_sizeModel(model), dtype=np.uint8)
    mujoco.mj_saveModel(model, None, raw)
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(gzip.compress(raw.tobytes(), compresslevel=GZIP_LEVEL, mtime=0))
    partial.replace(path)
    return raw.size


def load_scene(path: Path) -> tuple[mujoco.MjModel, int]:
    """A gzipped .mjb as the page will load it; returns the model and the uncompressed size."""
    raw = gzip.decompress(path.read_bytes())
    return mujoco.MjModel.from_binary_path("scene.mjb", {"scene.mjb": raw}), len(raw)


def build_object(name: str, build_dir: Path, out_dir: Path) -> dict:
    build = build_dir / name
    info = light_object_assets(name, build)
    model = compile_web_scene(name, build, build_dir / ARM_DIR)
    path = scene_file(out_dir, name)
    raw_bytes = save_scene(model, path)
    (build / "info.json").write_text(json.dumps(info, indent=2))
    render_thumbnail(build, np.array(info["bounds_m"]), out_dir / "thumbs" / f"{name}.png")
    print(f"{name}: {info['visual_faces_source']} -> {info['visual_faces']} faces "
          f"({info['uv_fallback_corners']} fallback UV corners), texture {info['texture_px_source']} -> "
          f"{info['texture_px']}, mesh faces in all {int(model.nmeshface)}, {path.name} {path.stat().st_size / 1e6:.1f} MB "
          f"({raw_bytes / 1e6:.1f} MB unpacked)", flush=True)
    return info


# ---------------------------------------------------------------- thumbnail


def render_thumbnail(build: Path, bounds: np.ndarray, out: Path) -> None:
    """The light object alone, three-quarter view, transparent background (from the depth image).
    `bounds` is the mesh's (min, max) corner as written, so the camera can frame it."""
    size_px = THUMB_PX * THUMB_SUPERSAMPLE
    xml = f"""<mujoco><compiler meshdir="{build}" texturedir="{build}"/>
    <visual><global offwidth="{size_px}" offheight="{size_px}" fovy="30"/>
      <headlight ambient="0.45 0.45 0.45" diffuse="0.35 0.35 0.35" specular="0 0 0"/>
      <rgba haze="{' '.join(map(str, THUMB_BACKGROUND))} 1"/></visual>
    <asset><texture type="2d" name="t" file="texture.png"/><material name="m" texture="t" specular="0.1" shininess="0.1"/>
      <mesh name="v" file="visual.obj"/></asset>
    <worldbody><light pos="0.4 -0.5 0.8" dir="-0.4 0.5 -0.8" directional="true" diffuse="0.6 0.6 0.58"/>
      <geom type="mesh" mesh="v" material="m"/></worldbody></mujoco>"""
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    low, high = bounds
    camera = mujoco.MjvCamera()
    camera.lookat[:] = (low + high) / 2
    camera.distance = THUMB_MARGIN * np.linalg.norm(high - low) / 2 / np.sin(np.radians(15))  # fovy 30
    camera.azimuth, camera.elevation = THUMB_AZIMUTH, THUMB_ELEVATION
    with mujoco.Renderer(model, size_px, size_px) as renderer:
        renderer.update_scene(data, camera)
        rgb = renderer.render().copy()
        renderer.enable_depth_rendering()
        renderer.update_scene(data, camera)
        depth = renderer.render()
    alpha = np.where(depth < depth.max() * 0.999, 255, 0).astype(np.uint8)
    out.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
    image.resize((THUMB_PX, THUMB_PX), Image.Resampling.LANCZOS).save(out)


# ---------------------------------------------------------------- manifest


def start_pose() -> np.ndarray:
    """Per-joint median of the arm's first-frame joint angles over the policy's training episodes."""
    frames = pd.concat(pd.read_parquet(f, columns=["frame_index", STATE_KEY]) for f in sorted((STATE_DATASET / "data").glob("*/*.parquet")))
    return np.median(np.stack(frames.loc[frames["frame_index"] == 0, STATE_KEY].to_numpy()), axis=0)


def start_pose_clearance(model: mujoco.MjModel, pose: np.ndarray) -> list[dict]:
    """Placements on a grid over the play area where the arm at `pose` touches the object or it does not settle.

    Uses evaluate.set_up_trial, the policy evaluation's own start check: arm placed and held at
    the pose, object dropped, SETTLE_FRAMES frames simulated, then no contact allowed.
    """
    from evaluate import set_up_trial
    from teleop import SimArm

    data = mujoco.MjData(model)
    arm = SimArm(model, data)
    blocked = []
    for x in grid(scene.SPAWN_X_M):
        for y in grid(scene.SPAWN_Y_M):
            for yaw_deg in CLEARANCE_YAWS_DEG:
                placement = scene.ObjectPose(float(x), float(y), float(np.radians(yaw_deg)))
                if not set_up_trial(model, data, arm, placement, pose):
                    blocked.append({"x": round(float(x), 4), "y": round(float(y), 4), "yaw_deg": yaw_deg})
    return blocked


def grid(span: tuple[float, float]) -> np.ndarray:
    """CLEARANCE_STEP_M grid over `span`, both ends included."""
    count = round((span[1] - span[0]) / CLEARANCE_STEP_M) + 1
    return np.linspace(span[0], span[1], count)


def blocked_box(blocked: list[dict]) -> dict | None:
    """The x and y ranges the blocked placements span (None if there are none)."""
    if not blocked:
        return None
    return {axis: [min(p[axis] for p in blocked), max(p[axis] for p in blocked)] for axis in ("x", "y")}


def keepout_box(box: dict | None) -> dict | None:
    """The blocked box grown by KEEPOUT_PAD_M on every side, clipped to the play area: a grid
    placement just outside the box can still touch the arm (overlaps reach ~1 cm past it)."""
    if box is None:
        return None
    area = {"x": scene.SPAWN_X_M, "y": scene.SPAWN_Y_M}
    return {
        axis: [round(max(low - KEEPOUT_PAD_M, area[axis][0]), 4), round(min(high + KEEPOUT_PAD_M, area[axis][1]), 4)]
        for axis, (low, high) in box.items()
    }


def gripper_at(model: mujoco.MjModel, pose: np.ndarray) -> dict:
    """Where the gripper is at `pose` (no physics): its frame site and the lowest point of its collision geoms."""
    data = mujoco.MjData(model)
    for name, angle in zip(JOINT_NAMES, pose):
        data.qpos[model.joint(name).qposadr[0]] = angle
    mujoco.mj_forward(model, data)
    jaw_bodies = {model.body("gripper").id, model.body("moving_jaw_so101_v1").id}
    lowest = min(
        float(data.geom_xpos[g][2] - model.geom_rbound[g])
        for g in range(model.ngeom)
        if model.geom_bodyid[g] in jaw_bodies and model.geom_contype[g]
    )
    return {"gripperframe_xyz_m": [round(float(v), 4) for v in data.site("gripperframe").xpos], "lowest_collision_z_m_bound": round(lowest, 4)}


def object_state_layout() -> list[dict]:
    """How lift_scene.object_state builds its 12 numbers, for the page to do the same (float32 at the end)."""
    quat = "q = (w, x, y, z) = qpos[object.qpos_adr + 3 : + 7], MuJoCo's mju_quat2Mat (no normalisation)"
    return [
        {"slice": [0, 3], "name": "position_m", "how": "qpos[object.qpos_adr : + 3], world frame, metres"},
        {"slice": [3, 6], "name": "rotation_column_0", "how": f"{quat}: [w*w + x*x - y*y - z*z, 2*(x*y + w*z), 2*(x*z - w*y)]"},
        {"slice": [6, 9], "name": "rotation_column_1", "how": f"{quat}: [2*(x*y - w*z), w*w - x*x + y*y - z*z, 2*(y*z + w*x)]"},
        {"slice": [9, 12], "name": "size_m", "how": "constant per object: objects[].size_m (bounding box of the collision mesh "
         "in the object's body frame, lift_scene.object_size_m); copy it, do not recompute"},
    ]


def object_entry(name: str, model: mujoco.MjModel, raw_bytes: int, out_dir: Path, trained: set[str], blocked: list[dict]) -> dict:
    root = default_root(name)
    info_path = root / "meta" / "info.json"
    path = scene_file(out_dir, name)
    return {
        "name": name,
        "label": OBJECTS[name].label,
        "mjb": path.name,
        "mjb_bytes": path.stat().st_size,
        "mjb_raw_bytes": raw_bytes,
        "thumb": f"thumbs/{name}.png",
        "size_m": [float(v) for v in scene.object_size_m(model)],
        "mass_kg": OBJECTS[name].mass_kg,
        "trained": name in trained,
        "recorded_episodes": json.loads(info_path.read_text())["total_episodes"] if info_path.exists() else 0,
        "start_pose_keepout": keepout_box(blocked_box(blocked)),
    }


def write_manifest(out_dir: Path) -> dict:
    names = [n for n in scene.available_objects() if scene_file(out_dir, n).exists()]
    loaded = {n: load_scene(scene_file(out_dir, n)) for n in names}
    models = {n: m for n, (m, _) in loaded.items()}
    model = models[names[0]]  # addresses and options are the same in every scene (checked below)
    pose = start_pose()
    blocked = {n: start_pose_clearance(m, pose) for n, m in models.items()}
    trained = set(json.loads((STATE_DATASET / "meta" / "sources.json").read_text()))
    table = model.geom("table")
    manifest = {
        "mujoco_version": mujoco.__version__,
        "timestep": float(model.opt.timestep),
        "steps_per_frame": steps_per_frame(model),
        "fps": FPS,
        "nq": model.nq, "nv": model.nv, "nu": model.nu,
        "joint_names": list(JOINT_NAMES),
        "joints": [joint_entry(model, name) for name in JOINT_NAMES],
        "object": {"body": scene.OBJECT_BODY, "joint": scene.OBJECT_BODY, "qpos_adr": scene.object_qpos_adr(model),
                   "dof_adr": int(model.joint(scene.OBJECT_BODY).dofadr[0]), "qpos_len": 7, "dof_len": 6},
        "play_area_x_m": list(scene.SPAWN_X_M), "play_area_y_m": list(scene.SPAWN_Y_M),
        "spawn_drop_m": scene.SPAWN_DROP_M,
        "placement": "qpos[object.qpos_adr:+7] = (x, y, spawn_drop_m, cos(yaw/2), 0, 0, sin(yaw/2)); "
        "qvel[object.dof_adr:+6] = 0; mj_forward (lift_scene.place_object)",
        "lift_success_m": scene.LIFT_SUCCESS_M, "hold_success_s": scene.HOLD_SUCCESS_S,
        "success": "object height qpos[object.qpos_adr + 2] >= lift_success_m continuously for hold_success_s of sim time",
        "min_upright": MIN_UPRIGHT, "on_table_m": ON_TABLE_M,
        "upright": "z of cross(rotation_column_0, rotation_column_1); below min_upright on the table = knocked over",
        "table_top_z_m": float(table.pos[2] + table.size[2]),
        "start_pose_rad": [float(v) for v in pose],
        "start_pose_source": f"per-joint median of frame-0 {STATE_KEY} over {STATE_DATASET.relative_to(REPO)}",
        "start_pose_gripper": gripper_at(model, pose),
        "start_pose_check": f"objects on a {CLEARANCE_STEP_M * 100:g} cm grid over the play area x yaw "
        f"{list(CLEARANCE_YAWS_DEG)} deg; listed placements touch the arm or do not settle (evaluate.set_up_trial)",
        "start_pose_blocked": blocked,
        "start_pose_blocked_box": {n: blocked_box(b) for n, b in blocked.items()},
        "start_pose_keepout_rule": f"objects[].start_pose_keepout: start_pose_blocked_box grown by {KEEPOUT_PAD_M} m on every "
        "side and clipped to the play area (placements just outside the grid box can still touch the arm); null if none blocked",
        "object_state_size": scene.OBJECT_STATE_SIZE,
        "object_state": object_state_layout(),
        "objects": [object_entry(n, m, loaded[n][1], out_dir, trained, blocked[n]) for n, m in models.items()],
    }
    for other in models.values():
        if (other.nq, other.nv, other.nu, other.opt.timestep) != (model.nq, model.nv, model.nu, model.opt.timestep):
            raise SystemExit("Scenes differ in layout or timestep; the manifest's shared fields would be wrong.")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def joint_entry(model: mujoco.MjModel, name: str) -> dict:
    actuator = model.actuator(name)
    return {
        "joint": name,
        "actuator": actuator.name,
        "actuator_id": int(actuator.id),
        "qpos_adr": int(model.joint(name).qposadr[0]),
        "dof_adr": int(model.joint(name).dofadr[0]),
        "ctrl_range": [float(v) for v in model.actuator_ctrlrange[actuator.id]],
    }


# ---------------------------------------------------------------- verification


def looks_geoms(model: mujoco.MjModel) -> list[int]:
    """Geoms that never collide (contype and conaffinity 0) and draw a visual-only mesh: the
    object's visual geom and the arm's. MuJoCo moves a mesh geom's frame to its mesh's centre of
    mass and principal axes, so a decimated mesh changes these geoms' pos, quat, size and bounds."""
    visual_meshes = set(visual_only_meshes(model))
    return [
        g for g in range(model.ngeom)
        if model.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH and int(model.geom_dataid[g]) in visual_meshes
        and not model.geom_contype[g] and not model.geom_conaffinity[g]
    ]


# The geom fields MuJoCo derives from a mesh's shape; only these may differ, only in looks_geoms rows.
MESH_DERIVED_GEOM_FIELDS = ("geom_pos", "geom_quat", "geom_size", "geom_aabb", "geom_rbound")


def model_differences(train: mujoco.MjModel, web: mujoco.MjModel) -> list[str]:
    """Names of model fields that differ, leaving out the looks_geoms rows of MESH_DERIVED_GEOM_FIELDS.
    Every other geom field (contype, conaffinity, group, mass-related, ...) is compared in full."""
    visual = looks_geoms(train)
    differ = []
    for field in sorted(dir(train)):
        if field.startswith("_"):
            continue
        a, b = getattr(train, field, None), getattr(web, field, None)
        if isinstance(a, np.ndarray):
            if field in MESH_DERIVED_GEOM_FIELDS and a.shape == b.shape and len(a) == train.ngeom:
                a, b = np.delete(a, visual, axis=0), np.delete(b, visual, axis=0)
            same = a.shape == b.shape and np.array_equal(a, b, equal_nan=True)
        elif isinstance(a, (int, float, bytes)):
            same = a == b
        else:
            continue
        if not same:
            differ.append(field)
    for group in ("opt", "stat"):
        for field in dir(getattr(train, group)):
            value = getattr(getattr(train, group), field)
            if field.startswith("_") or callable(value):
                continue
            if not np.array_equal(np.asarray(value), np.asarray(getattr(getattr(web, group), field))):
                differ.append(f"{group}.{field}")
    return differ


# Fields allowed to differ: mesh, texture and BVH data, sizes of those arrays, file paths, and
# `signature`, a hash of the whole compiled model.
LOOKS_FIELDS = ("mesh_", "bvh_", "tex_", "nmesh", "nbvh", "ntex", "paths", "npaths", "narena", "nbuffer", "signature")


def readable_episodes(root: Path) -> dict[int, np.ndarray]:
    """Recorded sim states per episode; a parquet file being written right now is skipped."""
    episodes = {}
    for path in sorted((root / "data").glob("*/*.parquet")):
        try:
            frames = pd.read_parquet(path, columns=["episode_index", "frame_index", SIM_STATE_KEY])
        except Exception as error:  # noqa: BLE001 - a half-written file raises several pyarrow types
            print(f"  skipped {path.relative_to(REPO)}: {error}")
            continue
        for index, group in frames.groupby("episode_index"):
            episodes[int(index)] = np.stack(group.sort_values("frame_index")[SIM_STATE_KEY].to_numpy())
    return episodes


def side_by_side(train: mujoco.MjModel, web: mujoco.MjModel, states: np.ndarray) -> tuple[float, int]:
    """Start both models from states[0] and apply the recorded ctrl of every frame; returns the largest
    full-physics state difference and the number of frames in which the arm touched the object."""
    datas = [mujoco.MjData(train), mujoco.MjData(web)]
    recorded = mujoco.MjData(train)
    size = mujoco.mj_stateSize(train, FULL_STATE)
    buffers = [np.empty(size), np.empty(size)]
    for model, data in zip((train, web), datas):
        mujoco.mj_setState(model, data, states[0], SIM_STATE_SPEC)
    worst, touching = 0.0, 0
    object_body = train.body(scene.OBJECT_BODY).id
    for frame in states:
        mujoco.mj_setState(train, recorded, frame, SIM_STATE_SPEC)
        for model, data, buffer in zip((train, web), datas, buffers):
            data.ctrl[:] = recorded.ctrl
            for _ in range(steps_per_frame(model)):
                mujoco.mj_step(model, data)
            mujoco.mj_getState(model, data, buffer, FULL_STATE)
        worst = max(worst, float(np.max(np.abs(buffers[0] - buffers[1]))))
        bodies = {(train.geom_bodyid[c.geom1], train.geom_bodyid[c.geom2]) for c in datas[0].contact[: datas[0].ncon]}
        touching += any(object_body in pair and 0 not in pair for pair in bodies)
    return worst, touching


def manifest_object_state(qpos: np.ndarray, adr: int, size_m: list[float]) -> np.ndarray:
    """object_state computed the way manifest.json describes it (what the page will do)."""
    w, x, y, z = qpos[adr + 3 : adr + 7]
    column_0 = [w * w + x * x - y * y - z * z, 2 * (x * y + w * z), 2 * (x * z - w * y)]
    column_1 = [2 * (x * y - w * z), w * w - x * x + y * y - z * z, 2 * (y * z + w * x)]
    return np.array([*qpos[adr : adr + 3], *column_0, *column_1, *size_m], dtype=np.float64).astype(np.float32)


def verify_object(name: str, out_dir: Path, manifest: dict) -> bool:
    train = mujoco.MjModel.from_xml_path(str(scene.scene_path(name)))
    web, raw_bytes = load_scene(scene_file(out_dir, name))
    differ = model_differences(train, web)
    physics = [f for f in differ if not f.startswith(LOOKS_FIELDS)]
    print(f"{name}: {scene_file(out_dir, name).name} ({raw_bytes / 1e6:.1f} MB unpacked, mesh faces "
          f"{int(train.nmeshface)} -> {int(web.nmeshface)}); fields that differ from the training model: "
          f"looks {len(differ) - len(physics)}, other {physics or 'none'}; visual-only geoms with looks rows "
          f"{len(looks_geoms(train))}")
    ok = not physics and looks_geoms(train) == looks_geoms(web)
    root = default_root(name)
    episodes = readable_episodes(root) if (root / "meta" / "sim.json").exists() else {}
    if episodes:
        steps = json.loads((root / "meta" / "sim.json").read_text())["steps_per_frame"]
        data = mujoco.MjData(web)
        from replay import replay

        worst = {i: replay(web, data, states, steps) for i, states in sorted(episodes.items())}
        exact = sum(v == 0.0 for v in worst.values())
        print(f"  replay of its own recordings on the .mjb: {exact}/{len(worst)} episodes exact, max diff {max(worst.values()):.3g}")
        ok &= exact == len(worst)
    # Without its own recordings, an object gets another object's: same state layout, so its arm
    # commands and the object's start pose apply as they are (the arm then meets this object).
    source = episodes or readable_episodes(default_root(SCRIPTED_SOURCE))
    entry = next(o for o in manifest["objects"] if o["name"] == name)
    adr, state_worst, results = manifest["object"]["qpos_adr"], 0.0, []
    for index in sorted(source)[:SCRIPTED_EPISODES]:
        states = source[index]
        results.append(side_by_side(train, web, states))
        data = mujoco.MjData(web)
        for frame in states:
            mujoco.mj_setState(web, data, frame, SIM_STATE_SPEC)
            expected = scene.object_state(web, data)
            state_worst = max(state_worst, float(np.max(np.abs(manifest_object_state(data.qpos, adr, entry["size_m"]) - expected))))
    label = "its own" if episodes else f"{SCRIPTED_SOURCE}'s"
    print(f"  {label} recorded commands, training vs .mjb side by side ({len(results)} episodes): max full-state diff "
          f"{max(r[0] for r in results):.3g}, frames with the arm touching the object {[r[1] for r in results]}")
    print(f"  manifest's object_state recipe vs lift_scene.object_state: max diff {state_worst:.3g}")
    return ok and all(r[0] == 0.0 for r in results) and state_worst == 0.0


# ---------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--objects", nargs="+", default=None, choices=list(OBJECTS), help="default: every converted object")
    parser.add_argument("--out-dir", type=Path, required=True, help="the page's scene folder, e.g. web/public/scenes")
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR, help="decimated assets and scene.xml per object")
    parser.add_argument("--no-build", action="store_true", help="only rewrite the manifest (and --verify) from the .mjb files there")
    parser.add_argument("--verify", action="store_true", help="prove each .mjb simulates exactly like its training scene")
    args = parser.parse_args()

    available = scene.available_objects()
    objects = args.objects or available
    missing = sorted(set(objects) - set(available))
    if missing:
        raise SystemExit(f"Not converted on this machine: {missing}. Run: python sim/prep_object.py --all")
    out_dir, build_dir = args.out_dir.resolve(), args.build_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_build:
        light_arm_meshes(build_dir / ARM_DIR)
        for name in objects:
            build_object(name, build_dir, out_dir)
    manifest = write_manifest(out_dir)
    print(f"manifest: {len(manifest['objects'])} objects; start pose {np.round(manifest['start_pose_rad'], 3).tolist()}, "
          f"gripper at {manifest['start_pose_gripper']['gripperframe_xyz_m']}")
    keepouts = {o["name"]: o["start_pose_keepout"] for o in manifest["objects"]}
    for name, placements in manifest["start_pose_blocked"].items():
        print(f"  {name}: {len(placements)} placements blocked by the start pose, within "
              f"{manifest['start_pose_blocked_box'][name]}, keep-out {keepouts[name]}")
    total = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file() and not f.name.endswith(".mjb"))
    print(f"{out_dir}: {total / 1e6:.1f} MB (old uncompressed .mjb files left there not counted)")
    if args.verify:
        results = [verify_object(name, out_dir, manifest) for name in objects]
        print(f"verified: {sum(results)}/{len(results)} objects simulate exactly like their training scenes")
        return 0 if all(results) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
