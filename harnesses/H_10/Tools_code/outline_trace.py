"""outline_trace — read a part's shape out of ONE photograph and build from it.

The reference is the geometry, even when there is no blueprint: a lacquered pedestal leg, a
chair back, a handle, a leaf — anything with a readable silhouette in the photo. This module
is the pipeline used by hand in mem/06_tablecloth_drape_run_003 (2026-09-12), where run_001's tube
feet were replaced by legs traced from the photograph in ~200 lines and the side legs landed
within 8-11 px of the photo's outline on 1024 px.

Shell side (PIL + numpy, no Blender):
    img = load_rgb(photo)
    m = largest(colour_mask(img))                 # the wood, the biggest connected piece
    print_row_table(m, 600, 950, 10)              # LOOK at it: runs per row = the anatomy
    x0 = axis_x(m, rows)                          # symmetric column -> axis
    pitch = pitch_from_floor_points(y_near, y_far, L_px)   # 3 feet on one floor
    part = cut_region(m, x_max=x0 - neck_hw, y_min=row_below_ring)
    poly = resample_smooth(boundary_polygon(part))  # closed outline, ~5 px spacing
    prof = image_to_plane(poly, x_axis=x0, y_floor=y_toe, L_px=L_px, pitch_deg=pitch)
    draw_polygon(photo, poly, out_png)             # the trace drawn back on the photo
Blender side:
    ob = extrude_profile("Foot_Front", [(r*L, z*L) for r, z in prof], thickness=t)
    place_radial(ob, -90)                          # toward the camera at -Y
Check (shell side, any render through the scene camera):
    a = align_by_landmarks(render_mask, (x_axis_r, y_floor_r, span_r), (x0, y_toe, span), shape)
    print(mask_residuals(ref_mask, a, rows))       # per-row span / edge residual in photo px

Every number in the build must be traceable to a pixel read printed by one of these calls.
"""
from __future__ import annotations

import math

import numpy as np

# ----------------------------------------------------------------------------- image side


def load_rgb(path):
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB")).astype(int)


def colour_mask(img, *, max_sum=360, red_over_blue=6, rule=None):
    """Boolean mask of one material. Default: dark reddish pixels (wood, leather). Pass
    `rule(r, g, b) -> bool array` for anything else (a white cloth: r+g+b > 560 & |r-b| < 12)."""
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    if rule is not None:
        return rule(r, g, b)
    return (r + g + b < max_sum) & (r > b + red_over_blue)


def components(mask):
    """4-connected labels (BFS, no scipy). Returns (labels, count)."""
    H, W = mask.shape
    lab = np.zeros(mask.shape, dtype=np.int32)
    n = 0
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys, xs):
        if lab[y0, x0]:
            continue
        n += 1
        stack = [(y0, x0)]
        lab[y0, x0] = n
        while stack:
            y, x = stack.pop()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < H and 0 <= xx < W and mask[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n
                    stack.append((yy, xx))
    return lab, n


def largest(mask):
    lab, n = components(mask)
    if n == 0:
        return mask.copy()
    sizes = [(lab == i).sum() for i in range(1, n + 1)]
    return lab == (int(np.argmax(sizes)) + 1)


def runs(row):
    """[(x0, x1)] foreground runs of a boolean row, x1 inclusive."""
    out, start = [], None
    for x, v in enumerate(row):
        if v and start is None:
            start = x
        elif not v and start is not None:
            out.append((start, x - 1)); start = None
    if start is not None:
        out.append((start, len(row) - 1))
    return out


def row_table(mask, y0, y1, step=10):
    return [(y, runs(mask[y])) for y in range(y0, y1 + 1, step)]


def print_row_table(mask, y0, y1, step=10):
    """The single most useful thing to look at: where one run splits into three is a neck
    with two knees beside it; where runs merge is a collar; a run that stays narrow and
    central is the near leg seen end-on."""
    for y, rr in row_table(mask, y0, y1, step):
        print(f"  y={y:4d}: {rr}")


def central_run(mask, y, x):
    for x0, x1 in runs(mask[y]):
        if x0 <= x <= x1:
            return x0, x1
    return None


def axis_x(mask, rows, x_guess=None):
    """Median centre of the run containing x_guess (default: the mask's median column) over
    `rows` — use rows of a symmetric turned part (bulb, ring, collar)."""
    ys, xs = np.nonzero(mask)
    xg = int(np.median(xs)) if x_guess is None else x_guess
    cs = []
    for y in rows:
        r = central_run(mask, y, xg)
        if r:
            cs.append((r[0] + r[1]) / 2)
    return float(np.median(cs))


def bbox(mask):
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def cut_region(mask, *, x_min=None, x_max=None, y_min=None, y_max=None):
    """The part's pixels: the mask restricted to a window, largest piece kept. A straight
    cut at a neck/collar becomes the root edge that gets buried in the neighbouring part."""
    m = mask.copy()
    if x_min is not None:
        m[:, :int(round(x_min))] = False
    if x_max is not None:
        m[:, int(round(x_max)):] = False
    if y_min is not None:
        m[:int(round(y_min)), :] = False
    if y_max is not None:
        m[int(round(y_max)):, :] = False
    return largest(m)


def boundary_polygon(mask):
    """Closed outline of a single region as [(x, y)] pixel centres (Moore neighbour trace)."""
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    i = np.lexsort((xs, ys))[0]
    start = (int(ys[i]), int(xs[i]))
    nb = [(0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1)]

    def fg(p):
        return 0 <= p[0] < h and 0 <= p[1] < w and mask[p[0], p[1]]

    cur, back_i = start, 0
    contour = [start]
    for _ in range(400000):
        found = None
        for k in range(1, 9):
            j = (back_i + k) % 8
            p = (cur[0] + nb[j][0], cur[1] + nb[j][1])
            if fg(p):
                found = (p, (j - 1) % 8)
                break
        if found is None:
            break
        nxt, prev_j = found
        by, bx = cur[0] + nb[prev_j][0], cur[1] + nb[prev_j][1]
        back_i = nb.index((by - nxt[0], bx - nxt[1]))
        cur = nxt
        if cur == start and len(contour) > 2:
            break
        contour.append(cur)
    return [(x, y) for y, x in contour]


def rdp(points, eps):
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy)
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm if norm > 1e-9 else math.hypot(px - x1, py - y1)
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        return rdp(points[:idx + 1], eps)[:-1] + rdp(points[idx:], eps)
    return [points[0], points[-1]]


