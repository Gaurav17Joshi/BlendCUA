"""
Annotates a viewport screenshot with labeled face centers inside a specified region.

Faces whose projected center falls inside the bounding box get:
  - A yellow dot at the face center
  - A red label "F1", "F2", ... next to the dot

A blue bounding box marks the filter region.

JSON format (produced by perceive.face_map()):
    {
      "image":           "<path-to-screenshot>",
      "viewport_width":  W,
      "viewport_height": H,
      "region_tl":       [x_norm, y_norm],
      "region_br":       [x_norm, y_norm],
      "faces": {
        "F1": {"face_idx": 5,  "center": {"x": ..., "y": ...}},
        "F2": {"face_idx": 12, "center": {"x": ..., "y": ...}},
        ...
      }
    }
    center x/y are in viewport pixel coords (y-down, PIL convention).

Usage:
    python overlays/face_map_overlay.py --json overlay_json/action_02_facemap.json
    python overlays/face_map_overlay.py --json ... --tl 0.2 0.1 --br 0.8 0.9
    python overlays/face_map_overlay.py --json ... --tl 200 100 --br 800 900 --pixel
"""

import argparse
import json
import os
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--json",   required=True,  help="Path to facemap JSON")
parser.add_argument("--image",  default=None,   help="Override source image path")
parser.add_argument("--tl",     nargs=2, type=float, default=None, metavar=("X", "Y"),
                    help="Top-left of filter region (normalised unless --pixel)")
parser.add_argument("--br",     nargs=2, type=float, default=None, metavar=("X", "Y"),
                    help="Bottom-right of filter region")
parser.add_argument("--pixel",  action="store_true",
                    help="Interpret --tl/--br as image pixel coords instead of 0-1")
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
sx   = W / vp_w          # viewport px → image px
sy   = H / vp_h

lw = max(2, min(W, H) // 300)
r  = max(4, min(W, H) // 130)
fs = max(12, min(W, H) // 55)


def _load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc",
                 "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

font = _load_font(fs)


def resolve_region():
    tl = args.tl or data.get("region_tl")
    br = args.br or data.get("region_br")
    if tl is None or br is None:
        return None
    if args.pixel:
        return int(tl[0]), int(tl[1]), int(br[0]), int(br[1])
    return (int(round(tl[0] * W)), int(round(tl[1] * H)),
            int(round(br[0] * W)), int(round(br[1] * H)))


region = resolve_region()
if region:
    x1, y1, x2, y2 = region
else:
    x1, y1, x2, y2 = 0, 0, W, H

# Draw each face center that falls inside the region.
n = 0
for label, face in data["faces"].items():
    cx = face["center"]["x"] * sx
    cy = face["center"]["y"] * sy

    if not (x1 <= cx <= x2 and y1 <= cy <= y2):
        continue

    # Yellow dot with white outline for contrast.
    draw.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2],
                 fill=(255, 255, 255))
    draw.ellipse([cx - r,     cy - r,     cx + r,     cy + r    ],
                 fill=(255, 220, 0))

    # Red label.
    draw.text((cx + r + 4, cy - fs // 2), label, fill=(220, 30, 30), font=font)
    n += 1

# Blue bounding box.
if region:
    draw.rectangle([x1, y1, x2, y2], outline=(30, 120, 255), width=lw)

base, ext = os.path.splitext(img_path)
out = args.output or f"{base}_fmap{ext or '.png'}"
img.save(out)
print(f"[BlendCUA] Face map overlay saved: {out}  ({n} face{'s' if n != 1 else ''} labeled)")
