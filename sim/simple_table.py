"""A small, plain table for the cobot: wooden top, four slim legs, two clamps holding the arm.

World frame: the table top is the z=0 plane; the arm base sits at the origin, clamped to the
table's left edge, and reaches along +x. A dark mat on the top marks PLAY_AREA, the rectangle
in which objects are placed (by the recorder at random, by a visitor in the web demo). The arm
reaches every point of it with a near-vertical gripper (sampled 2026-11-18: 8-34 cm from the
base at table height with under 15 degrees of tilt).

Everything here is drawn from primitives and is looks only, except "table" (the top) and
"floor", which objects can rest on.
"""

import io
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

GENERATED_DIR = Path(__file__).parent / "models" / "table"
GENERATED_FROM_MODEL = "../table"  # textures resolve from models/so101

TABLE_EDGE_X_M = -0.035  # the edge the arm is clamped to; the base overhangs nothing
TABLE_LENGTH_M, TABLE_WIDTH_M = 0.62, 0.52
TABLE_THICKNESS_M = 0.026
TABLE_HEIGHT_M = 0.74
TABLE_CENTER_X_M = TABLE_EDGE_X_M + TABLE_LENGTH_M / 2
LEG_RADIUS_M, LEG_INSET_M = 0.016, 0.045

PLAY_AREA_X_M = (0.15, 0.28)
PLAY_AREA_Y_M = (-0.11, 0.11)
MAT_MARGIN_M = 0.035  # the mat is this much larger than the play area, so objects sit inside its border
MAT_BORDER_M = 0.003
MAT_THICKNESS_M = 0.0006

CLAMP_Y_M = (-0.043, 0.043)
CLAMP_JAW_TOP_Z_M = 0.0105  # just above the arm base's mounting flange

TEXTURE_SIZE = 512
WOOD_TONES = ((0.86, 0.74, 0.58), (0.74, 0.60, 0.44))

ASSETS_XML = """
    <texture type="skybox" builtin="gradient" rgb1="0.96 0.96 0.95" rgb2="0.80 0.82 0.84" width="64" height="384"/>
    <texture type="2d" name="table_wood" file="{generated}/table_wood.png"/>
    <material name="table_wood" texture="table_wood" texuniform="true" texrepeat="2 2" specular="0.15" shininess="0.3"/>
    <material name="table_leg" rgba="0.13 0.13 0.14 1" specular="0.2" shininess="0.4"/>
    <material name="play_mat" rgba="0.20 0.23 0.26 1" specular="0.05" shininess="0.1"/>
    <material name="play_mat_border" rgba="0.93 0.93 0.90 1" specular="0"/>
    <material name="clamp_body" rgba="0.16 0.17 0.19 1" specular="0.4" shininess="0.6"/>
    <material name="clamp_steel" rgba="0.72 0.73 0.75 1" specular="0.7" shininess="0.8"/>
    <material name="floor" rgba="0.60 0.59 0.57 1" specular="0"/>
"""

LIGHTS_XML = """
    <light name="key" pos="0.9 -1.0 1.6" dir="-0.45 0.5 -1" directional="true"
      diffuse="0.78 0.76 0.72" specular="0.25 0.25 0.25" castshadow="true"/>
    <light name="fill" pos="-0.6 0.8 1.2" dir="0.4 -0.5 -1" directional="true"
      diffuse="0.22 0.24 0.27" specular="0 0 0" castshadow="false"/>
"""

LOOKS_ONLY = 'contype="0" conaffinity="0" group="2"'


def wood_texture(seed: int = 4) -> Image.Image:
    """Pale, straight-grained wood for the table top."""
    rng = np.random.default_rng(seed)
    grain = gaussian_filter(rng.standard_normal((TEXTURE_SIZE, TEXTURE_SIZE)), sigma=(1.0, 60), mode="wrap")
    waves = gaussian_filter(rng.standard_normal((TEXTURE_SIZE, TEXTURE_SIZE)), sigma=(18, 120), mode="wrap")
    mix = 0.5 + 0.5 * np.tanh(0.30 * grain / grain.std() + 0.30 * waves / waves.std())
    mix = mix[..., None]
    light, dark = (np.array(tone) for tone in WOOD_TONES)
    return Image.fromarray(((light * (1 - mix) + dark * mix) * 255).astype(np.uint8))


def write_if_changed(path: Path, data: bytes) -> None:
    """Write `data` to `path` only if it differs, atomically (temp file + rename), so processes
    loading scenes in parallel never read a half-written file."""
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_textures() -> None:
    png = io.BytesIO()
    wood_texture().save(png, format="PNG")
    write_if_changed(GENERATED_DIR / "table_wood.png", png.getvalue())


