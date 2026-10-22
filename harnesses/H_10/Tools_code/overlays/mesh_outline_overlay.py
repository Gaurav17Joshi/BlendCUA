"""
Draws a BUILT mesh's silhouette on a viewport render, so the geometry can be
checked against the reference photograph it was traced from.

The counterpart to the *_plan overlays: those draw what is about to be made,
this draws what was made. A plan preview can be perfect and the result still
wrong — the plan is a path and a set of radii, and what you actually judge a
body by is its outline.

Usage:
    python Tool_scripts/Tools_code/overlays/mesh_outline_overlay.py --json <path>
"""

import argparse
import json
import os
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--json", required=True)
parser.add_argument("--output", default=None)
args = parser.parse_args()

with open(args.json) as f:
    data = json.load(f)

img = Image.open(data["image"]).convert("RGB")
W, H = img.size
draw = ImageDraw.Draw(img)

fs = max(13, min(W, H) // 62)
lw = max(2, min(W, H) // 300)


def load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc",
                 "/System/Library/Fonts/Arial.ttf",
                 "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


font = load_font(fs)

OUTLINE_COLOR = (255, 40, 40)     # the silhouette
WIRE_COLOR    = (255, 170, 40)    # the mesh's own edges, faint
LABEL_COLOR   = (245, 245, 245)


def to_px(pt):
    return int(round(pt[0] * W)), int(round(pt[1] * H))


# Wireframe first, so the outline reads on top of it.
for a, b in data.get("edges", []):
    draw.line([to_px(a), to_px(b)], fill=WIRE_COLOR, width=max(1, lw - 1))

# Silhouette edges, as segments. Not a single closed loop on purpose: a
# silhouette can legitimately be several loops (a wing crossing a body, a
# leg in front of a belly), and stitching them into one would invent a
# boundary that is not there.
for a, b in data.get("silhouette", []):
    draw.line([to_px(a), to_px(b)], fill=OUTLINE_COLOR, width=lw + 1)

draw.text((10, 10), data.get("title", "Mesh outline on the reference"),
          fill=LABEL_COLOR, font=font)

if args.output is None:
    base, ext = os.path.splitext(data["image"])
    args.output = f"{base}_outline{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Mesh outline overlay saved: {args.output}")
