"""
Draws a grab destination grid: NxN red dots inside a blue perimeter.

No text labels — the agent identifies a target dot by its (i, j) position
read from the JSON. The grid is centred on the selection pivot (drawn as a
white dot). 50% black-blend on the source screenshot for contrast.

Usage:
    python grab_grid_overlay.py --json screenshots/grab_grid.json
"""

import argparse
import json
import os
from PIL import Image, ImageDraw

parser = argparse.ArgumentParser()
parser.add_argument("--json",   required=True)
parser.add_argument("--output", default=None)
args = parser.parse_args()

with open(args.json) as f:
    data = json.load(f)

img  = Image.open(data["image"]).convert("RGB")
W, H = img.size
img  = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), alpha=0.5)
draw = ImageDraw.Draw(img)

vp_w   = data["viewport_width"]
vp_h   = data["viewport_height"]
sx, sy = W / vp_w, H / vp_h

def to_px(sp):
    return int(round(sp["x"] * sx)), int(round(sp["y"] * sy))

r  = max(4, int(min(W, H) / 130 * 0.8))
lw = max(2, min(W, H) // 300)

DOT_COLOR   = (220,  40,  40)
PERIM_COLOR = (60,  130, 255)
PIVOT_COLOR = (255, 255, 255)

# ── Blue perimeter — outermost bounding box of all grid points, padded ──
xs = [to_px(p["screen"])[0] for p in data["grid_points"]]
ys = [to_px(p["screen"])[1] for p in data["grid_points"]]
if xs and ys:
    pad = r + 4
    draw.rectangle(
        [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad],
        outline=PERIM_COLOR, width=lw,
    )

# ── Red dots at every grid point ──
for pt in data["grid_points"]:
    tx, ty = to_px(pt["screen"])
    draw.ellipse([tx - r, ty - r, tx + r, ty + r],
                 fill=DOT_COLOR, outline=(255, 255, 255))

# ── White pivot (current position) on top so it's not hidden by a dot ──
px, py = to_px(data["pivot_screen"])
draw.ellipse([px - r, py - r, px + r, py + r],
             fill=PIVOT_COLOR, outline=(80, 80, 80))

base, ext = os.path.splitext(data["image"])
out = args.output or f"{base}_ggrid{ext or '.png'}"
img.save(out)
print(f"[BlendCUA] Grab grid overlay saved: {out}  ({len(data['grid_points'])} dots)")
