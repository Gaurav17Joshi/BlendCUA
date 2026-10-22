"""
Ruler builders. Each function returns a JSON-ready dict matching the
contract documented in TOOL_AUTHORING.md.
"""

import math

from bpy_extras import view3d_utils
from mathutils import Matrix, Vector

from .view import proj_fn, viewpoint_quality


def screen_ruler(pivot, axis, region, rv3d, image_path,
                 px_step=40, k_range=None):
    """Ticks spaced at `px_step` pixels along `axis` through `pivot`.

    Matches the extrude_map.json format.
    Default k_range covers -6..+6 excluding 0.
    """
    if k_range is None:
        k_range = list(range(-6, 0)) + list(range(1, 7))

    proj = proj_fn(region, rv3d)
    p0 = view3d_utils.location_3d_to_region_2d(region, rv3d, pivot)
    p1 = view3d_utils.location_3d_to_region_2d(region, rv3d, pivot + axis)
    ticks, px_per_unit = [], 0.0
    if p0 and p1:
        px_per_unit = (p1 - p0).length
        if px_per_unit > 1e-6:
            for k in k_range:
                if k == 0:
                    continue
                t  = (px_step * k) / px_per_unit
                sp = proj(pivot + axis * t)
                if sp:
                    ticks.append({"ordinal": f"e{k}", "t": round(t, 4), "screen": sp})

    return {
        "viewport_width":    region.width,
        "viewport_height":   region.height,
        "image":             image_path,
        "pivot_screen":      proj(pivot),
        "axis_world":        [round(v, 4) for v in axis],
        "viewpoint_quality": round(viewpoint_quality(axis, rv3d), 3),
        "screen_ruler": {
            "px_step":     px_step,
            "px_per_unit": round(px_per_unit, 3),
            "ticks":       ticks,
        },
    }


def world_ruler(pivot, axis, region, rv3d, image_path,
                world_step=0.3, k_range=None):
    """Ticks spaced at fixed world-unit steps along `axis` through `pivot`.

    Emits a `world_ruler` key so the extrude overlay produces
    `*_world_exmap.png` (and no screen ruler image).

    `axis` should be a unit vector for the per-step distance to be exactly
    `world_step` metres.
    """
    if k_range is None:
        k_range = list(range(-5, 0)) + list(range(1, 6))

    proj = proj_fn(region, rv3d)
    ticks = []
    for k in k_range:
        if k == 0:
            continue
        t = k * world_step
        sp = proj(pivot + axis * t)
        if sp:
            ticks.append({"ordinal": f"e{k}", "t": round(t, 4), "screen": sp})

    return {
        "viewport_width":    region.width,
        "viewport_height":   region.height,
        "image":             image_path,
        "pivot_screen":      proj(pivot),
        "axis_world":        [round(v, 4) for v in axis],
        "viewpoint_quality": round(viewpoint_quality(axis, rv3d), 3),
        "world_ruler": {
            "step_m": world_step,
            "ticks":  ticks,
        },
    }


def scale_ruler(pivot, spoke, axis_mask, region, rv3d, image_path, factors):
    """Ticks at world-space multiples of `spoke` from `pivot`.

    spoke   : vector from pivot to the factor=1.0 "handle" position
    factors : iterable of multipliers (e.g. [0.5, 0.8, 1.2, 1.5, 2.0])

    Matches scale_map.json format.
    """
    proj = proj_fn(region, rv3d)
    ticks = []
    for f in factors:
        sp = proj(pivot + spoke * f)
        if sp:
            ticks.append({"ordinal": f"s{f}", "factor": f, "screen": sp})

    q = viewpoint_quality(spoke, rv3d) if spoke.length > 1e-6 else 0.0

    return {
        "viewport_width":    region.width,
        "viewport_height":   region.height,
        "image":             image_path,
        "axis_mask":         list(axis_mask),
        "pivot_screen":      proj(pivot),
        "handle_screen":     proj(pivot + spoke),
        "px_per_factor":     0.0,
        "viewpoint_quality": round(q, 3),
        "ticks":             ticks,
    }


