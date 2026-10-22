"""
Handle-building helpers. Split so each segment is two actions:

  prepare_segment(label, extrude_t, rotate_deg)
      Extrude the selected face by extrude_t along its current world
      normal, rotate the new face by rotate_deg around its local
      horizontal axis (world_Z × face_normal), then render the grab grid
      overlay so the next action can pick (row, col) from the image.

  apply_grab(label, grab_row, grab_col)
      Read the JSON the prepare step wrote, look up the dot at image
      (row, col) — view-agnostic, gotchas §14 — translate the new face's
      verts by that dot's world offset.

For segments with no grab (typically the handle tip) use:

  extrude_rotate(label, extrude_t, rotate_deg)
      Extrude + rotate in one shot, no grab phase, no grid render.

For building an arc/loop from a handful of points chosen by eye off a
single reference image, instead of one prepare/apply round-trip per
segment:

  chain_preview(label)
      Render the current selected face's centre as a red dot on a
      normalized (0-1, top-left origin) coordinate grid overlay. Use once
      at the start of a chain to read off the starting point + grid.

  chain_plan_preview(points, label)
      READ-ONLY. Given a candidate list of (x_norm, y_norm) points, compute
      the exact 3D path apply_chain() would produce for them (same
      step-by-step unprojection logic) and draw it as numbered dots +
      connecting lines directly on the CURRENT viewport render — no
      geometry is touched. Re-run this as many times as needed with
      adjusted points to check the planned path against the real model
      (clipping, silhouette, proportions) before committing.

  apply_chain(points, label, auto_face=True, face_mode="average", rotations=None)
      Given a list of (x_norm, y_norm) points — normally the ones just
      confirmed via chain_plan_preview() — extrude the face through each
      in turn, in ONE action. Each point is unprojected onto the plane
      through the CURRENT face's centre (so a front-ortho view's depth
      axis stays put through the whole chain). By DEFAULT (auto_face=True)
      each new face is also rotated to face `face_mode`'s direction — this
      is what keeps the tube's cross-section smooth through turns instead
      of shearing/kinking at every direction change. `face_mode` defaults
      to "average" (bisector of the incoming + outgoing edge directions —
      a proper miter joint); "previous" or "next" use just one edge.
      Pass an explicit `rotations` list (degrees, one entry per
      point, None = use the default) for arbitrary manual rotation on top
      of or instead of auto-facing.

State going in (every helper):  FACE mode + one face selected.
State going out:                FACE mode + the new (or rotated) face selected.
"""

import bpy
import bmesh
import json
import math
import os
from mathutils import Vector, Matrix
from bpy_extras import view3d_utils

from lib.view  import get_viewport, render_viewport, proj_fn
from lib.util  import run_overlay
from lib.ruler import grab_grid

import runtime as _rt

OVERLAYS         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlays")
GRABGRID_OVERLAY = f"{OVERLAYS}/grab_grid_overlay.py"
CHAIN_OVERLAY    = f"{OVERLAYS}/chain_extrude_overlay.py"
CHAIN_PLAN_OVERLAY = f"{OVERLAYS}/chain_plan_overlay.py"
QUAD_PLAN_OVERLAY  = f"{OVERLAYS}/quad_plan_overlay.py"
BODY_PROFILE_OVERLAY = f"{OVERLAYS}/body_profile_overlay.py"


def _step_dir():
    return f"{_rt._RUN}/steps/step_{_rt._STEP:03d}"


def _grab_paths(label):
    """Per-segment grab grid PNG + JSON paths under the current action."""
    return (
        f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}_grab.png",
        f"{_step_dir()}/overlay_json/action_{_rt._ACTION:02d}_{label}_grab.json",
    )


def _grab_json_path_for(label, action):
    """Look up the JSON written by prepare_segment in `action`."""
    return f"{_step_dir()}/overlay_json/action_{action:02d}_{label}_grab.json"


