"""
Draws the 2D grab map grid on the viewport screenshot.

Grid: 7×7 dots centred at the selection pivot, 40px screen-space spacing.
  • White dot  = pivot  (0, 0)
  • Red dots   = all other grid positions
  • (i, j) labels in red — i = horizontal step, j = vertical step from pivot
  • Thin gray lines connect the grid

The label (i, j) decodes to a world-space translation via the JSON scale fields:
  translate_h = i  *  (px_step / px_per_unit_h)  metres along cam_right
  translate_v = j  *  (px_step / px_per_unit_v)  metres along cam_up

Usage:
    python Tool_scripts/grab_map_overlay.py --json screenshots/grab_map.json
"""

import argparse
import json
import os
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--json",   required=True)
parser.add_argument("--output", default=None)
args = parser.parse_args()

with open(args.json) as f:
    data = json.load(f)

img  = Image.open(data["image"]).convert("RGB")
W, H = img.size
draw = ImageDraw.Draw(img)

vp_w = data["viewport_width"]
vp_h = data["viewport_height"]
sx   = W / vp_w
sy   = H / vp_h

def to_px(sp):
    return int(round(sp["x"] * sx)), int(round(sp["y"] * sy))

HALF_N = max(pt["i"] for pt in data["grid_points"])   # inferred from JSON

r = max(3, int(min(W, H) / 100 * 0.4))

DOT_COLOR  = (220, 40,  40)
LINE_COLOR = (60,  130, 255)

# Build 2D lookup
grid = {(pt["i"], pt["j"]): pt for pt in data["grid_points"]}

# ── Grid lines ────────────────────────────────────────────────────────────────
# Horizontal rows (constant j)
for j in range(-HALF_N, HALF_N + 1):
    row_pts = [to_px(grid[(i, j)]["screen"]) for i in range(-HALF_N, HALF_N + 1)]
    for k in range(len(row_pts) - 1):
        draw.line([row_pts[k], row_pts[k + 1]], fill=LINE_COLOR, width=1)

# Vertical columns (constant i)
for i in range(-HALF_N, HALF_N + 1):
    col_pts = [to_px(grid[(i, j)]["screen"]) for j in range(-HALF_N, HALF_N + 1)]
    for k in range(len(col_pts) - 1):
        draw.line([col_pts[k], col_pts[k + 1]], fill=LINE_COLOR, width=1)

# ── Dots ─────────────────────────────────────────────────────────────────────
for j in range(-HALF_N, HALF_N + 1):
    for i in range(-HALF_N, HALF_N + 1):
        tx, ty = to_px(grid[(i, j)]["screen"])
        draw.ellipse([tx - r, ty - r, tx + r, ty + r], fill=DOT_COLOR)

if args.output is None:
    base, ext = os.path.splitext(data["image"])
    args.output = f"{base}_grab{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Grab map overlay saved: {args.output}")
