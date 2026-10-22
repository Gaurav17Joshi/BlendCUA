"""
Draws a PLANNED chain-extrude path directly on a viewport render: the
starting face's centre (yellow), then each candidate point (red, numbered
1..N) connected by lines in order — a preview of exactly what
handle.apply_chain(points) would build, with no geometry touched.

Usage:
    python Tool_scripts/Tools_code/overlays/chain_plan_overlay.py --json <path>
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

START_COLOR = (255, 210, 0)     # yellow — starting face centre
DOT_COLOR   = (230, 30, 30)     # red — planned points
LINE_COLOR  = (230, 30, 30)
OUTLINE     = (255, 255, 255)


def to_px(pt):
    return int(round(pt["x_norm"] * W)), int(round(pt["y_norm"] * H))


all_pts = [data["current_point"]] + data["planned_points"]
px_pts  = [to_px(p) for p in all_pts]

# Connecting path, start -> point1 -> point2 -> ...
for a, b in zip(px_pts, px_pts[1:]):
    draw.line([a, b], fill=LINE_COLOR, width=lw)

# The RING each point will carry, when the plan supplies one. Drawn first so
# the dots and their labels stay readable on top. A path alone says where the
# tube goes and nothing about how thick it is, which on anything with a neck
# is the half that decides whether it looks right.
RING_COLOR = (80, 200, 255)
for i, (pt, (x, y)) in enumerate(zip(all_pts, px_pts)):
    # radius as a fraction of frame width -> this render's pixels, so the
    # circle is the true size whatever the render was scaled to
    rad = pt.get("radius_norm", 0.0) * W
    if rad < 1.5:
        continue
    draw.ellipse([x - rad, y - rad, x + rad, y + rad],
                 outline=RING_COLOR, width=max(1, lw - 1))
    if i == 0 or i == len(all_pts) - 1 or i % 2 == 0:
        draw.text((x - rad, y + rad + 2), f"r{pt.get('radius_mm', 0):.0f}mm",
                  fill=RING_COLOR, font=font)

# Start dot (yellow) — labelled with its own normalized coordinate too,
# not just "start", so the agent can read exact values straight off the
# image for planning the next attempt.
sx, sy = px_pts[0]
start_norm = all_pts[0]
draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=START_COLOR, outline=OUTLINE, width=2)
draw.text((sx + r + 4, sy - r - fs - 4),
          f"start ({start_norm['x_norm']:.2f}, {start_norm['y_norm']:.2f})",
          fill=START_COLOR, font=font)

# Planned points (red, numbered) — each labelled "N (x, y)".
for i, (pt, (x, y)) in enumerate(zip(all_pts[1:], px_pts[1:]), start=1):
    draw.ellipse([x - r, y - r, x + r, y + r], fill=DOT_COLOR, outline=OUTLINE, width=2)
    draw.text((x + r + 4, y - r - fs - 4),
              f"{i} ({pt['x_norm']:.2f}, {pt['y_norm']:.2f})",
              fill=DOT_COLOR, font=font)

draw.text((10, 10), "Chain plan preview — read-only, no geometry changed",
          fill=(220, 220, 220), font=font)

if args.output is None:
    base, ext = os.path.splitext(data["image"])
    args.output = f"{base}_plan{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Chain plan overlay saved: {args.output}")
