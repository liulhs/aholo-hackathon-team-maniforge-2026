"""Build a SimReady USD of the Lux3D takeout box plus a LeIsaac table scene.

Runs locally with Pixar's usd-core (no Isaac Sim needed):

    python build_takeout_box_usd.py --variant real   # keep the Lux3D size (~12 cm)
    python build_takeout_box_usd.py --variant small  # shrink to fit the SO-101 gripper

Inputs (from the 2026-11-08 Lux3D test):
    textured.glb  -> visual mesh + PBR textures
    raw_mesh.glb  -> watertight mesh, used to build the convex-hull collider
    table_with_cube/scene.usd from LightwheelAI/leisaac_env -> the table we place the box on

Physics values that Lux3D does not provide are explicit parameters below; replace the
defaults with measured values (scale, mass) and tuned values (friction) when available.
"""
import argparse
import io
import json
import shutil
import struct
from pathlib import Path

import numpy as np
from PIL import Image
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade, Vt
from scipy.spatial import ConvexHull

HERE = Path(__file__).resolve().parent
LUX3D_DIR = HERE.parent / "experiments" / "2026-11-08-lux3d-takeout-box" / "g1_standard"
OUT_ROOT = HERE / "assets" / "scenes"

# The LeIsaac table_with_cube scene: table top surface height and the cube's spot in front of the robot.
TABLE_TOP_Z = 0.041
OBJECT_XY = (0.3460526111597802, -0.3616141379696716)
DROP_CLEARANCE = 0.002

VARIANTS = {
    # max horizontal width in metres; None keeps the Lux3D-predicted size (longest edge 0.12 m)
    "real": {"max_width_m": None, "scene": "table_with_takeout_box"},
    # SO-101 jaw: ~65 mm effective opening (measured from the follower USD collision meshes)
    "small": {"max_width_m": 0.055, "scene": "table_with_takeout_box_small"},
}

COMPONENT_DTYPE = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def parse_glb(path):
    data = Path(path).read_bytes()
    json_len = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + json_len]), data[20 + json_len + 8:]


def accessor(doc, blob, index):
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    width = TYPE_WIDTH[acc["type"]]
    arr = np.frombuffer(blob, COMPONENT_DTYPE[acc["componentType"]], acc["count"] * width, start)
    return arr.reshape(-1, width) if width > 1 else arr


def image_bytes(doc, blob, index):
    view = doc["bufferViews"][doc["images"][index]["bufferView"]]
    start = view.get("byteOffset", 0)
    return blob[start:start + view["byteLength"]]


def y_up_to_z_up(points):
    """glTF is Y-up; Isaac Sim / LeIsaac scenes are Z-up. (x, y, z) -> (x, -z, y)."""
    return np.stack([points[:, 0], -points[:, 2], points[:, 1]], axis=1)


def load_geometry():
    vis_doc, vis_blob = parse_glb(LUX3D_DIR / "textured.glb")
    prim = vis_doc["meshes"][0]["primitives"][0]
    vis = {
        "points": y_up_to_z_up(accessor(vis_doc, vis_blob, prim["attributes"]["POSITION"]).astype(np.float64)),
        "normals": y_up_to_z_up(accessor(vis_doc, vis_blob, prim["attributes"]["NORMAL"]).astype(np.float64)),
        "uv": accessor(vis_doc, vis_blob, prim["attributes"]["TEXCOORD_0"]).astype(np.float64),
        "faces": accessor(vis_doc, vis_blob, prim["indices"]).astype(np.int64).reshape(-1, 3),
        "basecolor_png": image_bytes(vis_doc, vis_blob, 0),
        "metal_rough_png": image_bytes(vis_doc, vis_blob, 1),
    }
    raw_doc, raw_blob = parse_glb(LUX3D_DIR / "raw_mesh.glb")
    raw_prim = raw_doc["meshes"][0]["primitives"][0]
    raw_points = y_up_to_z_up(accessor(raw_doc, raw_blob, raw_prim["attributes"]["POSITION"]).astype(np.float64))
    return vis, raw_points


