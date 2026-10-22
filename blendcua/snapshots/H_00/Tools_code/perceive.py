"""
Perception helpers — render an overlay for the agent to read next turn.

Each function:
  1. screenshots the current viewport,
  2. builds the ruler/map JSON from the current selection + view,
  3. writes JSON to mem/<run>/overlay_json/step_NN_<kind>.json,
  4. invokes the matching overlay subprocess to draw the labelled image.

Returns the parsed payload so the step can pick a tick by ordinal and
apply an op in the same step. The agent reads the overlay PNG in the next
turn and edits the step's ordinal/factor if it overshot.

These are extractions of the perceive-overlay patterns that recur across
every overlay-using step in `Tool_scripts/scripts/build_cup.py`. See
BLENDCUA_AGENT.md §10.
"""

import bmesh
import bpy
import json
import os

from mathutils import Vector

from lib.mesh  import centroid
from lib.ruler import screen_ruler, world_ruler, scale_ruler, grab_grid, trackball_grid, rotate_ruler
from lib.util  import run_overlay
from lib.view  import get_viewport, render_viewport

import runtime as _rt

OVERLAYS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlays")

EXTRUDE_OVERLAY   = f"{OVERLAYS}/extrude_map_overlay.py"
SCALE_OVERLAY     = f"{OVERLAYS}/scale_map_overlay.py"
LOOPCUT_OVERLAY   = f"{OVERLAYS}/loopcut_map_overlay.py"
INSET_OVERLAY     = f"{OVERLAYS}/inset_map_overlay.py"
GRID_OVERLAY      = f"{OVERLAYS}/grid_map.py"
DRAG_OVERLAY      = f"{OVERLAYS}/viewport_drag_overlay.py"
FACE_MAP_OVERLAY  = f"{OVERLAYS}/face_map_overlay.py"
EDGE_MAP_OVERLAY  = f"{OVERLAYS}/edge_map.py"
GRAB_OVERLAY      = f"{OVERLAYS}/grab_grid_overlay.py"
TRACKBALL_OVERLAY = f"{OVERLAYS}/grab_grid_overlay.py"
ROTATE_OVERLAY    = f"{OVERLAYS}/rotate_map_overlay.py"
BODY_PROFILE_OVERLAY = f"{OVERLAYS}/body_profile_overlay.py"
SILHOUETTE_OVERLAY   = f"{OVERLAYS}/silhouette_overlay.py"
REF_OUTLINE_OVERLAY  = f"{OVERLAYS}/reference_outline_overlay.py"


def _paths(kind):
    """Return (screenshot_path, json_path) for the current action + overlay kind."""
    step     = _rt._STEP
    action   = _rt._ACTION
    step_dir = f"{_rt._RUN}/steps/step_{step:03d}"
    return (
        f"{step_dir}/screenshots/action_{action:02d}.png",
        f"{step_dir}/overlay_json/action_{action:02d}_{kind}.json",
    )


def _selected_centroid_world(obj):
    """World-space centroid of currently selected verts."""
    mw = obj.matrix_world
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    sel = [mw @ v.co for v in bm.verts if v.select]
    return centroid(sel), sel, mw


def extrude_ruler(axis=(0, 0, 1), kind='screen', step=40, k_range=None):
    """Render the extrude ruler overlay along `axis` from selected verts.

    axis      world-space direction the extrude will go (unit vector).
    kind      'screen' = ticks at `step` pixels apart;
              'world'  = ticks at `step` metres apart.
    step      px (screen) or metres (world).
    k_range   optional list of tick indices (overrides default -6..-1, 1..6).

    Returns the JSON dict (so you can `pick(data, "e2")` and use t).
    """
    obj = bpy.context.active_object
    pivot, _, _ = _selected_centroid_world(obj)

    shot_path, json_path = _paths("extrude")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()

    axis_v = Vector(axis)
    if kind == 'screen':
        data = screen_ruler(pivot, axis_v, region, rv3d, shot_path,
                            px_step=step, k_range=k_range)
    else:
        data = world_ruler(pivot, axis_v, region, rv3d, shot_path,
                           world_step=step, k_range=k_range)

    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    run_overlay(EXTRUDE_OVERLAY, "--json", json_path)
    return data


def body_profile_preview(steps, direction=1, label="profile", pre_scale=1.0):
    """READ-ONLY preview of a chained extrude+scale-along-local-Z profile,
    for building a tapered body (bat torso, etc.) from a seed cylinder.

    Requires the current end-cap FACE to be selected (edit mode, face
    select). Draws each candidate ring as a perpendicular tick (length =
    that ring's radius, direction = the object's local X axis) plus rails
    connecting consecutive rings, straight onto the current viewport
    render — so the whole candidate taper is visible against whatever
    reference image is in the same view, no geometry touched.

    steps      list of (dist, scale) pairs. dist = local-Z distance for
               that segment (always positive — `direction` sets the sign).
               scale = XY factor applied to the CURRENT ring radius,
               chained multiplicatively (e.g. 0.9 shrinks 10% from
               whatever the radius already is at that point in the chain).
    direction  +1 or -1 — which way along local Z to extrude.
    pre_scale  scale factor applied to ring s0 ITSELF — i.e. the selected
               face is (previewed as) scaled in place before any
               extrusion. Use this when the seed's own cross-section
               needs to taper right from its root instead of staying a
               uniform cylinder up to the first extrusion (e.g. the seed
               cap is wider than the body actually is at that point).
               Default 1.0 = no change to s0.

    Returns the payload dict (rings, in image-normalized screen coords),
    or None if no face is selected or a ring fails to project. Re-run with
    adjusted steps as many times as needed, then call
    handle.apply_body_profile(steps, direction, pre_scale) once happy —
    same "preview -> agent reads it -> apply" shape as chain_plan_preview /
    apply_chain.
    """
    from lib.view import proj_fn

    obj = bpy.context.active_object
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    face = next((f for f in bm.faces if f.select), None)
    if face is None:
        return None

    mw = obj.matrix_world
    center0 = face.calc_center_median()   # local space
    radius0 = sum((v.co - center0).length for v in face.verts) / len(face.verts)
    perp = Vector((1.0, 0.0, 0.0))        # local perpendicular, for visualization only

    shot_path, json_path = _paths("bodyprofile")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()
    if region is None:
        return None
    proj = proj_fn(region, rv3d)

    def ring_payload(lbl, z, radius):
        c_local = center0 + Vector((0.0, 0.0, z))
        l_local = c_local - perp * radius
        r_local = c_local + perp * radius
        out = {"label": lbl}
        for key, lp in (("center", c_local), ("left", l_local), ("right", r_local)):
            s = proj(mw @ lp)
            if s is None:
                return None
            out[key] = {"x_norm": round(s["x"] / region.width, 4),
                        "y_norm": round(s["y"] / region.height, 4)}
        return out

    rings = [ring_payload("s0", 0.0, radius0 * pre_scale)]
    if rings[0] is None:
        return None
    z_cum, r_cum = 0.0, radius0 * pre_scale
    for i, (dist, scale) in enumerate(steps, start=1):
        z_cum += direction * dist
        r_cum *= scale
        rp = ring_payload(f"s{i}", z_cum, r_cum)
        if rp is None:
            return None
        rings.append(rp)

    payload = {"image": shot_path, "viewport_width": region.width,
               "viewport_height": region.height, "rings": rings}
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(BODY_PROFILE_OVERLAY, "--json", json_path)
    return payload