def _extrude_then_rotate(extrude_t, rotate_deg):
    """Shared body: extrude the selected face along its normal, then rotate
    the new face around (world_Z × face_normal). Returns the new face's
    centroid (world) for any caller that needs to plant a grid there, or
    None if a phase aborted.
    """
    cup = bpy.context.active_object
    mw  = cup.matrix_world

    # --- Extrude along the source face's world normal ---
    bm = bmesh.from_edit_mesh(cup.data)
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    if not any(f.select for f in bm.faces):
        return None
    bpy.ops.mesh.extrude_region_shrink_fatten(
        TRANSFORM_OT_shrink_fatten={"value": extrude_t},
    )

    # --- Rotate the new (post-extrude, currently selected) face ---
    bm = bmesh.from_edit_mesh(cup.data)
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    new_face = next((f for f in bm.faces if f.select), None)
    if new_face is None:
        return None

    if abs(rotate_deg) > 1e-6:
        rot_pivot  = mw @ new_face.calc_center_median()
        rot_normal = (mw.to_3x3() @ new_face.normal).normalized()
        rot_axis   = Vector((0, 0, 1)).cross(rot_normal).normalized()
        rot_mat    = Matrix.Rotation(math.radians(rotate_deg), 4, rot_axis)
        mw_inv     = mw.inverted()
        for v in new_face.verts:
            world_pos = mw @ v.co
            rotated_w = rot_pivot + (rot_mat @ (world_pos - rot_pivot))
            v.co      = mw_inv @ rotated_w
        bmesh.update_edit_mesh(cup.data)

        # Re-fetch the face after the manual co writes.
        bm = bmesh.from_edit_mesh(cup.data)
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        new_face = next((f for f in bm.faces if f.select), None)
        if new_face is None:
            return None

    return mw @ new_face.calc_center_median()


def prepare_segment(label, extrude_t, rotate_deg, n_dots=6, px_step=40):
    """Extrude + rotate + render the grab grid for this segment.

    The next action calls `apply_grab(label, row, col)` to translate the
    new face to whichever dot was picked off the rendered overlay.

    Returns True if all phases applied; False otherwise.
    """
    grab_pivot = _extrude_then_rotate(extrude_t, rotate_deg)
    if grab_pivot is None:
        return False

    # XZ plane: world +X is grid horizontal (i), +Z is grid vertical (j).
    plane_axes      = (Vector((1, 0, 0)), Vector((0, 0, 1)))
    shot_path, json_path = _grab_paths(label)

    _, region, rv3d = get_viewport()
    render_viewport(shot_path)

    payload = grab_grid(grab_pivot, plane_axes, region, rv3d, shot_path,
                        n_dots=n_dots, px_step=px_step)
    if payload is None:
        return False
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(GRABGRID_OVERLAY, "--json", json_path)
    return True


def apply_grab(label, grab_row, grab_col, prepare_action=None):
    """Translate the currently-selected face's verts to image (grab_row, grab_col)
    on the grab grid that `prepare_segment(label, ...)` last wrote.

    prepare_action defaults to the immediately preceding action; pass it
    explicitly if some other arrangement is in play.
    """
    if prepare_action is None:
        prepare_action = _rt._ACTION - 1

    json_path = _grab_json_path_for(label, prepare_action)
    with open(json_path) as f:
        payload = json.load(f)

    # Pick by IMAGE position — view-agnostic (gotchas §14).
    n_dots      = payload["n_dots"]
    dots        = payload["grid_points"]
    sorted_by_y = sorted(dots, key=lambda p: p["screen"]["y"])
    grid_rows   = []
    for r in range(n_dots):
        row_dots = sorted_by_y[r * n_dots:(r + 1) * n_dots]
        row_dots.sort(key=lambda p: p["screen"]["x"])
        grid_rows.append(row_dots)
    if not (0 <= grab_row < n_dots and 0 <= grab_col < n_dots):
        return False
    target_pt = grid_rows[grab_row][grab_col]
    dh, dv    = target_pt["world_offset"]

    bpy.context.scene.tool_settings.transform_pivot_point = 'MEDIAN_POINT'
    bpy.ops.transform.translate(value=(dh, 0.0, dv), orient_type='GLOBAL')
    bpy.ops.mesh.select_mode(type='FACE')
    return True


def extrude_rotate(label, extrude_t, rotate_deg):
    """Extrude + rotate, no grab. For segments where the rotation alone
    lands the tip where you want (typically the handle's final segment).
    """
    return _extrude_then_rotate(extrude_t, rotate_deg) is not None


def _chain_paths(label):
    """Per-chain PNG + JSON paths under the current action. Base screenshot
    has no '_chain' suffix of its own — the overlay script appends exactly
    one '_chain' to whatever base name it's given, so the final overlay
    file is '<label>_chain.png', not '<label>_chain_chain.png'.
    """
    return (
        f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}.png",
        f"{_step_dir()}/overlay_json/action_{_rt._ACTION:02d}_{label}_chain.json",
    )


