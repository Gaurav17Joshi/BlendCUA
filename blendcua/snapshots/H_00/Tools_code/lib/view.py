"""
Viewport + projection helpers.

The cardinal rule (see TOOL_AUTHORING.md): direct writes to rv3d.view_*
do NOT update the internal matrices. Always call rv3d.update() before
rendering or projecting, or you'll get an ortho-rendered image but
perspective-projected screen coords.
"""

import bpy
from mathutils import Vector
from bpy_extras import view3d_utils

# ─── Screenshot resolution policy ────────────────────────────────────────────
# render_viewport() renders at SHOT_SCALE × the viewport region's size. The 3D
# region is only as big as the Blender window (e.g. 797×598), which is far less
# detail than the models can actually use: at 797×598 a bat body 60 px wide
# occupies ~2 patches of a vision model's input, so a 20% width error is
# invisible. Rendering at 2× gives genuinely rendered pixels — not interpolation
# — which then downsample to the delivered size with free antialiasing on the
# thin wireframe and silhouette edges that the shape judgments depend on.
#
# Everything downstream already copes: every overlay scales its coordinates by
# `img.size / data["viewport_width"]`, and derives font and dot sizes from the
# image, so annotations stay legible at any scale.
#
# IMPORTANT — the PNG the agent is SHOWN is NOT in region pixels.
# render_viewport() writes SHOT_SCALE × region, and then
# `run_steps.py` / `blendcua_core._resize_png_inplace()` cap the shown
# screenshot at 1440×1080 (aspect preserved, never upscaled) *after* the
# overlays are drawn. So a pixel read off the delivered image is wrong twice
# over if fed straight to a Blender projection call:
#
#   1. SCALE  — delivered image px  vs  region px  (both directions, and the
#               factor is not fixed: it depends on the window size)
#   2. Y FLIP — image y grows DOWN from the top-left;
#               region y grows UP from the bottom-left.
#
# Passing raw image pixels to `view3d_utils.region_2d_to_location_3d()` was a
# real, repeated failure in production runs (bat_gpt56luna_med step 1 action 3,
# step 4 action 20): the correct point was picked by eye, then unprojected to
# completely the wrong world location, and the object jumped far off target.
#
# THE RULE: never carry raw pixels across the Blender/screenshot boundary.
# Express every screen pick as NORMALISED top-left coords (0–1) — which is
# exactly what every overlay in this toolkit already labels its dots with —
# and convert with `norm_to_region_px()` / `unproject_norm()` below.


def get_viewport():
    """Return (area, region, rv3d) for the first VIEW_3D area, or (None, None, None).

    Always calls rv3d.update() so the matrices match the current properties.
    """
    area = next((a for a in bpy.context.screen.areas if a.type == 'VIEW_3D'), None)
    if not area:
        return None, None, None
    region = next(r for r in area.regions if r.type == 'WINDOW')
    rv3d = area.spaces.active.region_3d
    rv3d.update()
    return area, region, rv3d


SHOT_SCALE = 2   # render at this multiple of the 3D region's size


def shot_size(region, scale=None):
    """Pixel size render_viewport() will produce for `region`."""
    k = SHOT_SCALE if scale is None else scale
    return int(region.width * k), int(region.height * k)


def render_viewport(path, scale=None):
    """Render the active VIEW_3D viewport to `path` at SHOT_SCALE × region size.

    Saves and restores render settings. Pass `scale=1` for a render whose
    pixels are region pixels (nothing needs that today — every consumer
    rescales — but it makes the assumption visible where it matters).
    """
    area, region, _ = get_viewport()
    if not area:
        return
    scene = bpy.context.scene
    prev = (scene.render.filepath,
            scene.render.image_settings.file_format,
            scene.render.resolution_x,
            scene.render.resolution_y,
            scene.render.resolution_percentage)
    res_x, res_y                       = shot_size(region, scale)
    scene.render.resolution_x          = res_x
    scene.render.resolution_y          = res_y
    scene.render.resolution_percentage = 100
    scene.render.filepath                    = path
    scene.render.image_settings.file_format = 'PNG'
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.render.opengl(write_still=True, view_context=True)
    (scene.render.filepath,
     scene.render.image_settings.file_format,
     scene.render.resolution_x,
     scene.render.resolution_y,
     scene.render.resolution_percentage) = prev


