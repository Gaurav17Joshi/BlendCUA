# WEATHERING — texture-driven surface damage, at the level an action should
# work at.
#
# sculpt_native gives you the primitives (displace, footprints, vertex groups,
# a face axis, draped paths). This assembles them into the two calls a
# weathering action actually needs:
#
#     preview_paths(...)   draw the strokes, the brush size and the texture
#                          size, and stop
#     weather(...)         lay the texture layers into those strokes
#
# Nothing here knows what it is weathering. It takes an object, some paths in
# world space, and a list of layers.
#
# THE ONE RULE THIS ENCODES. All the paths are combined into a SINGLE
# footprint and each texture layer is displaced through it once. Displacing
# per stroke instead applies the texture twice everywhere two bands overlap,
# which shows up as a bright seam running down the middle of every face. If
# you are tempted to loop over paths calling displace, don't — that is the bug
# this exists to prevent.

import os

import bpy
import numpy as np
from mathutils import Vector

from runtime import shot
from lib.view import get_viewport, project_to_norm
from paint import stroke_lines_preview
import sculpt_native as sn
import wear_textures as wt


def vertical_face_lines(obj, normal, offsets, z0, z1, n=40, standoff=3.0):
    """Vertical strokes on one flat face of an upright object.

    `offsets` are positions ACROSS the face in metres, measured from its
    centre line, so (-0.3, -0.1, 0.1, 0.3) gives four evenly spread lines. The
    across direction is derived from the face normal, so the same call works
    on any of the four sides of a prism without the caller doing trigonometry.

    Every line is draped onto the real surface, so it follows steps, tapers
    and grooves rather than hanging in space over them.
    """
    nz = Vector(normal).normalized()
    across = nz.cross(Vector((0.0, 0.0, 1.0)))
    if across.length < 1e-6:
        across = Vector((1.0, 0.0, 0.0))     # a horizontal face; pick any
    across.normalize()

    out = []
    for t in offsets:
        base = across * float(t) + nz * standoff
        a = base + Vector((0.0, 0.0, float(z0)))
        b = base + Vector((0.0, 0.0, float(z1)))
        path = sn.drape_line(obj, a, b, -nz, n=n)
        if len(path) >= 2:
            out.append(path)
    return out


def _resolve_layer(spec, assets_dir, size=1024):
    """One layer spec -> a ready Texture datablock plus its numbers.

    spec: {"texture": <name in wear_textures.LIBRARY> or a bpy Texture,
           "feature": metres, "strength": m, "mid_level": float,
           "cells": int, "seed": int, "tile": int,
           ...any other generator kwarg}

    SIZE. Give "feature" in metres and the size comes out exactly that — it
    sets the texture axis scale, which is continuous. "tile" is the older
    control: an integer repeat count, so it can only step the size in whole
    fractions of the object. Use feature; tile is there for when you want a
    specific number of repeats rather than a specific size.

    Anything omitted falls back to the library's recommendation, so a layer
    can be as short as {"texture": "pits", "feature": 0.05}.
    """
    spec = dict(spec)
    tex_in = spec.pop("texture")
    tile = int(spec.pop("tile", 1))
    label = spec.pop("label", None)
    feature = spec.pop("feature", None)

    if isinstance(tex_in, bpy.types.Texture):
        tex, name = tex_in, tex_in.name
        strength = float(spec.pop("strength"))
        mid = float(spec.pop("mid_level"))
        cells = spec.pop("cells", None)
    else:
        name = tex_in
        fn, mid_d, str_d, _minf, _desc = wt.LIBRARY[name]
        strength = float(spec.pop("strength", str_d))
        mid = float(spec.pop("mid_level", mid_d))
        # NOT popped: cells is a real generator argument on the cell-based
        # maps and also the number feature_size needs. Popping it here made
        # the generator quietly fall back to its default while the preview
        # reported the size that had been asked for.
        cells = spec.get("cells")
        arr = fn(size=size, **spec)
        os.makedirs(assets_dir, exist_ok=True)
        path = os.path.join(assets_dir, "%s.png" % (label or name))
        wt.write_png(path, arr)
        tex = sn.image_texture(label or name, path)
    tex.repeat_x = tex.repeat_y = tile
    scale = axis_scale_for(feature, tile, cells) if feature else None
    return dict(name=label or name, tex=tex, tile=tile, strength=strength,
                mid=mid, cells=cells, feature=feature, axis_scale=scale)


def feature_size(tile, cells, axis_scale=1.0):
    """Metres per feature: one tile spans 2*axis_scale metres, and holds
    `cells` of them. For a map with no cell structure this returns the size
    of one whole tile instead, which is the only length it has."""
    span = 2.0 * axis_scale / float(tile)
    return span / cells if cells else span


def axis_scale_for(feature, tile, cells):
    """The Empty scale that makes one feature come out `feature` metres.

    This is the texture SCALE control, and it is continuous — unlike the tile
    count, which is an integer repeat and so can only step the size in whole
    fractions. Ask for 45 mm pebbles and you get 45 mm pebbles.

    For a map with no cells (erosion, granular, scratches) `feature` is the
    size of one whole tile, since nothing smaller in it has a defined size.
    """
    return float(feature) * float(tile) * (cells if cells else 1) / 2.0


