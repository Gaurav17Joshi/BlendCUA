"""plate_loft — build a low-poly mass from a FRONT and a SIDE blueprint, with the plates as the
geometry rather than as an after-the-fact check.

The recipe (proved on the skull, mem/Skull_tryout, 2026-09-11):

  1. measure_plates(front_png, side_png, t_stations)      shell or Blender, PIL + numpy
         -> {"frame": {...}, "stations": [{t, z, half_width, x_center, y_front, y_back}...]}
     Both plates are thresholded from their background and registered on the subject's top-to-
     bottom span into one world frame: top at z=+H/2, bottom at z=-H/2, subject facing -Y.
     At each station height t (0 = top, 1 = bottom) the front plate gives the half-width and
     lateral centre of the fill, the side plate the front-most and back-most fill pixel.
  2. place_plates(front_png, side_png, frame)                Blender
     Two image empties whose display size and offset come from each plate's own pixel scale,
     so a plate pixel and the mesh share one frame; perceive.reference_outline can then draw
     the built silhouette on the plate.
  3. loft_rings(name, stations, crown=..., base_rows=...)     Blender
     One n-vertex superellipse ring per station spanning exactly the four measured extents,
     an optional pole at the top, an optional slanted base (its 150/180-degree vertices on
     measured base rows), ladder caps. Closed, flat-shaded, manifold. No number typed in.
  4. outline_residual(outline_json, plate_png, frame_side, cut_t)  shell, PIL
     Row-by-row difference between the drawn outline (perceive.reference_outline's JSON) and
     the plate fill, in plate pixels: the number a review asks for.

What a ring cannot do: follow a bulge between two stations (add a station), or fix the
cross-section shape (two views cannot; use `egg` for a front-narrow section, or a top plate).
Features drawn INSIDE the fill (sockets, apertures, tooth rows, a ramus edge) are strokes,
not fill: read them with a dark-pixel mask inside a window, see mem/Skull_tryout/scripts/
measure_features.py, and cut them into the mass with an exact boolean.
"""
from __future__ import annotations

import json
import math
import os
import sys


def _ensure_pil():
    """Blender's own Python has no Pillow; it is installed in the user site-packages, which a
    Blender started before that folder existed does not have on sys.path."""
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        pass
    try:
        import site
        usp = site.getusersitepackages()
        if usp and os.path.isdir(usp) and usp not in sys.path:
            sys.path.append(usp)
    except Exception:  # noqa: BLE001
        pass


# ── measurement (PIL side) ───────────────────────────────────────────────────────────────

def fill_mask(png_path, tolerance=12):
    """Boolean mask of the plate's subject fill: every pixel that differs from the corner
    (background) colour by more than `tolerance` summed over RGB. Returns (mask, size)."""
    _ensure_pil()
    import numpy as np
    from PIL import Image
    im = Image.open(png_path).convert("RGB")
    a = np.asarray(im).astype(int)
    bg = a[2, 2]
    return (np.abs(a - bg).sum(axis=2) > tolerance), im.size


def row_extent(mask, v, longest_run=True):
    """(left, right) fill extent on row v: the longest contiguous run (the subject) by default,
    or the whole row's min/max when the subject and another mass share the row."""
    import numpy as np
    v = int(round(v))
    xs = np.where(mask[v])[0]
    if xs.size == 0:
        return None
    if not longest_run:
        return int(xs.min()), int(xs.max())
    runs, start = [], xs[0]
    for i in range(1, len(xs)):
        if xs[i] != xs[i - 1] + 1:
            runs.append((start, xs[i - 1])); start = xs[i]
    runs.append((start, xs[-1]))
    l, r = max(runs, key=lambda ab: ab[1] - ab[0])
    return int(l), int(r)