def proj_fn(region, rv3d):
    """Return a closure: world Vector -> {'x','y'} in image-down coords.

    image-down means origin top-left, y growing downward (PIL convention).
    """
    rv3d.update()
    def proj(pt):
        s = view3d_utils.location_3d_to_region_2d(region, rv3d, pt)
        if s is None:
            return None
        return {"x": round(s.x, 2), "y": round(region.height - s.y, 2)}
    return proj


def norm_to_region_px(x_norm, y_norm, region):
    """Normalised image coords (0–1, top-left origin, y down) → region pixels.

    Region pixels are what every `bpy_extras.view3d_utils` call expects:
    bottom-left origin, y up, sized `region.width × region.height` — NOT the
    size of the screenshot PNG the agent was shown. See the resolution-policy
    note at the top of this module.

    Raises ValueError on out-of-range input, because the overwhelmingly common
    way to get here wrong is to pass screenshot pixels (e.g. `(570, 405)`)
    where a 0–1 fraction belongs.
    """
    if not (-0.05 <= x_norm <= 1.05 and -0.05 <= y_norm <= 1.05):
        raise ValueError(
            f"norm_to_region_px expects NORMALISED 0–1 image coords, got "
            f"({x_norm}, {y_norm}). If you read those numbers off a screenshot "
            f"in pixels, divide by the IMAGE's own width/height first — the "
            f"delivered PNG is a different size from this region "
            f"({region.width}x{region.height}), and by how much depends on the "
            f"window, so the fraction is the only portable form."
        )
    return Vector((x_norm * region.width, (1.0 - y_norm) * region.height))


def unproject_norm(x_norm, y_norm, region, rv3d, depth=(0.0, 0.0, 0.0)):
    """World point under a screen pick given in normalised image coords.

    x_norm, y_norm  0–1, top-left origin, y down — i.e. exactly the numbers
                    printed on `viewport_drag_dots()` / `face_grid()` /
                    `chain_preview()` dots, and exactly what you get by
                    dividing a pixel you measured on the delivered PNG by
                    that PNG's own width/height.
    depth           world point whose depth-plane the pick is unprojected
                    onto (perpendicular to the view direction). Default
                    world origin, i.e. the z=0 modelling plane in TOP ortho.

    Returns a world-space `Vector`, or None if the projection is degenerate.

    This is the ONE supported way to turn "where I see it on screen" into
    "where it is in the scene". Hand-rolling it with
    `region_2d_to_location_3d(region, rv3d, screenshot_pixels, ...)` silently
    produces a wrong point — wrong scale AND wrong Y sign (see module note).

        area, region, rv3d = get_viewport()
        torso = unproject_norm(0.557, 0.527, region, rv3d)
        ref.location = (-torso.x, -torso.y, ref.location.z)   # torso → origin
    """
    rv3d.update()
    px = norm_to_region_px(x_norm, y_norm, region)
    return view3d_utils.region_2d_to_location_3d(region, rv3d, px, Vector(depth))


def project_to_norm(world_pt, region, rv3d):
    """Inverse of `unproject_norm` — world point → (x_norm, y_norm), or None.

    Use it to VERIFY a move actually landed where you meant before spending
    another action on a screenshot: after centring, `project_to_norm(<the
    world point you targeted>, ...)` should come back at the same normalised
    coords you picked.
    """
    rv3d.update()
    s = view3d_utils.location_3d_to_region_2d(region, rv3d, Vector(world_pt))
    if s is None:
        return None
    return (s.x / region.width, 1.0 - (s.y / region.height))


def viewpoint_quality(axis_world, rv3d):
    """Return 1.0 when axis is perpendicular to the view direction, 0.0 head-on.

    Below ~0.3 the ruler degenerates (everything projects to one point).
    """
    if axis_world.length < 1e-9:
        return 0.0
    view_fwd = rv3d.view_rotation @ Vector((0, 0, -1))
    return 1.0 - abs(axis_world.normalized().dot(view_fwd.normalized()))


def pan_to_norm(x_norm, y_norm, region, rv3d):
    """Pan the viewport so the point at normalised image coords becomes the view centre.

    x_norm, y_norm: 0.0–1.0, PIL convention (origin top-left, y grows downward).
    Returns the world Vector the view was moved to.
    """
    world_pt = unproject_norm(x_norm, y_norm, region, rv3d,
                              depth=rv3d.view_location)
    rv3d.view_location = world_pt
    rv3d.update()
    return world_pt


