"""Derive an SO-101 model without the wrist camera mount from the Menagerie model.

Menagerie added a camera mount (shell, PCB, lens, two collision boxes) on top of the official
`so101_new_calib` model; our arm has no camera. This drops every geom of the `camera_mount`
body, so it is neither drawn nor collides, and keeps the rest of the Menagerie tuning. The
`wrist_cam` viewpoint stays: it is invisible and may serve as a wrist view for recorded demos.
The printed parts are also recoloured from yellow to white (looks only).

Writes so101_nocam.xml and scene_nocam.xml next to the originals (run by fetch_models.sh):

    python sim/make_nocam_model.py
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MODEL_DIR = Path(__file__).parent / "models" / "so101"
MOUNT_BODY = "camera_mount"
UNUSED_MESH = "wrist_roll_follower_so101_camera_mount"
PRINTED_PART_RGBA = "1 0.82 0.12 1"  # Menagerie's yellow filament
WHITE_PART_RGBA = "0.94 0.94 0.92 1"


def strip_camera_mount(robot_xml: Path, out_xml: Path) -> int:
    tree = ET.parse(robot_xml)
    root = tree.getroot()
    mount = root.find(f".//body[@name='{MOUNT_BODY}']")
    if mount is None:
        raise ValueError(f"No body '{MOUNT_BODY}' in {robot_xml}")
    geoms = mount.findall("geom")
    for geom in geoms:
        mount.remove(geom)
    for asset in root.iter("asset"):
        for mesh in asset.findall("mesh"):
            if Path(mesh.get("file", "")).stem == UNUSED_MESH:
                asset.remove(mesh)
    for material in root.iter("material"):
        if material.get("rgba") == PRINTED_PART_RGBA:  # printed parts go white; motors stay black
            material.set("rgba", WHITE_PART_RGBA)
            material.set("specular", "0.3")
            material.set("shininess", "0.5")
    tree.write(out_xml, encoding="unicode")
    return len(geoms)


def write_scene(scene_xml: Path, robot_name: str, out_xml: Path) -> None:
    text = scene_xml.read_text()
    if 'file="so101.xml"' not in text:
        raise ValueError(f"{scene_xml} does not include so101.xml")
    out_xml.write_text(text.replace('file="so101.xml"', f'file="{robot_name}"'))


def main() -> int:
    removed = strip_camera_mount(MODEL_DIR / "so101.xml", MODEL_DIR / "so101_nocam.xml")
    write_scene(MODEL_DIR / "scene.xml", "so101_nocam.xml", MODEL_DIR / "scene_nocam.xml")
    print(f"Removed {removed} camera-mount geoms -> {MODEL_DIR / 'scene_nocam.xml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