def _box(size: tuple[float, float, float], pos: tuple[float, float, float], material: str, name: str = "") -> str:
    """A looks-only box given its full size and centre."""
    half = " ".join(f"{v / 2:.5f}" for v in size)
    centre = " ".join(f"{v:.5f}" for v in pos)
    label = f'name="{name}" ' if name else ""
    return f'<geom {label}type="box" size="{half}" pos="{centre}" material="{material}" {LOOKS_ONLY}/>'


def table_xml() -> list[str]:
    half_x, half_y, half_z = TABLE_LENGTH_M / 2, TABLE_WIDTH_M / 2, TABLE_THICKNESS_M / 2
    geoms = [
        # The one solid part: objects and the arm base rest on this.
        f'<geom name="table" type="box" size="{half_x} {half_y} {half_z}" pos="{TABLE_CENTER_X_M} 0 {-half_z}" '
        f'material="table_wood"/>',
        f'<geom name="floor" type="plane" size="6 6 0.05" pos="0 0 {-TABLE_HEIGHT_M}" material="floor"/>',
    ]
    leg_length = TABLE_HEIGHT_M - TABLE_THICKNESS_M
    for sign_x in (-1, 1):
        for sign_y in (-1, 1):
            x = TABLE_CENTER_X_M + sign_x * (half_x - LEG_INSET_M)
            y = sign_y * (half_y - LEG_INSET_M)
            geoms.append(
                f'<geom type="cylinder" size="{LEG_RADIUS_M} {leg_length / 2:.4f}" '
                f'pos="{x:.4f} {y:.4f} {-TABLE_THICKNESS_M - leg_length / 2:.4f}" material="table_leg" {LOOKS_ONLY}/>'
            )
    return geoms


def mat_xml() -> list[str]:
    (x_lo, x_hi), (y_lo, y_hi) = PLAY_AREA_X_M, PLAY_AREA_Y_M
    x_lo, x_hi, y_lo, y_hi = x_lo - MAT_MARGIN_M, x_hi + MAT_MARGIN_M, y_lo - MAT_MARGIN_M, y_hi + MAT_MARGIN_M
    centre_x, centre_y = (x_lo + x_hi) / 2, (y_lo + y_hi) / 2
    length, width = x_hi - x_lo, y_hi - y_lo
    z = MAT_THICKNESS_M / 2
    border_z = MAT_THICKNESS_M + 0.0002
    inset = 0.008  # the border line runs this far inside the mat's edge
    geoms = [_box((length, width, MAT_THICKNESS_M), (centre_x, centre_y, z), "play_mat", "play_mat")]
    for y in (y_lo + inset, y_hi - inset):
        geoms.append(_box((length - 2 * inset, MAT_BORDER_M, 0.0002), (centre_x, y, border_z), "play_mat_border"))
    for x in (x_lo + inset, x_hi - inset):
        geoms.append(_box((MAT_BORDER_M, width - 2 * inset, 0.0002), (x, centre_y, border_z), "play_mat_border"))
    return geoms


def clamp_xml(y: float) -> list[str]:
    """A C-clamp over the table edge: top jaw on the arm's base flange, screw pad under the table top."""
    spine_x = TABLE_EDGE_X_M - 0.011
    jaw_length, jaw_width, bar = 0.034, 0.016, 0.008
    bottom_z = -TABLE_THICKNESS_M - 0.045
    jaw_x = spine_x + jaw_length / 2 - bar / 2
    screw_x = TABLE_EDGE_X_M + 0.012
    pad_z = -TABLE_THICKNESS_M - 0.003
    screw_half = (pad_z - (bottom_z - 0.022)) / 2
    return [
        _box((bar, jaw_width, CLAMP_JAW_TOP_Z_M - bottom_z), (spine_x, y, (CLAMP_JAW_TOP_Z_M + bottom_z) / 2), "clamp_body"),
        _box((jaw_length, jaw_width, bar * 0.75), (jaw_x, y, CLAMP_JAW_TOP_Z_M - bar * 0.375), "clamp_body"),
        _box((jaw_length, jaw_width, bar), (jaw_x, y, bottom_z + bar / 2), "clamp_body"),
        f'<geom type="cylinder" size="0.0035 {screw_half:.4f}" pos="{screw_x:.4f} {y} {pad_z - screw_half:.4f}" '
        f'material="clamp_steel" {LOOKS_ONLY}/>',
        f'<geom type="cylinder" size="0.009 0.003" pos="{screw_x:.4f} {y} {pad_z:.4f}" material="clamp_steel" {LOOKS_ONLY}/>',
        f'<geom type="cylinder" size="0.0025 0.016" pos="{screw_x:.4f} {y} {bottom_z - 0.018:.4f}" euler="1.5708 0 0" '
        f'material="clamp_steel" {LOOKS_ONLY}/>',
    ]


def room_xml() -> str:
    geoms = table_xml() + mat_xml()
    for y in CLAMP_Y_M:
        geoms += clamp_xml(y)
    return "\n    ".join(geoms)


def assets_xml() -> str:
    return ASSETS_XML.format(generated=GENERATED_FROM_MODEL)
