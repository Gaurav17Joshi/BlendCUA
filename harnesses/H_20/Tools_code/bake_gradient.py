"""
Rasterizes a list of UV polygons, each filled with its own flat grey value,
into a texture image. The caller (a Blender action) computes each polygon's
grey value and UV coordinates however it wants — this script's only job is
drawing them, so it's reusable for any "bake some per-face/per-patch flat
colour into UV space" need, not just one specific gradient direction.

Used by:
  - 03_bake_gradient.py (world-Z-driven gradient — one flat colour per
    mesh face, banded but correct regardless of UV layout).
  - paint.apply_screen_gradient() (screen-projected gradient, matching
    Blender's own Texture Paint "Fill" tool with Gradient content — each
    face is pre-subdivided into a fine grid of small polygons so the
    result reads as smooth rather than banded).

Usage:
    python bake_gradient.py --json <path> --output <path>

JSON shape:
    {
      "tex_size": 2048,
      "background": 0.3,              # optional, default 0.5
      "faces": [ {"uv": [[u,v], ...], "grey": 0.0-1.0}, ... ]
    }
"""

import argparse
import json
from PIL import Image, ImageDraw

parser = argparse.ArgumentParser()
parser.add_argument("--json",   required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

with open(args.json) as f:
    data = json.load(f)

W = H = data["tex_size"]
bg = int(round(data.get("background", 0.5) * 255))
img = Image.new("RGB", (W, H), (bg, bg, bg))
draw = ImageDraw.Draw(img)

n_drawn = 0
for face in data["faces"]:
    val = int(round(max(0.0, min(1.0, face["grey"])) * 255))
    # UV v=0 is the BOTTOM of the image in Blender's convention; PIL's
    # (0,0) is top-left, so flip v.
    pts = [(u * W, (1.0 - v) * H) for u, v in face["uv"]]
    if len(pts) >= 3:
        draw.polygon(pts, fill=(val, val, val))
        n_drawn += 1

img.save(args.output)
print(f"[BlendCUA] Gradient texture baked: {args.output} ({n_drawn} polygons drawn)")
