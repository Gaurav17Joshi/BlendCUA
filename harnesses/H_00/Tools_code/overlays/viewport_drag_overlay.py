"""
Draws a grid of labelled red dots across the entire viewport screenshot.
Each dot's label is its normalised image coordinate ("x.x,y.y"), so the
agent can specify a pan target directly from the label — no JSON lookup needed.

Usage:
    python overlays/viewport_drag_overlay.py --image path/to/screenshot.png
    python overlays/viewport_drag_overlay.py --image shot.png --rows 6 --cols 8
    python overlays/viewport_drag_overlay.py --image shot.png --output drag_out.png
"""

import argparse
import os
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--image",  required=True,             help="Input viewport screenshot")
parser.add_argument("--rows",   type=int, default=8,       help="Dot rows (intersections = rows+1)")
parser.add_argument("--cols",   type=int, default=10,      help="Dot cols (intersections = cols+1)")
parser.add_argument("--output", type=str, default=None,    help="Output path (default: <image>_drag.png)")
args = parser.parse_args()

img  = Image.open(args.image).convert("RGB")
W, H = img.size

# Darken background 35% so dots and labels read clearly (TOOL_AUTHORING.md overlay rule).
dark = Image.new("RGB", (W, H), (0, 0, 0))
img  = Image.blend(img, dark, alpha=0.35)
draw = ImageDraw.Draw(img)

r = max(3, int(min(W, H) / 90 * 0.6))

def _load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc",
                 "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

font = _load_font(max(10, min(W, H) // 70))

for row in range(args.rows + 1):
    y_norm = row / args.rows
    fy = int(round(y_norm * H))
    for col in range(args.cols + 1):
        x_norm = col / args.cols
        fx = int(round(x_norm * W))

        # Red dot with white outline.
        draw.ellipse([fx - r, fy - r, fx + r, fy + r],
                     fill=(220, 30, 30), outline=(255, 255, 255), width=1)

        # Label: "x.x,y.y" in yellow — this IS the value the agent passes to pan_to_norm().
        label = f"{x_norm:.1f},{y_norm:.1f}"
        draw.text((fx + r + 3, fy - r), label, fill=(255, 230, 0), font=font)

if args.output is None:
    base, ext = os.path.splitext(args.image)
    args.output = f"{base}_drag{ext or '.png'}"

img.save(args.output)
print(f"[BlendCUA] Viewport drag overlay saved: {args.output}  "
      f"({args.rows + 1}×{args.cols + 1} dots)")