def chain_preview(label="chain", history_points=None):
    """Render the currently-selected face's centre as a red dot on a
    normalized (0-1, top-left origin) coordinate grid overlay.

    Read the saved `_chain.png`, then call `apply_chain(points, label)`
    with a list of (x_norm, y_norm) points off the SAME grid to extrude a
    whole chain of segments in one action.

    `history_points` (optional): list of (x_norm, y_norm) already applied
    by a previous `apply_chain()` call, if you want them marked (blue) on
    a fresh preview mid-chain — purely cosmetic, does not affect geometry.

    Returns the payload dict, or None if no face is selected / the face
    doesn't project onto screen.
    """
    obj = bpy.context.active_object
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    face = next((f for f in bm.faces if f.select), None)
    if face is None:
        return None
    mw = obj.matrix_world
    world_center = mw @ face.calc_center_median()

    shot_path, json_path = _chain_paths(label)
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()

    proj = proj_fn(region, rv3d)
    px_pt = proj(world_center)
    if px_pt is None:
        return None

    payload = {
        "image": shot_path,
        "viewport_width": region.width,
        "viewport_height": region.height,
        "current_point": {
            "x_norm": round(px_pt["x"] / region.width, 4),
            "y_norm": round(px_pt["y"] / region.height, 4),
        },
        "history_points": [
            {"x_norm": round(x, 4), "y_norm": round(y, 4)}
            for x, y in (history_points or [])
        ],
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(CHAIN_OVERLAY, "--json", json_path)
    return payload


def _chain_plan_paths(label):
    """Base screenshot + JSON + final overlay PNG paths. The overlay path
    is passed explicitly via --output (rather than relying on the overlay
    script's auto-suffix-the-base-name default) so the base screenshot
    name doesn't need any '_plan'-avoidance gymnastics.
    """
    base = f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}_planbase.png"
    return (
        base,
        f"{_step_dir()}/overlay_json/action_{_rt._ACTION:02d}_{label}_plan.json",
        f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}_plan.png",
    )


