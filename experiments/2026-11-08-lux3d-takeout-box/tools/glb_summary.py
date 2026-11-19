"""Print structure of one or more GLBs. Usage: glb_summary.py <tools_dir> <file.glb>..."""
import json
import sys

import numpy as np

sys.path.insert(0, sys.argv[1])
from inspect_glb import parse_glb, read_accessor  # noqa: E402

for path in sys.argv[2:]:
    doc, blob = parse_glb(path)
    print("=====", "/".join(path.split("/")[-2:]), "| generator", doc.get("asset", {}).get("generator"))
    print(" counts", {k: len(v) for k, v in doc.items() if isinstance(v, list)},
          "| extUsed", doc.get("extensionsUsed"), "| extras", doc.get("extras"))
    print(" nodes", json.dumps(doc["nodes"])[:300])
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            pos = read_accessor(doc, blob, prim["attributes"]["POSITION"]).astype(float)
            tris = doc["accessors"][prim["indices"]]["count"] // 3 if "indices" in prim else None
            print("  prim attrs", list(prim["attributes"]), "verts", len(pos), "tris", tris,
                  "size", np.round(np.ptp(pos, 0), 4).tolist(),
                  "center", np.round((pos.max(0) + pos.min(0)) / 2, 4).tolist())
    for mat in doc.get("materials", []):
        print("  material", json.dumps(mat)[:400])
    for i, img in enumerate(doc.get("images", [])):
        view = doc["bufferViews"][img["bufferView"]] if "bufferView" in img else None
        print("  image", i, img.get("mimeType"), img.get("name"), view and view["byteLength"])