def placement(raw_points, max_width_m):
    """Uniform scale + offset that centres the box in XY and puts its bottom at z = 0."""
    size = np.ptp(raw_points, axis=0)
    scale = 1.0 if max_width_m is None else max_width_m / max(size[0], size[1])
    centre_xy = (raw_points[:, :2].max(0) + raw_points[:, :2].min(0)) / 2
    offset = np.array([-centre_xy[0], -centre_xy[1], -raw_points[:, 2].min()])
    return scale, offset


def convex_hull_mesh(points):
    hull = ConvexHull(points)
    centroid = points[hull.vertices].mean(axis=0)
    faces = []
    for simplex, eq in zip(hull.simplices, hull.equations):
        a, b, c = points[simplex]
        if np.dot(np.cross(b - a, c - a), a - centroid) < 0:
            simplex = simplex[[0, 2, 1]]
        faces.append(simplex)
    used, remap = np.unique(np.array(faces), return_inverse=True)
    return points[used], remap.reshape(-1, 3)


def write_mesh(stage, path, points, faces, normals=None, uv=None):
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points.astype(np.float32)))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(np.full(len(faces), 3, dtype=np.int32)))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(faces.reshape(-1).astype(np.int32)))
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    mesh.CreateExtentAttr([Gf.Vec3f(*points.min(0)), Gf.Vec3f(*points.max(0))])
    if normals is not None:
        mesh.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(normals.astype(np.float32)))
        mesh.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
    if uv is not None:
        st = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.vertex)
        # glTF UV origin is top-left; USD st origin is bottom-left.
        st.Set(Vt.Vec2fArray.FromNumpy(np.stack([uv[:, 0], 1.0 - uv[:, 1]], 1).astype(np.float32)))
    return mesh


def write_visual_material(stage, root, tex_dir_rel):
    material = UsdShade.Material.Define(stage, f"{root}/Looks/takeout_box_pbr")
    surface = UsdShade.Shader.Define(stage, f"{root}/Looks/takeout_box_pbr/Surface")
    surface.CreateIdAttr("UsdPreviewSurface")
    reader = UsdShade.Shader.Define(stage, f"{root}/Looks/takeout_box_pbr/StReader")
    reader.CreateIdAttr("UsdPrimvarReader_float2")
    reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    st = reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

    base = UsdShade.Shader.Define(stage, f"{root}/Looks/takeout_box_pbr/BaseColorTex")
    base.CreateIdAttr("UsdUVTexture")
    base.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(f"{tex_dir_rel}/basecolor.png")
    base.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB")
    base.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(st)
    surface.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        base.CreateOutput("rgb", Sdf.ValueTypeNames.Float3))

    mr = UsdShade.Shader.Define(stage, f"{root}/Looks/takeout_box_pbr/MetalRoughTex")
    mr.CreateIdAttr("UsdUVTexture")
    mr.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(f"{tex_dir_rel}/metal_rough.png")
    mr.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("raw")
    mr.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(st)
    surface.CreateInput("roughness", Sdf.ValueTypeNames.Float).ConnectToSource(
        mr.CreateOutput("g", Sdf.ValueTypeNames.Float))
    surface.CreateInput("metallic", Sdf.ValueTypeNames.Float).ConnectToSource(
        mr.CreateOutput("b", Sdf.ValueTypeNames.Float))
    material.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), "surface")
    return material


