"""
Draws a built mesh's silhouette directly onto the REFERENCE PHOTO — not onto a
viewport render — so the model's own outline can be compared against the thing
it is tracing, at the photo's full resolution.

Why not just look at the viewport? A viewport screenshot shows the model
composited over the reference at whatever zoom the view happens to be at, with
the model's solid shading HIDING the photo underneath exactly where the
comparison matters. You can see that the model covers the bat; you cannot see
by how much it misses. Drawing an outline instead leaves the photo visible on
both sides of every edge, and the crop is chosen around the mesh, so a 20%
width error reads as an obvious gap rather than a judgement call.

Usage:
    python .../overlays/silhouette_overlay.py --json <path>

JSON: {image, output, top: [[x_px, y_px], ...], bottom: [...], rings: [...],
       label, crop: [l, t, r, b] | null}
"""

import argparse
import json

from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--json", required=True)
args = parser.parse_args()

with open(args.json) as f:
    data = json.load(f)

img = Image.open(data["image"]).convert("RGB")
W, H = img.size
draw = ImageDraw.Draw(img)

OUTLINE = (255, 40, 40)      # the model's silhouette
RING    = (255, 200, 0)      # the cross-section at each sampled station
lw      = max(3, min(W, H) // 260)


def load_font(size):
    for path in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


top = [tuple(p) for p in data.get("top", [])]
bottom = [tuple(p) for p in data.get("bottom", [])]

# Rings first, so the outline draws over them.
for a, b in zip(top, bottom):
    draw.line([a, b], fill=RING, width=max(1, lw // 3))
if len(top) > 1:
    draw.line(top, fill=OUTLINE, width=lw)
if len(bottom) > 1:
    draw.line(bottom, fill=OUTLINE, width=lw)
# Close the ends so the silhouette reads as one shape.
for pair in ((top[:1] + bottom[:1]), (top[-1:] + bottom[-1:])):
    if len(pair) == 2:
        draw.line(pair, fill=OUTLINE, width=lw)

crop = data.get("crop")
if crop:
    img = img.crop(tuple(crop))

label = data.get("label") or ""
if label:
    d2 = ImageDraw.Draw(img)
    font = load_font(max(15, min(img.size) // 34))
    d2.text((12, 10), label, fill=(255, 255, 255), font=font,
            stroke_width=3, stroke_fill=(0, 0, 0))

img.save(data["output"])
print(f"[silhouette_overlay] wrote {data['output']} ({img.size[0]}x{img.size[1]})")
