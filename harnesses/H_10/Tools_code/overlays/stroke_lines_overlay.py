"""
Draws N candidate stroke paths (already-resolved dense polylines, one
color per stroke) plus their anchor points on a viewport render — a
preview of exactly what paint.apply_paint_lines(strokes) would bake, with
no texture changed.

Usage:
    python Tool_scripts/Tools_code/overlays/stroke_lines_overlay.py --json <path>
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

fs = max(13, min(W, H) // 60)
r  = max(4, int(min(W, H) / 140))
lw = max(2, min(W, H) // 350)


def load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


font = load_font(fs)

PALETTE = [(230, 30, 30), (255, 210, 0), (60, 200, 255),
           (140, 255, 90), (255, 140, 220), (255, 150, 50)]

for i, stroke in enumerate(data["strokes"]):
    color = tuple(stroke.get("color_hint") or PALETTE[i % len(PALETTE)])
    poly = [(p[0] * W, p[1] * H) for p in stroke["polyline"]]
    if len(poly) >= 2:
        draw.line(poly, fill=color, width=lw)
    # A stroke can suppress its per-anchor dots. Closed shapes drawn as a
    # polyline — a brush-size circle, say — have dozens of anchors, and a
    # numbered dot on each buries the picture under its own annotation.
    if stroke.get("show_anchors", True):
        for j, (ax, ay) in enumerate(stroke["anchors"]):
            px, py = ax * W, ay * H
            draw.ellipse([px - r, py - r, px + r, py + r], fill=color,
                         outline=(255, 255, 255), width=2)
            draw.text((px + r + 3, py - r - fs - 2),
                      f"{stroke.get('label', 's')}{j}", fill=color, font=font)
    elif stroke.get("label"):
        # one label for the whole shape, at its top
        top = min(stroke["polyline"], key=lambda q: q[1])
        draw.text((top[0] * W + 4, top[1] * H - fs - 4), stroke["label"],
                  fill=color, font=font)

draw.text((10, 10), "Stroke lines preview — read-only, no texture changed",
          fill=(220, 220, 220), font=font)

if args.output is None:
    base, ext = os.path.splitext(data["image"])
    args.output = f"{base}_lines{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Stroke lines overlay saved: {args.output} ({len(data['strokes'])} stroke(s))")
