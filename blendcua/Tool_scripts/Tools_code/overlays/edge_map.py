"""
Annotates a viewport screenshot with labeled edge lines inside a specified region.

Usage:
    python Tool_scripts/edge_map.py --json screenshots/edges.json --tl 0.2 0.3 --br 0.7 0.8

    # Pixel coords
    python Tool_scripts/edge_map.py --json screenshots/edges.json --tl 200 150 --br 800 600 --pixel

    # Override image
    python Tool_scripts/edge_map.py --json screenshots/edges.json --image screenshots/other.png --tl 0.1 0.1 --br 0.9 0.9
"""

import argparse
import json
import os
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--json",   required=True,  help="Path to edges.json from export_edges.py")
parser.add_argument("--image",  default=None,   help="Override image path (default: from JSON)")
parser.add_argument("--tl",     nargs=2, type=float, required=True, metavar=("X", "Y"))
parser.add_argument("--br",     nargs=2, type=float, required=True, metavar=("X", "Y"))
parser.add_argument("--pixel",  action="store_true", help="Coords are pixels, not 0-1 normalized")
parser.add_argument("--output", default=None)
args = parser.parse_args()

with open(args.json) as f:
    data = json.load(f)

img_path = args.image or data["image"]
img      = Image.open(img_path).convert("RGB")
W, H     = img.size
draw     = ImageDraw.Draw(img)

vp_w = data["viewport_width"]
vp_h = data["viewport_height"]
sx   = W / vp_w
sy   = H / vp_h

def to_pixel(x, y):
    if args.pixel:
        return int(round(x)), int(round(y))
    return int(round(x * W)), int(round(y * H))

x1, y1 = to_pixel(*args.tl)
x2, y2 = to_pixel(*args.br)

lw   = max(2, min(W, H) // 300)
elw  = max(2, min(W, H) // 200)   # edge line width
fs   = max(12, min(W, H) // 55)

# Blue bounding box
draw.rectangle([x1, y1, x2, y2], outline=(30, 120, 255), width=lw)

# Font
font = None
for _font_path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf",
                    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
    try:
        font = ImageFont.truetype(_font_path, fs)
        break
    except Exception:
        pass
if font is None:
    font = ImageFont.load_default()

def sp(p):
    """Scale a viewport point to image coords."""
    return (p["x"] * sx, p["y"] * sy)

label_n = 1
for eid, e in data["edges"].items():
    mx, my = sp(e["mid"])

    # Filter: midpoint inside box
    if not (x1 <= mx <= x2 and y1 <= my <= y2):
        continue

    ax, ay = sp(e["v0"])
    bx, by = sp(e["v1"])

    # Yellow edge line (white outline for contrast)
    draw.line([(ax, ay), (bx, by)], fill=(255, 255, 255), width=elw + 3)
    draw.line([(ax, ay), (bx, by)], fill=(255, 215, 0),   width=elw)

    # Label at midpoint
    label = f"E_{label_n}"
    draw.text((mx + 4, my - fs // 2), label, fill=(220, 30, 30), font=font)
    label_n += 1

if args.output is None:
    base, ext = os.path.splitext(img_path)
    args.output = f"{base}_emap{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Edge map saved: {args.output}  ({label_n - 1} edges labeled)")
