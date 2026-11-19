"""Estimate physics for a Lux3D object with an LLM, then write it into the object's USD.

    export LLM_BASE_URL=https://.../v1   # any OpenAI-compatible /chat/completions endpoint
    export LLM_API_KEY=...               # never hard-code keys
    export LLM_MODEL=...                 # a vision-capable model
    python estimate_physics.py --glb raw_mesh.glb --photo input.jpg --name "paper takeout box" \
        --scale 1.0 --samples 5 --out physics.json --usd assets/scenes/.../takeout_box.usd

Needs: numpy, usd-core (pxr; only for --usd). Re-uses the GLB reader idea from build_takeout_box_usd.py.

Notes (see ../SO101-NEXT-STEPS.md):
- Only an explicit mass is written to USD (explicit mass overrides density x volume). Never write a
  density for hollow objects: the watertight Lux3D mesh is solid, so density x volume is ~20x too heavy.
- Friction belongs to a material PAIR. The prompt asks for box-vs-PLA-gripper; measure the real value
  with a tilt test (mu_s = tan(theta)) and compare, instead of trusting the LLM.
- The photo is sent to a third-party LLM. Keys come only from env vars.
"""
import argparse
import base64
import json
import os
import statistics
import struct
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

# Sanity table: (density kg/m^3, static mu vs. hard plastic/rubber-ish finger, typical shell thickness m).
# Values are engineering ballparks; replace with your own measurements when you have them.
MATERIALS = {
    "paperboard": (700.0, (0.3, 0.8), 0.0005),
    "pp_plastic": (905.0, (0.2, 0.5), 0.0008),
    "ps_foam":    (50.0,  (0.3, 0.7), 0.003),
    "ceramic":    (2400.0, (0.4, 0.9), 0.004),
    "glass":      (2500.0, (0.3, 0.9), 0.003),
    "wood":       (600.0, (0.3, 0.6), None),
    "fruit":      (950.0, (0.4, 0.9), None),
}
SCHEMA_HINT = {
    "material": f"one of {sorted(MATERIALS)}",
    "is_hollow": "bool: thin-walled container/shell rather than solid",
    "wall_thickness_mm": "float or null",
    "mass_kg": "float: direct estimate of the real object's mass",
    "static_friction": "float", "dynamic_friction": "float (<= static)", "restitution": "float 0..1",
    "confidence": "0..1", "reasoning": "<= 2 sentences",
}


def read_glb_mesh(path):
    data = Path(path).read_bytes()
    jlen = struct.unpack("<I", data[12:16])[0]
    doc, blob = json.loads(data[20:20 + jlen]), data[20 + jlen + 8:]
    dtypes, widths = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}, {"SCALAR": 1, "VEC3": 3}

    def acc(i):
        a = doc["accessors"][i]
        v = doc["bufferViews"][a["bufferView"]]
        w = widths[a["type"]]
        arr = np.frombuffer(blob, dtypes[a["componentType"]], a["count"] * w,
                            v.get("byteOffset", 0) + a.get("byteOffset", 0))
        return arr.reshape(-1, w) if w > 1 else arr

    prim = doc["meshes"][0]["primitives"][0]
    return acc(prim["attributes"]["POSITION"]).astype(float), acc(prim["indices"]).astype(int).reshape(-1, 3)


def mesh_stats(points, faces, scale):
    a, b, c = (points[faces[:, k]] * scale for k in range(3))
    return {
        "bbox_m": np.ptp(points * scale, axis=0).round(4).tolist(),
        "area_m2": float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum()),
        "volume_m3": float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0),  # needs watertight mesh
    }


MASS_BOUNDS_KG = (0.001, 2.0)  # SO-101 cannot lift more than ~0.3 kg anyway; anything outside is a bad answer
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def validate_sample(s):
    """Return a cleaned sample or None if the LLM reply is unusable."""
    try:
        clean = {
            "material": str(s["material"]),
            "is_hollow": bool(s["is_hollow"]),
            "wall_thickness_mm": float(s["wall_thickness_mm"]) if s.get("wall_thickness_mm") else None,
            "mass_kg": float(s["mass_kg"]),
            "static_friction": float(s["static_friction"]),
            "dynamic_friction": float(s["dynamic_friction"]),
            "restitution": float(s.get("restitution", 0.0)),
            "confidence": float(s.get("confidence", 0.5)),
            "reasoning": str(s.get("reasoning", "")),
        }
    except (KeyError, TypeError, ValueError) as err:
        print(f"[skip] malformed LLM sample: {err!r}")
        return None
    if not MASS_BOUNDS_KG[0] <= clean["mass_kg"] <= MASS_BOUNDS_KG[1]:
        print(f"[skip] mass {clean['mass_kg']} kg outside {MASS_BOUNDS_KG}")
        return None
    if not (0.0 < clean["static_friction"] <= 2.0 and 0.0 < clean["dynamic_friction"] <= 2.0):
        print("[skip] friction outside (0, 2]")
        return None
    return clean


