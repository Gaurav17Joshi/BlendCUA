"""
Rotation preview overlay.

Reads a payload like screen_ruler but treats the ticks as positions on
an arc around the pivot. Each tick gets:
  • a small RADIAL line mark (perpendicular to the arc tangent, so it
    points toward/away from pivot)
  • an angle label OUTSIDE the arc

Consecutive ticks (sorted by angle) are connected with a faint blue line
to show the rotation path. The pivot is a white dot with "pivot" below.

Reuses the JSON contract of screen_ruler — pass it the same payload
emitted by `lib.ruler.rotate_ruler`.

Usage:
    python rotate_map_overlay.py --json screenshots/rotate_handle_map.json
"""

import argparse
import json
import math
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
img  = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), alpha=0.5)
draw = ImageDraw.Draw(img)

vp_w, vp_h = data["viewport_width"], data["viewport_height"]
sx, sy     = W / vp_w, H / vp_h

def to_px(sp):
    return sp["x"] * sx, sp["y"] * sy

def load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc",
                 "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

fs       = max(13, min(W, H) // 60)
fs_label = int(fs * 1.17)
fs_value = max(9, int(fs * 0.675))
r        = max(4, int(min(W, H) / 130 * 0.8))
lw       = max(2, min(W, H) // 300)

font       = load_font(fs)
font_label = load_font(fs_label)
font_value = load_font(fs_value)

def text_wh(t, f):
    bbox = draw.textbbox((0, 0), t, font=f)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

DOT_COLOR   = (220,  40,  40)
ARC_COLOR   = (60,  130, 255)
PIVOT_COLOR = (255, 255, 255)
LABEL_COLOR = (220,  40,  40)

px, py = to_px(data["pivot_screen"])
ticks  = data["screen_ruler"]["ticks"]

tick_px = [(*to_px(t["screen"]), t) for t in ticks]

# ── Faint arc: polyline through tick positions sorted by angle ──────────────
if len(tick_px) >= 2:
    s = sorted(tick_px, key=lambda x: x[2]["t"])
    pts = [(int(round(t[0])), int(round(t[1]))) for t in s]
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=ARC_COLOR, width=max(2, lw))

# ── Pivot dot + label below ────────────────────────────────────────────────
draw.ellipse([px - r, py - r, px + r, py + r],
             fill=PIVOT_COLOR, outline=(80, 80, 80))
pw, ph = text_wh("pivot", font_label)
draw.text((int(px - pw / 2), int(py + r + 4)),
          "pivot", fill=(200, 200, 200), font=font_label)

# ── Radial tick marks + labels outside the arc ─────────────────────────────
tick_half = max(int(r * 1.4), lw + 2)
label_gap = int(r * 3)

for tx, ty, t in tick_px:
    dx, dy = tx - px, ty - py
    dlen   = math.sqrt(dx * dx + dy * dy) or 1.0
    ux, uy = dx / dlen, dy / dlen     # outward radial unit vector

    # Radial tick mark — line segment along the radial direction
    x1 = int(round(tx - ux * tick_half))
    y1 = int(round(ty - uy * tick_half))
    x2 = int(round(tx + ux * tick_half))
    y2 = int(round(ty + uy * tick_half))
    draw.line([(x1, y1), (x2, y2)], fill=DOT_COLOR, width=max(2, lw))

    # Label OUTSIDE the tick, centred on its anchor
    val_str = t.get("value_str") or f"{t['t']}°"
    vw, vh  = text_wh(val_str, font_value)
    lx = int(round(tx + ux * label_gap - vw / 2))
    ly = int(round(ty + uy * label_gap - vh / 2))
    draw.text((lx, ly), val_str, fill=LABEL_COLOR, font=font_value)

# ── Legend ────────────────────────────────────────────────────────────────
quality = data.get("viewpoint_quality", 0)
draw.text((10, 10), f"Rotation preview  Q={quality:.2f}",
          fill=(200, 200, 200), font=font)

base, ext = os.path.splitext(data["image"])
out = args.output or f"{base}_rot{ext or '.png'}"
img.save(out)
print(f"[BlendCUA] Rotation overlay saved: {out}")
