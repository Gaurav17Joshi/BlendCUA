"""Render ten comparable views of a saved BlendCUA scene. Headless.

    blender --background <task>.blend --python render_views.py -- <outdir>

Writes az_000 az_045 ... az_315 (eight azimuths at elevation 0, 0 deg at +X)
plus top and bottom, as ordinary opaque renders, and one extra:

    front_solid.png   the mesh in VIEWPORT SOLID SHADING, on opaque grey

front_solid is rendered with the BLENDER_WORKBENCH engine, which is the same
renderer the 3D viewport's Solid mode uses. It is here because the lit,
textured, alpha views are for judging the finished object, and this one is for
judging the FORM: no materials, no textures, no shadows to hide behind, plus
cavity shading so edges and creases read. `bpy.ops.render.opengl` would be the
other way to get it and does not work under --background; Workbench does.

Its background is a darker grey than the ten angle views, so the two kinds of
image are easy to tell apart at a glance.

HEADLESS ON PURPOSE. Opening one of these files into the GUI Blender that is
running the socket server would discard its scene and probably take the
server's timers with it. `lib/view.get_viewport()` segfaults under --background,
but nothing here needs it: these are camera renders through
bpy.ops.render.render(), which is happy with no window.

THE FRAMING AND LIGHTING ARE REBUILT, NOT INHERITED
---------------------------------------------------
A saved scene is a studio set built for exactly one camera:

* Framing the union of every mesh puts the camera outside the backdrop and
  renders a rectangle of flat grey. The subject is picked the way
  save_final_blend's fit render picks it -- drop objects named like scenery,
  then drop anything still more than 2.5x the diagonal of its next-largest
  neighbour.
* The backdrop covers only the hemisphere the plan camera shoots from, so it
  would block about half of these views; the scene's own lights are aimed for
  that one camera and leave the subject black from behind. Both are hidden and
  replaced with a fixed ambient world plus a sun re-aimed along each view, so
  all ten views of all twenty tasks are lit identically and any difference
  between them is a difference in the model.

THE DISTANCE FIT
----------------
For a bounding-box corner at depth `t` along the view axis with horizontal
offset `x` and vertical offset `y`, the camera must sit at least

    max(|x| / tan(half_x), |y| / tan(half_y)) + t

away. The two axes are tested SEPARATELY. Measuring the combined perpendicular
offset as a single radius treats the frustum as a cone drawn around the
rectangular frame; that over-estimates by up to sqrt(2) and left the chess set
filling under half the frame.

One distance is used for all eight ring views so they are directly comparable,
and a second for top and bottom.
"""

import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

RES_X, RES_Y = 1200, 1200
LENS_MM = 50.0
MARGIN = 1.06                 # a little air around the subject
SUN_ENERGY = 3.0
WORLD_STRENGTH = 0.35
SAMPLES = 64

SCENERY_WORDS = ("backdrop", "floor", "wall", "ground", "studio", "plane",
                 "sweep", "ref", "guide", "datum", "cyclorama", "table")

RING_AZIMUTHS = [0, 45, 90, 135, 180, 225, 270, 315]

# Blender's "Front" looks from -Y toward +Y. In this azimuth scheme (0 deg at
# +X, measured toward +Y) that is 270 deg.
FRONT_AZIMUTH = 270
SOLID_BG = (0.24, 0.24, 0.26, 1.0)

# The ten angle views render on an OPAQUE world background, not alpha.
# The runbook (section 10) specifies film_transparent = True so "the object
# arrives on alpha", which is the more composable output -- but a transparent
# PNG composites to black in Windows Photos and most other viewers, so every
# one of these read as a black background. Ordinary renders are what is
# actually wanted here. Set VIEW_TRANSPARENT = True to get the alpha behaviour
# back; nothing else changes, the lighting and framing are identical either way.
VIEW_TRANSPARENT = False


def log(msg):
    print("[views] " + msg)


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _extent(obj):
    bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in bb), min(p.y for p in bb), min(p.z for p in bb)))
    hi = Vector((max(p.x for p in bb), max(p.y for p in bb), max(p.z for p in bb)))
    return hi - lo


def _is_planar(obj, ratio=0.12):
    """True if the object is essentially flat: a backdrop, floor or sweep.

    This is what separates scenery from a dominant subject. A studio backdrop
    is a plane, so its thinnest bbox dimension is ~0 next to its widest; a
    shark body or a carved stone is not, whatever its size.
    """
    d = _extent(obj)
    mx = max(d)
    return mx > 0 and (min(d) / mx) <= ratio


def diag(obj):
    bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in bb), min(p.y for p in bb), min(p.z for p in bb)))
    hi = Vector((max(p.x for p in bb), max(p.y for p in bb), max(p.z for p in bb)))
    return (hi - lo).length


