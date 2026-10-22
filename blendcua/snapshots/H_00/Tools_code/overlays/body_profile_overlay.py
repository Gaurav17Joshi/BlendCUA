"""
Draws a PLANNED extrude+scale-along-local-Z chain directly on a viewport
render: each candidate ring as a perpendicular tick (length = that ring's
radius) plus rails connecting consecutive rings' tick endpoints — a taper
silhouette preview, so it can be visually compared against a reference
image composited in the same viewport. Read-only, no geometry touched.

Usage:
    python Tool_scripts/Tools_code/overlays/body_profile_overlay.py --json <path>
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

fs = max(13, min(W, H) // 65)
r  = max(4, int(min(W, H) / 140))
lw = max(2, min(W, H) // 320)


def load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


font = load_font(fs)

TICK_COLOR   = (0, 220, 255)
RAIL_COLOR   = (255, 140, 0)
CENTER_COLOR = (255, 210, 0)
OUTLINE      = (255, 255, 255)


def to_px(pt):
    return int(round(pt["x_norm"] * W)), int(round(pt["y_norm"] * H))


rings = data["rings"]

# Rails: connect consecutive rings' left points, and consecutive rings'
# right points, so the whole candidate chain reads as a taper silhouette.
for a, b in zip(rings, rings[1:]):
    draw.line([to_px(a["left"]), to_px(b["left"])], fill=RAIL_COLOR, width=lw)
    draw.line([to_px(a["right"]), to_px(b["right"])], fill=RAIL_COLOR, width=lw)

for ring in rings:
    lx, ly = to_px(ring["left"])
    rx, ry = to_px(ring["right"])
    cx, cy = to_px(ring["center"])
    draw.line([(lx, ly), (rx, ry)], fill=TICK_COLOR, width=lw)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CENTER_COLOR, outline=OUTLINE, width=1)
    draw.text((cx + r + 3, cy - r - fs - 2), ring["label"], fill=CENTER_COLOR, font=font)

draw.text((10, 10), "Body profile preview — read-only, no geometry changed",
          fill=(220, 220, 220), font=font)

if args.output is None:
    base, ext = os.path.splitext(data["image"])
    args.output = f"{base}_profile{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Body profile overlay saved: {args.output}")