def scale_overlay(axis_mask, factors):
    """Render the scale ruler overlay for currently selected verts.

    axis_mask  (1,1,0) = radial XY, (0,0,1) = Z-only, etc.
    factors    list of scale factors to label (e.g. [0.5, 0.8, 1.2, 1.5]).

    Returns the JSON dict.
    """
    from lib.view import proj_fn
    from mathutils import Vector

    obj = bpy.context.active_object
    pivot, sel_w, _ = _selected_centroid_world(obj)

    shot_path, json_path = _paths("scale")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()

    # Pick the spoke whose ON-SCREEN distance from pivot is largest, not
    # the one with the largest world-space delta. For radial XY scaling in
    # an axis-aligned ortho view (e.g. RIGHT ortho), all rim verts have
    # equal world XY length but their screen projections vary — verts near
    # the camera's view axis (world +X in RIGHT view) collapse to the pivot
    # while verts perpendicular to it (world ±Y) project to the cup edge.
    # The on-screen spoke is what the user actually sees, so use that.
    mx, my, mz   = axis_mask
    proj         = proj_fn(region, rv3d)
    pivot_screen = proj(pivot)
    best_spoke   = Vector((0.0, 0.0, 0.0))
    best_d       = -1.0
    if pivot_screen is not None:
        for w in sel_w:
            d = w - pivot
            masked = Vector((d.x * mx, d.y * my, d.z * mz))
            sp = proj(pivot + masked)
            if sp is None:
                continue
            dist = ((sp["x"] - pivot_screen["x"]) ** 2 +
                    (sp["y"] - pivot_screen["y"]) ** 2) ** 0.5
            if dist > best_d:
                best_d     = dist
                best_spoke = masked
    spoke = best_spoke

    data = scale_ruler(pivot, spoke, axis_mask, region, rv3d, shot_path, factors)
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    run_overlay(SCALE_OVERLAY, "--json", json_path)
    return data


