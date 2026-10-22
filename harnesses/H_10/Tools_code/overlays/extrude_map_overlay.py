"""
Generates TWO annotated images from extrude_map.json:
  1. viewport_extrude_world_exmap.png  — world ruler
  2. viewport_extrude_screen_exmap.png — screen ruler

Both show:
  • Blue axis line through pivot (both directions, like Blender's constraint indicator)
  • Red dots at each tick (both + and - directions)
  • Red labels: ordinal + world value

Usage:
    python Tool_scripts/extrude_map_overlay.py --json screenshots/extrude_map.json
"""

import argparse
import json
import math
import os
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--json",   required=True)
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

DOT_COLOR   = (220, 40,  40)   # red
LABEL_COLOR = (220, 40,  40)   # red
AXIS_COLOR  = (60,  130, 255)  # blue (like Blender's constraint line)
PIVOT_COLOR = (255, 255, 255)

def render_ruler(ruler_key, suffix):
    img  = Image.open(data["image"]).convert("RGB")
    W, H = img.size
    # Fade background by 50% so red/blue overlays read clearly
    img  = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), alpha=0.5)
    draw = ImageDraw.Draw(img)

    fs       = max(13, min(W, H) // 60)
    fs_label = int(fs * 1.17)                    # ordinal font (10% smaller than prior 1.3x)
    fs_value = max(9, int(fs * 0.675))           # value font, smaller still
    r        = max(4,  int(min(W, H) / 130 * 0.8))
    lw       = max(1,  min(W, H) // 400)
    font        = load_font(fs)
    font_label  = load_font(fs_label)
    font_value  = load_font(fs_value)

    def text_wh(text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    px, py = to_px(data["pivot_screen"], W, H)
    ticks  = data[ruler_key]["ticks"]

    # ── Blue axis line (through pivot, both directions, full image span) ──────
    # Determine screen direction from any positive tick; fallback to first tick.
    ref_tick = next((t for t in ticks if t["t"] > 0), ticks[0] if ticks else None)
    if ref_tick is not None:
        tx, ty  = to_px(ref_tick["screen"], W, H)
        ddx, ddy = tx - px, ty - py
    else:
        ddx, ddy = 1, 0
    dlen   = math.sqrt(ddx**2 + ddy**2) or 1.0
    ux, uy = ddx / dlen, ddy / dlen
    extend = max(W, H) + 100
    x0 = int(px - ux * extend)
    y0 = int(py - uy * extend)
    x1 = int(px + ux * extend)
    y1 = int(py + uy * extend)
    draw.line([(x0, y0), (x1, y1)], fill=AXIS_COLOR, width=max(2, lw))

    # Perpendicular unit vectors: up_perp points "up in image" (smaller y).
    perp_a = (-uy, ux)
    perp_b = ( uy, -ux)
    up_perp, down_perp = (perp_a, perp_b) if perp_a[1] < perp_b[1] else (perp_b, perp_a)

    tick_half = max(int(r * 1.4), lw + 2)
    label_gap = int(r * 3)

    # ── Pivot: white dot, "pivot" label BELOW the line ──
    draw.ellipse([px - r, py - r, px + r, py + r],
                 fill=PIVOT_COLOR, outline=(80, 80, 80))
    pw, ph = text_wh("pivot", font_label)
    pivx = int(px + down_perp[0] * label_gap - pw / 2)
    pivy = int(py + down_perp[1] * label_gap)
    draw.text((pivx, pivy), "pivot", fill=(200, 200, 200), font=font_label)

    # ── Perpendicular tick marks (every tick) ──
    for tick in ticks:
        tx, ty = to_px(tick["screen"], W, H)
        x1t = int(tx + up_perp[0]   * tick_half)
        y1t = int(ty + up_perp[1]   * tick_half)
        x2t = int(tx + down_perp[0] * tick_half)
        y2t = int(ty + down_perp[1] * tick_half)
        draw.line([(x1t, y1t), (x2t, y2t)], fill=DOT_COLOR, width=max(2, lw))

    # ── Labels every other tick (declutter): ordinal ABOVE, value BELOW ──
    for i, tick in enumerate(ticks):
        if i % 2 != 0:
            continue
        tx, ty = to_px(tick["screen"], W, H)

        ord_str = tick["ordinal"]
        ow, oh  = text_wh(ord_str, font_label)
        ox = int(tx + up_perp[0] * label_gap - ow / 2)
        oy = int(ty + up_perp[1] * label_gap - oh)
        draw.text((ox, oy), ord_str, fill=LABEL_COLOR, font=font_label)

        val_str = tick.get("value_str") or f"{tick['t']:.2f}m"
        vw, vh  = text_wh(val_str, font_value)
        vx = int(tx + down_perp[0] * label_gap - vw / 2)
        vy = int(ty + down_perp[1] * label_gap)
        draw.text((vx, vy), val_str, fill=LABEL_COLOR, font=font_value)

    # ── Legend ────────────────────────────────────────────────────────────────
    if ruler_key == "world_ruler":
        info = f"World ruler  step={data['world_ruler']['step_m']}m"
    else:
        ppu = data["screen_ruler"].get("px_per_unit", 0)
        info = f"Screen ruler  step={data['screen_ruler']['px_step']}px"
        if ppu:
            info += f"  (~{data['screen_ruler']['px_step']/ppu:.3f}m each)"
    quality = data.get("viewpoint_quality", 0)
    draw.text((10, 10),          info,                              fill=(200, 200, 200), font=font)
    draw.text((10, 10 + fs + 5), f"Viewpoint Q={quality:.2f}",     fill=(200, 200, 200), font=font)

    base, ext = os.path.splitext(data["image"])
    out = f"{base}_{suffix}{ext or '.png'}"
    img.save(out)
    print(f"[BlendCUA] Saved: {out}")

if "world_ruler"  in data: render_ruler("world_ruler",  "world_exmap")
if "screen_ruler" in data: render_ruler("screen_ruler", "screen_exmap")