def bevel_ruler(pivot, axis, region, rv3d, image_path,
                px_step=40, n_ticks=6):
    """One-sided screen ruler for symmetric operations like `bpy.ops.mesh.bevel`.

    `mesh.bevel`'s `offset` parameter is symmetric — it creates new edges at
    +offset and -offset from each selected edge in the face plane. So only
    positive ticks are useful as a magnitude picker. Tick label `eK` decodes
    to a bevel offset of `K * px_step / px_per_unit` metres (look up the
    `t` field in the JSON).

    `axis` should be the direction perpendicular to the edges being beveled,
    within the face plane (for horizontal loops on a vertical wall: `(0,0,1)`).
    """
    return screen_ruler(pivot, axis, region, rv3d, image_path,
                        px_step=px_step,
                        k_range=list(range(1, n_ticks + 1)))


def loopcut_polylines(obj_mw, ring_edges, n_cuts, region, rv3d):
    """For each of n_cuts evenly-spaced fractions, project the cut polyline.

    Returns a list of {id, frac, polyline} dicts.
    """
    proj = proj_fn(region, rv3d)
    cuts = []
    for k in range(1, n_cuts + 1):
        frac = k / (n_cuts + 1)
        polyline = []
        for e in ring_edges:
            pt3d = obj_mw @ (e.verts[0].co.lerp(e.verts[1].co, frac))
            sp = proj(pt3d)
            if sp:
                polyline.append(sp)
        if polyline:
            cuts.append({"id": f"lc{k}", "frac": round(frac, 4), "polyline": polyline})
    return cuts


def rotate_ruler(pivot, axis, reference_pt, region, rv3d, image_path,
                 angles=None):
    """Preview rotation angles by projecting where `reference_pt` lands
    after rotating around `axis` through `pivot`.

    `angles` is an iterable of finite numeric degrees; integer-like floats
    are accepted as well as fractional degrees. Tick label `r+30` decodes to a
    rotation of +30° around `axis` — apply via
    `bpy.ops.transform.rotate(value=math.radians(30), orient_axis=...)`.

    Emits a `screen_ruler` payload so the standard extrude overlay can
    render it. Each tick carries a `value_str` like "30°" so the overlay
    doesn't display the t as metres.

    For small angle ranges this looks like a near-straight ruler; for
    wide ranges it's a visible arc. The blue axis line drawn by the
    overlay is approximate (tangent through pivot), not the true arc —
    use the tick positions, not the line, as the source of truth.
    """
    if angles is None:
        angles = [-60, -45, -30, -15, 15, 30, 45, 60]

    proj   = proj_fn(region, rv3d)
    axis_n = axis.normalized()
    ticks  = []
    for raw_deg in angles:
        # The public contract says degrees, not integer degrees.  Accept
        # integer-like floats and genuinely fractional angles alike; the
        # ordinal is a label, so formatting it as an integer made a valid
        # rotation preview fail before it could draw anything.
        try:
            deg = float(raw_deg)
        except (TypeError, ValueError):
            raise ValueError("rotate_ruler: each angle must be numeric") from None
        if not math.isfinite(deg):
            raise ValueError("rotate_ruler: each angle must be finite")
        rot = Matrix.Rotation(math.radians(deg), 4, axis_n)
        rotated = pivot + (rot @ (reference_pt - pivot))
        sp = proj(rotated)
        if sp:
            label = f"{deg:+g}"
            ticks.append({
                "ordinal":   f"r{label}",
                "t":         deg,
                "value_str": f"{label}°",
                "screen":    sp,
            })

    return {
        "viewport_width":    region.width,
        "viewport_height":   region.height,
        "image":             image_path,
        "pivot_screen":      proj(pivot),
        "axis_world":        [round(v, 4) for v in axis_n],
        "viewpoint_quality": round(viewpoint_quality(axis_n, rv3d), 3),
        "screen_ruler": {
            "px_step":     0,
            "px_per_unit": 0,
            "ticks":       ticks,
        },
    }