def focus_selected(area, region, rv3d):
    """Centre and fit the viewport on the current selection (Numpad . equivalent)."""
    import bpy
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.view3d.view_selected()
    rv3d.update()


def fit_objects_ortho_view(area, region, rv3d, axis='FRONT', names='all', ratio=80):
    """Snap to an ortho axis and auto-zoom so named objects fill ratio% of the viewport.

    names: 'all', a single object name string, or a list of object name strings.
    ratio: 0–100 — the bounding box occupies this % of the viewport in the limiting
           dimension (width or height, whichever would overflow first).

    Steps:
      1. Snap to axis + view_all (clean starting matrix).
      2. Center the view on the objects' world-space bounding box.
      3. Project the 8 bbox corners to screen; measure their screen-space extent.
      4. Scale view_distance so the extent equals ratio% of the viewport.
    """
    # 1. Snap + fit all as a stable starting point
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.view3d.view_axis(type=axis)
        rv3d.view_perspective = 'ORTHO'
        bpy.ops.view3d.view_all(center=False)
    rv3d.update()

    # 2. Collect target objects
    if names == 'all':
        objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    else:
        name_list = [names] if isinstance(names, str) else list(names)
        objs = [bpy.context.scene.objects.get(n) for n in name_list]
        objs = [o for o in objs if o is not None]
    if not objs:
        return

    # 3. World-space corners from each object's bounding box (8 corners × n objects).
    # Image Empties have a degenerate (all-zero) bound_box — Blender doesn't compute
    # one for them — so derive the displayed image's local-space rectangle instead,
    # from empty_display_size (long-side world length), the image's pixel aspect
    # ratio, and empty_image_offset (fractional offset of the image rect from the
    # empty's origin; default (-0.5,-0.5) = centered).
    corners = []
    for obj in objs:
        mw = obj.matrix_world
        if obj.type == 'EMPTY' and obj.empty_display_type == 'IMAGE' and obj.data is not None:
            img_w, img_h = obj.data.size[0], obj.data.size[1]
            size = obj.empty_display_size
            if img_w >= img_h:
                w, h = size, size * img_h / img_w
            else:
                w, h = size * img_w / img_h, size
            ox, oy = obj.empty_image_offset
            local_corners = [
                (ox * w, oy * h, 0.0), ((ox + 1) * w, oy * h, 0.0),
                (ox * w, (oy + 1) * h, 0.0), ((ox + 1) * w, (oy + 1) * h, 0.0),
            ]
        else:
            local_corners = obj.bound_box
        for local_corner in local_corners:
            corners.append(mw @ Vector(local_corner))

    # 4. Center the view on the world-space centroid of the bounding box
    xs = [c.x for c in corners]; ys = [c.y for c in corners]; zs = [c.z for c in corners]
    world_center = Vector((
        (max(xs) + min(xs)) / 2,
        (max(ys) + min(ys)) / 2,
        (max(zs) + min(zs)) / 2,
    ))
    rv3d.view_location = world_center
    rv3d.update()

    # 5. Project corners → screen space and measure extent (pixels)
    screen_pts = []
    for c in corners:
        s = view3d_utils.location_3d_to_region_2d(region, rv3d, c)
        if s is not None:
            screen_pts.append(s)
    if len(screen_pts) < 2:
        return

    sxs = [p.x for p in screen_pts]; sys_ = [p.y for p in screen_pts]
    bb_w = max(sxs) - min(sxs)
    bb_h = max(sys_) - min(sys_)
    if bb_w < 1 and bb_h < 1:
        return

    # 6. Current fraction of viewport the bbox occupies (use the larger dimension)
    vw, vh = region.width, region.height
    frac_w = bb_w / vw if bb_w > 0 else 0.0
    frac_h = bb_h / vh if bb_h > 0 else 0.0
    current_frac = max(frac_w, frac_h)

    # view_distance ∝ 1/zoom: shrink it to zoom in, grow it to zoom out
    if current_frac > 1e-6:
        rv3d.view_distance *= current_frac / (ratio / 100.0)
    rv3d.update()


