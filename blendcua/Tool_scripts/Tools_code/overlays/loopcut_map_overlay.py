"""
Draws loop-cut polylines on a viewport screenshot.

Handles two JSON formats:
  • {"cuts": [...]}        — from export_loopcut_map (all cuts on one image)
  • {"directions": [...]}  — from export_face_loopcut_map (one image per direction)

Usage:
    python Tool_scripts/loopcut_map_overlay.py --json screenshots/loopcut_dir_map.json
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

vp_w = data["viewport_width"]
vp_h = data["viewport_height"]

def to_px(sp, W, H):
    return int(round(sp["x"] * W / vp_w)), int(round(sp["y"] * H / vp_h))

def load_font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

CUT_COLOR = (255, 220, 0)   # yellow — same as Blender's loop cut preview

def draw_one(cut_item, out_path):
    img  = Image.open(data["image"]).convert("RGB")
    W, H = img.size
    # Fade background by 50%
    img  = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), alpha=0.5)
    draw = ImageDraw.Draw(img)

    fs   = max(14, min(W, H) // 55)
    fs_l = int(fs * 1.3)
    lw   = max(2,  min(W, H) // 250)
    font   = load_font(fs)
    font_l = load_font(fs_l)

    pts = [to_px(p, W, H) for p in cut_item["polyline"]]
    if len(pts) > 1:
        # white outline for contrast then yellow line
        for k in range(len(pts) - 1):
            draw.line([pts[k], pts[k+1]], fill=(255,255,255), width=lw+3)
            draw.line([pts[k], pts[k+1]], fill=CUT_COLOR,     width=lw)
        draw.line([pts[-1], pts[0]], fill=(255,255,255), width=lw+3)
        draw.line([pts[-1], pts[0]], fill=CUT_COLOR,     width=lw)

    # Label at centroid
    cx = int(sum(p[0] for p in pts) / len(pts))
    cy = int(sum(p[1] for p in pts) / len(pts))
    label = cut_item.get("id", "?")
    draw.text((cx + 6, cy - fs_l // 2), label, fill=CUT_COLOR, font=font_l)

    # Legend
    draw.text((10, 10), f"{label} — {cut_item['ring_len'] if 'ring_len' in cut_item else len(pts)} edges",
              fill=(200, 200, 200), font=font)

    img.save(out_path)
    print(f"[BlendCUA] Saved: {out_path}")

base, ext = os.path.splitext(data["image"])
ext = ext or ".png"

# ── Two separate images for direction maps ─────────────────────────────────────
if "directions" in data:
    for d in data["directions"]:
        out = f"{base}_{d['id']}_lcmap{ext}"
        draw_one(d, out)

# ── Single image with all cuts overlaid ───────────────────────────────────────
elif "cuts" in data:
    img  = Image.open(data["image"]).convert("RGB")
    W, H = img.size
    # Fade background by 50%
    img  = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), alpha=0.5)
    draw = ImageDraw.Draw(img)

    fs   = max(14, min(W, H) // 55)
    fs_l = int(fs * 1.3)
    lw   = max(2,  min(W, H) // 250)
    font   = load_font(fs)
    font_l = load_font(fs_l)

    COLORS = [(255,220,0), (255,120,0), (0,200,255), (180,0,255)]
    for i, cut in enumerate(data["cuts"]):
        color = COLORS[i % len(COLORS)]
        pts   = [to_px(p, W, H) for p in cut["polyline"]]
        if len(pts) > 1:
            for k in range(len(pts) - 1):
                draw.line([pts[k], pts[k+1]], fill=(255,255,255), width=lw+3)
                draw.line([pts[k], pts[k+1]], fill=color,          width=lw)
            draw.line([pts[-1], pts[0]], fill=(255,255,255), width=lw+3)
            draw.line([pts[-1], pts[0]], fill=color,          width=lw)
        cx = int(sum(p[0] for p in pts) / len(pts))
        cy = int(sum(p[1] for p in pts) / len(pts))
        draw.text((cx+6, cy-fs_l//2), cut["id"], fill=color, font=font_l)
        draw.text((10, 10 + i*(fs+4)), cut["id"], fill=color, font=font)

    out = args.output or f"{base}_lcmap{ext}"
    img.save(out)
    print(f"[BlendCUA] Saved: {out}")