def ask_llm(photo, name, stats):
    missing = [k for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Set env vars first: {', '.join(missing)}")
    url, key, model = (os.environ[k] for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))
    mime = MIME.get(Path(photo).suffix.lower())
    if mime is None:
        raise SystemExit(f"Unsupported photo type: {photo} (use jpg/png/webp)")
    prompt = (
        f"Object: {name}. Bounding box (m): {stats['bbox_m']}. Outer surface area: {stats['area_m2']:.4f} m^2. "
        f"Enclosed volume: {stats['volume_m3'] * 1000:.3f} L (includes empty interior if hollow). "
        "Estimate physical properties of the REAL object in the photo for a rigid-body simulator. "
        "Friction is against a dry 3D-printed PLA robot gripper. "
        f"Reply with JSON only, keys: {json.dumps(SCHEMA_HINT)}"
    )
    img = base64.b64encode(Path(photo).read_bytes()).decode()
    body = {
        "model": model, "temperature": 0.7, "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img}"}},
        ]}],
    }
    req = urllib.request.Request(f"{url.rstrip('/')}/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(json.loads(resp.read())["choices"][0]["message"]["content"])
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as err:
        print(f"[skip] LLM request failed: {err!r}")
        return None


def reconcile(samples, stats):
    """Median over samples, then cross-check mass against geometry x material table."""
    material = statistics.mode(s["material"] for s in samples)
    density, mu_range, default_t = MATERIALS.get(material, (1000.0, (0.2, 1.0), None))
    hollow = sum(bool(s["is_hollow"]) for s in samples) > len(samples) / 2
    med = lambda k: float(statistics.median(float(s[k]) for s in samples))  # noqa: E731
    thickness = next((s["wall_thickness_mm"] / 1000 for s in samples if s.get("wall_thickness_mm")), default_t)
    geo_mass = (stats["area_m2"] * thickness * density) if hollow and thickness else stats["volume_m3"] * density
    llm_mass = med("mass_kg")
    static = float(np.clip(med("static_friction"), *mu_range))
    out = {
        "material": material, "is_hollow": hollow,
        "mass_kg": llm_mass, "mass_geometry_kg": round(geo_mass, 4),
        "mass_ratio_llm_vs_geometry": round(llm_mass / max(geo_mass, 1e-6), 2),
        "static_friction": static, "dynamic_friction": min(med("dynamic_friction"), static),
        "restitution": float(np.clip(med("restitution"), 0.0, 0.5)),
        "mass_samples": [s["mass_kg"] for s in samples],
        "confidence": med("confidence"), "provenance": "LLM median; friction clipped to material table",
    }
    out["flag_review"] = not (0.5 <= out["mass_ratio_llm_vs_geometry"] <= 2.0)
    return out


def write_usd(usd_path, phys, body="/root/takeout_box", mat="/root/Physics/PhysicsMaterial"):
    from pxr import Sdf, Usd, UsdPhysics
    stage = Usd.Stage.Open(str(usd_path))
    UsdPhysics.MassAPI.Apply(stage.GetPrimAtPath(body)).CreateMassAttr().Set(phys["mass_kg"])
    mprim = stage.GetPrimAtPath(mat)
    api = UsdPhysics.MaterialAPI.Apply(mprim)
    api.CreateStaticFrictionAttr().Set(phys["static_friction"])
    api.CreateDynamicFrictionAttr().Set(phys["dynamic_friction"])
    api.CreateRestitutionAttr().Set(phys["restitution"])
    # PhysX combine mode (usd-core lacks PhysxSchema, so author the schema name + attribute directly).
    mprim.AddAppliedSchema("PhysxMaterialAPI")
    mprim.CreateAttribute("physxMaterial:frictionCombineMode", Sdf.ValueTypeNames.Token).Set("average")
    mprim.SetCustomDataByKey("llm_physics", json.dumps(phys))  # keep provenance in the asset
    stage.GetRootLayer().Save()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--glb", required=True)
    p.add_argument("--photo", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--scale", type=float, default=1.0, help="same uniform scale applied in the USD builder")
    p.add_argument("--samples", type=int, default=5)
    p.add_argument("--out", default="physics.json")
    p.add_argument("--usd", help="optional: object USD to update in place")
    args = p.parse_args()

    stats = mesh_stats(*read_glb_mesh(args.glb), args.scale)
    raw = [ask_llm(args.photo, args.name, stats) for _ in range(args.samples)]
    samples = [c for c in (validate_sample(r) for r in raw if r is not None) if c is not None]
    if len(samples) < max(1, args.samples // 2):
        raise SystemExit(f"Only {len(samples)}/{args.samples} usable LLM samples; not writing physics.")
    phys = {**reconcile(samples, stats), "geometry": stats}
    Path(args.out).write_text(json.dumps({"result": phys, "raw_samples": samples}, indent=1))
    print(json.dumps(phys, indent=1))
    if args.usd:
        write_usd(args.usd, phys)


if __name__ == "__main__":
    main()
