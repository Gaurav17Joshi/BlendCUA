"""
Draws the inset thickness ruler on a viewport screenshot.

  • Blue ruler line from boundary edge midpoint inward toward face center
  • White dot at ruler start (boundary), labeled "boundary"
  • Green dot at face center
  • Red dots + labels at each tick
  • Labels: ordinal (t1, t2 …) + decoded thickness in meters

Usage:
    python Tool_scripts/inset_map_overlay.py --json screenshots/inset_map.json
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
fs_l = int(fs * 1.17)        # 10% smaller than the prior 1.3× ordinal font
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

TICK_COLOR   = (220, 40,  40)
RULER_COLOR  = (60,  130, 255)
START_COLOR  = (255, 255, 255)
CENTER_COLOR = (60,  200, 60)
LABEL_COLOR  = (220, 40,  40)

ticks = data["ticks"]

# Ruler line: from boundary start through ticks toward center, extended past center
bx, by = to_px(data["start_screen"])
cx, cy = to_px(data["center_screen"])
dx, dy = cx - bx, cy - by
dlen   = (dx**2 + dy**2)**0.5 or 1.0
ext    = max(W, H) + 100
draw.line([(int(bx - dx/dlen*r*2), int(by - dy/dlen*r*2)),
           (int(bx + dx/dlen*ext), int(by + dy/dlen*ext))],
          fill=RULER_COLOR, width=max(2, lw))

# Boundary start dot
draw.ellipse([bx-r, by-r, bx+r, by+r], fill=START_COLOR, outline=(80, 80, 80))
draw.text((bx + r + 4, by - fs_l // 2), "boundary", fill=(200, 200, 200), font=font_l)

# Center dot
draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=CENTER_COLOR, outline=(255, 255, 255))
draw.text((cx + r + 4, cy - fs_l // 2), "center", fill=CENTER_COLOR, font=font_l)

# Perpendicular unit vectors to the ruler line.
# Of the two perpendiculars, pick the one pointing "up in image" (smaller y)
# for ordinal labels, the other for value labels.
ux, uy = dx / dlen, dy / dlen
perp_a = (-uy, ux)
perp_b = ( uy, -ux)
up_perp, down_perp = (perp_a, perp_b) if perp_a[1] < perp_b[1] else (perp_b, perp_a)

# Smaller font for the value (numeric) labels (10% smaller than before)
fs_v   = max(9, int(fs * 0.675))
font_v = load_font(fs_v)

def text_wh(text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

tick_half = max(int(r * 1.4), lw + 2)   # half-length of perpendicular tick mark
label_gap = int(r * 4)                  # 2× the prior offset — declutters labels

# Perpendicular tick marks (always all of them — the marks themselves don't clutter)
for tick in ticks:
    tx, ty = to_px(tick["screen"])
    x1 = int(tx + up_perp[0]   * tick_half)
    y1 = int(ty + up_perp[1]   * tick_half)
    x2 = int(tx + down_perp[0] * tick_half)
    y2 = int(ty + down_perp[1] * tick_half)
    draw.line([(x1, y1), (x2, y2)], fill=TICK_COLOR, width=max(2, lw))

# Labels on every THIRD tick (3× the original spacing)
for i, tick in enumerate(ticks):
    if i % 3 != 0:
        continue
    tx, ty = to_px(tick["screen"])

    # Ordinal ABOVE the line
    ord_str = tick["ordinal"]
    ow, oh  = text_wh(ord_str, font_l)
    ox = int(tx + up_perp[0] * label_gap - ow / 2)
    oy = int(ty + up_perp[1] * label_gap - oh)
    draw.text((ox, oy), ord_str, fill=LABEL_COLOR, font=font_l)

    # Value BELOW the line (smaller font)
    val_str = f"{tick['thickness']:.3f}"
    vw, vh  = text_wh(val_str, font_v)
    vx = int(tx + down_perp[0] * label_gap - vw / 2)
    vy = int(ty + down_perp[1] * label_gap)
    draw.text((vx, vy), val_str, fill=LABEL_COLOR, font=font_v)

# Legend
mode_str = "individual" if data.get("use_individual") else "region"
draw.text((10, 10),          f"Inset map — mode: {mode_str}",               fill=(200, 200, 200), font=font)
draw.text((10, 10+fs+4),     f"max_thickness = {data.get('max_thickness',0):.4f} m", fill=(200, 200, 200), font=font)
draw.text((10, 10+2*(fs+4)), f"px/unit = {data.get('px_per_unit',0):.1f} px",        fill=(200, 200, 200), font=font)
draw.text((10, 10+3*(fs+4)), f"ticks = {len(ticks)}",                                fill=(200, 200, 200), font=font)

if args.output is None:
    base, ext = os.path.splitext(data["image"])
    args.output = f"{base}_imap{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Inset map overlay saved: {args.output}")