def preview_paths(paths, radius, features=(), label="paths", note="",
                  at=None, face_normal=None, thin=6):
    """Draw the strokes plus the two sizes that decide how they will look.

    features: [(name, metres), ...] — one circle each, drawn inside the brush
    circle. A path line says where a stroke goes and NOTHING about how wide it
    is or how big the texture on it will be, and both are invisible until
    after the stroke has run.

    Read it like this: if a feature circle is a large fraction of the brush
    circle, only a couple of features fit across the band and it will read as
    lumps rather than as texture. If it is tiny against the mesh, it will
    alias instead of displacing.
    """
    region, rv3d = get_viewport()[1:]

    def to_screen(pts):
        out = [project_to_norm(Vector(p), region, rv3d) for p in pts]
        return [q for q in out if q]

    strokes = []
    for i, p in enumerate(paths):
        pts = to_screen(p)
        if len(pts) < 2:
            continue
        strokes.append({"points": pts[::max(1, thin)], "waviness": "straight",
                        "label": "line%d" % (i + 1),
                        "color_hint": (255, 210, 0)})

    if at is None and paths:
        # mid-height of an inner line: at the end of a path the circle lands
        # on whatever the model does next, and on an outer line it overhangs
        # the silhouette and reads as floating in space
        inner = paths[min(1, len(paths) - 1)]
        at = inner[len(inner) // 2]

    nrm = face_normal or (0.0, 0.0, 1.0)
    if at is not None:
        strokes.append({"points": to_screen(sn.brush_circle(at, radius,
                                                            normal=nrm, n=64)),
                        "waviness": "straight", "smooth": False,
                        "show_anchors": False, "color_hint": (60, 200, 255),
                        "label": "brush %.0f mm" % (radius * 2000)})
        for fname, fsize in features:
            if not fsize:
                continue
            strokes.append({
                "points": to_screen(sn.brush_circle(at, fsize / 2.0,
                                                    normal=nrm, n=40)),
                "waviness": "straight", "smooth": False,
                "show_anchors": False, "color_hint": (255, 90, 90),
                "label": "%s %.0f mm" % (fname, fsize * 1000)})

    stroke_lines_preview(strokes, label=label)
    if note:
        shot(note, enabled=False)
    return strokes


def weather(obj_name, paths, radius, layers, assets_dir,
            face_normal=None, face_dot=0.25, hardness=0.0, tail=0.0,
            axis_name=None, axis_scale=1.0, group="weather",
            texture_size=1024):
    """Lay texture layers into the footprint of a set of brush paths.

    obj_name     mesh to damage
    paths        list of world-space polylines
    radius       brush radius, metres
    layers       list of layer specs, see _resolve_layer
    face_normal  restrict to geometry facing this way, and orient the texture
                 axis to match. Omit on a surface that is not flat-ish.

    Returns a dict with `before`, `after` (world coordinate arrays for the
    same vertices), `layers` (per-layer displacement reports), `footprint`,
    and `text` (a ready-made summary). Displacement never changes topology,
    so `before` and `after` are directly comparable with sn.movement().
    """
    obj = bpy.data.objects[obj_name]
    resolved = [_resolve_layer(s, assets_dir, size=texture_size)
                for s in layers]

    before = sn.world_arrays(obj)[0]

    f = sn.strokes_footprint(obj, paths, radius, hardness=hardness, tail=tail,
                             face_normal=face_normal, face_dot=face_dot)
    gname, n_group = sn.make_vertex_group(obj, group, f)

    rows = ["%s: %d paths, brush r=%.0f mm, footprint %d verts"
            % (obj_name, len(paths), radius * 1000, n_group)]
    reports = []
    for lay in resolved:
        # ONE AXIS PER LAYER. A single shared Empty forces every layer to the
        # same scale, so the only size control left is the integer tile count
        # and a fine layer over a coarse one becomes impossible to place.
        axis = None
        if face_normal is not None:
            axis = sn.face_axis(
                "%s_%s" % (axis_name or ("axis_%s" % group), lay["name"]),
                face_normal, scale=lay["axis_scale"] or axis_scale)
        rep = sn.displace(obj_name, lay["tex"], strength=lay["strength"],
                          mid_level=lay["mid"], direction='NORMAL',
                          texture_coords='OBJECT' if axis else 'LOCAL',
                          coords_object=axis, vertex_group=gname,
                          label=lay["name"])
        reports.append(rep)
        feat = feature_size(lay["tile"], lay["cells"],
                            lay["axis_scale"] or axis_scale)
        rows.append("  %-15s tile %2d  feature %s  strength %5.1f mm  "
                    "mid %.2f  -> out %+.4f in %+.4f m, %d verts"
                    % (lay["name"], lay["tile"],
                       ("%3.0f mm" % (feat * 1000)) if feat else "  n/a ",
                       lay["strength"] * 1000, lay["mid"],
                       rep["max_out"], rep["max_in"], rep["verts_moved"]))

    after = sn.world_arrays(obj)[0]
    mx, mean, n_moved = sn.movement(before, after)
    rows.append("  total movement: max %.2f mm, mean %.2f mm over %d verts"
                % (mx, mean, n_moved))

    return dict(before=before, after=after, layers=reports, resolved=resolved,
                footprint=n_group, weights=f, text="\n".join(rows))