def measure_plates(front_png, side_png, t_stations, *, height=2.0, base_rows=(),
                   face_left_in_side=True, longest_run=True):
    """Station table for loft_rings from a FRONT and a SIDE plate.

    t_stations   heights as fractions of the subject's top-to-bottom span (0 top, 1 bottom).
    height       world height of that span (top at +height/2, bottom at -height/2).
    base_rows    extra fractions whose back extent / width are read for a slanted base
                 (see loft_rings base_rows); their rows use the whole-row extent.
    face_left_in_side  the subject faces image-left in the side plate (then it faces -Y).

    Returns {"frame": {front: {...}, side: {...}, crown_point, base_rows}, "stations": [...]}.
    Every station holds the pixel reads under "px" so the table can be audited on the plate.
    """
    fm, (fw, fh) = fill_mask(front_png)
    sm, (sw, sh) = fill_mask(side_png)
    import numpy as np

    def plate(mask, w, h):
        ys, xs = np.where(mask)
        top, bot = int(ys.min()), int(ys.max())
        s = height / (bot - top)
        return {"top_px": top, "bottom_px": bot, "world_per_px": s, "w": w, "h": h,
                "display_size": max(w, h) * s, "location_z": height / 2 - (h / 2 - top) * s}

    F, S = plate(fm, fw, fh), plate(sm, sw, sh)
    l, r = row_extent(fm, F["top_px"] + 0.3 * (F["bottom_px"] - F["top_px"]))
    F["subject_center_u"] = (l + r) / 2
    F["location_x"] = -((l + r) / 2 - fw / 2) * F["world_per_px"]
    sgn = 1.0 if face_left_in_side else -1.0

    def station(t, whole=False):
        vf = F["top_px"] + t * (F["bottom_px"] - F["top_px"])
        vs = S["top_px"] + t * (S["bottom_px"] - S["top_px"])
        fl, fr = row_extent(fm, vf, longest_run=not whole and longest_run)
        sl, sr = row_extent(sm, vs, longest_run=not whole and longest_run)
        if not face_left_in_side:
            sl, sr = sr, sl
        return {"t": t, "z": round(height / 2 - t * height, 4),
                "half_width": round((fr - fl) / 2 * F["world_per_px"], 4),
                "x_center": round(((fl + fr) / 2 - F["subject_center_u"]) * F["world_per_px"], 4),
                "y_front": round(sgn * (sl - sw / 2) * S["world_per_px"], 4),
                "y_back": round(sgn * (sr - sw / 2) * S["world_per_px"], 4),
                "px": {"front_row": int(vf), "front_l": fl, "front_r": fr, "side_row": int(vs), "side_l": sl, "side_r": sr}}

    stations = [station(t) for t in t_stations]
    top_cols = np.where(sm[S["top_px"]])[0]
    frame = {"front": F, "side": S, "height": height,
             "crown_point": {"z": height / 2, "y": round(sgn * (float(top_cols.mean()) - sw / 2) * S["world_per_px"], 4)},
             "base_rows": []}
    last_hw = stations[-1]["half_width"] if stations else 1.0
    for t in base_rows:
        st = station(t, whole=True)
        frame["base_rows"].append({"t": t, "z": st["z"], "y_back": st["y_back"],
                                   "width_scale": round(st["half_width"] / last_hw, 4), "px": st["px"]})
    return {"frame": frame, "stations": stations}


# ── Blender side ─────────────────────────────────────────────────────────────────────────

def _sp(v, n):
    return math.copysign(abs(v) ** (2.0 / n), v)


def ring_points(st, n=12, exponent=2.4, egg=0.0):
    """The (x, y) points of one station's ring: a superellipse between the four measured
    extents; `egg` (0..1) narrows the front half so a face reads narrower than the temples."""
    w, yf, yb, xc = st["half_width"], st["y_front"], st["y_back"], st.get("x_center", 0.0)
    yc, d = (yf + yb) / 2.0, (yb - yf) / 2.0
    pts = []
    for k in range(n):
        th = 2.0 * math.pi * k / n            # 0 = front point, pi = back point
        x = w * _sp(math.sin(th), exponent)
        y = yc - d * _sp(math.cos(th), exponent)
        if y < yc and egg and d:
            x *= 1.0 - egg * (yc - y) / d
        pts.append((xc + x, y))
    return pts


