"""
Screen-projected linear gradient painting — mirrors Blender's own Texture
Paint "Fill" tool with Linear Gradient content: you drag a line across the
VIEWPORT and the gradient follows that line's direction in SCREEN space,
so it looks right no matter how the UV unwrap happens to be laid out.
This is a generalization of bake_gradient.py's original fixed-world-Z
approach (see that file's docstring) to an ARBITRARY direction chosen by
eye off a rendered view, exactly like dragging a gradient fill across the
viewport in texture paint mode.

  gradient_line_preview(label="grad", rows=8, cols=8)
      Render the current view with a normalized (0-1, top-left origin)
      reference grid overlay — no geometry touched — so you can read off
      two (x_norm, y_norm) points defining the gradient line.

  gradient_line_plan_preview(point0, point1, label="grad")
      READ-ONLY. Draws the two candidate points + connecting line on a
      fresh render of the CURRENT view, each labelled with its exact
      coordinate. Re-run with adjusted points as many times as needed
      before committing — never touches geometry or the texture.

  apply_screen_gradient(obj_name, image_name, point0, point1,
                         value0=0.0, value1=1.0, subdiv=12, label="grad")
      Bakes a grey gradient into `image_name`'s pixels: point0's
      projected position (in the SAME view the preview was rendered
      from) maps to value0, point1's to value1, linear in between,
      clamped outside. Every face — triangle, quad, or n-gon (bevels
      leave pentagons/hexagons behind, which a quad-only subdivision
      would silently flat-fill) — is fan-triangulated from its first
      vertex, then each triangle is barycentrically subdivided into
      subdiv*subdiv micro-triangles before rasterizing, so the result
      reads as smooth rather than one flat colour per face.

Also in this module — decorative stroke painting (carved seams, panel
outlines, worn-edge highlights): a general "pick a few points, get a
hand-drawn line, paint it with a brush" tool, not tied to any one shape.

  stroke_lines_preview(strokes, label="lines")
      READ-ONLY. Preview N candidate strokes at once (see build_stroke_
      path's anchor/waviness fields — same "points"/"waviness"/
      "amplitude"/"frequency"/"seed"/"roughness" keys) on a fresh render
      of the CURRENT view, each in its own color, labelled. Re-pick
      points or swap waviness presets and re-run until the paths track
      what you want, then bake with apply_paint_lines() using the SAME
      strokes.

      waviness="jagged" (see lib.pathgen.add_jagged_wobble) is the one to
      reach for on CRACKS specifically — every other preset is a single
      sine wave, which reads as a smooth "wave" no matter the amplitude;
      jagged sums 3 incommensurate-frequency sines instead (cheap
      multi-octave noise), which doesn't repeat and mixes a broad wander
      with fine jitter, reading as an irregular fracture instead. Tune
      the mix with "roughness" (>1 finer/jitterier, <1 broader/smoother).
      A branching crack is just two-or-more strokes that happen to SHARE
      a point (one stroke's anchor list starts at a point taken from the
      MIDDLE of another stroke's already-baked path, not just its
      endpoint) — apply_paint_lines() already composites arbitrarily many
      independent strokes per call, so branching needs no new machinery,
      just picking anchors that meet up. Likewise a tapering crack is
      just 2-3 strokes chained end to end with decreasing "width".

  apply_paint_lines(obj_name, image_name, strokes, label="lines")
      Bakes N strokes into `image_name` in one pass, each stroke
      compositing onto the result of the previous ones (paint-over-paint,
      in list order). Each stroke dict adds brush fields on top of the
      path fields: "width", "softness", "strength", "color" (grey 0-1 or
      (r,g,b)), "blend" ("multiply" — darken, for carved seams/grime; or
      "screen" — lighten, for worn/polished edge highlights). Unlike
      apply_screen_gradient()'s coarse per-face subdivision (fine for a
      whole-face gradient, too coarse for a thin line), every face is
      rasterized at the ACTUAL texture pixel grid via numpy, so brush
      edges stay clean regardless of how thin the stroke is. Needs no
      external PIL subprocess — blending happens directly on the image's
      pixel array.

State going in: OBJECT or EDIT mode, any selection (ignored — every
face on the mesh is baked). State going out: OBJECT mode.

IMPORTANT: the view must not move/rotate/zoom between a preview call
(gradient_line_preview/gradient_line_plan_preview/stroke_lines_preview)
and the matching apply call — points are meaningless outside the view
they were read off.
"""

