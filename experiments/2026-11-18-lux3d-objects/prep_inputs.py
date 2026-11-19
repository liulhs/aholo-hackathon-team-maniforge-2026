"""Crop each source photo to a square around the object, for Lux3D image-to-3D.

The object is found as the pixels that differ from the background colour (median of the image
border); the crop is that bounding box plus a margin, padded to a square with the background
colour and resized to OUTPUT_PX. `python -I prep_inputs.py` from this folder.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage

HERE = Path(__file__).resolve().parent
OUTPUT_PX = 1024
MARGIN = 0.12
# name -> colour-difference threshold (0-255) that separates the object from its background
SOURCES = {"labubu_original_v3": 18, "twinkle_little_devil_star": 18, "airpods_pro_case": 14}


def object_box(rgb: np.ndarray, threshold: int) -> tuple[int, int, int, int]:
    border = np.concatenate([rgb[:20].reshape(-1, 3), rgb[-20:].reshape(-1, 3), rgb[:, :20].reshape(-1, 3), rgb[:, -20:].reshape(-1, 3)])
    background = np.median(border, axis=0)
    mask = np.abs(rgb.astype(int) - background).max(axis=2) > threshold
    mask = ndimage.binary_opening(mask, iterations=3)
    labels, count = ndimage.label(mask)
    if count == 0:
        raise ValueError("no object found")
    largest = 1 + int(np.argmax(ndimage.sum(mask, labels, range(1, count + 1))))
    ys, xs = np.nonzero(labels == largest)
    return xs.min(), ys.min(), xs.max(), ys.max()


def main() -> None:
    for name, threshold in SOURCES.items():
        image = ImageOps.exif_transpose(Image.open(HERE / "input" / "source" / f"{name}.jpg")).convert("RGB")
        rgb = np.asarray(image)
        x0, y0, x1, y1 = object_box(rgb, threshold)
        side = int(max(x1 - x0, y1 - y0) * (1 + 2 * MARGIN))
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        left, top = cx - side // 2, cy - side // 2
        fill = tuple(int(v) for v in np.median(rgb[:20].reshape(-1, 3), axis=0))
        canvas = Image.new("RGB", (side, side), fill)
        canvas.paste(image, (-left, -top))
        canvas.resize((OUTPUT_PX, OUTPUT_PX), Image.LANCZOS).save(HERE / "input" / f"{name}.png")
        print(f"{name}: object {x1 - x0}x{y1 - y0} px in {image.size}, crop side {side}")


if __name__ == "__main__":
    main()