def loopcut_dirs(seed_loop_indices=(0, 1)):
    """Render the loopcut direction preview overlay for the selected face.

    For each loop index, walks the ring and emits a polyline. The overlay
    draws both candidate ring directions so the agent can pick dirA vs dirB.

    Returns (payload_dict, [ring_edges_per_dir]).
    """
    from lib.mesh  import walk_ring
    from lib.ruler import ring_midpoints_polyline

    obj = bpy.context.active_object
    mw  = obj.matrix_world
    bm  = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    face = next(f for f in bm.faces if f.select)

    shot_path, json_path = _paths("loopcut")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()

    directions, rings = [], []
    for i in seed_loop_indices:
        ring = walk_ring(face.loops[i].edge)
        polyline = ring_midpoints_polyline(mw, ring, region, rv3d)
        directions.append({"id": f"dir{'AB'[i]}",
                           "ring_len": len(ring),
                           "polyline": polyline})
        rings.append(ring)

    payload = {
        "viewport_width":  region.width,
        "viewport_height": region.height,
        "image":           shot_path,
        "directions":      directions,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(LOOPCUT_OVERLAY, "--json", json_path)
    return payload, rings


def inset_overlay(px_step=12):
    """Render the inset-thickness overlay for the currently selected face.

    Ticks march inward from the rightmost boundary edge of the selection at
    `px_step` pixels apart, capped at half the minimum distance to any
    opposite boundary edge.

    Returns the JSON dict (ticks live at `data["ticks"]` with key `thickness`).
    """
    from bpy_extras import view3d_utils
    from lib.view   import proj_fn

    obj = bpy.context.active_object
    mw  = obj.matrix_world
    bm  = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    seen, sel_w = set(), []
    for f in bm.faces:
        if not f.select:
            continue
        for v in f.verts:
            if v.index not in seen:
                seen.add(v.index)
                sel_w.append(mw @ v.co)
    inset_center = centroid(sel_w)

    boundary = [e for e in bm.edges
                if sum(1 for f in e.link_faces if f.select) == 1]

    def _edge_dist(pt, e):
        a = mw @ e.verts[0].co
        b = mw @ e.verts[1].co
        ab = b - a
        if ab.length < 1e-9:
            return (pt - a).length
        t = max(0.0, min(1.0, (pt - a).dot(ab) / ab.length_squared))
        return (pt - (a + ab * t)).length

    max_t = 0.5 * min(_edge_dist(inset_center, e) for e in boundary)

    best     = max(boundary, key=lambda e: (mw @ ((e.verts[0].co + e.verts[1].co) / 2)).x)
    edge_mid = mw @ ((best.verts[0].co + best.verts[1].co) / 2)
    edge_dir = (mw @ best.verts[1].co - mw @ best.verts[0].co).normalized()
    inward   = inset_center - edge_mid
    inward   = inward - inward.project(edge_dir)
    inward_h = inward.normalized()

    shot_path, json_path = _paths("inset")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()
    proj = proj_fn(region, rv3d)

    p0 = view3d_utils.location_3d_to_region_2d(region, rv3d, edge_mid)
    p1 = view3d_utils.location_3d_to_region_2d(region, rv3d, edge_mid + inward_h)
    px_per_unit = (p1 - p0).length if (p0 and p1) else 0.0

    ticks = []
    if px_per_unit > 1e-6:
        step_world = px_step / px_per_unit
        k = 1
        while step_world * k <= max_t:
            t = step_world * k
            sp = proj(edge_mid + inward_h * t)
            if sp:
                ticks.append({"ordinal": f"t{k}", "thickness": round(t, 4), "screen": sp})
            k += 1

    payload = {
        "viewport_width":  region.width,
        "viewport_height": region.height,
        "image":           shot_path,
        "start_screen":    proj(edge_mid),
        "center_screen":   proj(inset_center),
        "max_thickness":   round(max_t, 4),
        "px_per_unit":     round(px_per_unit, 3),
        "use_individual":  False,
        "ticks":           ticks,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(INSET_OVERLAY, "--json", json_path)
    return payload


def face_map(tl_norm=(0.2, 0.15), br_norm=(0.75, 0.85)):
    """Label the center of every visible face whose projected center falls inside the region.

    Projects each face center of the active mesh to screen space, filters to
    those inside the normalised bounding box, and calls face_map_overlay.py to
    draw yellow dots + red "F1", "F2", ... labels on the screenshot.

    Returns the parsed JSON payload so the agent can look up face_idx by label.
    """
    from lib.view import proj_fn

    obj = bpy.context.active_object
    mw  = obj.matrix_world
    bm  = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    shot_path, json_path = _paths("facemap")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()
    proj = proj_fn(region, rv3d)

    # Bounding box in viewport pixel coords (y-down).
    x1 = tl_norm[0] * region.width;  y1 = tl_norm[1] * region.height
    x2 = br_norm[0] * region.width;  y2 = br_norm[1] * region.height

    faces_data = {}
    label_n = 1
    for f in bm.faces:
        sp = proj(mw @ f.calc_center_median())
        if sp is None:
            continue
        px, py = sp["x"], sp["y"]
        if x1 <= px <= x2 and y1 <= py <= y2:
            faces_data[f"F{label_n}"] = {
                "face_idx": f.index,
                "center":   {"x": px, "y": py},
            }
            label_n += 1

    payload = {
        "image":           shot_path,
        "viewport_width":  region.width,
        "viewport_height": region.height,
        "region_tl":       list(tl_norm),
        "region_br":       list(br_norm),
        "faces":           faces_data,
    }
    with open(json_path, "w") as f_:
        json.dump(payload, f_, indent=2)
    run_overlay(FACE_MAP_OVERLAY, "--json", json_path)
    return payload


def face_at_label(label, prior_action=None):
    """Return the face_idx for a label (e.g. "F3") from a previous face_map() call.

    prior_action defaults to the action immediately before the current one.
    """
    if prior_action is None:
        prior_action = _rt._ACTION - 1
    step_dir  = f"{_rt._RUN}/steps/step_{_rt._STEP:03d}"
    json_path = f"{step_dir}/overlay_json/action_{prior_action:02d}_facemap.json"
    with open(json_path) as f_:
        data = json.load(f_)
    return data["faces"][label]["face_idx"]


def edge_map(tl_norm=(0.0, 0.0), br_norm=(1.0, 1.0), max_edges=60, visible_only=True):
    """Label every mesh edge whose projected MIDPOINT falls inside the
    region (and is actually within the render frame) with a red line +
    "E_N" tag, drawn straight onto a fresh render of the CURRENT view by
    edge_map.py. This is the ground truth for "where is this specific
    edge on screen" — read coordinates off the returned payload (or the
    saved *_emap.png overlay) instead of computing/guessing a point's
    projection independently, which is easy to get backwards (e.g. a
    front/back Y-sign mixup) with no visual feedback until it's already
    baked wrong.

    tl_norm, br_norm  normalized (0-1, top-left origin) screen region —
                      narrow this to cut clutter on a dense mesh (e.g.
                      just the area around a seam you're hunting for).
    max_edges         safety cap — raise the region tighter instead of
                      raising this if you hit it on a dense mesh.
    visible_only      default True — drop edges hidden from the CURRENT
                      view. For a PERSPECTIVE view (the normal case —
                      every gravestone/cup action sets rv3d.view_
                      perspective='PERSP') this is a REAL raycast
                      occlusion test: cast a ray from the camera to each
                      edge's midpoint via a BVHTree built from this same
                      mesh, and drop the edge if something else on the
                      mesh sits in front of that point. This is what
                      actually answers "can the camera see this edge" —
                      a plain backface/normal test is NOT enough: an edge
                      bounding a face that tests "front-facing" by its
                      normal (e.g. the gravestone base's near-horizontal
                      top face) can still be physically hidden behind
                      OTHER geometry from this angle (true self-
                      occlusion), and silently slipped through an
                      earlier version of this function that only checked
                      linked-face normals. For an ORTHOGRAPHIC view
                      (no single finite camera point to raycast from)
                      this falls back to that same normal-only
                      approximation, with the same limitation. Set False
                      to see every edge regardless (e.g. to sanity-check
                      the mesh itself).

    Returns the parsed JSON payload: payload["edges"]["E_3"] etc, each
    with "v0"/"v1"/"mid" in VIEWPORT PIXEL coords (image-down, same
    convention as lib.view.proj_fn). Use edge_at_label() next action to
    resolve a label to exact (v0, v1) world-independent pixel endpoints,
    or normalize yourself via payload["viewport_width"/"height"].
    """
    from lib.view import proj_fn
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    obj = bpy.context.active_object
    mw = obj.matrix_world
    mw_inv = mw.inverted()
    bm = bmesh.from_edit_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()

    shot_path, json_path = _paths("edges")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()
    proj = proj_fn(region, rv3d)
    view_fwd = rv3d.view_rotation @ Vector((0, 0, -1))

    use_raycast = visible_only and rv3d.view_perspective == 'PERSP'
    if use_raycast:
        bvh = BVHTree.FromBMesh(bm)
        cam_local = mw_inv @ rv3d.view_matrix.inverted().translation

    def is_visible(e):
        if not visible_only:
            return True
        midw = (e.verts[0].co + e.verts[1].co) / 2   # local space
        if use_raycast:
            to_target = midw - cam_local
            dist = to_target.length
            if dist < 1e-6:
                return True
            direction = to_target / dist
            hit_loc, _, _, hit_dist = bvh.ray_cast(cam_local, direction, dist - 0.002)
            return hit_loc is None   # nothing closer blocks the view of this point
        if not e.link_faces:
            return True   # no adjacent face to test — don't silently drop it
        for f in e.link_faces:
            normal_w = (mw.to_3x3() @ f.normal).normalized()
            if normal_w.dot(view_fwd) < 0:
                return True   # at least one linked face is front-facing
        return False

    x1 = tl_norm[0] * region.width;  y1 = tl_norm[1] * region.height
    x2 = br_norm[0] * region.width;  y2 = br_norm[1] * region.height

    edges_data = {}
    label_n = 1
    for e in bm.edges:
        if not is_visible(e):
            continue
        v0w = mw @ e.verts[0].co
        v1w = mw @ e.verts[1].co
        midw = (v0w + v1w) / 2
        sp0, sp1, spm = proj(v0w), proj(v1w), proj(midw)
        if sp0 is None or sp1 is None or spm is None:
            continue
        if not (x1 <= spm["x"] <= x2 and y1 <= spm["y"] <= y2):
            continue
        edges_data[f"E_{label_n}"] = {
            "edge_idx": e.index,
            "v0": sp0, "v1": sp1, "mid": spm,
        }
        label_n += 1
        if label_n > max_edges:
            break

    payload = {
        "image": shot_path,
        "viewport_width": region.width,
        "viewport_height": region.height,
        "edges": edges_data,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(EDGE_MAP_OVERLAY, "--json", json_path,
                "--tl", "0", "0", "--br", "1", "1")
    return payload


def edge_at_label(label, prior_action=None):
    """Return {"v0":{x,y}, "v1":{x,y}, "mid":{x,y}} (viewport pixel coords)
    for a label (e.g. "E_7") from a previous edge_map() call.
    """
    if prior_action is None:
        prior_action = _rt._ACTION - 1
    step_dir  = f"{_rt._RUN}/steps/step_{_rt._STEP:03d}"
    json_path = f"{step_dir}/overlay_json/action_{prior_action:02d}_edges.json"
    with open(json_path) as f_:
        data = json.load(f_)
    e = data["edges"][label]
    return {"v0": e["v0"], "v1": e["v1"], "mid": e["mid"]}


def viewport_drag_dots(rows=8, cols=10):
    """Render a full-viewport drag-dot grid so the agent can pick a pan target.

    Each dot is labelled with its normalised image coord ("x.x,y.y").
    The agent reads the overlay PNG, finds the dot nearest to where it wants
    the view to move, and passes that label's two numbers directly to
    lib/view.pan_to_norm() in the next action.

    No JSON sidecar is produced — the label IS the value.
    Returns the path to the saved overlay PNG.
    """
    shot_path, _ = _paths("drag")
    render_viewport(shot_path)
    run_overlay(DRAG_OVERLAY,
                "--image", shot_path,
                "--rows",  str(rows),
                "--cols",  str(cols))
    # Overlay script writes <shot_path_stem>_drag.png next to the screenshot.
    base, ext = shot_path.rsplit(".", 1)
    return f"{base}_drag.{ext}"


def face_grid(tl_norm=(0.25, 0.25), br_norm=(0.75, 0.75),
              rows=8, cols=8, labels=False, style="dots"):
    """Render a face-selection grid over the current viewport.

    Wraps `grid_map.py`: takes a viewport screenshot, draws a grid inside
    a blue perimeter (style-dependent), and writes a JSON of intersection
    positions so `face_at_grid()` can resolve a picked one to a pixel.

    labels  When True, draws the yellow "(row,col)" label next to each
            dot/intersection. Default False — labels off, for a cleaner
            image; the agent counts row/col from the top-left of the
            perimeter. Turning labels on over busy reference imagery can
            obscure exactly the detail being picked — leave off unless
            actually needed.
    style   "dots" (default) — red dots at each intersection, thicker
            blue border. "lines" — thin red grid lines (both horizontal
            and vertical) + a thin blue border (~30% thinner strokes
            throughout) — reads as a reference overlay rather than
            competing with the underlying image, useful when picking a
            point against detailed reference photography.

    Returns the parsed JSON payload from grid_map.py.
    """
    shot_path, json_path = _paths("grid")
    render_viewport(shot_path)

    overlay_args = [
        "--image",    shot_path,
        "--tl",       str(tl_norm[0]), str(tl_norm[1]),
        "--br",       str(br_norm[0]), str(br_norm[1]),
        "--rows",     str(rows),
        "--cols",     str(cols),
        "--style",    style,
        "--json-out", json_path,
    ]
    if labels:
        overlay_args.append("--labels")

    run_overlay(GRID_OVERLAY, *overlay_args)
    with open(json_path) as f:
        return json.load(f)


def face_at_grid(row, col, prior_action=None):
    """Resolve a (row, col) pick to a face index via raycast through the viewport.

    Reads the grid JSON written by an earlier `face_grid()` call (defaults
    to the immediately previous action in this Step). Casts a ray from the
    grid dot's pixel and returns the first hit face's index (int), or None
    on miss. We return the int (not a BMFace) because the local bmesh used
    for the cast goes out of scope on return and any subsequent
    bpy.ops.mesh.* call invalidates BMFace handles anyway. Look the face
    back up with `bm.faces[idx]` from a fresh bmesh in the caller.
    """
    from bpy_extras import view3d_utils
    from mathutils  import Vector

    if prior_action is None:
        prior_action = _rt._ACTION - 1

    step_dir = f"{_rt._RUN}/steps/step_{_rt._STEP:03d}"
    json_path = f"{step_dir}/overlay_json/action_{prior_action:02d}_grid.json"
    with open(json_path) as f:
        data = json.load(f)

    pt = next(p for p in data["points"]
              if p["row"] == row and p["col"] == col)

    _, region, rv3d = get_viewport()
    # grid_map.py works in IMAGE pixels, and the render is SHOT_SCALE x the
    # region (see lib/view.py), so scale back before using region coords.
    # It also uses PIL convention (origin top-left, y-down); convert to
    # Blender's region coords (origin bottom-left, y-up) for view3d_utils.
    sx = region.width  / data.get("viewport_width",  region.width)
    sy = region.height / data.get("viewport_height", region.height)
    pix = Vector((pt["px"] * sx, region.height - pt["py"] * sy))
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, pix)
    ray_dir    = view3d_utils.region_2d_to_vector_3d(region, rv3d, pix)

    obj = bpy.context.active_object
    bm  = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    # Object.ray_cast tests against the evaluated mesh, which lags the
    # live bmesh in EDIT mode even after update_from_editmode(). Build a
    # BVH directly from the bmesh so we test against the current geometry.
    from mathutils.bvhtree import BVHTree
    bvh = BVHTree.FromBMesh(bm)

    mw_inv       = obj.matrix_world.inverted()
    local_origin = mw_inv @ ray_origin
    local_dir    = (mw_inv.to_3x3() @ ray_dir).normalized()

    hit_loc, _, face_idx, _ = bvh.ray_cast(local_origin, local_dir)
    if hit_loc is None:
        return None
    return face_idx


def grab_preview(plane_axes=None, n_dots=7, px_step=40):
    """Render the 2D grab destination grid on the current selection.

    plane_axes  (axis_h, axis_v) world Vectors defining the grab plane.
                Defaults to (X, Y) — XY-plane grab for top-down views.
                For a FRONT-view ZX grab, pass (Vector((1,0,0)), Vector((0,0,1))).
    n_dots      grid side length (odd → centred on pivot). Default 7 → 7×7.
    px_step     screen-pixel spacing between adjacent dots.

    Returns the JSON dict. Each `grid_points[k]` carries `world_offset` —
    the translation in metres along (axis_h, axis_v) to feed into
    `bpy.ops.transform.translate(value=(dx, dy, dz))` next action.
    """
    if plane_axes is None:
        plane_axes = (Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)))

    obj = bpy.context.active_object
    pivot, _, _ = _selected_centroid_world(obj)

    shot_path, json_path = _paths("grab")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()

    data = grab_grid(pivot, plane_axes, region, rv3d, shot_path,
                     n_dots=n_dots, px_step=px_step)
    if data is None:
        raise RuntimeError("grab_preview: degenerate projection — viewpoint too oblique")

    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    run_overlay(GRAB_OVERLAY, "--json", json_path)
    return data


