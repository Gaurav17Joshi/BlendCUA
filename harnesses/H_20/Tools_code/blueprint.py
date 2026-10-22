"""blueprint — turn a modelling plate (a straight front/side/top picture of the subject on a
plain background) into a BLUEPRINT drawing like plans/04_skull/side_blueprint.png: a pale
fill of the subject's silhouette, its outline as one dark contour, and light construction
strokes for the edges inside it (a leg against the belly, an ear, the mouth line, a band of
colour), plus any landmark strokes you add from measurement. The drawing is what goes into
Blender as the guide; the plate photo stays beside it for checking.

Shell side (PIL + numpy):
    import blueprint as BP
    rep = BP.make_blueprint("reference/side_plate.png", "reference/side_blueprint.png")
    # rep: bbox, contour polygon (px), stroke count, background colour used
    # with measured landmarks (circles / polylines in plate px):
    BP.make_blueprint(plate, out, landmarks={"circles": [(cx, cy, r)], "lines": [[(x, y), ...]]})

Everything the drawing contains is written to <out>.json (contour polygon, bbox, strokes'
pixel counts), so the blueprint is also a measurement, not only a picture.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

PALE = (223, 233, 244)      # skull blueprint fill
PAGE = (247, 250, 253)      # skull blueprint page
CONTOUR = (52, 84, 128)     # dark outline
STROKE = (96, 140, 190)     # light construction lines


def load(path):
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    return np.asarray(im).astype(int)


def subject_mask(img, tol=28):
    """Pixels that differ from the plate's background (the median of the border pixels) by
    more than `tol` in any channel, or that are opaque where the border is transparent."""
    a = img[..., 3]
    if a.min() < 128 and np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])) < 128:
        return a > 128, (0, 0, 0)
    border = np.concatenate([img[0, :, :3], img[-1, :, :3], img[:, 0, :3], img[:, -1, :3]])
    bg = np.median(border, axis=0)
    diff = np.abs(img[..., :3] - bg).max(axis=2)
    return diff > tol, tuple(int(v) for v in bg)


def _components(mask, eight=False):
    H, W = mask.shape
    lab = np.zeros(mask.shape, dtype=np.int32)
    n = 0
    ys, xs = np.nonzero(mask)
    nbrs = ((1, 0), (-1, 0), (0, 1), (0, -1)) + (((1, 1), (1, -1), (-1, 1), (-1, -1)) if eight else ())
    for y0, x0 in zip(ys, xs):
        if lab[y0, x0]:
            continue
        n += 1
        stack = [(y0, x0)]; lab[y0, x0] = n
        while stack:
            y, x = stack.pop()
            for dy, dx in nbrs:
                yy, xx = y + dy, x + dx
                if 0 <= yy < H and 0 <= xx < W and mask[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n; stack.append((yy, xx))
    return lab, n


def largest(mask):
    lab, n = _components(mask)
    if n == 0:
        return mask
    sizes = [(lab == i).sum() for i in range(1, n + 1)]
    return lab == (int(np.argmax(sizes)) + 1)


def fill_holes(mask):
    """Holes (background fully enclosed by the subject) become subject: the outline is the
    outer silhouette only. Any enclosed gap worth drawing shows up as strokes anyway."""
    H, W = mask.shape
    outside = np.zeros_like(mask)
    stack = [(y, x) for y in (0, H - 1) for x in range(W)] + [(y, x) for x in (0, W - 1) for y in range(H)]
    for y, x in stack:
        if not mask[y, x]:
            outside[y, x] = True
    seeds = list(zip(*np.nonzero(outside)))
    while seeds:
        y, x = seeds.pop()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < H and 0 <= xx < W and not mask[yy, xx] and not outside[yy, xx]:
                outside[yy, xx] = True; seeds.append((yy, xx))
    return ~outside


def _shift(m, dy, dx):
    out = np.zeros_like(m)
    H, W = m.shape
    ys, ye = max(0, dy), min(H, H + dy)
    xs, xe = max(0, dx), min(W, W + dx)
    out[ys:ye, xs:xe] = m[ys - dy:ye - dy, xs - dx:xe - dx]
    return out


def erode(m, r):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                out &= _shift(m, dy, dx)
    return out


def dilate(m, r):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                out |= _shift(m, dy, dx)
    return out


def boundary(mask):
    """Closed outline of a region as [(x, y)] (Moore trace on the largest piece)."""
    import outline_trace as OT
    return OT.boundary_polygon(largest(mask))


MARKINGS = {
    # colour rules for a marking whose boundary is a construction line (r, g, b int arrays)
    "tan":   lambda r, g, b: (r > g + 18) & (r > b + 40) & (r > 60),
    "dark":  lambda r, g, b: (r + g + b) < 3 * 70,
    "light": lambda r, g, b: (r + g + b) > 3 * 170,
    "red":   lambda r, g, b: (r > g + 50) & (r > b + 50),
    "gold":  lambda r, g, b: (r > 150) & (g > 100) & (b < 90) & (r > b + 80),
}


def marking_strokes(img, mask, rule, *, margin=4, min_px=150):
    """The boundary of a colour marking inside the subject (a dog's tan legs against the
    black coat, a gold band on a stone head): the edge of the marking's mask, kept where it is
    inside the outline, pieces of at least min_px. A construction line that says where one
    material ends and the next begins."""
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    m = rule(r, g, b) & erode(mask, margin)
    m = dilate(erode(m, 2), 2)                       # drop specks
    edge = m & ~(_shift(m, 1, 0) & _shift(m, -1, 0) & _shift(m, 0, 1) & _shift(m, 0, -1))
    lab, n = _components(edge, eight=True)
    out = np.zeros_like(edge); kept = 0
    for i in range(1, n + 1):
        c = lab == i
        if c.sum() >= min_px:
            out |= c; kept += 1
    return out, kept


def inner_strokes(img, mask, *, blur=3, thresh=None, min_len=60, margin=6, percentile=95):
    """Edges inside the subject: the gradient magnitude of the smoothed luminance, kept where
    it is strong, well inside the outline, and in a connected piece of at least `min_len`
    pixels. Returns a boolean stroke mask and the number of pieces kept."""
    lum = (0.299 * img[..., 0] + 0.587 * img[..., 1] + 0.114 * img[..., 2]).astype(float)
    # box blur
    k = blur
    if k > 0:
        pad = np.pad(lum, k, mode="edge")
        acc = np.zeros_like(lum)
        for dy in range(-k, k + 1):
            for dx in range(-k, k + 1):
                acc += pad[k + dy:k + dy + lum.shape[0], k + dx:k + dx + lum.shape[1]]
        lum = acc / ((2 * k + 1) ** 2)
    gy = np.zeros_like(lum); gx = np.zeros_like(lum)
    gy[1:-1] = lum[2:] - lum[:-2]
    gx[:, 1:-1] = lum[:, 2:] - lum[:, :-2]
    g = np.hypot(gx, gy)
    inside = erode(mask, margin)
    g[~inside] = 0
    if thresh is None:
        vals = g[inside]
        thresh = float(np.percentile(vals, percentile)) if vals.size else 1e9
    edges = g > thresh
    # keep the ridge of each edge (local maximum across the gradient direction) but judge
    # the piece length on the unthinned, 8-connected edge so a stroke is not cut into crumbs
    ax = np.abs(gx) >= np.abs(gy)
    ridge = edges & np.where(ax, (g >= _shift(g, 0, 1)) & (g >= _shift(g, 0, -1)),
                             (g >= _shift(g, 1, 0)) & (g >= _shift(g, -1, 0)))
    lab, n = _components(edges, eight=True)
    out = np.zeros_like(edges)
    kept = 0
    for i in range(1, n + 1):
        m = lab == i
        ys_, xs_ = np.nonzero(m)
        extent = max(ys_.max() - ys_.min(), xs_.max() - xs_.min()) + 1
        if extent >= min_len:
            out |= (m & ridge); kept += 1
    return out, kept, thresh


def make_blueprint(plate_png, out_png, *, landmarks=None, tol=28, min_len=60, smooth_step=3,
                   contour_width=3, stroke_width=2, page=PAGE, pale=PALE, strokes=True,
                   markings=()):
    """Draw the blueprint of one plate. Returns a report dict (also written to <out>.json).
    markings: names from MARKINGS (or callables) whose colour boundary is drawn as strokes."""
    from PIL import Image, ImageDraw
    import outline_trace as OT
    img = load(plate_png)
    H, W = img.shape[:2]
    mask, bg = subject_mask(img, tol)
    mask = fill_holes(largest(mask))
    poly = OT.boundary_polygon(mask)
    dense = OT.resample_smooth(poly, step=smooth_step, win=5)
    ys, xs = np.nonzero(mask)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]

    canvas = Image.new("RGB", (W, H), page)
    d = ImageDraw.Draw(canvas)
    d.polygon(dense, fill=pale)
    n_strokes = 0; thresh = None
    sm = np.zeros(mask.shape, dtype=bool)
    if strokes:
        sm, n_strokes, thresh = inner_strokes(img, mask, min_len=min_len)
    n_mark = 0
    for mk in markings:
        rule = MARKINGS[mk] if isinstance(mk, str) else mk
        em, k = marking_strokes(img, mask, rule)
        sm |= em; n_mark += k
    if strokes or markings:
        sy, sx = np.nonzero(sm)
        px = canvas.load()
        for y, x in zip(sy, sx):
            for ddy in range(stroke_width):
                for ddx in range(stroke_width):
                    yy, xx = y + ddy, x + ddx
                    if 0 <= yy < H and 0 <= xx < W:
                        px[xx, yy] = STROKE
    lm = landmarks or {}
    for (cx, cy, r) in lm.get("circles", []):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=STROKE, width=stroke_width)
    for line in lm.get("lines", []):
        d.line([tuple(p) for p in line], fill=STROKE, width=stroke_width)
    d.line(dense + dense[:1], fill=CONTOUR, width=contour_width)
    canvas.save(out_png)
    rep = {"plate": str(plate_png), "out": str(out_png), "size": [W, H], "background_rgb": bg,
           "subject_px": int(mask.sum()), "bbox": bbox, "contour_points": len(dense),
           "contour_px": [[round(x, 1), round(y, 1)] for x, y in dense],
           "strokes": n_strokes, "stroke_threshold": thresh, "marking_strokes": n_mark,
           "markings": [mk if isinstance(mk, str) else "callable" for mk in markings], "landmarks": lm}
    Path(str(out_png)).with_suffix(".json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    ap = argparse.ArgumentParser(description="plate -> blueprint drawing (+ .json with the contour)")
    ap.add_argument("plate"); ap.add_argument("out")
    ap.add_argument("--min-len", type=int, default=60); ap.add_argument("--tol", type=int, default=28)
    ap.add_argument("--no-strokes", action="store_true")
    ap.add_argument("--marking", nargs="*", default=[], choices=sorted(MARKINGS),
                    help="colour markings whose boundary is drawn (tan, dark, light, red, gold)")
    a = ap.parse_args()
    r = make_blueprint(a.plate, a.out, min_len=a.min_len, tol=a.tol, strokes=not a.no_strokes, markings=a.marking)
    print({k: r[k] for k in ("size", "background_rgb", "subject_px", "bbox", "contour_points", "strokes", "marking_strokes")})