def points_plan_preview(world_points, label="points"):
    """READ-ONLY preview of arbitrary WORLD-SPACE 3D points (not a chain
    path off the selected face — any points, e.g. proposed vertex targets
    for a flat patch mesh like the wing) — projects each to screen and
    draws the same numbered-dot/connecting-line overlay chain_plan_preview
    uses, via the same overlay script. No geometry is touched.

    world_points: list of mathutils.Vector (or 3-tuples), world space.
                  The first is drawn as the "start" (yellow) dot purely
                  for the overlay's own styling — there's no geometric
                  significance to which point is first here, unlike a
                  real chain.

    Returns the payload dict (with "planned_points" in image-normalized
    coords), or None if the viewport/any point fails to project.
    """
    _, region, rv3d = get_viewport()
    if region is None or not world_points:
        return None
    proj = proj_fn(region, rv3d)

    shot_path, json_path, overlay_path = _chain_plan_paths(label)
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()

    screen_pts = []
    for w in world_points:
        s = proj(Vector(w))
        if s is None:
            return None
        screen_pts.append({
            "x_norm": round(s["x"] / region.width, 4),
            "y_norm": round(s["y"] / region.height, 4),
        })

    payload = {
        "image": shot_path,
        "viewport_width": region.width,
        "viewport_height": region.height,
        "current_point": screen_pts[0],
        "planned_points": screen_pts[1:],
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(CHAIN_PLAN_OVERLAY, "--json", json_path, "--output", overlay_path)
    return payload


def quad_plan_preview(corners, label="quad"):
    """READ-ONLY preview of a set of vertex moves — each corner drawn in
    its OWN color, as a hollow circle at its CURRENT position connected
    by a line to a filled circle at its TARGET position (so it reads as
    "this vertex moves to there"), plus the targets connected to each
    other as a closed outline in the given order. No geometry is touched.

    corners: list of dicts, each:
        {"label": str, "color": (r,g,b) 0-255,
         "current": Vector|None (world; None if nothing to show yet),
         "target":  Vector (world)}

    Returns the payload dict, or None if the viewport/any point fails to
    project.
    """
    _, region, rv3d = get_viewport()
    if region is None or not corners:
        return None
    proj = proj_fn(region, rv3d)

    shot_path, json_path, overlay_path = _chain_plan_paths(label)
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()

    def to_norm(world_pt):
        s = proj(Vector(world_pt))
        if s is None:
            return None
        return {"x_norm": round(s["x"] / region.width, 4),
                "y_norm": round(s["y"] / region.height, 4)}

    out_corners = []
    for c in corners:
        target_n = to_norm(c["target"])
        if target_n is None:
            return None
        current_n = to_norm(c["current"]) if c.get("current") is not None else None
        out_corners.append({
            "label": c["label"],
            "color": list(c["color"]),
            "current": current_n,
            "target": target_n,
        })

    payload = {
        "image": shot_path,
        "viewport_width": region.width,
        "viewport_height": region.height,
        "corners": out_corners,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(QUAD_PLAN_OVERLAY, "--json", json_path, "--output", overlay_path)
    return payload


def chain_plan_preview(points, label="chain", scales=None):
    """READ-ONLY preview of the whole candidate chain, drawn directly on
    the current viewport render as numbered dots + connecting lines — no
    geometry is touched. Computes the exact same step-by-step unprojection
    apply_chain() would (each point's depth-reference is the PREVIOUS
    point in the chain, starting from the current selected face's centre),
    so what you see here is exactly what apply_chain(points) would build.

    Re-run with adjusted points as many times as needed — this never
    modifies the mesh — then call apply_chain() once you're happy.

    Pass the same `scales` you intend to give apply_chain and each point is
    drawn with the RING it will produce, not just its centre. Worth doing
    whenever thickness varies: a chain of points alone says where the tube
    goes and nothing about how fat it is, and on anything with a neck that
    is the half you actually need to see.

    Returns the payload dict (with "planned_points" in image-normalized
    coords, same convention as the input), or None if no face is selected
    or a point fails to project.
    """
    obj = bpy.context.active_object
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    face = next((f for f in bm.faces if f.select), None)
    if face is None:
        return None
    mw = obj.matrix_world
    start = mw @ face.calc_center_median()

    shot_path, json_path, overlay_path = _chain_plan_paths(label)
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()
    if region is None:
        return None

    proj = proj_fn(region, rv3d)

    # Walk the SAME step logic apply_chain() uses, purely in Python — no
    # bpy.ops, no mesh edits — depth-reference for each unprojection is
    # the PREVIOUS point in the chain (or the starting face for point 1).
    world_pts = [start]
    current = start
    for x_norm, y_norm in points:
        px = x_norm * region.width
        py = (1.0 - y_norm) * region.height
        target = view3d_utils.region_2d_to_location_3d(
            region, rv3d, Vector((px, py)), current
        )
        if target is None:
            return None
        world_pts.append(target)
        current = target

    # Ring radius at every point: the seed face's own radius, then each
    # scale factor chained onto it — exactly what apply_chain will do.
    r0 = face_radius_world(face, mw)
    radii = [r0]
    acc = r0
    for i in range(len(points)):
        f = None if scales is None else scales[i]
        acc *= 1.0 if f in (None,) else float(f)
        radii.append(acc)

    # One world metre as a FRACTION OF THE FRAME's width, measured along the
    # view's own right vector.
    #
    # Not pixels. The overlay draws on render_viewport's output, which is a
    # different size from the live region — 1432 px wide against the region's
    # 798 — so a radius measured in region pixels comes out 44% too small once
    # the overlay treats it as render pixels. Everything else in this preview
    # is already normalized for exactly that reason; the radius has to be too.
    right = (rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))).normalized()
    o = proj(world_pts[0])
    o1 = proj(world_pts[0] + right)
    per_m = abs(o1["x"] - o["x"]) / float(region.width) if (o and o1) else 0.0

    screen_pts = []
    for w, rad in zip(world_pts, radii):
        sp = proj(w)
        if sp is None:
            return None
        screen_pts.append({
            "x_norm": round(sp["x"] / region.width, 4),
            "y_norm": round(sp["y"] / region.height, 4),
            "radius_norm": round(rad * per_m, 5),
            "radius_mm": round(rad * 1000.0, 1),
        })

    payload = {
        "image": shot_path,
        "viewport_width": region.width,
        "viewport_height": region.height,
        "current_point": screen_pts[0],
        "planned_points": screen_pts[1:],
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(CHAIN_PLAN_OVERLAY, "--json", json_path, "--output", overlay_path)
    return payload


def _chain_profile_paths(label):
    base = (f"{_step_dir()}/screenshots/"
            f"action_{_rt._ACTION:02d}_{label}_profbase.png")
    return (
        base,
        f"{_step_dir()}/overlay_json/action_{_rt._ACTION:02d}_{label}_prof.json",
        f"{_step_dir()}/screenshots/action_{_rt._ACTION:02d}_{label}_profile.png",
    )


def chain_profile_preview(points, label="chain", scales=None):
    """READ-ONLY. The chain drawn as a SILHOUETTE: each station as a
    cross-section tick, plus the rails joining their ends.

    The companion to chain_plan_preview, and it answers a different
    question. The plan preview draws a circle at each station and says how
    THICK the tube is there. This one draws the same radius as a bar laid
    across the path and joins consecutive bars up, so what you see is the
    OUTLINE the finished tube will have from this view — whether the neck
    flows into the breast or steps into it, whether the taper to the tail
    is straight or bellied. Two previews because a duck can have every ring
    the right size and still have the wrong profile between them.

    Same overlay the bat's body_profile_preview uses, so the two read
    identically: cyan ticks, orange rails, yellow centres.

    The tick is perpendicular to the path IN SCREEN SPACE, which is what
    makes it an honest edge-on view of the ring: a tick drawn along a fixed
    world axis would foreshorten to nothing wherever the chain turned to
    face it, exactly at the joints worth looking at.
    """
    obj = bpy.context.active_object
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    face = next((f for f in bm.faces if f.select), None)
    if face is None:
        return None
    mw = obj.matrix_world
    start = mw @ face.calc_center_median()

    shot_path, json_path, overlay_path = _chain_profile_paths(label)
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()
    if region is None:
        return None
    proj = proj_fn(region, rv3d)

    world_pts = [start]
    cur = start
    for x_norm, y_norm in points:
        px = x_norm * region.width
        py = (1.0 - y_norm) * region.height
        tgt = view3d_utils.region_2d_to_location_3d(
            region, rv3d, Vector((px, py)), cur)
        if tgt is None:
            return None
        world_pts.append(tgt)
        cur = tgt

    r0 = face_radius_world(face, mw)
    radii, acc = [r0], r0
    for i in range(len(points)):
        f = None if scales is None else scales[i]
        acc *= 1.0 if f is None else float(f)
        radii.append(acc)

    right = (rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))).normalized()
    o, o1 = proj(world_pts[0]), proj(world_pts[0] + right)
    if o is None or o1 is None:
        return None
    ppm = abs(o1["x"] - o["x"])           # region pixels per metre

    screen = []
    for w in world_pts:
        s = proj(w)
        if s is None:
            return None
        screen.append((s["x"], s["y"]))

    rings = []
    n = len(screen)
    for i, ((cx, cy), rad) in enumerate(zip(screen, radii)):
        a = screen[max(0, i - 1)]
        b = screen[min(n - 1, i + 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        tl = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tl, tx / tl        # perpendicular, screen space
        half = rad * ppm

        def pt(x, y):
            return {"x_norm": round(x / region.width, 4),
                    "y_norm": round(y / region.height, 4)}

        rings.append({
            "label": "s%d" % i,
            "center": pt(cx, cy),
            "left": pt(cx - nx * half, cy - ny * half),
            "right": pt(cx + nx * half, cy + ny * half),
            "radius_mm": round(rad * 1000.0, 1),
        })

    payload = {"image": shot_path, "viewport_width": region.width,
               "viewport_height": region.height, "rings": rings}
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(BODY_PROFILE_OVERLAY, "--json", json_path,
                "--output", overlay_path)
    return payload


def _rotate_face_about_axis(face, mw, mw_inv, pivot, axis, angle):
    """Rotate `face`'s verts (written back to local coords) by `angle`
    (radians) around `axis` (world, need not be normalized), pivoting at
    world-space `pivot`. In-place; caller must bmesh.update_edit_mesh and
    re-fetch afterward (mode-toggle-free, but Blender still wants a flush).
    """
    axis = axis.normalized()
    rot_mat = Matrix.Rotation(angle, 4, axis)
    for v in face.verts:
        world_pos = mw @ v.co
        rotated_w = pivot + (rot_mat @ (world_pos - pivot))
        v.co = mw_inv @ rotated_w


def _scale_face_about_centroid(face, mw, mw_inv, factor):
    """Scale `face`'s verts uniformly about the face's own world centroid.

    The missing third verb. apply_chain could already move a cross-section
    and turn it; this lets it get thicker or thinner, which is what the
    difference between a neck and a belly is. Factors CHAIN — each one
    multiplies the ring that arrived, the same convention
    apply_body_profile's `scale` uses — so a run of 1.0s holds a constant
    thickness and you only ever state a change.
    """
    if factor is None or abs(factor - 1.0) < 1e-9:
        return False
    pivot = mw @ face.calc_center_median()
    for v in face.verts:
        world_pos = mw @ v.co
        v.co = mw_inv @ (pivot + (world_pos - pivot) * factor)
    return True


def face_radius_world(face, mw):
    """Mean distance from a face's centroid to its verts, in world units —
    the radius of the ring, for previews that want to draw it."""
    pivot = mw @ face.calc_center_median()
    if not face.verts:
        return 0.0
    return sum(((mw @ v.co) - pivot).length for v in face.verts) / len(face.verts)


def _align_face_to_direction(face, mw, mw_inv, direction):
    """Rotate `face` (minimal rotation, around its own centroid) so its
    world-space normal points along `direction` (world Vector, any
    length). This is what makes a chained extrude's cross-section face
    the way it's actually travelling instead of staying stuck at its
    original orientation — without it, a direction change at any segment
    reads as a sheared/kinked joint instead of a smooth turn.
    """
    face.normal_update()
    current_n = (mw.to_3x3() @ face.normal).normalized()
    target_n  = direction.normalized()
    dot   = max(-1.0, min(1.0, current_n.dot(target_n)))
    angle = math.acos(dot)
    if angle < 1e-6:
        return False
    axis = current_n.cross(target_n)
    if axis.length < 1e-9:
        axis = current_n.orthogonal()   # 180 deg case — any perpendicular axis works
    pivot = mw @ face.calc_center_median()
    _rotate_face_about_axis(face, mw, mw_inv, pivot, axis, angle)
    return True


def align_seed_face(points, label="align"):
    """Pre-rotate the currently selected face (around its own centroid) so
    its normal already points toward `points[0]` — call this ONCE, right
    before `apply_chain(points, ...)`, ONLY on a genuinely fresh seed face
    that has no adjacent extruded geometry yet (e.g. a just-separated
    coincident duplicate face for a new independent limb/branch — see
    apply_chain's docstring and the finger2/3/4 seed-separate pattern).
    Do NOT call this when continuing an already-extruded chain (e.g.
    finger1's continuation off BatArm's own tip face) — there the face is
    already connected to prior rings, and rotating it in place would warp
    THAT existing geometry instead of fixing anything.

    Why this is needed: a coincident-duplicate seed face inherits its
    PARENT's own surface normal (e.g. BatArm's wrist cap points along the
    arm's own travel direction), which is usually very different from the
    new branch's actual first-segment direction. apply_chain's auto_face
    only ever rotates the FAR (newly extruded) ring, leaving the seed's
    ring fixed — so if the seed's inherited orientation is far from the
    branch's real direction, that first segment's connecting quads have
    to swing through a huge angle on one side only, producing badly
    non-planar ("twisted") side faces. Pre-aligning the lone seed face
    (safe here — it has no neighbours yet to distort) removes nearly all
    of that swing before any extrusion happens.

    Does not affect chain_plan_preview()'s path (rotating a face about its
    own centroid doesn't move that centroid), so plan previews taken
    before this call stay accurate.
    """
    obj = bpy.context.active_object
    _, region, rv3d = get_viewport()
    if region is None or not points:
        return False
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    face = next((f for f in bm.faces if f.select), None)
    if face is None:
        return False
    mw = obj.matrix_world
    start = mw @ face.calc_center_median()

    x_norm, y_norm = points[0]
    px = x_norm * region.width
    py = (1.0 - y_norm) * region.height
    target = view3d_utils.region_2d_to_location_3d(region, rv3d, Vector((px, py)), start)
    if target is None:
        return False
    direction = target - start
    if direction.length < 1e-9:
        return False

    mw_inv = mw.inverted()
    if _align_face_to_direction(face, mw, mw_inv, direction):
        bmesh.update_edit_mesh(obj.data)
    return True


def apply_chain(points, label="chain", auto_face=True, face_mode="average",
                rotations=None, scales=None):
    """Extrude the currently-selected face through a chain of normalized
    (x_norm, y_norm) points — the same 0-1, top-left-origin grid drawn by
    `chain_preview()` / `chain_plan_preview()`.

    The whole target path is unprojected up front (same step-by-step logic
    `chain_plan_preview()` uses), so each segment's rotation can see BOTH
    its incoming edge (the segment that just got extruded) and its
    outgoing edge (the segment about to be extruded next) — not just the
    incoming one. Then for each point in order:

      1. Extrude the current face, translating it from its current
         centroid to that point's precomputed target (straight line).
      2. (auto_face, default True) Rotate the new face — around its own
         centroid, minimal rotation — to face `face_mode`'s direction (see
         below). This is what keeps the tube's cross-section smooth
         through turns instead of staying fixed at whatever orientation
         it had (which reads as a sheared, kinked joint at every direction
         change) — default on because it's rarely NOT what you want for
         an arc/loop.

    Each step's target becomes the next step's starting point, so N points
    produce N new chained segments in a single action. Leaves the face
    selected at the FINAL point.

    Args:
        points:     list of (x_norm, y_norm).
        auto_face:  default True — auto-orient each segment's face per
                    `face_mode`. Set False for the old translate-only
                    behaviour (fixed cross-section orientation throughout).
        face_mode:  "previous" | "next" | "average" (default "average").
                    Which edge direction(s) auto_face uses at each point:
                      "previous" — the incoming edge (the segment that was
                        just extruded to reach this point).
                      "next"     — the outgoing edge (the segment about to
                        be extruded next).
                      "average"  — bisector of incoming + outgoing edge
                        directions. This is the standard technique for a
                        smooth polyline tube: the cross-section at a joint
                        is shared evenly between both adjacent segments
                        instead of snapping hard to just one of them.
                    The LAST point has no outgoing edge, so all three modes
                    fall back to the incoming direction there. If the
                    incoming and outgoing directions are exactly opposite
                    (an 180° reversal — the bisector is undefined), falls
                    back to the incoming direction too.
        scales:     optional list, same length as `points`. Each entry is
                    either None/1.0 (leave the ring's thickness alone) or a
                    factor applied to the new ring about its own centroid
                    AFTER the extrude and any rotation. Factors CHAIN, the
                    same convention as apply_body_profile: 1.0 holds, 0.8
                    is a fifth thinner than the ring before it, and a run
                    of 1.0s keeps a constant tube. Without this a chain can
                    only ever be a constant-thickness pipe, which is fine
                    for a finger and useless for anything that has a neck
                    and a belly.
        rotations:  optional list, same length as `points`. Each entry is
                    either None (segment just uses the auto_face/face_mode
                    default) or a degrees value — an EXTRA rotation applied
                    around the segment's local horizontal axis (world_Z ×
                    its normal, same convention as `prepare_segment`) on
                    top of whatever auto_face already did, for arbitrary
                    manual tweaks (twisting the cross-section, overriding
                    a turn the default gets wrong, etc). Works even with
                    auto_face=False.

    Returns True if every point applied; False (and stops) on the first
    failure (e.g. selection lost, point doesn't project).
    """
    obj = bpy.context.active_object
    _, region, rv3d = get_viewport()
    if region is None:
        return False

    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    face = next((f for f in bm.faces if f.select), None)
    if face is None:
        return False
    mw = obj.matrix_world
    start = mw @ face.calc_center_median()

    # Precompute the WHOLE path up front (same logic chain_plan_preview()
    # uses) so rotation can look at the outgoing edge too, not just the
    # incoming one — world_pts[0] is the starting face's centroid,
    # world_pts[k+1] is the target for points[k].
    world_pts = [start]
    cur = start
    for x_norm, y_norm in points:
        px = x_norm * region.width
        py = (1.0 - y_norm) * region.height   # flip to Blender y-up coords
        tgt = view3d_utils.region_2d_to_location_3d(region, rv3d, Vector((px, py)), cur)
        if tgt is None:
            return False
        world_pts.append(tgt)
        cur = tgt

    n = len(points)
    if rotations is None:
        rotations = [None] * n
    if scales is None:
        scales = [None] * n

    for i in range(n):
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        face = next((f for f in bm.faces if f.select), None)
        if face is None:
            return False
        mw = obj.matrix_world

        translation = world_pts[i + 1] - world_pts[i]

        if bpy.context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.extrude_region_move(
            TRANSFORM_OT_translate={"value": tuple(translation), "orient_type": "GLOBAL"}
        )

        extra_deg = rotations[i]
        scale_f = scales[i]
        if auto_face or extra_deg or (scale_f not in (None, 1.0)):
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            bm.normal_update()
            new_face = next((f for f in bm.faces if f.select), None)
            if new_face is None:
                return False
            mw     = obj.matrix_world
            mw_inv = mw.inverted()

            if auto_face:
                incoming = world_pts[i + 1] - world_pts[i]
                outgoing = world_pts[i + 2] - world_pts[i + 1] if (i + 2) <= n else None

                if outgoing is None or face_mode == "previous":
                    direction = incoming
                elif face_mode == "next":
                    direction = outgoing
                else:   # "average" (default) — bisector of both edges
                    inc_n = incoming.normalized()
                    out_n = outgoing.normalized()
                    direction = inc_n + out_n
                    if direction.length < 1e-9:
                        direction = incoming   # exact 180° reversal — bisector undefined

                if direction.length > 1e-9:
                    if _align_face_to_direction(new_face, mw, mw_inv, direction):
                        bmesh.update_edit_mesh(obj.data)
                        bm = bmesh.from_edit_mesh(obj.data)
                        bm.faces.ensure_lookup_table()
                        bm.normal_update()
                        new_face = next((f for f in bm.faces if f.select), None)
                        if new_face is None:
                            return False
                        mw = obj.matrix_world
                        mw_inv = mw.inverted()

            if extra_deg:
                new_face.normal_update()
                face_n   = (mw.to_3x3() @ new_face.normal).normalized()
                rot_axis = Vector((0, 0, 1)).cross(face_n)
                if rot_axis.length < 1e-9:
                    rot_axis = Vector((1, 0, 0))
                pivot = mw @ new_face.calc_center_median()
                _rotate_face_about_axis(new_face, mw, mw_inv, pivot,
                                        rot_axis, math.radians(extra_deg))
                bmesh.update_edit_mesh(obj.data)
                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                new_face = next((f for f in bm.faces if f.select), None)
                if new_face is None:
                    return False
                mw     = obj.matrix_world
                mw_inv = mw.inverted()

            # Scale LAST. Rotating a ring turns it about its centroid and
            # scaling moves its verts towards that same centroid, so the
            # order does not change the result — but doing it last means
            # the scale acts on the ring in its final orientation, which is
            # the one the preview drew.
            if _scale_face_about_centroid(new_face, mw, mw_inv, scale_f):
                bmesh.update_edit_mesh(obj.data)

    return True


def apply_body_profile(steps, direction=1, label="profile", pre_scale=1.0):
    """Apply a chained extrude+scale-along-local-Z profile — the same
    `steps`/`pre_scale` `perceive.body_profile_preview(steps, direction,
    pre_scale)` showed. Mutates the mesh for real. Requires the current
    end-cap FACE to already be selected (edit mode, face select), same as
    the preview.

    steps      list of (dist, scale) pairs — see body_profile_preview.
    direction  +1 or -1 — which way along local Z to extrude (must match
               whatever was previewed).
    pre_scale  scale factor applied to the SELECTED face itself, in
               place, before any extrusion — no new geometry, just
               resizes the existing ring. Default 1.0 = no-op.

    Leaves the newest face selected, ready for the next chain call (e.g.
    the mouth extrusion after the head chain finishes).
    """
    if bpy.context.mode != 'EDIT_MESH':
        bpy.ops.object.mode_set(mode='EDIT')
    if pre_scale != 1.0:
        bpy.context.scene.tool_settings.transform_pivot_point = 'MEDIAN_POINT'
        bpy.ops.transform.resize(
            value=(pre_scale, pre_scale, 1.0), constraint_axis=(True, True, False),
            orient_type='LOCAL',
        )

    for dist, scale in steps:
        if bpy.context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.extrude_region_move(
            TRANSFORM_OT_translate={"value": (0, 0, direction * dist), "orient_type": "LOCAL"}
        )
        bpy.context.scene.tool_settings.transform_pivot_point = 'MEDIAN_POINT'
        bpy.ops.transform.resize(
            value=(scale, scale, 1.0), constraint_axis=(True, True, False),
            orient_type='LOCAL',
        )
    return True