def grab_line_preview(axis=(0, 0, 1), kind='world', step=0.05, k_range=None):
    """Linear grab-along-axis preview — ticks at fixed spacing along `axis`.

    Same primitive as extrude_ruler() (they are the same overlay), just named
    for grab semantics. Use this when you want to translate a selection along
    a single world axis (typically Z for a lift) and read the distance off a
    tick instead of picking a dot in a 2-D grid.

        data = grab_line_preview(axis=(0,0,1), kind='world', step=0.05)
        # ... agent reads action_N_exmap.png, picks e2 ...
        tick = pick(data, "e2")
        T = tick["t"]
        bpy.ops.transform.translate(value=(0, 0, T))

    Returns the same JSON payload as extrude_ruler. The overlay PNG suffix
    is `_exmap` (rendered by extrude_map_overlay.py).
    """
    return extrude_ruler(axis=axis, kind=kind, step=step, k_range=k_range)


def grab_at(i, j, prior_action=None):
    """Look up world_offset (dh, dv) for grid point (i, j) from a prior grab_preview()."""
    if prior_action is None:
        prior_action = _rt._ACTION - 1
    step_dir  = f"{_rt._RUN}/steps/step_{_rt._STEP:03d}"
    json_path = f"{step_dir}/overlay_json/action_{prior_action:02d}_grab.json"
    with open(json_path) as f:
        data = json.load(f)
    for pt in data["grid_points"]:
        if pt["i"] == i and pt["j"] == j:
            return tuple(pt["world_offset"])
    raise KeyError(f"grab_preview point ({i},{j}) not found in {json_path}")