def simplify_closed(poly, eps=1.2):
    """Douglas-Peucker on a closed polygon: exact corners, few vertices. Good for the record
    and for measuring; for a mesh prefer resample_smooth (even spacing shades smoothly)."""
    n = len(poly)
    b = max(range(n), key=lambda k: (poly[k][0] - poly[0][0]) ** 2 + (poly[k][1] - poly[0][1]) ** 2)
    p1 = rdp(poly[:b + 1], eps)
    p2 = rdp(poly[b:] + poly[:1], eps)
    return p1[:-1] + p2[:-1]


def resample_smooth(poly, step=5, win=5):
    """Every step-th boundary pixel, then a circular moving average of `win` points."""
    pts = poly[::step]
    n, h = len(pts), win // 2
    return [(sum(pts[(i + k) % n][0] for k in range(-h, h + 1)) / win,
             sum(pts[(i + k) % n][1] for k in range(-h, h + 1)) / win) for i in range(n)]


def pitch_from_floor_points(y_near, y_far, L_px, d_near=-1.0, d_far=0.5):
    """Camera pitch (deg, looking down) from two floor contacts at the same radius whose
    depths differ: the near one is drawn lower. d_* are depths in units of L along the view
    direction (a leg pointing at the camera: -1; the two others at 120 deg: +0.5).
    Orthographic approximation: y_far - y_near = (d_far - d_near) * L * sin(pitch)."""
    s = (y_near - y_far) / ((d_far - d_near) * L_px)
    return math.degrees(math.asin(max(-0.99, min(0.99, s))))


def image_to_plane(points_xy, *, x_axis, y_floor, L_px, pitch_deg, plane_angle_deg=30.0, side=-1):
    """Map image pixels of a part that lies in a vertical plane through the axis to that
    plane's (r, z), both divided by L_px. plane_angle_deg = angle between the part's radial
    direction and the image plane (a leg at 120 deg from the one facing the camera: 30).
    side = -1 for a part drawn left of the axis, +1 right. y_floor = image row where this
    part touches the floor (z = 0) at r = L."""
    c, s = math.cos(math.radians(plane_angle_deg)), math.sin(math.radians(plane_angle_deg))
    sp, cp = math.sin(math.radians(pitch_deg)), math.cos(math.radians(pitch_deg))
    out = []
    for x, y in points_xy:
        r = side * (x - x_axis) / c                 # radial distance in px
        Y = (y_floor - y) + s * L_px * sp           # image-up from the floor at r = L
        z = (Y - s * r * sp) / cp                   # undo the depth-induced rise
        out.append((r / L_px, z / L_px))
    return out


def draw_polygon(photo_path, poly_xy, out_path, *, lines=(), text=""):
    from PIL import Image, ImageDraw
    ov = Image.open(photo_path).convert("RGB")
    d = ImageDraw.Draw(ov)
    d.line(list(poly_xy) + [poly_xy[0]], fill=(255, 0, 0), width=2)
    for x, y in poly_xy:
        d.ellipse([x - 2, y - 2, x + 2, y + 2], outline=(255, 255, 0))
    for (a, b, col) in lines:
        d.line([a, b], fill=col, width=1)
    if text:
        d.text((10, 10), text, fill=(255, 0, 0))
    ov.save(out_path)