import bpy
import bmesh
import json
import os
import numpy as np
from mathutils import Vector

from lib.view import get_viewport, render_viewport, proj_fn
from lib.util  import run_overlay
from lib.pathgen import build_stroke_path

import runtime as _rt

OVERLAYS            = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlays")
GRID_OVERLAY         = f"{OVERLAYS}/grid_map.py"
LINE_PLAN_OVERLAY    = f"{OVERLAYS}/chain_plan_overlay.py"
STROKE_LINES_OVERLAY = f"{OVERLAYS}/stroke_lines_overlay.py"
BAKE_SCRIPT          = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bake_gradient.py")


def _step_dir():
    return f"{_rt._RUN}/steps/step_{_rt._STEP:03d}"


def gradient_line_preview(label="grad", rows=8, cols=8):
    """Render the current view + a normalized reference grid (no geometry
    touched) so you can read off two (x_norm, y_norm) points defining the
    gradient line for apply_screen_gradient().
    """
    shot_path = f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}.png"
    _, region, rv3d = get_viewport()
    if region is None:
        return None
    render_viewport(shot_path)
    run_overlay(GRID_OVERLAY, "--image", shot_path,
                "--tl", "0", "0", "--br", "1", "1",
                "--rows", str(rows), "--cols", str(cols))
    return {"image": shot_path, "viewport_width": region.width, "viewport_height": region.height}


def _line_plan_paths(label):
    base = f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}_linebase.png"
    return (
        base,
        f"{_step_dir()}/overlay_json/action_{_rt._ACTION:02d}_{label}_line.json",
        f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}_line.png",
    )