def rotate_trackball(reference_pt, pivot=None, n_dots=5, deg_step=10):
    """Render the 2D trackball-rotation preview around a pivot.

    Mirrors Blender's double-tap-R: yaw around camera_up, pitch around
    camera_right, applied together. The overlay shows where `reference_pt`
    lands for each (yaw, pitch) on a `n_dots × n_dots` grid spaced
    `deg_step` degrees apart.

    pivot         world Vector to rotate around. Defaults to the centroid
                  of the currently selected verts.
    reference_pt  world Vector whose post-rotation position is previewed.
                  Pick a vertex that moves visibly (e.g. the bottom of a leg
                  when rotating around its top).
    n_dots        grid side (odd → centred on identity rotation).
    deg_step      degrees between adjacent ticks.

    Returns the JSON dict. To apply the pick:

        from perceive import trackball_at
        yaw, pitch = trackball_at(i, j)   # degrees
        # Place the pivot under the transform pivot point:
        bpy.context.scene.cursor.location = pivot
        bpy.context.scene.tool_settings.transform_pivot_point = 'CURSOR'
        bpy.ops.transform.trackball(
            value=(math.radians(yaw), math.radians(pitch))
        )
    """
    obj = bpy.context.active_object
    if pivot is None:
        pivot, _, _ = _selected_centroid_world(obj)
    pivot         = Vector(pivot)
    reference_pt  = Vector(reference_pt)

    shot_path, json_path = _paths("trackball")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()

    data = trackball_grid(pivot, reference_pt, region, rv3d, shot_path,
                          n_dots=n_dots, deg_step=deg_step)
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    run_overlay(TRACKBALL_OVERLAY, "--json", json_path)
    return data


def trackball_at(i, j, prior_action=None):
    """Look up (yaw_deg, pitch_deg) for grid point (i, j) from a prior rotate_trackball()."""
    if prior_action is None:
        prior_action = _rt._ACTION - 1
    step_dir  = f"{_rt._RUN}/steps/step_{_rt._STEP:03d}"
    json_path = f"{step_dir}/overlay_json/action_{prior_action:02d}_trackball.json"
    with open(json_path) as f:
        data = json.load(f)
    for pt in data["grid_points"]:
        if pt["i"] == i and pt["j"] == j:
            return pt["yaw_deg"], pt["pitch_deg"]
    raise KeyError(f"rotate_trackball point ({i},{j}) not found in {json_path}")


def rotate_preview(axis=(1, 0, 0), reference_pt=None, pivot=None,
                   angles=None):
    """Single-axis rotation preview — an arc of angle ticks around `pivot`
    projecting where `reference_pt` would land for each rotation.

    axis          world-space axis to rotate around (usually the profile
                  axis, e.g. X for a side-profile duck).
    reference_pt  world position whose rotated location is drawn per tick.
                  Defaults to the point in the current selection that is
                  farthest from `pivot` (most visible motion).
    pivot         world position to rotate around. Defaults to the
                  selected-verts centroid.
    angles        list of degrees to preview. Default `[-60, -45, -30,
                  -15, 15, 30, 45, 60]`.

    Returns the parsed JSON payload. Look up a tick with `pick(data, 'r+30')`;
    apply with `bpy.ops.transform.rotate(value=math.radians(deg),
    orient_axis=<AXIS_LETTER>)` after making sure the transform pivot
    matches `pivot`.

    JSON suffix: `_rotate` (JSON) + `_rot.png` (drawer output).
    """
    obj = bpy.context.active_object
    sel_pivot, sel_ws, _ = _selected_centroid_world(obj)
    if pivot is None:
        pivot = sel_pivot
    if reference_pt is None:
        # Pick the selected vert farthest from the pivot in the plane
        # perpendicular to the rotation axis (max on-screen arc length).
        axis_v  = Vector(axis).normalized()
        best_pt, best_d = None, -1.0
        for w in sel_ws:
            d = w - Vector(pivot)
            # Component perpendicular to axis
            perp = d - axis_v * d.dot(axis_v)
            if perp.length > best_d:
                best_d = perp.length
                best_pt = w
        reference_pt = best_pt if best_pt is not None else Vector(pivot) + Vector((0, 0, 1))

    shot_path, json_path = _paths("rotate")
    render_viewport(shot_path)
    _, region, rv3d = get_viewport()

    data = rotate_ruler(
        Vector(pivot),
        Vector(axis),
        Vector(reference_pt),
        region, rv3d,
        shot_path,
        angles=angles,
    )
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    run_overlay(ROTATE_OVERLAY, "--json", json_path)
    return data


