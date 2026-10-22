"""
Draws ONLY a mesh's true outline on the REFERENCE PHOTO — no cross-section
rings, no wireframe, nothing else on top of the picture.

The counterpart to `silhouette_overlay.py`. That one samples the mesh into
vertical stations and draws a yellow line down each one, which turns a
wide subject into a picket fence and hides the photograph underneath. It
also joins the topmost and bottommost projected vertex per column, which is
only a silhouette when the object is elongated along the image's horizontal
axis; on anything upright (a glass, a bottle, a lamp) every column spans the
subject's whole height and the "outline" comes out as a bounding box.

This one takes the silhouette already resolved by edge facing and draws it as
segments, so the only thing added to the photo is the red line to compare
against.

Usage:
    python .../overlays/reference_outline_overlay.py --json <path>

JSON: {image, output, silhouette: [[[x,y],[x,y]], ...], label,
       crop: [l, t, r, b] | null}
Coordinates are fractions of the FULL reference image, 0-1, top-left origin.
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

OUTLINE = (255, 40, 40)
LABEL = (245, 245, 245)


def load_font(size):
    for path in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/System/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


crop = data.get("crop")
# Line weight is chosen from the CROPPED size, not the full image. A 6000 px
# photo cropped to a 400 px subject would otherwise get a 23 px line that
# swallows the very edge it is meant to show.
if crop:
    cw, ch = max(1, crop[2] - crop[0]), max(1, crop[3] - crop[1])
else:
    cw, ch = W, H
lw = max(2, min(cw, ch) // 240)

# Segments, not one closed loop: a silhouette is legitimately several loops
# (a stem seen through a bowl, a leg in front of a belly) and stitching them
# would invent a boundary that is not in the mesh.
for a, b in data.get("silhouette", []):
    draw.line([(a[0] * W, a[1] * H), (b[0] * W, b[1] * H)],
              fill=OUTLINE, width=lw)

if crop:
    img = img.crop(tuple(crop))
    W, H = img.size
    draw = ImageDraw.Draw(img)

font = load_font(max(13, min(W, H) // 46))
label = data.get("label", "Mesh outline on the reference")
draw.rectangle([0, 0, W, int(H * 0.045) + 8], fill=(0, 0, 0))
draw.text((8, 4), label, fill=LABEL, font=font)

img.save(data["output"])
print(f"[BlendCUA] Reference outline saved: {data['output']}")
