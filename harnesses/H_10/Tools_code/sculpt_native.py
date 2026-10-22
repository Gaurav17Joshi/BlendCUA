"""Blender's OWN sculpt brushes, driven from a script over the socket.

The counterpart to sculpt.py, which does the same job with hand-written numpy
on the vertex array. That module reimplements two brushes in ~250 lines and
can only ever have the brushes I write. This one hands the work to Blender's
sculpt engine — bpy.ops.sculpt.brush_stroke and the trim gesture operators —
so all 32 sculpt brush types, the boolean trims, the mesh filters and masking
are available for the cost of a wrapper.

Strokes are authored the same way as everywhere else in this harness:
normalized screen coordinates, x and y in 0..1 with y growing DOWN, picked off
a render of the current view. So the existing preview/pick workflow is
unchanged; only the thing that moves the vertices is different.

WHAT THIS COSTS
    sculpt.py could promise "cut exactly 30 mm" and verify 29.77 mm, because
    it owned the maths. A native brush is driven by SCREEN PIXELS and strength,
    and how deep it bites depends on brush size, the view, the surface and the
    number of dabs. So: set size/strength, then MEASURE the result. Every
    function here returns max/mean displacement for exactly that reason.

FIVE THINGS THAT COST ME AN HOUR EACH, ALL SPECIFIC TO 5.x
    1. tool_settings.sculpt.brush is READ-ONLY — brushes became assets. You
       cannot assign a different brush datablock. What works is retyping the
       ACTIVE datablock in place: brush.sculpt_brush_type = 'CREASE'.
       (bpy.ops.brush.asset_activate returns {'FINISHED'} but does NOT
       actually change the active brush, so it is a trap, not a solution.)
    2. Brush.sculpt_tool was renamed Brush.sculpt_brush_type.
    3. OperatorStrokeElement has no pen_flip and no use_falloff. Passing
       either raises a TypeError from the RNA layer. The complete set is:
       name, location, mouse, mouse_event, pressure, size, x_tilt, y_tilt,
       time, is_start.
    4. unified_paint_settings moved from ToolSettings to ToolSettings.sculpt,
       and while use_unified_size/strength are on they SILENTLY OVERRIDE
       brush.size and brush.strength. Every setting you make is ignored and
       you have no idea why. _configure turns them off.
    5. Sculpt symmetry defaults to X ON. Every stroke is silently mirrored,
       which is catastrophic for asymmetric damage. Off by default here.

AND ONE THAT IS EASY TO MISS
    Each stroke element carries BOTH a 2D `mouse` and a 3D `location`, and
    the operator needs the 3D one to be a real point on the surface. My first
    attempt left location at (0,0,0) and the brush tore a 0.37 m gouge across
    the model. _stroke_points raycasts every sample onto the object and drops
    the ones that miss.
"""

import math
import os

import bpy
import numpy as np
from mathutils import Vector
from bpy_extras.view3d_utils import (region_2d_to_origin_3d,
                                     region_2d_to_vector_3d)

from lib.pathgen import build_stroke_path

# Sensible starting points per brush, so an action only has to name the brush.
# Sizes are in SCREEN PIXELS — they are not world units and they do not scale
# with the object; a brush is as big as it looks in the viewport.
DEFAULTS = {
    'DRAW':              dict(size=60, strength=0.50),
    'DRAW_SHARP':        dict(size=35, strength=0.60, hardness=0.50),
    # The clay family builds material up to an "area plane" fitted to the
    # surface under the brush, so with plane_offset=0 on an ALREADY FLAT
    # surface the target plane is the surface and the brush moves nothing —
    # measured 13,816 verts "moved" by under 0.05 mm. plane_offset (in brush
    # radii) lifts that target plane off the surface and is what makes clay
    # build rather than merely level.
    'CLAY':              dict(size=60, strength=0.50, plane_offset=0.15),
    'CLAY_STRIPS':       dict(size=60, strength=0.55, plane_offset=0.20,
                              tip_roundness=0.18, normal_radius_factor=1.0),
    'CREASE':            dict(size=32, strength=0.60, crease_pinch_factor=0.60),
    'BLOB':              dict(size=50, strength=0.50),
    'INFLATE':           dict(size=60, strength=0.40),
    'PINCH':             dict(size=45, strength=0.50),
    # 5.x merged Flatten / Scrape / Fill into one PLANE brush, and which of
    # the three you get depends on plane_height and plane_depth. They name the
    # side of the area plane the brush REACHES INTO, not the direction it
    # pushes — which is the opposite of what the names suggest, and measuring
    # is the only way to be sure:
    #     flatten = height 1, depth 1     (levels both ways)
    #     scrape  = height 1, depth 0     (only takes material off  -> in)
    #     fill    = height 0, depth 1     (only adds material       -> out)
    # Both default to 0.0 on a bare datablock, which gives the brush zero
    # range — it ran over a rough surface at strength 0.9 and moved exactly 0
    # vertices, silently. Only the Essentials brush ASSETS carry non-zero
    # presets, and asset activation does not work over the socket, so these
    # have to be set explicitly.
    'PLANE':             dict(size=70, strength=0.70, plane_offset=0.0,
                              plane_depth=1.0, plane_height=1.0,
                              use_plane_trim=True, plane_trim=0.5),
    'MULTIPLANE_SCRAPE': dict(size=70, strength=0.70,
                              multiplane_scrape_angle=20.0),
    'SMOOTH':            dict(size=70, strength=0.50),
    'LAYER':             dict(size=55, strength=0.50),
    'NUDGE':             dict(size=55, strength=0.50),
    'SNAKE_HOOK':        dict(size=55, strength=0.50),
}

# Brush settings this module is willing to forward. Anything not in here is
# rejected loudly rather than silently ignored — a misspelled brush setting
# that quietly does nothing is the worst possible failure mode for this kind
# of work, because the render just looks a bit wrong.
_BRUSH_SETTINGS = (
    "size", "strength", "hardness", "spacing", "auto_smooth_factor",
    "normal_radius_factor", "area_radius_factor", "jitter", "sharp_threshold",
    "plane_offset", "plane_trim", "use_plane_trim", "plane_depth",
    "plane_height", "plane_inversion_mode", "crease_pinch_factor",
    "multiplane_scrape_angle", "use_multiplane_scrape_dynamic",
    "tip_roundness", "tip_scale_x", "use_frontface", "use_original_normal",
    "use_original_plane", "use_accumulate", "use_space_attenuation",
    "falloff_shape", "sculpt_plane", "stroke_method", "direction",
    "smooth_deform_type", "surface_smooth_shape_preservation",
    "stabilize_plane", "texture_sample_bias",
    # Sizing mode. brush.size (pixels) is only honoured under 'VIEW'; under
    # 'SCENE' Blender uses unprojected_radius (metres) and ignores the pixels.
    "use_locked_size", "unprojected_radius",
    # Whether the per-dab pressure carried by each stroke element is allowed
    # to scale strength and radius. See apply_stroke(profile=...).
    "use_pressure_strength", "use_pressure_size",
)


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------

