"""
Annotates a viewport screenshot with labeled, color-coded edge lines.

Edges whose midpoint falls inside the specified region are highlighted:
  - Boundary edges (1 linked face, "boundary": true in JSON) → orange
    These are the open-loop edges we need to bridge / fill.
  - Interior edges (2+ linked faces) → yellow

All other edges are drawn as thin gray context lines so the shape
stays readable without cluttering the label area.

A blue bounding box marks the filter region.

JSON format (compatible with export_edges.py):
    {
      "image":           "<path-to-screenshot>",
      "viewport_width":  W,          # viewport pixel dimensions
      "viewport_height": H,
      "region_tl":       [x, y],     # top-left  in normalised 0-1 image coords
      "region_br":       [x, y],     # bottom-right  (can be overridden by CLI)
      "edges": {
        "<index>": {
          "v0":       {"x": ..., "y": ...},   # viewport pixel coords
          "v1":       {"x": ..., "y": ...},
          "mid":      {"x": ..., "y": ...},
          "boundary": true | false            # absent → treated as false
        },
        ...
      }
    }

Usage:
    # Region from JSON:
    python edge_map_overlay.py --json overlay_json/action_01_edges.json

    # Override region (normalised 0-1):
    python edge_map_overlay.py --json ... --tl 0.55 0.2 --br 1.0 0.85

    # Override region (pixels):
    python edge_map_overlay.py --json ... --tl 900 150 --br 1800 700 --pixel
"""

import argparse
import json
import os
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--json",   required=True,   help="Path to edges JSON")
parser.add_argument("--image",  default=None,    help="Override source image path")
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

lw  = max(2, min(W, H) // 300)
elw = max(2, min(W, H) // 200)
fs  = max(11, min(W, H) // 60)

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


def vp_to_img(p):
    """Scale a viewport-pixel point to image-pixel coords."""
    return p["x"] * sx, p["y"] * sy


def resolve_region():
    """Return (x1, y1, x2, y2) in image pixels, or None if no region defined."""
    tl = args.tl or data.get("region_tl")
    br = args.br or data.get("region_br")
    if tl is None or br is None:
        return None
    if args.pixel:
        return int(tl[0]), int(tl[1]), int(br[0]), int(br[1])
    # normalised → image pixels
    return (int(round(tl[0] * W)), int(round(tl[1] * H)),
            int(round(br[0] * W)), int(round(br[1] * H)))


region = resolve_region()
if region:
    x1, y1, x2, y2 = region
else:
    x1, y1, x2, y2 = 0, 0, W, H   # full image — label everything

# ── Pass 1: thin gray context lines for edges OUTSIDE the region ──────────────
for e in data["edges"].values():
    mx, my = vp_to_img(e["mid"])
    if region and x1 <= mx <= x2 and y1 <= my <= y2:
        continue
    ax, ay = vp_to_img(e["v0"])
    bx, by = vp_to_img(e["v1"])
    draw.line([(ax, ay), (bx, by)], fill=(90, 90, 90), width=1)

# ── Pass 2: highlighted + labeled edges INSIDE the region ─────────────────────
#   boundary (open loop) → orange  (needs bridging)
#   interior             → yellow  (already has two faces)
BOUNDARY_COLOR = (255, 140,   0)
INTERIOR_COLOR = (255, 215,   0)
LABEL_COLOR    = (220,  30,  30)

label_n = 1
for e in data["edges"].values():
    mx, my = vp_to_img(e["mid"])
    if region and not (x1 <= mx <= x2 and y1 <= my <= y2):
        continue
    ax, ay = vp_to_img(e["v0"])
    bx, by = vp_to_img(e["v1"])
    color  = BOUNDARY_COLOR if e.get("boundary", False) else INTERIOR_COLOR
    # white outline for contrast, then coloured line on top
    draw.line([(ax, ay), (bx, by)], fill=(255, 255, 255), width=elw + 3)
    draw.line([(ax, ay), (bx, by)], fill=color,           width=elw)
    draw.text((mx + 4, my - fs // 2), f"E{label_n}", fill=LABEL_COLOR, font=font)
    label_n += 1

# ── Blue bounding box for the region ──────────────────────────────────────────
if region:
    draw.rectangle([x1, y1, x2, y2], outline=(30, 120, 255), width=lw)

base, ext = os.path.splitext(img_path)
out = args.output or f"{base}_emap{ext or '.png'}"
img.save(out)
n = label_n - 1
print(f"[BlendCUA] Edge map overlay saved: {out}  ({n} edge{'s' if n != 1 else ''} in region)")