def grab_grid(pivot, plane_axes, region, rv3d, image_path,
              n_dots=6, px_step=40):
    """2D grab destination grid in a world-space plane.

    Computes `n_dots × n_dots` candidate positions around `pivot`, with
    `px_step` pixels of screen spacing between neighbouring dots, and
    projects each to image coords.

    plane_axes : (axis_h, axis_v) — two world Vectors defining the plane.
                 axis_h becomes "horizontal" in the grid (i index),
                 axis_v becomes "vertical" (j index). For a ZX-plane grab
                 in a FRONT view, pass `(Vector((1,0,0)), Vector((0,0,1)))`.
    n_dots     : per side. Default 6 → 6×6 grid (36 dots).
    px_step    : desired screen-pixel spacing between adjacent dots.

    Each grid_point exposes its `world_offset` — apply via
    `pivot + axis_h*dx + axis_v*dy` and feed to `transform.translate`.
    """
    proj   = proj_fn(region, rv3d)
    axis_h, axis_v = plane_axes

    p0 = view3d_utils.location_3d_to_region_2d(region, rv3d, pivot)
    ph = view3d_utils.location_3d_to_region_2d(region, rv3d, pivot + axis_h)
    pv = view3d_utils.location_3d_to_region_2d(region, rv3d, pivot + axis_v)
    if not (p0 and ph and pv):
        return None
    px_per_h = (ph - p0).length
    px_per_v = (pv - p0).length
    if px_per_h < 1e-6 or px_per_v < 1e-6:
        return None

    world_step_h = px_step / px_per_h
    world_step_v = px_step / px_per_v
    center       = (n_dots + 1) / 2     # n=6 → 3.5

    grid_points = []
    for j in range(1, n_dots + 1):
        for i in range(1, n_dots + 1):
            dh = (i - center) * world_step_h
            dv = (j - center) * world_step_v
            world_pt = pivot + axis_h * dh + axis_v * dv
            sp = proj(world_pt)
            if sp:
                grid_points.append({
                    "i": i, "j": j,
                    "world_offset": [round(dh, 4), round(dv, 4)],
                    "screen": sp,
                })

    return {
        "viewport_width":  region.width,
        "viewport_height": region.height,
        "image":           image_path,
        "pivot_screen":    proj(pivot),
        "n_dots":          n_dots,
        "px_step":         px_step,
        "px_per_h":        round(px_per_h, 3),
        "px_per_v":        round(px_per_v, 3),
        "grid_points":     grid_points,
    }


def trackball_grid(pivot, reference_pt, region, rv3d, image_path,
                   n_dots=5, deg_step=10):
    """2D trackball rotation preview grid.

    Mirrors Blender's double-tap-R: yaw around camera_up, pitch around
    camera_right, applied together. Each grid point (i, j) shows where
    `reference_pt` lands after rotating by (i*deg_step, j*deg_step)
    degrees about `pivot`.

    Apply with `bpy.ops.transform.trackball(value=(math.radians(yaw_deg),
    math.radians(pitch_deg)))` after setting the transform pivot point
    so it matches `pivot` (e.g. CURSOR with the 3D cursor placed there).
    """
    proj      = proj_fn(region, rv3d)
    cam_right = (rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))).normalized()
    cam_up    = (rv3d.view_rotation @ Vector((0.0, 1.0, 0.0))).normalized()

    grid_points = []
    half = n_dots // 2
    for j in range(-half, half + 1):
        for i in range(-half, half + 1):
            yaw_deg, pitch_deg = i * deg_step, j * deg_step
            R = (Matrix.Rotation(math.radians(yaw_deg),   4, cam_up) @
                 Matrix.Rotation(math.radians(pitch_deg), 4, cam_right))
            rotated = pivot + (R @ (reference_pt - pivot))
            sp = proj(rotated)
            if sp:
                grid_points.append({
                    "i": i, "j": j,
                    "yaw_deg": yaw_deg, "pitch_deg": pitch_deg,
                    "screen": sp,
                })

    return {
        "viewport_width":  region.width,
        "viewport_height": region.height,
        "image":           image_path,
        "pivot_screen":    proj(pivot),
        "reference_screen": proj(reference_pt),
        "n_dots":          n_dots,
        "deg_step":        deg_step,
        "cam_right_world": [round(v, 4) for v in cam_right],
        "cam_up_world":    [round(v, 4) for v in cam_up],
        "grid_points":     grid_points,
    }


def ring_midpoints_polyline(obj_mw, ring_edges, region, rv3d):
    """Project the midpoint of each edge in the ring (loop-cut direction preview)."""
    proj = proj_fn(region, rv3d)
    polyline = []
    for e in ring_edges:
        mid = (e.verts[0].co + e.verts[1].co) / 2
        sp = proj(obj_mw @ mid)
        if sp:
            polyline.append(sp)
    return polyline
