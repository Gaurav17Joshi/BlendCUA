"""
Draws a grid over a region of an image, either as red dots at intersections
(style=dots, default) or as thin red grid lines with a thin blue border
(style=lines) — lines mode reads as less clutter/occlusion over busy
reference imagery than dots+labels.

Usage:
    # Normalized coords (default), dots
    python Tool_scripts/grid_map.py --image screenshots/viewport.png --tl 0.2 0.3 --br 0.7 0.8 --rows 4 --cols 4

    # Lines style, no labels
    python Tool_scripts/grid_map.py --image screenshots/viewport.png --tl 0.2 0.3 --br 0.7 0.8 --rows 4 --cols 4 --style lines

    # Pixel coords
    python Tool_scripts/grid_map.py --image screenshots/viewport.png --tl 200 150 --br 800 600 --rows 4 --cols 4 --pixel
"""

import argparse
import json
import os
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--image",    required=True,            help="Input image path")
parser.add_argument("--tl",       nargs=2, type=float, required=True, metavar=("X", "Y"), help="Top-left corner")
parser.add_argument("--br",       nargs=2, type=float, required=True, metavar=("X", "Y"), help="Bottom-right corner")
parser.add_argument("--rows",     type=int, default=4,      help="Number of grid rows")
parser.add_argument("--cols",     type=int, default=4,      help="Number of grid columns")
parser.add_argument("--pixel",    action="store_true",      help="Coords are pixels, not 0-1 normalized")
parser.add_argument("--output",   type=str, default=None)
parser.add_argument("--style",    choices=["dots", "lines"], default="dots",
                     help="dots = red dots at intersections (default); "
                          "lines = thin red grid lines + thin blue border, less occlusion")
parser.add_argument("--labels",   action="store_true",      help="Draw (row,col) text next to each dot/intersection")
parser.add_argument("--json-out", type=str, default=None,   help="Write a JSON of dot positions to this path")
args = parser.parse_args()

img  = Image.open(args.image).convert("RGB")
W, H = img.size
draw = ImageDraw.Draw(img)

def to_pixel(x, y):
    if args.pixel:
        return int(round(x)), int(round(y))
    return int(round(x * W)), int(round(y * H))

x1, y1 = to_pixel(*args.tl)
x2, y2 = to_pixel(*args.br)
lw = max(2, min(W, H) // 300)
r  = max(4, int(min(W, H) // 100 * 0.8))   # ~80% of prior radius for less visual clutter

# lines style uses thinner strokes throughout (~30% thinner than the
# dots-style border) so the grid reads as reference, not the main subject.
THIN_LW = max(1, round(lw * 0.7))

# Collect dot/intersection positions (used for drawing AND optional JSON output).
points = []
for row in range(args.rows + 1):
    fy = int(y1 + (y2 - y1) * row / args.rows)
    for col in range(args.cols + 1):
        fx = int(x1 + (x2 - x1) * col / args.cols)
        points.append({"row": row, "col": col, "px": fx, "py": fy})

if args.style == "lines":
    # Thin blue border + thin red interior grid lines (full horizontal/
    # vertical lines, not just intersection markers).
    draw.rectangle([x1, y1, x2, y2], outline=(30, 120, 255), width=THIN_LW)
    for row in range(1, args.rows):
        fy = int(y1 + (y2 - y1) * row / args.rows)
        draw.line([(x1, fy), (x2, fy)], fill=(220, 30, 30), width=THIN_LW)
    for col in range(1, args.cols):
        fx = int(x1 + (x2 - x1) * col / args.cols)
        draw.line([(fx, y1), (fx, y2)], fill=(220, 30, 30), width=THIN_LW)
else:
    # Blue border (perimeter only — interior grid lines intentionally omitted).
    draw.rectangle([x1, y1, x2, y2], outline=(30, 120, 255), width=lw)
    # Red dots at every intersection (including border).
    for p in points:
        fx, fy = p["px"], p["py"]
        draw.ellipse([fx - r, fy - r, fx + r, fy + r],
                     fill=(220, 30, 30), outline=(255, 255, 255), width=1)

# Optional labels next to each dot, "(r,c)".
if args.labels:
    def _load_font(size):
        for path in ("/System/Library/Fonts/Helvetica.ttc",
                     "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
            try: return ImageFont.truetype(path, size)
            except Exception: pass
        return ImageFont.load_default()
    font = _load_font(max(11, min(W, H) // 80))
    label_off = r + 3
    for p in points:
        draw.text((p["px"] + label_off, p["py"] - label_off),
                  f"{p['row']},{p['col']}",
                  fill=(255, 255, 0), font=font)

if args.output is None:
    base, ext = os.path.splitext(args.image)
    args.output = f"{base}_grid{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Grid map saved: {args.output}  ({args.rows+1}x{args.cols+1} dots)")

if args.json_out is not None:
    payload = {
        "viewport_width":  W,
        "viewport_height": H,
        "image":           args.image,
        "output":          args.output,
        "tl_norm":         list(args.tl) if not args.pixel else None,
        "br_norm":         list(args.br) if not args.pixel else None,
        "tl_px":           [x1, y1],
        "br_px":           [x2, y2],
        "rows":            args.rows,
        "cols":            args.cols,
        "points":          points,
    }
    with open(args.json_out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"[BlendCUA] Grid JSON saved: {args.json_out}")