def gradient_line_plan_preview(point0, point1, label="grad"):
    """READ-ONLY. Draws the candidate gradient line (point0 -> point1,
    normalized image coords) on a fresh viewport render, labelled with
    exact coordinates. Doesn't touch geometry or the texture.
    """
    shot_path, json_path, overlay_path = _line_plan_paths(label)
    _, region, rv3d = get_viewport()
    if region is None:
        return None
    render_viewport(shot_path)
    payload = {
        "image": shot_path,
        "viewport_width": region.width,
        "viewport_height": region.height,
        "current_point": {"x_norm": point0[0], "y_norm": point0[1]},
        "planned_points": [{"x_norm": point1[0], "y_norm": point1[1]}],
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(LINE_PLAN_OVERLAY, "--json", json_path, "--output", overlay_path)
    return payload


def _subdivide_triangle_grid(A, B, C, a, b, c, R):
    """Barycentric subdivision of a triangle (world corners A,B,C; UV
    corners a,b,c) into R*R small triangles. Returns a list of
    (world_corners[3], uv_corners[3]), each a flat-shadeable micro-tri.
    Works for any planar (or near-planar) triangle — this is what lets
    apply_screen_gradient() treat quads/pentagons/etc uniformly by first
    fan-triangulating them.
    """
    a_v, b_v, c_v = Vector(a), Vector(b), Vector(c)
    grid_w  = [[None] * (R + 1 - i) for i in range(R + 1)]
    grid_uv = [[None] * (R + 1 - i) for i in range(R + 1)]
    for i in range(R + 1):
        s = i / R
        for j in range(R + 1 - i):
            t = j / R
            grid_w[i][j]  = A   + (B   - A)   * s + (C   - A)   * t
            grid_uv[i][j] = a_v + (b_v - a_v) * s + (c_v - a_v) * t

    tris = []
    for i in range(R):
        for j in range(R - i):
            tris.append((
                [grid_w[i][j],  grid_w[i + 1][j],  grid_w[i][j + 1]],
                [grid_uv[i][j], grid_uv[i + 1][j], grid_uv[i][j + 1]],
            ))
            if j < R - i - 1:
                tris.append((
                    [grid_w[i + 1][j],  grid_w[i + 1][j + 1],  grid_w[i][j + 1]],
                    [grid_uv[i + 1][j], grid_uv[i + 1][j + 1], grid_uv[i][j + 1]],
                ))
    return tris


def apply_screen_gradient(obj_name, image_name, point0, point1,
                           value0=0.0, value1=1.0, subdiv=12, label="grad"):
    """Bake a grey gradient into `image_name`, driven by each point's
    projected position in the CURRENT view along the line point0->point1
    (normalized image coords, same convention as gradient_line_preview()).
    """
    obj = bpy.data.objects[obj_name]
    _, region, rv3d = get_viewport()
    if region is None:
        return False

    p0 = Vector(point0)
    p1 = Vector(point1)
    line_vec = p1 - p0
    line_len2 = line_vec.length_squared
    if line_len2 < 1e-9:
        return False

    proj = proj_fn(region, rv3d)

    def t_along_line(world_pt):
        s = proj(world_pt)
        if s is None:
            return 0.5
        sn = Vector((s["x"] / region.width, s["y"] / region.height))
        t = (sn - p0).dot(line_vec) / line_len2
        return max(0.0, min(1.0, t))

    if bpy.context.mode != 'EDIT_MESH':
        bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    mw = obj.matrix_world

    quads_payload = []
    for f in bm.faces:
        verts = list(f.verts)
        loops = list(f.loops)
        wpos  = [mw @ v.co for v in verts]
        uvs   = [tuple(l[uv_layer].uv) for l in loops]
        n     = len(verts)

        # Fan-triangulate from vertex 0 so this handles triangles, quads,
        # AND the pentagons/hexagons a vertex bevel leaves on neighbouring
        # faces — no separate flat-fill fallback needed.
        for k in range(1, n - 1):
            tris = _subdivide_triangle_grid(
                wpos[0], wpos[k], wpos[k + 1],
                uvs[0],  uvs[k],  uvs[k + 1],
                subdiv,
            )
            for world_corners, uv_corners in tris:
                tv = sum(t_along_line(w) for w in world_corners) / 3.0
                grey = value0 + (value1 - value0) * tv
                quads_payload.append({
                    "uv": [(p.x, p.y) for p in uv_corners],
                    "grey": grey,
                })

    bpy.ops.object.mode_set(mode='OBJECT')

    img = bpy.data.images[image_name]
    tex_size = img.size[0]

    json_path = f"{_step_dir()}/overlay_json/action_{_rt._ACTION:02d}_{label}_bake.json"
    png_path  = f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}_baked.png"
    payload = {"tex_size": tex_size, "background": value0, "faces": quads_payload}
    with open(json_path, "w") as f:
        json.dump(payload, f)

    run_overlay(BAKE_SCRIPT, "--json", json_path, "--output", png_path)

    # Batch replays stub viewport overlays, so an old resized PNG may remain at
    # png_path. Fall back to drawing the same UV polygons in-process rather than
    # copying a stale image whose size/order cannot match the target datablock.
    baked_path = png_path
    try:
        from PIL import Image, ImageDraw
        with Image.open(png_path) as probe:
            if probe.size != (tex_size, tex_size):
                raise ValueError("stale gradient PNG size")
    except Exception:
        from PIL import Image, ImageDraw
        baked_path = png_path.rsplit(".", 1)[0] + "_fallback.png"
        bg = int(round(max(0.0, min(1.0, value0)) * 255))
        baked = Image.new("RGB", (tex_size, tex_size), (bg, bg, bg))
        draw = ImageDraw.Draw(baked)
        for face in quads_payload:
            val = int(round(max(0.0, min(1.0, face["grey"])) * 255))
            pts = [(u * tex_size, (1.0 - v) * tex_size)
                   for u, v in face["uv"]]
            if len(pts) >= 3:
                draw.polygon(pts, fill=(val, val, val))
        baked.save(baked_path)

    loaded = bpy.data.images.load(baked_path, check_existing=False)
    arr = np.empty(len(loaded.pixels), dtype=np.float32)
    loaded.pixels.foreach_get(arr)
    img.pixels.foreach_set(arr)
    img.pack()
    img.update()
    bpy.data.images.remove(loaded)
    if baked_path != png_path:
        try:
            os.remove(baked_path)
        except OSError:
            pass

    return True