def build_object_usd(out_dir, vis, raw_points, scale, offset, mass_kg, static_mu, dynamic_mu):
    tex_dir = out_dir / "textures"
    tex_dir.mkdir(parents=True, exist_ok=True)
    (tex_dir / "basecolor.png").write_bytes(vis["basecolor_png"])
    (tex_dir / "metal_rough.png").write_bytes(vis["metal_rough_png"])

    usd_path = out_dir / "takeout_box.usd"
    stage = Usd.Stage.CreateNew(str(usd_path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdPhysics.SetStageKilogramsPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/root")
    stage.SetDefaultPrim(root.GetPrim())

    body = UsdGeom.Xform.Define(stage, "/root/takeout_box")
    UsdPhysics.RigidBodyAPI.Apply(body.GetPrim())
    UsdPhysics.MassAPI.Apply(body.GetPrim()).CreateMassAttr(mass_kg)

    phys_mat = UsdShade.Material.Define(stage, "/root/Physics/PhysicsMaterial")
    mat_api = UsdPhysics.MaterialAPI.Apply(phys_mat.GetPrim())
    mat_api.CreateStaticFrictionAttr(static_mu)
    mat_api.CreateDynamicFrictionAttr(dynamic_mu)
    mat_api.CreateRestitutionAttr(0.0)

    hull_points, hull_faces = convex_hull_mesh((raw_points + offset) * scale)
    collider = write_mesh(stage, "/root/takeout_box/Collisions/hull", hull_points, hull_faces)
    UsdGeom.Imageable(collider).CreatePurposeAttr(UsdGeom.Tokens.guide)
    UsdPhysics.CollisionAPI.Apply(collider.GetPrim())
    UsdPhysics.MeshCollisionAPI.Apply(collider.GetPrim()).CreateApproximationAttr(UsdPhysics.Tokens.convexHull)
    UsdShade.MaterialBindingAPI.Apply(collider.GetPrim()).Bind(
        phys_mat, UsdShade.Tokens.weakerThanDescendants, "physics")

    visual = write_mesh(stage, "/root/takeout_box/Visuals/mesh", (vis["points"] + offset) * scale,
                        vis["faces"], vis["normals"], vis["uv"])
    UsdShade.MaterialBindingAPI.Apply(visual.GetPrim()).Bind(write_visual_material(stage, "/root", "./textures"))
    stage.GetRootLayer().Save()
    return usd_path, np.ptp(hull_points, axis=0), len(hull_points)


def build_scene(scene_dir, cube_scene, box_height):
    """Copy the LeIsaac table scene and swap the cube payload for the takeout box."""
    shutil.copy(cube_scene.parent / "textures" / "light_wood_planks_0.png", scene_dir / "textures" / "light_wood_planks_0.png")
    layer = Sdf.Layer.FindOrOpen(str(cube_scene)).ExportToString()
    stage = Usd.Stage.CreateInMemory()
    stage.GetRootLayer().ImportFromString(layer)
    stage.RemovePrim("/world/cube")
    box = stage.DefinePrim("/world/takeout_box", "Xform")
    box.GetPayloads().AddPayload("./takeout_box/takeout_box.usd")
    xform = UsdGeom.Xformable(box)
    xform.AddTranslateOp().Set(Gf.Vec3d(OBJECT_XY[0], OBJECT_XY[1], TABLE_TOP_Z + DROP_CLEARANCE))
    xform.AddOrientOp().Set(Gf.Quatf(1, 0, 0, 0))
    stage.GetRootLayer().Export(str(scene_dir / "scene.usd"))
    return box_height


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=VARIANTS, default="real")
    parser.add_argument("--cube-scene", type=Path, required=True,
                        help="path to leisaac_env assets/scenes/table_with_cube/scene.usd")
    parser.add_argument("--mass-kg", type=float, default=0.02, help="ASSUMED until the real box is weighed")
    parser.add_argument("--static-friction", type=float, default=0.6, help="ASSUMED until slide/grasp tests")
    parser.add_argument("--dynamic-friction", type=float, default=0.5, help="ASSUMED until slide/grasp tests")
    args = parser.parse_args()

    variant = VARIANTS[args.variant]
    scene_dir = OUT_ROOT / variant["scene"]
    if scene_dir.exists():
        shutil.rmtree(scene_dir)
    (scene_dir / "takeout_box").mkdir(parents=True)
    (scene_dir / "textures").mkdir()

    vis, raw_points = load_geometry()
    scale, offset = placement(raw_points, variant["max_width_m"])
    usd_path, hull_size, hull_verts = build_object_usd(
        scene_dir / "takeout_box", vis, raw_points, scale, offset,
        args.mass_kg, args.static_friction, args.dynamic_friction)
    build_scene(scene_dir, args.cube_scene, hull_size[2])
    print(json.dumps({
        "variant": args.variant, "scene": str(scene_dir / "scene.usd"), "object": str(usd_path),
        "scale_applied": round(scale, 4), "size_xyz_m": np.round(hull_size, 4).tolist(),
        "collider_hull_vertices": hull_verts, "mass_kg": args.mass_kg,
        "friction_static_dynamic": [args.static_friction, args.dynamic_friction],
    }, indent=1))


if __name__ == "__main__":
    main()