def viewport():
    """(window, area, region, rv3d) for the first VIEW_3D.

    The sculpt operators are viewport operators: they need a real region to
    resolve brush size (pixels) and view-relative planes against. They run
    fine over the socket PROVIDED they are given that region through
    temp_override — which is the thing I wrongly assumed was impossible here.
    """
    win = bpy.context.window_manager.windows[0]
    area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
    if area is None:
        raise RuntimeError("no VIEW_3D area")
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        raise RuntimeError("no WINDOW region in the VIEW_3D")
    return win, area, region, area.spaces.active.region_3d


def world_to_px(region, rv3d, radius_world, at_world):
    """How many SCREEN PIXELS a world-space radius spans at a given point.

    Brush size is in pixels, but damage is specified in millimetres — "chip
    this edge by 20 mm" — and the conversion depends entirely on how zoomed in
    the view is. Getting it wrong is silent: a 4 m pillar fitted to a 603 px
    viewport puts a 22 mm brush at 3 px, which does almost nothing and looks
    like the brush failed.

    Measured, not derived: project the point and the point plus one screen-
    right radius, and take the distance. That is correct in ortho and in
    perspective, and it does not care what view_distance means for each.
    """
    right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    a = _project_point(region, rv3d, Vector(at_world))
    b = _project_point(region, rv3d, Vector(at_world) + right * radius_world)
    if a is None or b is None:
        raise RuntimeError("world_to_px: point is not on screen")
    return float((a - b).length)


def _project_point(region, rv3d, world):
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    return location_3d_to_region_2d(region, rv3d, world)


def frame_ortho(region, rv3d, axis_dir, center_world, half_height):
    """Ortho view down `axis_dir`, centred on a point, showing +/- half_height.

    fit_objects_ortho_view frames whole OBJECTS; sculpting a 26 cm block on a
    4 m pillar needs to frame a REGION of one. Ortho pixel scale is exactly
    inversely proportional to view_distance, so one measurement gives the
    distance needed — no iteration.
    """
    d = Vector(axis_dir).normalized()
    rv3d.view_perspective = 'ORTHO'
    rv3d.view_rotation = d.to_track_quat('Z', 'Y')
    rv3d.view_location = Vector(center_world)
    rv3d.view_distance = 1.0
    rv3d.update()

    ppm_now = world_to_px(region, rv3d, 1.0, center_world)
    ppm_want = (region.height * 0.92) / (2.0 * half_height)
    rv3d.view_distance = 1.0 * ppm_now / ppm_want
    rv3d.update()
    return world_to_px(region, rv3d, 1.0, center_world)      # final px per m


