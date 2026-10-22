"""
Draws the scale factor ruler on a viewport screenshot.

  • Blue axis line through pivot (full span)
  • White dot at pivot
  • Red dot + label at factor=1 (current handle position)
  • Red dots + labels at all other ticks
  • Labels: ordinal (s+1, s+2 …) + decoded factor

Usage:
    python Tool_scripts/scale_map_overlay.py --json screenshots/scale_map.json
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

# Fade background by 50%
black = Image.new("RGB", (W, H), (0, 0, 0))
img   = Image.blend(img, black, alpha=0.5)

draw = ImageDraw.Draw(img)

vp_w = data["viewport_width"]
vp_h = data["viewport_height"]
sx, sy = W / vp_w, H / vp_h

def to_px(sp):
    return int(round(sp["x"] * sx)), int(round(sp["y"] * sy))

fs   = max(13, min(W, H) // 60)
fs_l = int(fs * 1.3)
r    = max(4,  int(min(W, H) / 130 * 0.8))
lw   = max(2,  min(W, H) // 300)

def load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

font   = load_font(fs)
font_l = load_font(fs_l)

DOT_COLOR   = (220, 40,  40)
AXIS_COLOR  = (60,  130, 255)
PIVOT_COLOR = (255, 255, 255)
LABEL_COLOR = (220, 40,  40)
HANDLE_COLOR = (255, 200, 0)   # yellow = current position (factor=1)

px, py = to_px(data["pivot_screen"])

# Blue axis line (full image span)
ticks = data["ticks"]
ddx, ddy = 1, 0   # default: horizontal
if ticks:
    # direction from pivot to first positive tick
    pos = next((t for t in ticks if t["factor"] > 1.0), ticks[-1])
    tx, ty = to_px(pos["screen"])
    ddx, ddy = tx - px, ty - py
    dlen = (ddx**2 + ddy**2)**0.5 or 1.0
    ext  = max(W, H) + 100
    draw.line([(int(px - ddx/dlen*ext), int(py - ddy/dlen*ext)),
               (int(px + ddx/dlen*ext), int(py + ddy/dlen*ext))],
              fill=AXIS_COLOR, width=max(2, lw))

# Pivot dot
draw.ellipse([px - r, py - r, px + r, py + r], fill=PIVOT_COLOR, outline=(80,80,80))
draw.text((px + r + 4, py + r + 4), "pivot", fill=(200,200,200), font=font_l)

# Handle (factor=1) dot — yellow
if data.get("handle_screen"):
    hx, hy = to_px(data["handle_screen"])
    draw.ellipse([hx-r, hy-r, hx+r, hy+r], fill=HANDLE_COLOR, outline=(255,255,255))
    # draw.text((hx + r + 4, hy - r - fs_l - 4), "s=1 (current)", fill=HANDLE_COLOR, font=font_l)
    draw.text((hx + r + 4, hy + r + 4), "s=1 (current)", fill=HANDLE_COLOR, font=font_l)

# Axis orientation: vertical when |dy| > |dx| relative to pivot→first-tick
vertical_axis = abs(ddy) > abs(ddx) if ticks else False

# Ticks
for tick in ticks:
    tx, ty = to_px(tick["screen"])
    is_one = abs(tick["factor"] - 1.0) < 0.01
    if is_one:
        continue   # already drawn as handle
    draw.ellipse([tx-r, ty-r, tx+r, ty+r], fill=DOT_COLOR, outline=(255,255,255))
    ordinal = str(tick['ordinal'])
    value   = f"({tick['factor']:.2f}x)"
    if vertical_axis:
        # Factor only, to the right of the dot (e.g. "2x", "4x")
        draw.text((tx + r + 4, ty - fs_l // 2), f"{tick['factor']:g}x", fill=LABEL_COLOR, font=font_l)
    else:
        # Stacked labels above the dot (horizontal axis)
        draw.text((tx - r, ty - r - 4 - fs_l),          value,   fill=LABEL_COLOR, font=font_l)
        draw.text((tx - r, ty - r - 4 - fs_l * 2 - 2),  ordinal, fill=LABEL_COLOR, font=font_l)

# Legend
axis_names = {(1,0,0):"X",  (0,1,0):"Y",  (0,0,1):"Z",
              (1,1,0):"XY", (0,1,1):"YZ", (1,0,1):"XZ",
              (1,1,1):"XYZ"}
am = tuple(data.get("axis_mask", [1,1,1]))
axis_str = axis_names.get(am, str(am))
draw.text((10, 10),          f"Scale map — axis: {axis_str}", fill=(200,200,200), font=font)
draw.text((10, 10+fs+4),     f"Viewpoint Q={data.get('viewpoint_quality',0):.2f}", fill=(200,200,200), font=font)
draw.text((10, 10+2*(fs+4)), f"px/factor = {data.get('px_per_factor',0):.1f}px", fill=(200,200,200), font=font)

if args.output is None:
    base, ext = os.path.splitext(data["image"])
    args.output = f"{base}_smap{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Scale map overlay saved: {args.output}")
