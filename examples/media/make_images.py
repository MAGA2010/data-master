"""Build a tiny image set with a near-duplicate and a blank frame.

The near-duplicate is the same scene re-encoded at 60% quality, so the bytes
differ and a sha256 check calls them two files.  The aHash check is what notices
they are one image.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
OUT = HERE / "images"
OUT.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(3)
w, h = 640, 480
base = np.zeros((h, w, 3), dtype=np.uint8)
for y in range(h):
    base[y, :, :] = (40 + y // 6, 80 + y // 9, 150 - y // 10)
img = Image.fromarray(base)
d = ImageDraw.Draw(img)
d.ellipse((150, 120, 480, 400), fill=(220, 180, 90), outline=(30, 30, 30), width=4)
d.rectangle((40, 40, 200, 110), fill=(250, 250, 250))
img.save(OUT / "scene.png")

img.convert("RGB").save(OUT / "scene_reencoded.jpg", quality=60)
img.filter(ImageFilter.GaussianBlur(1.2)).rotate(0.4).save(OUT / "scene_soft.jpg", quality=88)

Image.new("RGB", (800, 600), (255, 255, 255)).save(OUT / "blank.png")
Image.new("RGB", (128, 96), (120, 120, 120)).save(OUT / "thumb.png")

(OUT / "corrupt.jpg").write_bytes(b"\xff\xd8\xff\xe0not-really-a-jpeg")
print("wrote", OUT)
