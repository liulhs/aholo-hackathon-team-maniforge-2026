"""Contact sheet of every .jpg/.png in a folder: python -I tools/sheet.py SRC OUT CELL COLS"""
import glob
import os
import sys

from PIL import Image, ImageDraw

src, out, cell, cols = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
files = sorted(glob.glob(os.path.join(src, "*.jpg")) + glob.glob(os.path.join(src, "*.png")))
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cell * cols, cell * rows), "white")
draw = ImageDraw.Draw(sheet)
for i, path in enumerate(files):
    try:
        image = Image.open(path).convert("RGB")
        image.thumbnail((cell, cell - 14))
        sheet.paste(image, ((i % cols) * cell, (i // cols) * cell + 14))
        draw.text(((i % cols) * cell + 4, (i // cols) * cell + 1), os.path.basename(path)[:-4], fill="red")
    except Exception as error:  # noqa: BLE001
        print(path, error)
sheet.save(out)
print(len(files), sheet.size)