def stroke_lines_preview(strokes, label="lines"):
    """READ-ONLY. Preview N candidate strokes at once on a fresh render of
    the CURRENT view. Each entry in `strokes` is a dict:
        {
          "points":    [(x_norm, y_norm), ...]   # 2+ anchors
          "waviness":  "straight"|"subtle"|"wavy"|"bumpy" (default "straight")
          "amplitude": float (optional, overrides the waviness preset)
          "frequency": float (optional, overrides the waviness preset)
          "seed":      int (optional, default 0)
          "smooth":    bool (default True — Catmull-Rom, every anchor
                       rounded; False — straight segments between
                       anchors, sharp corners, for angular shapes like a
                       panel border. wobble still applies on top either way)
          "label":     str (optional, short prefix for this stroke's dots)
          "show_anchors": bool (default True). False draws the line and one
                       label only — use it for closed shapes such as a
                       brush-size circle, where a numbered dot per anchor
                       buries the image under its own annotation.
          "color_hint": (r, g, b) 0-255 (optional, overrides the palette)
        }
    (brush/color/blend fields are ignored here — this previews the PATH
    only; call apply_paint_lines() with the same strokes once happy.)

    Returns the payload dict (each stroke's resolved dense polyline is
    included, normalized image coords) — never touches the texture.
    """
    shot_path    = f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}.png"
    json_path    = f"{_step_dir()}/overlay_json/action_{_rt._ACTION:02d}_{label}_lines.json"
    overlay_path = f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}_lines.png"
    _, region, rv3d = get_viewport()
    if region is None:
        return None
    render_viewport(shot_path)

    strokes_out = []
    for i, s in enumerate(strokes):
        poly = build_stroke_path(
            s["points"],
            waviness=s.get("waviness", "straight"),
            amplitude=s.get("amplitude"),
            frequency=s.get("frequency"),
            seed=s.get("seed", 0),
            smooth=s.get("smooth", True),
            roughness=s.get("roughness", 1.0),
            resolved=s.get("resolved", False),
        )
        strokes_out.append({
            "label":        s.get("label", f"L{i}_"),
            "anchors":      [list(p) for p in s["points"]],
            "polyline":     [list(p) for p in poly],
            # False draws the path only, with a single label instead of a
            # numbered dot per anchor — for closed shapes like size circles.
            "show_anchors": bool(s.get("show_anchors", True)),
            "color_hint":   s.get("color_hint"),
        })

    payload = {
        "image": shot_path,
        "viewport_width": region.width,
        "viewport_height": region.height,
        "strokes": strokes_out,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(STROKE_LINES_OVERLAY, "--json", json_path, "--output", overlay_path)
    return payload


def _point_seg_dist_batch(px, py, ax, ay, bx, by):
    """Vectorized point-to-segment distance. px, py: numpy arrays (any
    shape, same shape as each other). ax,ay,bx,by: scalars (one segment).
    Returns an array the same shape as px.
    """
    abx, aby = bx - ax, by - ay
    ab_len2 = abx * abx + aby * aby
    if ab_len2 < 1e-12:
        return np.hypot(px - ax, py - ay)
    t = ((px - ax) * abx + (py - ay) * aby) / ab_len2
    t = np.clip(t, 0.0, 1.0)
    cx = ax + t * abx
    cy = ay + t * aby
    return np.hypot(px - cx, py - cy)


def apply_paint_lines(obj_name, image_name, strokes, label="lines",
                       face_normal=None, normal_tolerance=0.9):
    """Bake N screen-space strokes into `image_name` in one optimized pass.
    The stroke path and brush fields are the same as the preview contract.

    Each entry in `strokes` — path fields as in stroke_lines_preview(),
    plus:
        "width":    float, normalized image space (default 0.012)
        "softness": float, normalized image space feather (default 0.008)
        "strength": float 0-1, max opacity at the stroke's centre (default 0.85)
        "color":    float (grey 0-1) or (r,g,b) 0-1 (default 0.0)
        "blend":    "multiply" (darken — carved seams, grime) or
                    "screen" (lighten — worn/polished edge highlights).
                    Default "multiply".

    ``resolved=True`` accepts a dense polyline already returned by a preview;
    ``face_normal`` and ``normal_tolerance`` optionally confine paint to one
    world-facing surface, preventing projected strokes from bleeding across a
    neighboring face.

    Every face (any vertex count — fan-triangulated) is rasterized at the
    ACTUAL texture pixel grid, so brush edges stay clean regardless of how
    thin the stroke is (unlike apply_screen_gradient()'s coarser
    per-face subdivision, which is fine for a whole-face gradient but too
    coarse for a thin line).

    Back-facing triangles (pointing away from the CURRENT view) are
    skipped — strokes are picked off a specific view and should only
    paint the side of the object actually visible there, not bleed onto
    the far side just because its screen-projection happens to land in
    the same spot.
    """
    return _apply_paint_lines_optimized(
        obj_name, image_name, strokes, label=label,
        face_normal=face_normal, normal_tolerance=normal_tolerance)

def _apply_paint_lines_optimized(obj_name, image_name, strokes, label="lines",
                                 face_normal=None, normal_tolerance=0.9):
    """Implementation shared by the public paint entry point."""
    obj = bpy.data.objects[obj_name]
    _, region, rv3d = get_viewport()
    if region is None:
        return False
    if obj.data.uv_layers.active is None:
        raise ValueError("apply_paint_lines: object has no active UV layer")

    normal_filter = None
    if face_normal is not None:
        normal_filter = Vector(face_normal)
        if normal_filter.length < 1e-12:
            raise ValueError("apply_paint_lines: face_normal must be non-zero")
        normal_filter.normalize()
    if not -1.0 <= float(normal_tolerance) <= 1.0:
        raise ValueError("apply_paint_lines: normal_tolerance must be in [-1, 1]")

    img = bpy.data.images[image_name]
    W, H = int(img.size[0]), int(img.size[1])
    arr = np.empty(W * H * 4, dtype=np.float32)
    img.pixels.foreach_get(arr)
    # Blender stores row 0 at UV v=0, so the raw array and UV raster grid
    # already have the same vertical orientation.
    arr = arr.reshape(H, W, 4)

    def compact_path(poly):
        """Remove collinear samples without changing a path's distance."""
        out = []
        for point in poly:
            point = (float(point[0]), float(point[1]))
            if len(out) >= 2:
                ax, ay = out[-2]
                bx, by = out[-1]
                cross = ((bx - ax) * (point[1] - by)
                         - (by - ay) * (point[0] - bx))
                # The tolerance is for floating-point samples of a line;
                # normalized screen coordinates make it safely sub-pixel.
                scale = max(1.0, abs(bx - ax) + abs(by - ay)
                            + abs(point[0] - bx) + abs(point[1] - by))
                if abs(cross) <= 1e-12 * scale:
                    out[-1] = point
                    continue
            out.append(point)
        return out

    paths = []
    for stroke in strokes:
        poly = build_stroke_path(
            stroke["points"],
            waviness=stroke.get("waviness", "straight"),
            amplitude=stroke.get("amplitude"),
            frequency=stroke.get("frequency"),
            seed=stroke.get("seed", 0),
            smooth=stroke.get("smooth", True),
            roughness=stroke.get("roughness", 1.0),
            resolved=stroke.get("resolved", False),
        )
        poly = compact_path(poly)
        if len(poly) < 2:
            raise ValueError("apply_paint_lines: every stroke needs 2 points")
        width = float(stroke.get("width", 0.012))
        softness = float(stroke.get("softness", 0.008))
        if width < 0.0 or softness < 0.0:
            raise ValueError("apply_paint_lines: width/softness must be non-negative")
        poly_xy = np.asarray(poly, dtype=np.float64)
        margin = width * 0.5 + softness
        paths.append({
            "poly": poly_xy,
            "bbox": (poly_xy[:, 0].min() - margin,
                     poly_xy[:, 1].min() - margin,
                     poly_xy[:, 0].max() + margin,
                     poly_xy[:, 1].max() + margin),
            "width": width,
            "softness": softness,
            "strength": float(stroke.get("strength", 0.85)),
            "blend": stroke.get("blend", "multiply"),
            "color": stroke.get("color", 0.0),
        })

    # No stroke is a valid no-op, but still leaves the image untouched.
    if not paths:
        return True

    pm = np.asarray(rv3d.perspective_matrix, dtype=np.float64)

    def project_world(world_pts):
        """World (N,3) -> normalized image-down screen coordinates."""
        world_pts = np.asarray(world_pts, dtype=np.float64)
        pts_h = np.concatenate((world_pts,
                                np.ones((len(world_pts), 1))), axis=1)
        clip = pts_h @ pm.T
        w = clip[:, 3:4].copy()
        w[np.abs(w) < 1e-12] = 1e-12
        ndc = clip[:, :3] / w
        return ndc[:, 0] * 0.5 + 0.5, 1.0 - (ndc[:, 1] * 0.5 + 0.5)

    # Cache visible, relevant triangle pixels once.  The previous implementation
    # repeated the barycentric world interpolation and screen projection for
    # every stroke, which is the expensive part on a large texture.
    mw = obj.matrix_world
    normal_matrix = mw.to_3x3().inverted().transposed()
    view_fwd = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    uv_layer = obj.data.uv_layers.active.data
    claimed = np.zeros((H, W), dtype=bool)
    prepared = []
    for face in obj.data.polygons:
        verts = list(face.vertices)
        loops = list(face.loop_indices)
        if len(verts) < 3:
            continue
        world_all = [mw @ obj.data.vertices[vi].co for vi in verts]
        world_normal = (normal_matrix @ face.normal).normalized()
        if (normal_filter is not None and
                world_normal.dot(normal_filter) < float(normal_tolerance)):
            continue
        uv_all = [tuple(uv_layer[li].uv) for li in loops]
        for k in range(1, len(verts) - 1):
            A, B, C = world_all[0], world_all[k], world_all[k + 1]
            # The view forward points from the camera into the scene; a front
            # surface normal therefore has a negative dot product.
            if (B - A).cross(C - A).dot(view_fwd) >= 0.0:
                continue
            uv_tri = np.asarray((uv_all[0], uv_all[k], uv_all[k + 1]),
                                dtype=np.float64)
            corners = np.asarray([[p.x, p.y, p.z] for p in (A, B, C)],
                                 dtype=np.float64)
            corner_x, corner_y = project_world(corners)
            tri_bbox = (corner_x.min(), corner_y.min(),
                        corner_x.max(), corner_y.max())
            if not any(not (tri_bbox[2] < p["bbox"][0] or
                            tri_bbox[0] > p["bbox"][2] or
                            tri_bbox[3] < p["bbox"][1] or
                            tri_bbox[1] > p["bbox"][3]) for p in paths):
                continue

            px0 = max(0, int(np.floor(uv_tri[:, 0].min() * W)))
            px1 = min(W, int(np.ceil(uv_tri[:, 0].max() * W)) + 1)
            py0 = max(0, int(np.floor(uv_tri[:, 1].min() * H)))
            py1 = min(H, int(np.ceil(uv_tri[:, 1].max() * H)) + 1)
            if px1 <= px0 or py1 <= py0:
                continue
            gx, gy = np.meshgrid(np.arange(px0, px1, dtype=np.int32),
                                 np.arange(py0, py1, dtype=np.int32))
            pu = (gx + 0.5) / W
            pv = (gy + 0.5) / H
            a, b, c = uv_tri
            denom = ((b[1] - c[1]) * (a[0] - c[0])
                     + (c[0] - b[0]) * (a[1] - c[1]))
            if abs(denom) < 1e-12:
                continue
            w0 = ((b[1] - c[1]) * (pu - c[0])
                  + (c[0] - b[0]) * (pv - c[1])) / denom
            w1 = ((c[1] - a[1]) * (pu - c[0])
                  + (a[0] - c[0]) * (pv - c[1])) / denom
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
            if not inside.any():
                continue
            pix_x, pix_y = gx[inside], gy[inside]
            unique = ~claimed[pix_y, pix_x]
            if not unique.any():
                continue
            # Fan triangles share edges. Claim each UV pixel once so a line
            # crossing a diagonal is composited once, not once per triangle.
            claimed[pix_y[unique], pix_x[unique]] = True
            mw0 = w0[inside][unique]
            mw1 = w1[inside][unique]
            mw2 = w2[inside][unique]
            A_np, B_np, C_np = np.asarray(A), np.asarray(B), np.asarray(C)
            world_pts = (mw0[:, None] * A_np + mw1[:, None] * B_np
                         + mw2[:, None] * C_np)
            sx, sy = project_world(world_pts)
            prepared.append({
                "x": pix_x[unique], "y": pix_y[unique],
                "sx": sx, "sy": sy,
                "bbox": tri_bbox,
            })

    for path in paths:
        poly = path["poly"]
        inner = path["width"] * 0.5
        outer = inner + max(path["softness"], 1e-6)
        colour = path["color"]
        color_arr = (np.array([colour, colour, colour], dtype=np.float32)
                     if isinstance(colour, (int, float)) else
                     np.asarray(colour, dtype=np.float32))
        if color_arr.shape != (3,):
            raise ValueError("apply_paint_lines: color must be scalar or RGB")
        for tri in prepared:
            if (tri["bbox"][2] < path["bbox"][0] or
                    tri["bbox"][0] > path["bbox"][2] or
                    tri["bbox"][3] < path["bbox"][1] or
                    tri["bbox"][1] > path["bbox"][3]):
                continue
            dist = None
            for i in range(len(poly) - 1):
                d = _point_seg_dist_batch(
                    tri["sx"], tri["sy"], poly[i, 0], poly[i, 1],
                    poly[i + 1, 0], poly[i + 1, 1])
                dist = d if dist is None else np.minimum(dist, d)
            if dist is None:
                continue
            opacity = path["strength"] * np.clip(
                (outer - dist) / max(outer - inner, 1e-6), 0.0, 1.0)
            if not (opacity > 0.0).any():
                continue
            old = arr[tri["y"], tri["x"], :3]
            op = opacity[:, None].astype(np.float32)
            if path["blend"] == "screen":
                blended = 1.0 - ((1.0 - old)
                                 * (1.0 - color_arr[None, :]))
            else:
                blended = old * color_arr[None, :]
            arr[tri["y"], tri["x"], :3] = old * (1.0 - op) + blended * op

    img.pixels.foreach_set(arr.reshape(-1))
    img.pack()
    img.update()
    return True