def pick_subject():
    """The objects a reviewer would call 'the model'."""
    cands = [o for o in bpy.data.objects
             if o.type in {"MESH", "CURVE", "FONT", "SURFACE"}]
    cands = [o for o in cands if not o.hide_render]
    if not cands:
        raise RuntimeError("no renderable geometry in this scene")

    named = [o for o in cands
             if not any(w in o.name.lower() for w in SCENERY_WORDS)]
    subject = named or cands

    # Drop a remaining outlier that dwarfs everything else -- an unnamed
    # backdrop, a ground plane called "Cube.003".
    #
    # BUT ONLY IF IT IS FLAT. Size alone is not evidence of scenery, and using
    # it alone deletes the subject in exactly the scenes where one part is the
    # model and the rest are details hung off it. 17_shark lost SharkBody
    # (diag 7.37 against the caudal fin's 2.92) and 04_datestone lost
    # Datestone_Cage (3.30 against 0.90); both rendered as a scatter of fins
    # and numerals around an empty middle. A real backdrop has a thinnest
    # dimension of ~0 relative to its widest; those two were 0.23 and 0.14.
    for _ in range(3):
        if len(subject) < 2:
            break
        ranked = sorted(subject, key=diag, reverse=True)
        if diag(ranked[0]) > 2.5 * diag(ranked[1]) and _is_planar(ranked[0]):
            subject = ranked[1:]
        else:
            break
    return subject


def hide_everything_but(subject):
    """Hide scenery and every existing light, and remember nothing: headless."""
    keep = {o.name for o in subject}
    for o in bpy.data.objects:
        if o.type == "LIGHT":
            o.hide_render = True
        elif o.type in {"MESH", "CURVE", "FONT", "SURFACE"}:
            o.hide_render = o.name not in keep


def neutral_world():
    world = bpy.data.worlds.new("ViewsWorld")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        bg.inputs["Strength"].default_value = WORLD_STRENGTH
    bpy.context.scene.world = world