def _verts(obj):
    """LOCAL coordinates and normals — what the displacement report needs,
    since it only ever compares a before and an after of the same object."""
    n = len(obj.data.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    no = np.empty(n * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("normal", no)
    return co.reshape(n, 3), no.reshape(n, 3)


def world_arrays(obj):
    """(N,3) WORLD coordinates and world normals.

    Anything that compares mesh positions against world-space geometry — a
    corner at (w, -w, z), a stroke path, a camera direction — must use this,
    not _verts. They agree only while the object transform is identity, which
    is a coincidence waiting to break.
    """
    co, no = _verts(obj)
    mw = np.array(obj.matrix_world.to_4x4(), dtype=np.float64)
    world = co @ mw[:3, :3].T + mw[:3, 3]
    nm = np.linalg.inv(mw[:3, :3]).T
    wn = no @ nm.T
    lens = np.linalg.norm(wn, axis=1)
    lens[lens < 1e-12] = 1.0
    return world, wn / lens[:, None]


def _report(before, after, label, extra=""):
    """Displacement stats. Native brushes are not predictable, so measuring
    the result is not optional bookkeeping — it is the only feedback there is.

    The stats are SIGNED, projected on each vertex's original normal: out is
    positive, in is negative. An unsigned magnitude is worse than useless here
    — it made a correctly-inverted brush report numbers identical to the
    normal one, which had me chasing a bug in the INVERT flag that did not
    exist.
    """
    (b, bn), (a, _an) = before, after
    if b.shape != a.shape:
        out = {"label": label, "topology_changed": True,
               "verts_before": int(b.shape[0]), "verts_after": int(a.shape[0]),
               "max_out": None, "max_in": None, "mean_signed": None,
               "verts_moved": None}
        print("[native:%s] topology rebuilt: %d -> %d verts %s"
              % (label, out["verts_before"], out["verts_after"], extra))
        return out

    delta = a - b
    signed = np.einsum("ij,ij->i", delta, bn)          # + = outward
    moved = np.linalg.norm(delta, axis=1) > 1e-6
    out = {"label": label, "topology_changed": False,
           "verts_moved": int(moved.sum()),
           "max_out": float(signed.max()) if signed.size else 0.0,
           "max_in": float(signed.min()) if signed.size else 0.0,
           "mean_signed": float(signed[moved].mean()) if moved.any() else 0.0}
    print("[native:%s] %d verts moved, out %+.4f m / in %+.4f m, mean %+.4f m %s"
          % (label, out["verts_moved"], out["max_out"], out["max_in"],
             out["mean_signed"], extra))
    return out


# --------------------------------------------------------------------------
# brush configuration
# --------------------------------------------------------------------------

def _bootstrap_brush():
    """Get a sculpt brush active on a freshly started Blender.

    ToolSettings.sculpt.brush is None until sculpt mode has been entered once
    in the session — brushes are assets and nothing activates one before then.
    Entering sculpt mode makes Blender pull the default from the Essentials
    library; that is the only reliable way in, since the property is read-only
    and bpy.ops.brush.asset_activate is unreliable.
    """
    obj = bpy.context.view_layer.objects.active
    if obj is None or obj.type != 'MESH':
        raise RuntimeError("no active mesh object to enter sculpt mode with")
    prev = bpy.context.mode
    bpy.ops.object.mode_set(mode='SCULPT')
    bpy.ops.object.mode_set(mode='OBJECT' if prev == 'OBJECT' else 'OBJECT')
    br = bpy.context.tool_settings.sculpt.brush
    if br is None:
        raise RuntimeError(
            "still no active sculpt brush after entering sculpt mode — "
            "the Essentials brush asset library is probably missing")
    print("[native] bootstrapped sculpt brush %r" % br.name)
    return br


# --------------------------------------------------------------------------
# brush textures
# --------------------------------------------------------------------------

def image_texture(name, path, reload=True):
    """A legacy IMAGE Texture datablock wrapping a PNG on disk.

    Brush textures are the OLD texture system (bpy.data.textures) — the one
    the shader nodes replaced everywhere else. brush.texture will not take a
    node group and will not take an Image directly; it wants a Texture, and
    the only Texture type that can carry an arbitrary height map is 'IMAGE'.

    Idempotent by name: re-running an action reloads the file into the same
    datablock instead of piling up Texture.001, Texture.002, ... Blender
    caches image pixels, so a regenerated PNG at the same path is NOT picked
    up without the explicit reload.
    """
    if not os.path.exists(path):
        raise FileNotFoundError("brush texture image not found: %s" % path)

    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.load(path, check_existing=False)
        img.name = name
    elif reload:
        img.filepath = path
        img.reload()

    tex = bpy.data.textures.get(name)
    if tex is None:
        tex = bpy.data.textures.new(name, type='IMAGE')
    elif tex.type != 'IMAGE':
        raise RuntimeError("texture %r already exists as %s, not IMAGE"
                           % (name, tex.type))
    # A height map is DATA, not a picture. Left on the default sRGB the
    # image is colour-managed on read and a mean of 0.50 arrives at the brush
    # as 0.21, which silently drags every textured stroke inward and makes
    # texture_sample_bias impossible to reason about.
    img.colorspace_settings.name = 'Non-Color'

    tex.image = img
    if hasattr(tex, "extension"):
        tex.extension = 'REPEAT'
    # THE ONE THAT COSTS A DAY. An ImageTexture defaults to use_alpha=True,
    # meaning "take the intensity from the alpha channel". A grayscale PNG has
    # no alpha channel, so alpha reads 1.0 at every pixel and the texture
    # evaluates to a CONSTANT 1.0 — attached, valid, reported by every
    # readback, and completely flat. A brush carrying it behaves exactly like
    # an untextured brush, so strength, amplitude, scale and mapping all look
    # like they do nothing, because with a constant texture they genuinely
    # don't. Check with tex.evaluate((x, y, 0))[3]: it must VARY.
    tex.use_alpha = False
    tex.intensity, tex.contrast, tex.saturation = 1.0, 1.0, 1.0
    return tex


def _set_map_mode(br, slot, mode):
    """Set the mapping, with a usable error when the brush cannot do it.

    map_mode is a DYNAMIC enum: the items depend on the active brush type, so
    bl_rna advertises all six while the brush only accepts some. AREA_PLANE in
    particular needs a brush that computes an area plane — the plane/clay
    family — and is simply absent on DRAW, which fails at assignment with a
    raw RNA TypeError that never mentions the brush.
    """
    try:
        slot.map_mode = mode
    except TypeError as exc:
        raise TypeError(
            "brush texture mapping %r is not available for sculpt_brush_type "
            "%r. %s  (AREA_PLANE only exists on the plane/clay family — "
            "PLANE, CLAY, CLAY_STRIPS, MULTIPLANE_SCRAPE. For a flat face "
            "viewed head-on, TILED is equivalent and does not restamp.)"
            % (mode, br.sculpt_brush_type, exc)) from None


def _apply_texture(br, spec):
    """Attach or detach the brush texture.

    Called on EVERY stroke, including with spec=None, for the same reason
    every brush setting is rewritten every time: the brush datablock is
    global and sticky, so a texture left behind by the previous action would
    silently modulate the next stroke that believed it was untextured.

    spec: None, or {"image": <png path>, "name": ..., "map_mode": ...,
                    "angle": deg, "use_random": bool, "random_angle": deg,
                    "use_rake": bool, "scale": (x,y,z), "offset": (x,y,z)}

    map_mode is the mapping in the reference screenshot's terms:
        AREA_PLANE  texture stamped on the plane of the surface under the
                    brush. Only offered by the plane/clay family of brushes,
                    NOT by DRAW — see _set_map_mode.
        VIEW_PLANE  same, but aligned to the screen
        TILED       tiles across the screen, fixed to it, so a drag reveals
                    new texture instead of restamping
        3D          sampled in object space, so overlapping dabs agree with
                    each other; scale is then in Blender units
    """
    if not spec:
        br.texture = None
        return None

    spec = dict(spec)
    if "datablock" in spec:
        # an already-built Texture (procedural, or one made elsewhere)
        tex = bpy.data.textures[spec.pop("datablock")]
        spec.pop("name", None)
        spec.pop("image", None)
    else:
        image = spec.pop("image")
        name = (spec.pop("name", None)
                or os.path.splitext(os.path.basename(image))[0])
        tex = image_texture(name, image)
    br.texture = tex

    slot = br.texture_slot
    _set_map_mode(br, slot, spec.pop("map_mode", 'TILED'))
    slot.angle        = math.radians(float(spec.pop("angle", 0.0)))
    slot.use_rake     = bool(spec.pop("use_rake", False))
    # A stamping mapping restamps the SAME image at every dab; without a
    # random angle a dragged stroke repeats one motif down its whole length
    # and reads as a pattern rather than as stone.
    slot.use_random   = bool(spec.pop("use_random", True))
    slot.random_angle = math.radians(float(spec.pop("random_angle", 360.0)))
    slot.scale        = spec.pop("scale", (1.0, 1.0, 1.0))
    slot.offset       = spec.pop("offset", (0.0, 0.0, 0.0))
    if spec:
        raise KeyError("unknown texture setting(s) %s" % sorted(spec))
    return tex


# LEAVE THIS OFF. See _localize.
LOCALIZE = False


def _localize(br):
    """Make the active brush local. DISABLED — it breaks everything. Kept,
    with its evidence, so nobody re-derives this.

    The chain, in order:

    1. The brush sculpt mode activates is LINKED from the Essentials asset
       library. A linked datablock cannot hold a pointer to local data, so
       `br.texture = tex` raises nothing, reports nothing and does nothing:
       it reads back None and the texture keeps zero users. Value properties
       (size, strength, sculpt_brush_type) DO stick, so only the texture is
       lost, silently.

    2. make_local() fixes the linking — but is a no-op both when a local
       counterpart already exists and when the datablock has no users, and
       the asset brush has no users. Neither no-op reports anything either.

    3. And with all that solved, it turns out bpy.ops.sculpt.brush_stroke
       does NOT use the local copy. It resolves its brush from the paint
       mode's asset reference. Measured, on a flat slab: with localizing ON,
       brush size 15 px and 60 px cut the same depth AND the same width
       (-46.33 mm, 100 mm), and strength 0.05 and 1.00 were indistinguishable
       — every stroke ran on the untouched asset brush's own defaults. With
       it OFF, the same sweep gives 0.9 / 3.6 / 13.6 mm for those sizes and
       0.9 / 38.5 / 46.0 mm for those strengths.

    So localizing trades away ALL brush control for a texture that still does
    not apply. The conclusion is that a brush texture cannot be used from a
    script at all: attaching one requires a local brush, and the operator
    only honours the linked one. Surface texture comes from displace()
    instead.

    (mem/texture_test_001/steps/step_002, reports 01-03.)
    """
    ts = bpy.context.tool_settings.sculpt
    if br.library is None or not LOCALIZE:
        return br

    while True:
        stale = next((b for b in bpy.data.brushes
                      if b.library is None and b != br), None)
        if stale is None:
            break
        bpy.data.brushes.remove(stale, do_unlink=True)

    br.use_fake_user = True
    br.make_local()
    now = ts.brush
    if now is None or now.library is not None:
        raise RuntimeError("could not make the active sculpt brush local")
    return now


def _configure(brush_type, settings, texture=None):
    """Retype the active brush datablock and apply settings.

    NB this MUTATES the shared active brush rather than swapping datablocks,
    because ToolSettings.sculpt.brush is read-only in 5.x. Consequence: brush
    state is global and sticky, so every setting that matters is written on
    every call — never rely on what a previous stroke left behind.
    """
    ts = bpy.context.tool_settings.sculpt
    br = ts.brush
    if br is None:
        br = _bootstrap_brush()
    br = _localize(br)

    # Unified settings silently override brush.size / brush.strength.
    ups = getattr(ts, "unified_paint_settings", None)
    if ups is not None:
        for flag in ("use_unified_size", "use_unified_strength",
                     "use_unified_color"):
            if hasattr(ups, flag):
                setattr(ups, flag, False)

    br.sculpt_brush_type = brush_type
    _apply_texture(br, texture)

    merged = dict(DEFAULTS.get(brush_type, dict(size=50, strength=0.5)))
    merged.update(settings)
    for k, v in merged.items():
        if k not in _BRUSH_SETTINGS:
            raise KeyError("unknown brush setting %r (known: %s)"
                           % (k, ", ".join(sorted(_BRUSH_SETTINGS))))
        if not hasattr(br, k):
            raise KeyError("Brush has no %r in Blender %s"
                           % (k, bpy.app.version_string))
        setattr(br, k, v)
    return br


def sample_profile(profile, n):
    """A pressure value per dab, resampled to n dabs.

    `profile` is either a callable f(t) -> 0..1 with t running 0..1 along the
    stroke, or a short sequence of values that is linearly interpolated to
    length n — [0, 1, 0.4, 1, 0] is five keyframes, not five dabs.
    """
    if profile is None:
        return None
    if n <= 0:
        return []
    if callable(profile):
        vals = [float(profile(i / max(1.0, n - 1.0))) for i in range(n)]
    else:
        src = [float(v) for v in profile]
        if len(src) == 1:
            vals = src * n
        else:
            xs = np.linspace(0.0, 1.0, len(src))
            vals = list(np.interp(np.linspace(0.0, 1.0, n), xs, src))
    # Blender treats pressure 0 as "no dab at all", which is what a feathered
    # end wants, but a negative would be a silent sign flip.
    return [min(1.0, max(0.0, float(v))) for v in vals]


def set_symmetry(x=False, y=False, z=False):
    """Sculpt symmetry. X defaults to ON in Blender, which mirrors every
    stroke — fine for a character, wrong for weathering. Off unless asked.
    """
    ts = bpy.context.tool_settings.sculpt
    ts.use_symmetry_x, ts.use_symmetry_y, ts.use_symmetry_z = x, y, z


# --------------------------------------------------------------------------
# strokes
# --------------------------------------------------------------------------

def _resolve_path(stroke):
    """Stroke dict -> dense [(x_norm, y_norm), ...]; same fields as paint.py."""
    return build_stroke_path(
        stroke["points"],
        waviness=stroke.get("waviness", "straight"),
        amplitude=stroke.get("amplitude"),
        frequency=stroke.get("frequency"),
        seed=int(stroke.get("seed", 0)),
        smooth=bool(stroke.get("smooth", True)),
        roughness=float(stroke.get("roughness", 1.0)),
        resolved=bool(stroke.get("resolved", False)),
    )


def _stroke_points(path2d, obj, region, rv3d, size, step_px=4.0):
    """Normalized screen path -> OperatorStrokeElement dicts.

    Each sample is raycast onto the object so `location` is a real point on
    the surface. Samples that miss the object are dropped: a stroke element
    with a bogus location does not do nothing, it drags geometry to that
    bogus point.

    `location` is OBJECT SPACE, not world. Measured, because it is invisible
    on anything sitting at the origin — an identical grid stroked at the
    origin cut 210 mm, the same grid moved to x=20 and stroked with world
    coordinates cut exactly 0.000 mm, and converting those same coordinates
    to local brought it back to 210 mm. Every object in this project so far
    has had an identity matrix, so the bug had nowhere to show.
    """
    mwi = obj.matrix_world.inverted()
    rot = mwi.to_3x3()

    # Resample to a fixed pixel step. Blender's SPACE stroke method spaces its
    # dabs between consecutive samples, so the samples only need to describe
    # the path finely enough not to cut corners.
    px = np.array([[p[0] * region.width, (1.0 - p[1]) * region.height]
                   for p in path2d], dtype=np.float64)
    if px.shape[0] < 2:
        return []
    seg = np.linalg.norm(np.diff(px, axis=0), axis=1)
    total = float(seg.sum())
    if total < 1e-6:
        return []
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    want = np.arange(0.0, total, max(1.0, step_px))
    xs = np.interp(want, cum, px[:, 0])
    ys = np.interp(want, cum, px[:, 1])

    out = []
    for i, (mx, my) in enumerate(zip(xs, ys)):
        origin = region_2d_to_origin_3d(region, rv3d, (mx, my))
        direction = region_2d_to_vector_3d(region, rv3d, (mx, my))
        if origin is None or direction is None:
            continue
        hit, loc, _nrm, _idx = obj.ray_cast(mwi @ origin,
                                            (rot @ direction).normalized())
        if not hit:
            continue
        out.append({
            "name": "s%d" % i,
            "location": (loc.x, loc.y, loc.z),
            "mouse": (float(mx), float(my)),
            "mouse_event": (float(mx), float(my)),
            "pressure": 1.0,
            "size": float(size),
            "x_tilt": 0.0,
            "y_tilt": 0.0,
            "time": i * 0.01,
            "is_start": i == 0,
        })
    return out


def apply_stroke(obj_name, brush, stroke, invert=False, symmetry=(False,) * 3,
                 step_px=4.0, texture=None, label=None, profile=None,
                 profile_size=True, **settings):
    """Drag one native brush along one screen-space path.

    obj_name  : mesh object to sculpt.
    brush     : a sculpt_brush_type — 'CREASE', 'CLAY_STRIPS', 'DRAW_SHARP',
                'PLANE', 'MULTIPLANE_SCRAPE', 'SMOOTH', ...
    stroke    : {"points": [(x,y), ...], "waviness": ..., "seed": ...} in
                normalized screen coords, y DOWN — identical to paint.py and
                sculpt.py, so a path can be authored once and driven by any
                of the three.
    invert    : run the brush in INVERT mode (carve instead of build, etc).
    texture   : brush texture spec, see _apply_texture. None detaches any
                texture a previous action left on the brush.
    profile   : how hard the brush presses ALONG the stroke — a callable
                f(t) -> 0..1 or a short list of keyframes (see
                sample_profile). None means press evenly, the old behaviour.
                This is what stops a stroke ending abruptly: the tail dabs
                carry pressure 0 and simply do not land. Measured on a flat
                grid, an even stroke cut 210 mm from end to end while the
                same stroke under sin(pi*t) ran 1 - 208 - 1 mm.
    profile_size : whether the profile scales the RADIUS as well as the
                strength. True (the default) narrows the stroke wherever it
                presses lighter, which is how a crack actually behaves;
                False keeps the width constant and only fades the depth,
                which is what a broad shoulder pass wants.
    settings  : any brush setting from _BRUSH_SETTINGS — size (PIXELS),
                strength, hardness, crease_pinch_factor, plane_offset, ...
                Unknown names raise rather than being ignored.

    Returns the displacement report. Nothing here predicts the result; read
    max_disp and adjust size/strength.
    """
    obj = bpy.data.objects[obj_name]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    win, area, region, rv3d = viewport()
    before = _verts(obj)

    path2d = _resolve_path(stroke)
    br = _configure(brush, settings, texture)
    pts = _stroke_points(path2d, obj, region, rv3d, br.size, step_px)
    if len(pts) < 2:
        raise RuntimeError("stroke %r projected to %d surface points — the "
                           "path missed the object in this view"
                           % (stroke.get("label", ""), len(pts)))

    # Pressure is stated explicitly on every call, not only when a profile is
    # given: these two flags live on a brush datablock that outlives the
    # action, so leaving them as the last stroke happened to want is how a
    # profile silently stops working three actions later.
    press = sample_profile(profile, len(pts))
    if "use_pressure_strength" not in settings:
        br.use_pressure_strength = press is not None
    if "use_pressure_size" not in settings:
        br.use_pressure_size = press is not None and bool(profile_size)
    if press is not None:
        for p, v in zip(pts, press):
            p["pressure"] = v

    set_symmetry(*symmetry)
    bpy.ops.object.mode_set(mode='SCULPT')
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.sculpt.brush_stroke(
                stroke=pts, mode='INVERT' if invert else 'NORMAL')
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    rep = _report(before, _verts(obj), label or brush,
                  "(%s size=%d str=%.2f %d dabs%s%s)"
                  % (brush, br.size, br.strength, len(pts),
                     " INVERT" if invert else "",
                     " tex=%s/%s" % (br.texture.name, br.texture_slot.map_mode)
                     if br.texture else ""))
    # What the operator ACTUALLY had, reported back rather than assumed. A
    # texture that failed to attach changes nothing observable except the
    # numbers, so the only way to tell a texture problem from a tuning problem
    # is to carry the brush state out with the result.
    rep["texture"] = br.texture.name if br.texture else None
    rep["map_mode"] = br.texture_slot.map_mode if br.texture else None
    rep["brush_is_local"] = br.library is None
    rep["strength"] = br.strength
    rep["size_px"] = br.size
    return rep


def apply_strokes(obj_name, brush, strokes, **kw):
    """Several paths with one brush. Returns a list of reports."""
    return [apply_stroke(obj_name, brush, s,
                         label=s.get("label") or None, **kw)
            for s in strokes]


def world_path_strokes(paths_world, radius_world=None, size_px=None,
                       center_world=None, labels=None,
                       waviness="straight", smooth=False,
                       show_anchors=False, color_hint=None):
    """Project world-space polylines into the current viewport stroke format.

    ``paths_world`` is a sequence of 3-D polylines. The returned ``strokes``
    use normalized top-left screen coordinates, exactly as
    ``paint.stroke_lines_preview`` and ``apply_stroke`` require. ``radius_world``
    is converted to one native screen-pixel diameter at the current view; pass
    ``size_px`` instead when the native pixel size is already known. A caller
    must keep the view fixed between this function and the operation that uses
    its result.

    This is the world-space counterpart to the existing screen-space stroke
    API. It deliberately does not raycast or mutate the mesh, so the same
    projected paths can be previewed and then applied without a second hand-
    written projection formula. Labels and colour hints are optional metadata.
    """
    if paths_world is None:
        raise ValueError("world_path_strokes: paths_world is required")
    paths = [list(path) for path in paths_world]
    if not paths:
        raise ValueError("world_path_strokes: at least one path is required")
    if labels is not None and len(labels) != len(paths):
        raise ValueError("world_path_strokes: labels/path count differs")
    if radius_world is not None and size_px is not None:
        raise ValueError("world_path_strokes: pass radius_world or size_px, not both")
    if radius_world is not None and float(radius_world) <= 0.0:
        raise ValueError("world_path_strokes: radius_world must be positive")
    if size_px is not None and float(size_px) < 1.0:
        raise ValueError("world_path_strokes: size_px must be at least one")

    _win, _area, region, rv3d = viewport()
    from lib.view import project_to_norm

    strokes = []
    for index, path in enumerate(paths):
        if len(path) < 2:
            raise ValueError("world_path_strokes: every path needs 2 points")
        points = []
        for point in path:
            projected = project_to_norm(Vector(point), region, rv3d)
            if projected is None:
                label = labels[index] if labels is not None else index
                raise RuntimeError(
                    "world_path_strokes: path %r has a point off screen" % label)
            points.append(tuple(projected))
        stroke = {
            "points": points,
            "waviness": waviness,
            "smooth": bool(smooth),
            "show_anchors": bool(show_anchors),
        }
        if labels is not None:
            stroke["label"] = str(labels[index])
        if color_hint is not None:
            stroke["color_hint"] = color_hint
        strokes.append(stroke)

    centre = None
    if radius_world is not None:
        if center_world is None:
            sample = paths[0][len(paths[0]) // 2]
            centre = Vector(sample)
        else:
            centre = Vector(center_world)
        diameter = 2.0 * world_to_px(region, rv3d, float(radius_world), centre)
        size_px = max(3, int(round(diameter)))
    elif center_world is not None:
        centre = Vector(center_world)

    return {
        "strokes": strokes,
        "size_px": int(round(size_px)) if size_px is not None else None,
        "center_world": tuple(centre) if centre is not None else None,
    }


def apply_world_strokes(obj_name, brush, paths_world, radius_world=None,
                        size_px=None, center_world=None, labels=None,
                        invert=False, symmetry=(False,) * 3, step_px=4.0,
                        texture=None, profile=None, profile_size=True,
                        waviness="straight", smooth=False,
                        show_anchors=False, color_hint=None, **settings):
    """Apply one native brush to several world-space polylines.

    The view is sampled once, a physical ``radius_world`` is converted to a
    native pixel diameter, and each projected path is sent through the same
    measured ``apply_stroke`` implementation. The return value contains the
    per-path reports plus the resolved screen strokes and size, making it
    suitable for a preview/apply pair and for persisted diagnostics.

    ``paths_world`` and ``labels`` are parallel sequences. This helper is
    intentionally subject-neutral: it follows any measured list of world
    points and does not assume a particular object, axis, or feature type.
    Keep the viewport unchanged until all paths have been applied.
    """
    if "size" in settings and (radius_world is not None or size_px is not None):
        raise ValueError(
            "apply_world_strokes: use radius_world/size_px instead of settings[size]")
    plan = world_path_strokes(
        paths_world, radius_world=radius_world, size_px=size_px,
        center_world=center_world, labels=labels, waviness=waviness,
        smooth=smooth, show_anchors=show_anchors, color_hint=color_hint)
    call_settings = dict(settings)
    if plan["size_px"] is not None:
        call_settings["size"] = plan["size_px"]
    reports = []
    for stroke in plan["strokes"]:
        reports.append(apply_stroke(
            obj_name, brush, stroke, invert=invert, symmetry=symmetry,
            step_px=step_px, texture=texture, profile=profile,
            profile_size=profile_size, label=stroke.get("label") or None,
            **call_settings))
    return {
        "reports": reports,
        "strokes": plan["strokes"],
        "size_px": plan["size_px"],
        "center_world": plan["center_world"],
    }


# --------------------------------------------------------------------------
# trim gestures — real booleans, not displacement
# --------------------------------------------------------------------------

def trim_box(obj_name, x0, y0, x1, y1, mode='DIFFERENCE', orientation='VIEW',
             extrude='FIXED', solver='EXACT', front_only=True,
             cursor_depth=False, label="trim_box"):
    """Cut a box through the model along the view axis.

    This is a genuine boolean: it removes material and REBUILDS TOPOLOGY (in
    testing 659,458 -> 610,648 verts). Anything downstream holding vertex
    indices across this call is invalid, so it cannot be mixed with
    index-based numpy work inside one action.

    Rect is in normalized screen coords, y DOWN, matching the stroke paths.
    """
    obj = bpy.data.objects[obj_name]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    win, area, region, _rv3d = viewport()
    before = _verts(obj)

    xs = sorted((x0 * region.width, x1 * region.width))
    # y flips: normalized y grows DOWN, region y grows UP.
    ys = sorted(((1.0 - y0) * region.height, (1.0 - y1) * region.height))

    bpy.ops.object.mode_set(mode='SCULPT')
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.sculpt.trim_box_gesture(
                xmin=int(xs[0]), xmax=int(xs[1]),
                ymin=int(ys[0]), ymax=int(ys[1]),
                trim_mode=mode, trim_orientation=orientation,
                trim_extrude_mode=extrude, trim_solver=solver,
                use_front_faces_only=front_only,
                use_cursor_depth=cursor_depth)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    return _report(before, _verts(obj), label, "(%s %s)" % (mode, orientation))


def trim_lasso(obj_name, points, mode='DIFFERENCE', orientation='VIEW',
               extrude='FIXED', solver='EXACT', front_only=True,
               cursor_depth=False, label="trim_lasso"):
    """Same as trim_box but through an arbitrary closed outline.

    `points` is a list of (x, y) in normalized screen coords, y DOWN. This is
    the one that makes irregular corner breaks easy: the outline IS the
    silhouette of the missing chunk, so it can be drawn to look broken
    instead of being derived from a falloff function.
    """
    obj = bpy.data.objects[obj_name]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    win, area, region, _rv3d = viewport()
    before = _verts(obj)

    path = [{"name": "p%d" % i,
             "loc": (int(p[0] * region.width),
                     int((1.0 - p[1]) * region.height)),
             "time": i * 0.01}
            for i, p in enumerate(points)]

    bpy.ops.object.mode_set(mode='SCULPT')
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.sculpt.trim_lasso_gesture(
                path=path,
                trim_mode=mode, trim_orientation=orientation,
                trim_extrude_mode=extrude, trim_solver=solver,
                use_front_faces_only=front_only,
                use_cursor_depth=cursor_depth)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    return _report(before, _verts(obj), label,
                   "(%s %s, %d outline pts)" % (mode, orientation, len(path)))


# --------------------------------------------------------------------------
# texture displacement — the route that actually works
# --------------------------------------------------------------------------

def displace(obj_name, texture, strength, mid_level=0.5, direction='NORMAL',
             texture_coords='LOCAL', coords_object=None, vertex_group=None,
             invert_group=False, label=None):
    """Push the surface along its normals by a texture. Applied immediately.

    WHY THIS EXISTS. bpy.ops.sculpt.brush_stroke ignores the brush texture
    when it is driven with an explicit stroke list instead of a real mouse.
    Not the image, not the mapping, not the colour space: a plain CLOUDS
    procedural changes the result by exactly nothing too, and an attached,
    valid, varying texture gives a stroke bit-identical to an untextured one
    (-46.32 mm in every lane of mem/texture_test_001). Texture sampling in
    sculpt depends on stroke state that only the interactive path sets up.

    So surface texture comes from a modifier instead. It is not a downgrade:
    strength is in METRES rather than an unpredictable fraction of the brush
    radius, it covers a whole face in one operation rather than in bands, and
    a vertex group gives a far better mask than a brush footprint does.

    strength       displacement range in metres, centred on mid_level
    mid_level      texture value that means "no movement" — 0.5 for a map
                   built around a 0.5 midpoint, so bright pushes out and dark
                   cuts in
    texture_coords LOCAL uses the object's own XY, which is right for a
                   surface lying in XY and WRONG for a vertical face — an
                   image sampled on XY is constant along the face's normal
                   and smears into stripes. Use OBJECT with coords_object set
                   to an Empty whose XY plane lies parallel to the face.
    vertex_group   restricts the effect, with the group's weights acting as a
                   falloff — this is how one face gets textured and its
                   neighbours do not
    """
    obj = bpy.data.objects[obj_name]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    tex = (texture if isinstance(texture, bpy.types.Texture)
           else bpy.data.textures[texture])
    before = _verts(obj)

    mod = obj.modifiers.new(name="blendcua_displace", type='DISPLACE')
    mod.texture = tex
    mod.strength = float(strength)
    mod.mid_level = float(mid_level)
    mod.direction = direction
    mod.texture_coords = texture_coords
    if coords_object is not None:
        mod.texture_coords_object = (
            coords_object if isinstance(coords_object, bpy.types.Object)
            else bpy.data.objects[coords_object])
    if vertex_group:
        mod.vertex_group = vertex_group
        mod.invert_vertex_group = bool(invert_group)

    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except Exception:
        obj.modifiers.remove(mod)
        raise

    return _report(before, _verts(obj), label or "displace",
                   "(%s %s %+.4f m mid %.2f%s)"
                   % (tex.name, texture_coords, strength, mid_level,
                      " group=%s" % vertex_group if vertex_group else ""))


def face_axis(name, normal, location=(0.0, 0.0, 0.0), scale=1.0):
    """An Empty whose local XY plane lies ON a face, for OBJECT texture coords.

    Image textures are sampled on two coordinates. Under LOCAL or GLOBAL
    coordinates those are the object's X and Y, which is correct only for a
    surface lying in XY — on any vertical face the sample point never moves in
    one of them and the map collapses into stripes running down the face.
    Nothing warns you; it simply comes out striped.

    This builds the frame that fixes it: local Z along the face normal, local
    Y as close to world up as possible, so the map's own vertical runs up the
    face the way it was drawn. Pass the result as displace(..., 
    texture_coords='OBJECT', coords_object=<this>).

    `scale` divides the texture coordinates, so it is the second size control
    alongside the texture's repeat count: one tile spans 2 * scale metres.
    """
    e = bpy.data.objects.get(name)
    if e is None:
        e = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(e)
    e.empty_display_size = 0.2
    e.location = location
    e.rotation_mode = 'QUATERNION'
    e.rotation_quaternion = Vector(normal).normalized().to_track_quat('Z', 'Y')
    e.scale = (scale, scale, scale)
    bpy.context.view_layer.update()
    return e


def drape_line(obj, a, b, direction, n=40, world=True):
    """A straight line in space, raycast onto a surface — a path that FOLLOWS
    the model instead of cutting through it.

    Sample n points along a->b, fire a ray from each along `direction`, and
    keep the hits. On anything with a stepped or tapered profile this is the
    difference between a stroke that stays on the surface for its whole length
    and one that leaves it the moment the profile changes.

    Misses are dropped rather than interpolated: a path point that is not on
    the surface is worse than a gap, because the footprint is a 3D distance
    and a stray point pulls in geometry from wherever it happens to sit.
    """
    mwi = obj.matrix_world.inverted()
    d = (mwi.to_3x3() @ Vector(direction)).normalized()
    a, b = Vector(a), Vector(b)
    out = []
    for i in range(int(n)):
        t = i / max(n - 1.0, 1.0)
        origin = mwi @ (a + (b - a) * t)
        hit, loc, _nrm, _idx = obj.ray_cast(origin, d)
        if hit:
            p = obj.matrix_world @ loc if world else loc
            out.append((p.x, p.y, p.z))
    return out


def movement(before, after, mask=None):
    """How far vertices moved between two world-coordinate snapshots, in mm.

    The honest way to prove a localised change stayed localised: compare the
    SAME vertices before and after, rather than measuring each region against
    a nominal plane. Measuring against a plane picks up the model's own shape
    — a groove, a taper, a chamfer — and reports it as damage.

    Returns (max_mm, mean_mm, moved_count).
    """
    d = np.linalg.norm(np.asarray(after) - np.asarray(before), axis=1) * 1000.0
    if mask is not None:
        d = d[mask]
    if d.size == 0:
        return 0.0, 0.0, 0
    return float(d.max()), float(d.mean()), int((d > 1e-6).sum())


def brush_circle(center_world, radius, normal=(0.0, 0.0, 1.0), n=48):
    """Closed polyline of a circle, for drawing a brush footprint in previews.

    A path line says WHERE a stroke goes and nothing about how wide it is or
    how big the texture on it will be. Both are the numbers most often wrong,
    and both are invisible until after the stroke has run. Drawing them at the
    start of the path makes them adjustable BEFORE that.
    """
    nz = Vector(normal).normalized()
    ref = Vector((0.0, 0.0, 1.0)) if abs(nz.z) < 0.9 else Vector((1.0, 0.0, 0.0))
    ax = nz.cross(ref).normalized()
    ay = nz.cross(ax).normalized()
    c = Vector(center_world)
    pts = []
    for i in range(n + 1):
        a = 2.0 * math.pi * i / n
        p = c + ax * (radius * math.cos(a)) + ay * (radius * math.sin(a))
        pts.append((p.x, p.y, p.z))
    return pts


def stroke_footprint(obj, path_world, radius, hardness=0.0, tail=0.0,
                     face_normal=None, face_dot=0.25):
    """Per-vertex weights for a brush dragged along a polyline.

    This is what makes displace() behave like a BRUSH rather than like a
    modifier: the weight is the brush's falloff measured from the stroke
    path, so the textured band has soft shoulders and stops where the stroke
    stops, exactly as a dragged dab trail would.

    hardness     0 = fully soft shoulder, 1 = flat-topped with a sharp edge.
    tail         fraction of the radius by which the weight keeps fading past
                 the ends, so the stroke does not finish on a blunt
                 semicircle.
    face_normal  restrict to geometry facing this way. The footprint is a 3D
                 distance, so a stroke run down a face reaches AROUND its
                 corners onto the neighbouring faces — on a pillar that means
                 quietly resurfacing the chipped arrises next door. Gating on
                 the vertex normal stops it at the corner without needing a
                 second mask.
    face_dot     normals below this dot product get no weight; the ramp up to
                 1.0 is smooth, so the effect fades out approaching the arris
                 rather than ending on a line.
    """
    world, normals = world_arrays(obj)
    p = np.asarray(path_world, dtype=np.float64)
    if p.shape[0] < 2:
        raise ValueError("stroke path needs at least two points")

    d = np.full(world.shape[0], np.inf)
    for i in range(p.shape[0] - 1):
        a, b = p[i], p[i + 1]
        ab = b - a
        ab2 = float(ab @ ab)
        t = np.clip(((world - a) @ ab) / max(ab2, 1e-12), 0.0, 1.0)
        d = np.minimum(d, np.linalg.norm(world - (a + t[:, None] * ab), axis=1))

    reach = radius * (1.0 + float(tail))
    u = np.clip(1.0 - d / reach, 0.0, 1.0)
    h = float(np.clip(hardness, 0.0, 0.99))
    u = np.clip((u - h) / (1.0 - h), 0.0, 1.0)
    w = u * u * (3.0 - 2.0 * u)                  # smoothstep shoulder

    if face_normal is not None:
        n = np.asarray(face_normal, dtype=np.float64)
        n /= max(np.linalg.norm(n), 1e-12)
        c = np.clip((normals @ n - face_dot) / max(1.0 - face_dot, 1e-9),
                    0.0, 1.0)
        w = w * (c * c * (3.0 - 2.0 * c))
    return w


def strokes_footprint(obj, paths, radius, **kw):
    """One footprint covering SEVERAL paths, combined by max.

    Overlapping strokes must be merged into a single weight field and
    displaced ONCE. Running displace per stroke instead stacks the passes, so
    wherever two bands overlap the surface gets the texture twice and the
    relief doubles — which shows up as bright seams running down the middle of
    a face.
    """
    w = None
    for p in paths:
        f = stroke_footprint(obj, p, radius, **kw)
        w = f if w is None else np.maximum(w, f)
    return w


def make_vertex_group(obj, name, weights, buckets=64):
    """Write per-vertex weights as a group.

    Bucketed: VertexGroup.add takes a LIST of indices per call, and adding
    600k vertices one at a time takes minutes. Quantising to 64 weight levels
    turns it into 64 calls and is finer than any falloff needs.
    """
    vg = obj.vertex_groups.get(name)
    if vg is not None:
        obj.vertex_groups.remove(vg)
    vg = obj.vertex_groups.new(name=name)

    q = np.clip((weights * buckets).round().astype(int), 0, buckets)
    for level in range(1, buckets + 1):
        idx = np.nonzero(q == level)[0]
        if idx.size:
            vg.add(idx.tolist(), level / float(buckets), 'REPLACE')
    return vg.name, int((q > 0).sum())


def stroke_displace(obj_name, texture, path_world, radius, strength,
                    mid_level=0.5, hardness=0.0, tail=0.0,
                    texture_coords='LOCAL', coords_object=None,
                    group="brush_stroke", label=None):
    """A TEXTURED BRUSH STROKE, built out of a displacement.

    Blender's own brush textures cannot be driven from a script (see
    _localize), so this reproduces the effect: the texture supplies the
    detail, and the stroke's falloff footprint supplies the where. Dragging
    it along a path gives a band of textured relief with soft edges — which
    is what a textured brush stroke IS.

    Unlike a real brush it does not accumulate along the stroke, so the band
    is even from end to end instead of deepening where dabs overlap. For
    surface texture that is an improvement.
    """
    obj = bpy.data.objects[obj_name]
    w = stroke_footprint(obj, path_world, radius, hardness=hardness, tail=tail)
    gname, n = make_vertex_group(obj, group, w)
    rep = displace(obj_name, texture, strength=strength, mid_level=mid_level,
                   direction='NORMAL', texture_coords=texture_coords,
                   coords_object=coords_object, vertex_group=gname,
                   label=label or "stroke_displace")
    rep["footprint_verts"] = n
    rep["footprint_max_weight"] = float(w.max())
    return rep



# --------------------------------------------------------------------------
# whole-mesh filters
# --------------------------------------------------------------------------

def mesh_filter(obj_name, kind='SMOOTH', strength=0.5, iterations=1,
                label=None):
    """Whole-mesh filter: SMOOTH, RELAX, SURFACE_SMOOTH, SHARPEN,
    ENHANCE_DETAILS, INFLATE, SCALE, SPHERE, RANDOM, RELAX_FACE_SETS,
    ERASE_DISPLACEMENT.

    Applies to everything unmasked, so mask first if it should be local. This
    replaces the hand-written Laplacian relax in sculpt.py.
    """
    obj = bpy.data.objects[obj_name]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    win, area, region, _rv3d = viewport()
    before = _verts(obj)

    bpy.ops.object.mode_set(mode='SCULPT')
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            for _ in range(int(iterations)):
                bpy.ops.sculpt.mesh_filter(type=kind, strength=strength)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    return _report(before, _verts(obj), label or ("filter_" + kind.lower()),
                   "(x%d @ %.2f)" % (iterations, strength))
