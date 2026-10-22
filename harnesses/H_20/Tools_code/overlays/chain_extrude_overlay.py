"""
Draws a normalized-coordinate reference grid (0.0-1.0, top-left origin,
same PIL convention used everywhere else in this codebase) plus a red dot
marking the currently selected face's centre, for
handle.chain_preview() / handle.apply_chain().

The agent reads this image, then supplies a list of (x_norm, y_norm)
points off the same grid to apply_chain(), which extrudes the selected
face through each point in turn — one action instead of one
prepare/apply round-trip per segment.

Usage:
    python Tool_scripts/Tools_code/overlays/chain_extrude_overlay.py --json <path>
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

fs = max(12, min(W, H) // 70)
r  = max(5, int(min(W, H) / 120))


def load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


font = load_font(fs)

GRID_COLOR  = (90, 90, 90)
LABEL_COLOR = (170, 170, 170)
DOT_COLOR   = (230, 30, 30)
DOT_OUTLINE = (255, 255, 255)
PT_COLOR    = (60, 160, 255)

# Reference grid every 0.1 normalized, labelled along the top + left edges,
# so the agent can read off (x_norm, y_norm) for future chain points by eye.
for i in range(1, 10):
    x_norm = i / 10.0
    x = int(round(x_norm * W))
    draw.line([(x, 0), (x, H)], fill=GRID_COLOR, width=1)
    draw.text((x + 2, 2), f"{x_norm:.1f}", fill=LABEL_COLOR, font=font)

    y_norm = i / 10.0
    y = int(round(y_norm * H))
    draw.line([(0, y), (W, y)], fill=GRID_COLOR, width=1)
    draw.text((2, y + 2), f"{y_norm:.1f}", fill=LABEL_COLOR, font=font)

# Any previously-applied chain points, if this is a re-render mid-chain.
for pt in data.get("history_points", []):
    hx, hy = int(round(pt["x_norm"] * W)), int(round(pt["y_norm"] * H))
    draw.ellipse([hx - r, hy - r, hx + r, hy + r], fill=PT_COLOR, outline=DOT_OUTLINE, width=2)

# Current face centre — red dot, labelled with its exact normalized coords.
cp = data["current_point"]
cx, cy = int(round(cp["x_norm"] * W)), int(round(cp["y_norm"] * H))
draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DOT_COLOR, outline=DOT_OUTLINE, width=2)
draw.text((cx + r + 4, cy - r - fs - 4),
          f"current ({cp['x_norm']:.2f}, {cp['y_norm']:.2f})",
          fill=DOT_COLOR, font=font)

if args.output is None:
    base, ext = os.path.splitext(data["image"])
    args.output = f"{base}_chain{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Chain extrude overlay saved: {args.output}")
