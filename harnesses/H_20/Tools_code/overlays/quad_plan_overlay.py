"""
Draws a PLANNED quad-vertex-move preview directly on a viewport render:
each corner gets its OWN color — a small hollow circle at its CURRENT
(unmoved) mesh position, a filled circle of the SAME color at its TARGET
position, and a line connecting current -> target so it's visually clear
"this vertex moves to there". The 4 target points are also connected to
each other as a closed quad outline (in the given order, wrapping back
to the first). No geometry is touched — this only reads a JSON payload
and draws on top of an existing screenshot.

Usage:
    python Tool_scripts/Tools_code/overlays/quad_plan_overlay.py --json <path>
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
r  = max(6, int(min(W, H) / 100))
lw = max(2, min(W, H) // 300)


def load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


font = load_font(fs)
OUTLINE = (255, 255, 255)


def to_px(pt):
    return int(round(pt["x_norm"] * W)), int(round(pt["y_norm"] * H))


corners = data["corners"]
target_px = [to_px(c["target"]) for c in corners]

# Closed quad outline connecting the targets, in order, wrapping around.
n = len(target_px)
for i in range(n):
    a = target_px[i]
    b = target_px[(i + 1) % n]
    draw.line([a, b], fill=(200, 200, 200), width=lw)

for c, (tx, ty) in zip(corners, target_px):
    color = tuple(c["color"])
    # Current position: hollow circle + line to target, labelled with its
    # own coordinate. Target: filled circle, also labelled with its
    # coordinate. No descriptive word labels ("near_leg" etc) — the
    # distinct color per corner is enough to tell which is which; the
    # coordinate numbers themselves stay, since those are the actually
    # useful/actionable part to read off the image.
    if c.get("current") is not None:
        cx, cy = to_px(c["current"])
        draw.line([(cx, cy), (tx, ty)], fill=color, width=max(1, lw - 1))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=3)
        draw.text((cx + r + 4, cy - r - fs - 4),
                  f"({c['current']['x_norm']:.2f}, {c['current']['y_norm']:.2f})",
                  fill=color, font=font)
    draw.ellipse([tx - r, ty - r, tx + r, ty + r], fill=color, outline=OUTLINE, width=2)
    draw.text((tx + r + 4, ty + 4),
              f"({c['target']['x_norm']:.2f}, {c['target']['y_norm']:.2f})",
              fill=color, font=font)

draw.text((10, 10), "Quad plan preview — read-only, no geometry changed",
          fill=(220, 220, 220), font=font)

if args.output is None:
    base, ext = os.path.splitext(data["image"])
    args.output = f"{base}_plan{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Quad plan overlay saved: {args.output}")