def setup_axis_ortho_view(area, region, rv3d, axis='RIGHT', zoom_out=1.0):
    """Set the viewport to an axis-aligned ortho view, fit all, then adjust zoom.

    axis: 'TOP'|'BOTTOM'|'LEFT'|'RIGHT'|'FRONT'|'BACK' (view3d.view_axis types)
    zoom_out: multiplier on view_distance after view_all.
              > 1.0 → farther away (zoom OUT); e.g. 1.5 = 50 % more headroom
              < 1.0 → closer         (zoom IN);  e.g. 0.5 = 2× closer
              = 1.0 → leave view_all's fit unchanged

    IMPORTANT: do NOT call focus_selected() AFTER this. view_selected re-fits
    view_distance to the current selection and silently overwrites zoom_out.
    Either use this function alone (fits the whole scene, then zoom), or
    use focus_selected alone (fits to selection, no zoom control).
    """
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.view3d.view_axis(type=axis)
        rv3d.view_perspective = 'ORTHO'
        bpy.ops.view3d.view_all(center=False)
        if zoom_out != 1.0:
            rv3d.view_distance *= zoom_out
    rv3d.update()


def material_shading(studio=None, world=False, floor=False, axes=False,
                     outline=False, wireframe=False):
    """Viewport shading set up for judging MATERIALS rather than geometry.

    The counterpart to solid_shading below. Solid shading ignores every
    texture on the object, so a run that has just baked a normal map and a
    colour map will show absolutely no change in a solid render — which
    looks exactly like a bake that failed.

    `world=False` lights with a studio HDRI instead of the scene world, so
    the model is lit the same way from every angle and two renders can be
    compared. Scene lighting is the right choice only once there is a scene.
    """
    import bpy
    # Deselect so nothing draws a selection outline over the model — but ONLY
    # in object mode. This operator's poll() fails in edit mode and RAISES,
    # killing the entire action, which is a bad trade for a cosmetic tweak that
    # show_outline_selected already handles a few lines below. Hit for real on
    # duck_run_001 step 1, where the builder set shading after entering edit
    # mode and lost the action to it.
    if bpy.context.mode == 'OBJECT':
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except RuntimeError:
            pass
    for a in bpy.context.screen.areas:
        if a.type != 'VIEW_3D':
            continue
        sp = a.spaces.active
        sp.shading.type = 'MATERIAL'
        sp.shading.use_scene_world = world
        sp.shading.use_scene_lights = world
        if studio:
            try:
                sp.shading.studiolight_rotate_z = 0.0
                sp.shading.studio_light = studio
            except TypeError:
                pass
        sp.shading.show_xray = False
        sp.overlay.show_floor = floor
        sp.overlay.show_axis_x = axes
        sp.overlay.show_axis_y = axes
        sp.overlay.show_outline_selected = outline
        sp.overlay.show_wireframes = wireframe
        if wireframe:
            sp.overlay.wireframe_opacity = 1.0


def solid_shading(shadows=True, cavity=False, light='STUDIO',
                  floor=False, axes=False, outline=False):
    """Solid viewport shading set up for judging GEOMETRY.

    The same dozen lines were copy-pasted into the top of nearly every action
    in every run. Two of them matter and are easy to get wrong:

    * cavity OFF by default. Cavity shading darkens concavities in SCREEN
      space whether or not there is geometry there, so it flatters damage and
      turns a broad shallow depression into a mottled blotch. Turn it on to
      find something, never to judge it.
    * the floor grid and axis lines off, because they draw over the model and
      read as edges in a render that is meant to show edges.
    """
    import bpy
    # Deselect so nothing draws a selection outline over the model — but ONLY
    # in object mode. This operator's poll() fails in edit mode and RAISES,
    # killing the entire action, which is a bad trade for a cosmetic tweak that
    # show_outline_selected already handles a few lines below. Hit for real on
    # duck_run_001 step 1, where the builder set shading after entering edit
    # mode and lost the action to it.
    if bpy.context.mode == 'OBJECT':
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except RuntimeError:
            pass
    for a in bpy.context.screen.areas:
        if a.type != 'VIEW_3D':
            continue
        sp = a.spaces.active
        sp.shading.type = 'SOLID'
        sp.shading.light = light
        sp.shading.show_shadows = shadows
        sp.shading.show_cavity = cavity
        sp.overlay.show_floor = floor
        sp.overlay.show_axis_x = axes
        sp.overlay.show_axis_y = axes
        sp.overlay.show_outline_selected = outline