# ----------------------------------------------------------------------------- checking


def align_by_landmarks(src_mask, src_lm, dst_lm, shape):
    """Similarity transform of a mask from (x_axis, y_floor, span) landmarks to another's:
    uniform scale from the spans, translation from axis and floor row. Align on landmarks,
    never on bounding boxes — a cloth hides a different amount of the column in each picture."""
    sx, sy, ss = src_lm
    dx, dy, ds = dst_lm
    s = ds / ss
    H, W = shape
    ys, xs = np.nonzero(src_mask)
    ax = np.clip(np.round(dx + (xs - sx) * s).astype(int), 0, W - 1)
    ay = np.clip(np.round(dy + (ys - sy) * s).astype(int), 0, H - 1)
    out = np.zeros(shape, dtype=bool)
    out[ay, ax] = True
    out |= np.roll(out, 1, 1) & np.roll(out, -1, 1)
    out |= np.roll(out, 1, 0) & np.roll(out, -1, 0)
    return out


def mask_residuals(ref_mask, aligned, rows):
    """Per-row occupied span and left/right edge residuals (px), IoU over the rows."""
    span_res, left, right = [], [], []
    for y in rows:
        a = np.nonzero(ref_mask[y])[0]; b = np.nonzero(aligned[y])[0]
        if len(a) and len(b):
            span_res.append(abs((a.max() - a.min()) - (b.max() - b.min())))
            left.append(abs(a.min() - b.min())); right.append(abs(a.max() - b.max()))
    band = np.zeros_like(ref_mask); band[list(rows)] = True
    inter = (ref_mask & aligned & band).sum(); union = ((ref_mask | aligned) & band).sum()
    return {"span_mean": float(np.mean(span_res)) if span_res else None,
            "span_worst": int(max(span_res)) if span_res else None,
            "left_mean": float(np.mean(left)) if left else None,
            "right_mean": float(np.mean(right)) if right else None,
            "iou": float(inter / union) if union else None}


def tone_stats(img, mask):
    """Median RGB over a material mask plus a gloss proxy (share of pixels far above the
    median luminance, 95th-percentile luminance). Compare photo vs render with the SAME rule."""
    import colorsys
    px = img[mask]
    med = np.median(px, axis=0)
    hsv = colorsys.rgb_to_hsv(*(med / 255.0))
    lum = px.sum(axis=1) / 3.0
    return {"n": int(mask.sum()), "median_rgb": [int(v) for v in med], "value": int(hsv[2] * 255),
            "highlight_frac": round(float((lum > np.median(lum) * 1.8).mean()), 3) if len(lum) else 0.0,
            "p95_lum": int(np.percentile(lum, 95)) if len(lum) else 0}


def base_colour_scale(photo_median, render_median, gamma=2.2):
    """Per-channel factor for a Principled base colour so the rendered median moves onto the
    photo's: (photo/render)^gamma, sRGB medians -> linear base."""
    return [(p / max(1, r)) ** gamma for p, r in zip(photo_median, render_median)]


# ----------------------------------------------------------------------------- Blender side


def extrude_profile(name, pts_xz, thickness, *, bevel=0.018, sharp_deg=60.0, material=None,
                    root_x=None, root_tol=0.02, z_offset=0.0):
    """One part from a closed 2D outline in the XZ plane (x = radial, z = up), extruded in Y
    by `thickness`, edges bevelled, smooth-shaded with sharp marks above `sharp_deg`.
    root_x: vertices within root_tol of the outline's minimum x (the straight cut at the
    neck) are pushed to this x so the root buries itself in the neighbouring part."""
    import bpy
    import bmesh
    xmin = min(x for x, _ in pts_xz)
    pts = [((root_x if (root_x is not None and x <= xmin + root_tol) else x), z + z_offset) for x, z in pts_xz]
    bm = bmesh.new()
    lower = [bm.verts.new((x, -thickness / 2, z)) for x, z in pts]
    face = bm.faces.new(lower)
    res = bmesh.ops.extrude_face_region(bm, geom=[face])
    upper = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=upper, vec=(0, thickness, 0))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=bm.edges[:], offset=bevel, segments=2, affect="EDGES",
                        profile=0.7, clamp_overlap=True)
    for e in bm.edges:
        if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(sharp_deg):
            e.smooth = False
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if material is not None:
        ob.data.materials.append(material)
    return ob


def place_radial(ob, angle_deg):
    """Rotate a part built along +X so its radial direction points at angle_deg about Z
    (-90 = toward a camera on -Y)."""
    ob.rotation_euler = (0.0, 0.0, math.radians(angle_deg))
    return ob
