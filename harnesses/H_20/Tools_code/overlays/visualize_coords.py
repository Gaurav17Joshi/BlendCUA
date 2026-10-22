"""
Draws a red dot (single point) or red arrow (two points) on an image.

Coordinates are (x, y) — x is horizontal (0=left), y is vertical (0=top).

Normalized mode (default):  x in [0.0, 1.0],  y in [0.0, 1.0]
Pixel mode (--pixel flag):  x in [0, width],   y in [0, height]

Usage:
    # Single point — red dot
    python Tool_scripts/visualize_coords.py --image screenshots/shot.png --coords 0.5 0.3

    # Two points — red arrow (drag)
    python Tool_scripts/visualize_coords.py --image screenshots/shot.png --coords 0.2 0.4 0.8 0.6

    # Pixel coordinates
    python Tool_scripts/visualize_coords.py --image screenshots/shot.png --coords 320 240 --pixel

    # Custom output path
    python Tool_scripts/visualize_coords.py --image screenshots/shot.png --coords 0.5 0.5 --output out.png
"""

import argparse
import math
import os
import sys

from PIL import Image, ImageDraw

parser = argparse.ArgumentParser(description="Annotate an image with a dot or arrow at given coordinates.")
parser.add_argument("--image",  required=True, help="Path to input image")
parser.add_argument("--coords", nargs="+", type=float, required=True,
                    help="'x y' for a dot, 'x1 y1 x2 y2' for an arrow")
parser.add_argument("--pixel",  action="store_true", help="Coords are pixel values, not 0-1 normalized")
parser.add_argument("--output", type=str, default=None, help="Output path (default: <input>_annotated.png)")
args = parser.parse_args()

if len(args.coords) not in (2, 4):
    print("[BlendCUA] --coords needs exactly 2 values (dot) or 4 values (arrow).")
    sys.exit(1)

img = Image.open(args.image).convert("RGB")
W, H = img.size
draw = ImageDraw.Draw(img)

def to_pixel(x, y):
    if args.pixel:
        return int(round(x)), int(round(y))
    return int(round(x * W)), int(round(y * H))

# Scale dot/arrow size relative to image dimensions
r  = max(10, min(W, H) // 60)   # dot radius
lw = max(3,  min(W, H) // 180)  # line width

if len(args.coords) == 2:
    px, py = to_pixel(args.coords[0], args.coords[1])
    # Outer white ring for contrast, red fill
    draw.ellipse([px - r - 2, py - r - 2, px + r + 2, py + r + 2],
                 fill=(255, 255, 255))
    draw.ellipse([px - r, py - r, px + r, py + r],
                 fill=(220, 30, 30))
    print(f"[BlendCUA] Dot at pixel ({px}, {py})")

else:
    x1, y1 = to_pixel(args.coords[0], args.coords[1])
    x2, y2 = to_pixel(args.coords[2], args.coords[3])

    # Shaft
    draw.line([(x1, y1), (x2, y2)], fill=(255, 255, 255), width=lw + 4)  # white outline
    draw.line([(x1, y1), (x2, y2)], fill=(220, 30, 30),   width=lw)

    # Arrowhead
    angle       = math.atan2(y2 - y1, x2 - x1)
    head_len    = r * 2.8
    head_angle  = math.radians(28)

    wing1 = (x2 - head_len * math.cos(angle - head_angle),
             y2 - head_len * math.sin(angle - head_angle))
    wing2 = (x2 - head_len * math.cos(angle + head_angle),
             y2 - head_len * math.sin(angle + head_angle))

    draw.polygon([(x2, y2), wing1, wing2], fill=(220, 30, 30),   outline=(255, 255, 255))

    # Start dot (lighter) and end dot (darker)
    draw.ellipse([x1 - r, y1 - r, x1 + r, y1 + r],
                 fill=(255, 100, 100), outline=(255, 255, 255), width=2)
    draw.ellipse([x2 - r // 2, y2 - r // 2, x2 + r // 2, y2 + r // 2],
                 fill=(160, 0, 0),   outline=(255, 255, 255), width=2)

    print(f"[BlendCUA] Arrow from pixel ({x1}, {y1}) → ({x2}, {y2})")

if args.output is None:
    base, ext = os.path.splitext(args.image)
    args.output = f"{base}_annotated{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Saved: {args.output}")