def _ladder(cap, flip):
    n = len(cap)
    fs = [(cap[0], cap[1], cap[n - 1])] + [(cap[k], cap[k + 1], cap[n - k - 1], cap[n - k]) for k in range(1, n // 2 - 1)] + [(cap[n // 2 - 1], cap[n // 2], cap[n // 2 + 1])]
    return [tuple(reversed(f)) for f in fs] if flip else fs


def loft_rings(name, stations, *, crown=None, base_rows=None, n=12, exponent=2.4,
               egg=0.0, egg_from_t=None, material=None, replace=True):
    """Build one closed flat-shaded mesh through measured station rings.

    stations   from measure_plates (top to bottom).
    crown      {"z", "y"}: a pole vertex above the first ring (a dome); None = flat ladder cap.
    base_rows  from measure_plates(...)["frame"]["base_rows"]: one or two rows below the last
               station. The last ring is then slanted: vertices up to 120 degrees from the
               front stay level, the 150-degree pair sits on base_rows[0], the 180-degree vertex
               on base_rows[-1] (so a skull base drops behind the tooth line). None = level.
    egg        front-narrowing factor; applied to rings with t >= egg_from_t (all if None).
    Returns the object. Custom props keep the station table for audits.
    """
    import bpy, bmesh
    verts, rings = [], []
    if crown:
        verts.append((0.0, crown["y"], crown["z"]))
    for st in stations:
        e = egg if (egg_from_t is None or st["t"] >= egg_from_t) else 0.0
        ring = []
        for (x, y) in ring_points(st, n, exponent, e):
            ring.append(len(verts)); verts.append((x, y, st["z"]))
        rings.append(ring)
    if base_rows:
        last = stations[-1]
        e = egg if (egg_from_t is None or last["t"] >= egg_from_t) else 0.0
        ring = []
        for k in range(n):
            th = 2.0 * math.pi * k / n
            c = math.cos(th)
            row = base_rows[-1] if c < -0.99 else (base_rows[0] if c < -0.6 else None)
            st = dict(last)
            if row is not None:
                st["z"], st["y_back"] = row["z"], row["y_back"]
                st["half_width"] = last["half_width"] * row.get("width_scale", 1.0)
            x, y = ring_points(st, n, exponent, e)[k]
            ring.append(len(verts)); verts.append((x, y, st["z"]))
        rings.append(ring)
    faces = []
    if crown:
        top = rings[0]
        faces += [(0, top[(k + 1) % n], top[k]) for k in range(n)]
    else:
        faces += _ladder(rings[0], True)
    for a, b in zip(rings[:-1], rings[1:]):
        faces += [(a[k], b[k], b[(k + 1) % n], a[(k + 1) % n]) for k in range(n)]
    faces += _ladder(rings[-1], False)

    if replace and name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me); bm.free(); me.update()
    for p in me.polygons:
        p.use_smooth = False
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if material is not None:
        me.materials.append(material)
    ob["plate_loft_stations"] = json.dumps([{k: s[k] for k in ("t", "z", "half_width", "y_front", "y_back")} for s in stations])
    ob["ring_vertices"] = n
    return ob


def place_plates(front_png, side_png, frame, names=("FrontRef", "SideRef")):
    """Image empties for the two plates in the frame measure_plates built (FRONT on XZ, RIGHT
    on YZ), so the mesh and the plate pixels coincide. Returns (front_empty, side_empty)."""
    import bpy
    from reference import load_reference
    F, S = frame["front"], frame["side"]
    for nm in names:
        if nm in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[nm], do_unlink=True)
    front = load_reference(front_png, axis="FRONT", name=names[0], display_size=F["display_size"],
                           location=(F.get("location_x", 0.0), 0.0, F["location_z"]))
    side = load_reference(side_png, axis="RIGHT", name=names[1], display_size=S["display_size"],
                          location=(0.0, 0.0, S["location_z"]))
    return front, side


# ── residual (PIL side) ──────────────────────────────────────────────────────────────────

def outline_residual(outline_json, plate_png, plate_frame, cut_t=1.0, *, step=16, whole_row=False):
    """Compare perceive.reference_outline's silhouette with the plate fill, row by row, from the
    subject's top to the fraction cut_t. plate_frame = measure_plates(...)["frame"]["front"|"side"].
    Returns {"rows": [(v, plate_l, plate_r, outline_l, outline_r)], "mean_abs", "max_abs", "max_row"}."""
    import numpy as np
    j = json.load(open(outline_json)) if isinstance(outline_json, (str, os.PathLike)) else outline_json
    segs, (w, h) = j["silhouette"], j["image_size"]
    mask, _ = fill_mask(plate_png)
    top, bot = plate_frame["top_px"], plate_frame["bottom_px"]
    cut = top + cut_t * (bot - top)
    rows, absd, worst = [], [], (0.0, None)
    for v in range(top + 4, int(cut) - 2, step):
        pl = row_extent(mask, v, longest_run=not whole_row)
        vv = v / h
        us = []
        for (u0, v0), (u1, v1) in segs:
            if (v0 - vv) * (v1 - vv) <= 0 and v0 != v1:
                us.append(u0 + (u1 - u0) * (vv - v0) / (v1 - v0))
        if pl is None or not us:
            continue
        ol = (min(us) * w, max(us) * w)
        dl, dr = ol[0] - pl[0], ol[1] - pl[1]
        rows.append((v, pl[0], pl[1], round(ol[0]), round(ol[1]), round(dl), round(dr)))
        absd += [abs(dl), abs(dr)]
        m = max(abs(dl), abs(dr))
        if m > worst[0]:
            worst = (m, v)
    return {"rows": rows, "mean_abs": round(float(np.mean(absd)), 1) if absd else None,
            "max_abs": round(worst[0]), "max_row": worst[1]}