def subject_bounds(subject):
    pts = [o.matrix_world @ Vector(c) for o in subject for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi, (lo + hi) / 2.0


def direction(azimuth_deg, elevation_deg):
    a = math.radians(azimuth_deg)
    e = math.radians(elevation_deg)
    return Vector((math.cos(a) * math.cos(e),
                   math.sin(a) * math.cos(e),
                   math.sin(e))).normalized()


def basis(u):
    """Right and up vectors for a camera at direction u looking back at centre."""
    world_up = Vector((0.0, 0.0, 1.0))
    if abs(u.dot(world_up)) > 0.999:          # straight up or down
        world_up = Vector((0.0, 1.0, 0.0))
    right = u.cross(world_up).normalized()
    up = right.cross(u).normalized() * -1.0
    return right, up


def fit_distance(corners, centre, u, half_x, half_y):
    """Smallest camera distance along u that keeps every corner in frame.

    Derivation: put the camera at C = centre + u*d looking at centre. For a
    corner p, let s = p - centre. Its depth in front of the camera is d - s.u,
    its horizontal offset is s.right and its vertical offset is s.up (both
    independent of d, since right and up are perpendicular to u). Requiring
    |s.right| <= (d - s.u) * tan(half_x) gives

        d >= |s.right| / tan(half_x) + s.u

    and likewise for the vertical axis. Take the max over both axes and every
    corner. Testing the axes separately is the whole point -- see the module
    docstring.
    """
    right, up = basis(u)
    tx, ty = math.tan(half_x), math.tan(half_y)
    best = 0.0
    for p in corners:
        s = p - centre
        need = max(abs(s.dot(right)) / tx, abs(s.dot(up)) / ty) + s.dot(u)
        best = max(best, need)
    return best



def render_front_solid(scene, cam, corners, centre, half_x, half_y, outdir):
    """One front view in viewport Solid shading, on opaque grey.

    BLENDER_WORKBENCH is the engine the 3D viewport's Solid mode uses, so this
    is the same picture you would get by looking at the model in the viewport
    -- and unlike bpy.ops.render.opengl it works under --background.

    Deliberately different from the ten lit views: materials off, single flat
    object colour, studio light and cavity shading on. Those choices strip away
    everything except FORM, which is what this render is for. Its own distance
    fit is used rather than the shared ring distance, so the mesh fills the
    frame instead of being sized for the widest azimuth.
    """
    prev = {
        "engine": scene.render.engine,
        "transparent": scene.render.film_transparent,
    }
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
    except TypeError:
        log("BLENDER_WORKBENCH unavailable; skipping front_solid")
        return None

    shading = scene.display.shading
    for attr, value in (("light", "STUDIO"), ("color_type", "SINGLE"),
                        ("show_cavity", True), ("cavity_type", "BOTH"),
                        ("show_object_outline", True),
                        ("show_shadows", False),
                        ("studio_light", "Default")):
        if hasattr(shading, attr):
            try:
                setattr(shading, attr, value)
            except (TypeError, ValueError):
                pass
    for attr, value in (("single_color", (0.78, 0.78, 0.80)),
                        ("object_outline_color", (0.05, 0.05, 0.06)),
                        ("cavity_ridge_factor", 1.4),
                        ("cavity_valley_factor", 1.4)):
        if hasattr(shading, attr):
            try:
                setattr(shading, attr, value)
            except (TypeError, ValueError):
                pass
    if hasattr(scene.display, "render_aa"):
        try:
            scene.display.render_aa = "16"
        except (TypeError, ValueError):
            pass

    # Opaque background: the point of this one is to be looked at, and alpha
    # composites to black in most viewers.
    scene.render.film_transparent = False
    world = scene.world
    prev_bg = None
    if world is not None and world.use_nodes:
        bg = world.node_tree.nodes.get("Background")
        if bg is not None:
            prev_bg = tuple(bg.inputs["Color"].default_value)
            bg.inputs["Color"].default_value = SOLID_BG

    u = direction(FRONT_AZIMUTH, 0.0)
    d = MARGIN * fit_distance(corners, centre, u, half_x, half_y)
    cam.location = centre + u * d
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()

    path = os.path.join(outdir, "front_solid.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)

    scene.render.engine = prev["engine"]
    scene.render.film_transparent = prev["transparent"]
    if prev_bg is not None:
        world.node_tree.nodes.get("Background").inputs["Color"].default_value = prev_bg
    log("front_solid d=%.3f -> %s" % (d, "ok" if os.path.exists(path) else "MISSING"))
    return path


def main():
    args = argv_after_ddash()
    if not args:
        log("usage: ... --python render_views.py -- <outdir>")
        sys.exit(2)
    outdir = os.path.abspath(args[0])
    os.makedirs(outdir, exist_ok=True)

    scene = bpy.context.scene
    subject = pick_subject()
    log("subject: %d object(s): %s"
        % (len(subject), ", ".join(o.name for o in subject[:8])))
    hide_everything_but(subject)
    neutral_world()

    lo, hi, centre = subject_bounds(subject)
    corners = [Vector((x, y, z))
               for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    log("bounds %.3f..%.3f x %.3f..%.3f x %.3f..%.3f"
        % (lo.x, hi.x, lo.y, hi.y, lo.z, hi.z))

    scene.render.resolution_x = RES_X
    scene.render.resolution_y = RES_Y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = VIEW_TRANSPARENT
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0

    # EEVEE: these are ten renders per task across twenty tasks and they only
    # have to be mutually comparable, not beautiful.
    for name in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES"):
        try:
            scene.render.engine = name
            break
        except TypeError:
            continue
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = SAMPLES
    else:
        if hasattr(scene.eevee, "taa_render_samples"):
            scene.eevee.taa_render_samples = SAMPLES

    cam_data = bpy.data.cameras.new("ViewsCam")
    cam_data.lens = LENS_MM
    cam = bpy.data.objects.new("ViewsCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    sun_data = bpy.data.lights.new("ViewsSun", type="SUN")
    sun_data.energy = SUN_ENERGY
    sun = bpy.data.objects.new("ViewsSun", sun_data)
    scene.collection.objects.link(sun)

    half_x, half_y = cam_data.angle_x / 2.0, cam_data.angle_y / 2.0

    ring = [(("az_%03d" % a), direction(a, 0.0)) for a in RING_AZIMUTHS]
    poles = [("top", Vector((0.0, 0.0, 1.0))), ("bottom", Vector((0.0, 0.0, -1.0)))]

    # ONE distance for the whole ring, so the eight are directly comparable,
    # and a second shared by top and bottom.
    ring_d = MARGIN * max(fit_distance(corners, centre, u, half_x, half_y)
                          for _n, u in ring)
    pole_d = MARGIN * max(fit_distance(corners, centre, u, half_x, half_y)
                          for _n, u in poles)
    log("ring distance %.3f, pole distance %.3f" % (ring_d, pole_d))

    written = []
    for name, u in ring + poles:
        d = ring_d if name.startswith("az_") else pole_d
        cam.location = centre + u * d
        cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
        # Sun re-aimed along this view, tilted a little so the form reads
        # instead of going flat under a dead-on light.
        right, up = basis(u)
        lit = (u + up * 0.45 + right * 0.25).normalized()
        sun.location = centre + lit * max(d, 1.0)
        sun.rotation_euler = (centre - sun.location).to_track_quat("-Z", "Y").to_euler()

        path = os.path.join(outdir, name + ".png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        ok = os.path.exists(path)
        written.append((name, ok, os.path.getsize(path) if ok else 0))
        log("%-8s d=%.3f -> %s" % (name, d, "ok" if ok else "MISSING"))

    solid = render_front_solid(scene, cam, corners, centre, half_x, half_y, outdir)
    if solid:
        written.append(("front_solid", os.path.exists(solid),
                        os.path.getsize(solid) if os.path.exists(solid) else 0))

    missing = [n for n, ok, _s in written if not ok]
    log("wrote %d/%d views into %s" % (len(written) - len(missing), len(written), outdir))
    if missing:
        log("MISSING: " + ", ".join(missing))
        sys.exit(1)


if __name__ == "__main__":
    main()