def between_ticks(data, a, b, frac=0.5):
    """World-space distance interpolated between two tick labels.

    frac = 0.0 → tick `a`, 1.0 → tick `b`, 0.5 → midpoint.
    Values outside [0, 1] extrapolate past the ticks.

        t = between_ticks(data, "e7", "e8", frac=0.5)   # midpoint of e7..e8
        t = between_ticks(data, "e2", "e3", frac=0.25)  # a quarter past e2
    """
    ta = pick(data, a)
    tb = pick(data, b)
    if ta is None or tb is None:
        missing = a if ta is None else b
        raise KeyError(f"Tick {missing!r} not found in ruler payload")
    return ta["t"] + (tb["t"] - ta["t"]) * frac


def pick(data, ordinal):
    """Look up a tick by ordinal in a ruler payload (screen, world, or scale)."""
    for key in ("screen_ruler", "world_ruler"):
        if key in data:
            for t in data[key]["ticks"]:
                if t["ordinal"] == ordinal:
                    return t
    # scale_ruler stores ticks at the top level
    if "ticks" in data:
        for t in data["ticks"]:
            if t["ordinal"] == ordinal:
                return t
    return None


def silhouette_vs_reference(obj_names, ref_name="BatRef", label="silhouette",
                            axis='Y', samples=48, margin=0.06):
    """Draw the built mesh's outline ON THE REFERENCE PHOTO and report the fit.

    This is the honest way to answer "does what I built match the picture?".
    A viewport screenshot can't answer it: the model's solid shading covers
    the photo exactly where you need to see it, so you can tell that the mesh
    is roughly over the bat but not that it is 2x too wide. Here the outline
    is drawn onto the photo itself, at the photo's own resolution, cropped
    around the mesh — so an error reads as a visible gap.

    obj_names   one name or a list. Every MESH given is measured together, in
                the evaluated (modifier-applied) state, so a Mirror shows up.
    ref_name    the Image Empty holding the reference photo.
    axis        world axis the object is long along — 'Y' for this build's
                head-tail direction. The silhouette is sampled in slices
                perpendicular to it.
    samples     UPPER BOUND on the number of slices, not a target. Slices are
                bins of raw vertices, so asking for more bins than the mesh has
                distinct cross-sections cannot produce more detail — it just
                produces empty ones. The call clamps to what the mesh supports
                and reports both numbers back as `samples_requested` /
                `samples_used`; a slice holding fewer than 2 vertices is dropped
                rather than reported as half_width 0.0, and the count comes back
                as `stations_dropped`. On a 17-ring low-poly body you get ~17
                stations however large a number you pass.
    margin      crop padding around the mesh, as a fraction of image size.

    Returns {"image", "image_size", "samples_requested", "samples_used",
    "stations_dropped", "stations": [{"u", "v_top", "v_bot", "half_width",
    "n_verts"}...]} and renders the overlay for this action.

    `u` and the `v_*`/`half_width` values are fractions of the reference image
    (0-1, top-left origin). To get pixels use the returned `image_size`:
    full_width_px = half_width * 2 * image_size[1]. Never hardcode the image
    dimensions — they differ per build.

    The numbers come back as well as the render, so a follow-up `bash` script
    can compare them against a pixel scan of the photo instead of eyeballing.
    """
    import bpy
    from mathutils import Vector

    if isinstance(obj_names, str):
        obj_names = [obj_names]
    ref = bpy.data.objects.get(ref_name)
    if ref is None or ref.data is None:
        return None

    img_w, img_h = ref.data.size
    size = ref.empty_display_size
    if img_w >= img_h:
        rect_w, rect_h = size, size * img_h / img_w
    else:
        rect_w, rect_h = size * img_w / img_h, size
    ox, oy = ref.empty_image_offset
    inv = ref.matrix_world.inverted()

    def world_to_uv(p):
        l = inv @ Vector(p)
        return (l.x / rect_w - ox, 1.0 - (l.y / rect_h - oy))

    depsgraph = bpy.context.evaluated_depsgraph_get()
    pts = []
    for name in obj_names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != 'MESH':
            continue
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        mw = ev.matrix_world
        pts += [mw @ v.co for v in mesh.vertices]
        ev.to_mesh_clear()
    if not pts:
        return None

    uvs = [world_to_uv(p) for p in pts]
    us = [u for u, _ in uvs]
    u_lo, u_hi = min(us), max(us)
    if u_hi - u_lo < 1e-6:
        return None

    # Clamp `samples` to what the mesh can actually support. This bins RAW
    # VERTICES, so a bin narrower than the spacing between rings catches one
    # vertex or none — and a one-vertex bin has v_top == v_bot, i.e. it reports
    # half_width 0.0 as though it had measured a zero-thickness slice. That is
    # indistinguishable from a real measurement downstream, and it is what a
    # low-poly mesh gets at the old default of 48: on a 17-ring duck, two
    # separate reviewers asked for 48 and 64 slices and got a profile that swung
    # between 0.0 and 0.28 between neighbouring stations. The ceiling is the
    # number of distinct u positions in the cloud, which for a ring-extruded
    # mesh is the ring count.
    # Density, not distinct-u, is the right ceiling. Mitred rings tilt, so their
    # verts spread along u and a 17-ring body reports ~119 distinct u values —
    # a clamp on that barely engages. What actually matters is having enough
    # verts per slice to span the cross-section: below ~8 a bin catches part of
    # a ring and understates the width, which is the same fabricated-measurement
    # failure as a zero, just quieter. On a dense sculpted mesh this is far
    # above any sane `samples`, so the caller stays in control there.
    effective = max(2, min(samples, len(uvs) // 8))

    bins = {}
    for u, v in uvs:
        i = min(effective - 1, int((u - u_lo) / (u_hi - u_lo) * effective))
        lo, hi, n = bins.get(i, (v, v, 0))
        bins[i] = (min(lo, v), max(hi, v), n + 1)

    # A slice needs at least two vertices to have a width at all. Drop the rest
    # rather than emitting half_width 0.0 — an absent station reads as "no data
    # here", a zero reads as "measured, and it is zero".
    stations, top_px, bot_px, dropped = [], [], [], 0
    for i in sorted(bins):
        v_top, v_bot, n = bins[i]
        # Two tests, because two different degeneracies produce the same lie.
        # An empty-ish bin (n < 2) has nothing to measure. But a bin holding
        # exactly two verts at the SAME height also yields v_top == v_bot — a
        # 12-gon ring has its verts in equal-height pairs, so this happens
        # routinely — and reports half_width 0.0 as though it had measured a
        # zero-thickness slice. A solid cross-section is never zero wide, not
        # even at the 8 mm tail tip, so treat any zero as no-data rather than
        # as data. Measured on duck_run_002: the n<2 test alone still let three
        # fabricated zeros through out of 25 stations.
        # Test the value that will actually be PUBLISHED, not the float it came
        # from. half_width is rounded to 4dp, so a slice whose true width is
        # ~6e-5 passes a `> 0.0` test on the raw difference and still prints as
        # 0.0000 — which is the same fabricated measurement, arrived at through
        # rounding instead of through an empty bin. Measured on the real duck:
        # a raw-difference test dropped 1 station and let 3 rounded zeros
        # through. Deriving the guard from the published number makes a zero
        # impossible by construction rather than by argument.
        half_width = round((v_bot - v_top) / 2.0, 4)
        if n < 2 or half_width <= 0.0:
            dropped += 1
            continue
        u = u_lo + (i + 0.5) / effective * (u_hi - u_lo)
        stations.append({"u": round(u, 4), "v_top": round(v_top, 4),
                         "v_bot": round(v_bot, 4),
                         "half_width": half_width,
                         "n_verts": n})
        top_px.append([u * img_w, v_top * img_h])
        bot_px.append([u * img_w, v_bot * img_h])

    if not stations:
        return None

    vs = [v for st in stations for v in (st["v_top"], st["v_bot"])]
    crop = [max(0, int((u_lo - margin) * img_w)),
            max(0, int((min(vs) - margin) * img_h)),
            min(img_w, int((u_hi + margin) * img_w)),
            min(img_h, int((max(vs) + margin) * img_h))]

    shot_path, json_path = _paths("silhouette")
    out_png = shot_path.replace(".png", f"_{label}.png")
    payload = {
        "image": bpy.path.abspath(ref.data.filepath) or ref.data.filepath,
        "output": out_png, "top": top_px, "bottom": bot_px,
        "label": f"{'+'.join(obj_names)} outline on the reference photo",
        "crop": crop, "stations": stations,
        # Everything needed to turn a station into real units, so no caller has
        # to carry a hardcoded pixel constant from whichever build it was
        # written for. full_width_px = half_width * 2 * img_h.
        "image_size": [img_w, img_h],
        "samples_requested": samples,
        "samples_used": effective,
        "stations_dropped": dropped,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    run_overlay(SILHOUETTE_OVERLAY, "--json", json_path)
    # Return the payload itself rather than a hand-picked subset. The subset
    # was {"image", "stations"} only, so callers following the docstring got
    # None for everything else — observed on duck_run_002, where the reviewer
    # asked for `image_size` exactly as documented, got None, and lost its
    # pixel scale. Anything worth writing to the sidecar is worth returning.
    return dict(payload)


MESH_OUTLINE_OVERLAY = f"{OVERLAYS}/mesh_outline_overlay.py"


def outline_preview(obj_names, label="outline", title=None, wire=True):
    """READ-ONLY. Draw what was BUILT over the reference photo behind it.

    Every other preview in this toolkit draws a plan — a path, a set of
    radii, a rectangle — and a plan can be right in every number and still
    produce the wrong shape, because what a body is judged by is its
    outline, and the outline is the radii, the path, the mitring at every
    joint and the cross-section's vertex count all at once. This closes
    that loop: render the current view, project the finished mesh into it,
    and trace its silhouette in red over the photograph it was traced from.

    THE SILHOUETTE IS FOUND BY EDGE FACING, not by sampling. For a closed
    mesh, an edge is on the silhouette exactly when one of its two faces
    points towards the viewer and the other points away — so the test is a
    sign change in the dot product of the two face normals with the view
    direction, and it is exact.

    The first version instead sliced the frame into vertical columns and
    joined the topmost and bottommost projected vertex in each. That works
    on a dense mesh and fails completely on this one: 192 vertices over 180
    columns leaves most columns holding a single vertex, where top and
    bottom are the same point, and the "outline" comes out as a zigzag
    between the upper and lower surfaces. Sampling a silhouette needs more
    samples than the mesh has; asking the topology is free.

    THE SUBJECT IS HIDDEN FOR THE BASE RENDER. The whole point is to
    compare the built shape against the photograph behind it, and a shaded
    model sitting in front of the photograph hides exactly the thing being
    compared — you can see where the outline runs but not what it is meant
    to be running along. Hide, render, unhide, then project: the geometry
    is read after the render, so visibility cannot affect it.

    obj_names   one name or a list. Each contributes its own silhouette.
    wire        also draw the mesh's edges faintly, so the ring spacing is
                visible inside the outline — that spacing is what turns a
                smooth curve into a low-poly one.
    """
    import bpy
    from mathutils import Vector
    from lib.view import proj_fn, get_viewport, render_viewport
    from lib.util import run_overlay

    if isinstance(obj_names, str):
        obj_names = [obj_names]

    step_dir = f"{_rt._RUN}/steps/step_{_rt._STEP:03d}"
    shot_path = (f"{step_dir}/screenshots/"
                 f"action_{_rt._ACTION:02d}_{label}_base.png")
    json_path = (f"{step_dir}/overlay_json/"
                 f"action_{_rt._ACTION:02d}_{label}_outline.json")
    out_path = (f"{step_dir}/screenshots/"
                f"action_{_rt._ACTION:02d}_{label}_outline.png")

    was = {}
    for n in obj_names:
        o = bpy.data.objects.get(n)
        if o is not None:
            was[n] = (o.hide_viewport, o.hide_get())
            o.hide_viewport = True
            o.hide_set(True)
    try:
        render_viewport(shot_path)
    finally:
        for n, (hv, hg) in was.items():
            o = bpy.data.objects[n]
            o.hide_viewport = hv
            o.hide_set(hg)

    _, region, rv3d = get_viewport()
    if region is None:
        return None
    proj = proj_fn(region, rv3d)
    view_dir = (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()

    sil, edges = [], []
    for name in obj_names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != 'MESH':
            continue
        # Evaluated, so a Mirror modifier's second half is included — the
        # unevaluated mesh would outline one leg of a pair.
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        mw = obj.matrix_world
        nm = mw.to_3x3().inverted().transposed()

        facing = [ (nm @ p.normal).normalized().dot(view_dir) < 0.0
                   for p in me.polygons ]
        by_edge = {}
        for pi, poly in enumerate(me.polygons):
            for ek in poly.edge_keys:
                by_edge.setdefault(ek, []).append(pi)

        def seg(a_co, b_co):
            a, b = proj(mw @ a_co), proj(mw @ b_co)
            if a is None or b is None:
                return None
            return [[round(a["x"] / region.width, 4),
                     round(a["y"] / region.height, 4)],
                    [round(b["x"] / region.width, 4),
                     round(b["y"] / region.height, 4)]]

        for ek, faces in by_edge.items():
            a_co = me.vertices[ek[0]].co
            b_co = me.vertices[ek[1]].co
            on_sil = (len(faces) == 1
                      or (len(faces) == 2 and facing[faces[0]] != facing[faces[1]]))
            s2 = seg(a_co, b_co)
            if s2 is None:
                continue
            if on_sil:
                sil.append(s2)
            elif wire:
                edges.append(s2)
        ev.to_mesh_clear()

    payload = {"image": shot_path, "silhouette": sil, "edges": edges,
               "title": title or ("%s outline on the reference"
                                  % ", ".join(obj_names))}
    with open(json_path, "w") as f:
        json.dump(payload, f)
    run_overlay(MESH_OUTLINE_OVERLAY, "--json", json_path,
                "--output", out_path)
    return payload


def reference_outline(obj_names, ref_name="BatRef", label="ref_outline",
                      title=None, margin=0.06, crop=True):
    """Draw the mesh's TRUE outline on the reference photo. Red line only.

    Use this instead of `silhouette_vs_reference` whenever the question is
    "does the shape match the picture?". That function samples the mesh into
    vertical stations and reports a width per station, which is a useful
    *measurement* but a bad *picture*: it draws a yellow ring down every
    station, so a wide subject ends up behind a picket fence, and its red line
    joins the topmost and bottommost projected vertex in each column.

    That column trick is only a silhouette when the object is elongated along
    the image's horizontal axis. It is right for a shark lying nose-to-tail
    across the frame. It is wrong for anything upright: on a wine glass the
    centre column runs from the rim down to the foot, so every column spans the
    subject's full height and the "outline" comes back as a bounding box with
    spikes where the inner wall reverses. There is no axis argument that fixes
    it — `silhouette_vs_reference` accepts `axis` and never reads it.

    THE OUTLINE HERE IS EXACT, NOT SAMPLED. An edge is on the silhouette when
    one of its faces points toward the reference plane and the other points
    away, plus any edge with a single face so open meshes still outline. That
    is a sign test on two dot products; it needs no samples, cannot alias, and
    does not care which way up the subject is.

    The projection is the reference image's own plane — the same mapping
    `silhouette_vs_reference` uses — so the line lands on the photo at full
    resolution, not at whatever zoom the viewport happens to be at, and the
    view direction is the reference plane's normal rather than the camera's.

    obj_names   one name or a list; each contributes its own silhouette.
    ref_name    the reference image Empty.
    margin      crop padding around the mesh, as a fraction of image size.
    crop        False to keep the full photo instead of cropping to the subject.

    Returns {"image", "output", "image_size", "bbox_uv", "segments"} and
    renders the overlay for this action.
    """
    import bpy
    from mathutils import Vector

    if isinstance(obj_names, str):
        obj_names = [obj_names]
    ref = bpy.data.objects.get(ref_name)
    if ref is None or ref.data is None:
        return None

    img_w, img_h = ref.data.size
    size = ref.empty_display_size
    if img_w >= img_h:
        rect_w, rect_h = size, size * img_h / img_w
    else:
        rect_w, rect_h = size * img_w / img_h, size
    ox, oy = ref.empty_image_offset
    inv = ref.matrix_world.inverted()

    def world_to_uv(p):
        l = inv @ Vector(p)
        return (l.x / rect_w - ox, 1.0 - (l.y / rect_h - oy))

    # The reference plane's own normal. The projection onto the photo is
    # orthographic along this axis, so this — not the viewport camera — is the
    # direction the facing test has to use, which is why the result is stable
    # no matter where the user left the view.
    view_dir = -(ref.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()

    dg = bpy.context.evaluated_depsgraph_get()
    segs, us, vs = [], [], []
    for name in obj_names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != 'MESH':
            continue
        # Evaluated, so Mirror/Subsurf output is outlined rather than the cage.
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        nm = mw.to_3x3().inverted().transposed()

        facing = [(nm @ p.normal).normalized().dot(view_dir) < 0.0
                  for p in me.polygons]
        by_edge = {}
        for pi, poly in enumerate(me.polygons):
            for ek in poly.edge_keys:
                by_edge.setdefault(ek, []).append(pi)

        for ek, faces in by_edge.items():
            on_sil = (len(faces) == 1
                      or (len(faces) == 2 and facing[faces[0]] != facing[faces[1]])
                      or len(faces) > 2)
            if not on_sil:
                continue
            a = world_to_uv(mw @ me.vertices[ek[0]].co)
            b = world_to_uv(mw @ me.vertices[ek[1]].co)
            segs.append([[round(a[0], 5), round(a[1], 5)],
                         [round(b[0], 5), round(b[1], 5)]])
            us += [a[0], b[0]]
            vs += [a[1], b[1]]
        ev.to_mesh_clear()

    if not segs:
        return None

    box = None
    if crop:
        box = [max(0, int((min(us) - margin) * img_w)),
               max(0, int((min(vs) - margin) * img_h)),
               min(img_w, int((max(us) + margin) * img_w)),
               min(img_h, int((max(vs) + margin) * img_h))]

    shot_path, json_path = _paths("ref_outline")
    out_png = shot_path.replace(".png", f"_{label}.png")
    payload = {
        "image": bpy.path.abspath(ref.data.filepath) or ref.data.filepath,
        "output": out_png,
        "silhouette": segs,
        "label": title or ("%s outline on the reference photo"
                           % "+".join(obj_names)),
        "crop": box,
        "image_size": [img_w, img_h],
        "bbox_uv": [round(min(us), 4), round(min(vs), 4),
                    round(max(us), 4), round(max(vs), 4)],
        "segments": len(segs),
    }
    with open(json_path, "w") as f:
        json.dump(payload, f)
    run_overlay(REF_OUTLINE_OVERLAY, "--json", json_path)
    return dict(payload)
