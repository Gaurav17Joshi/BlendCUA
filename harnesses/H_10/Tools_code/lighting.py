"""Camera, lights, backdrop and a real render.

Everything else in this toolkit renders the VIEWPORT — `lib.view.render_viewport`
drives `bpy.ops.render.opengl`, which is fast, ignores the scene's lights
entirely and lights the model with a fixed studio matcap instead. That is
exactly right while a shape is being judged, and useless the moment the
lighting IS the thing being judged.

So this is the other half: a scene camera, real lights, a backdrop for them
to fall on, and `render()`, which drives the actual engine.

WHAT MAKES A KEY LIGHT MATCH A REFERENCE
----------------------------------------
Three things, in this order of importance:

1. DIRECTION — which way the terminator runs. Read it off the reference by
   finding the line between lit and shadow on the roundest object in the
   frame; on a solid of revolution that line is a meridian, and which
   meridian tells you the light's azimuth directly.
2. HARDNESS — how wide that terminator is. A hard edge is a small light;
   a soft gradient is a big one. This is `size`, and it is the parameter
   people reach for last and should reach for second.
3. COLOUR and INTENSITY — which matter least because they are the two a
   viewer will forgive being slightly off, and the two most likely to be
   fought over by the tone mapping.

`aim()` exists because Blender lights point down their local -Z and setting
a rotation by hand to make that hit a particular point is three lines of
quaternion arithmetic that are easy to get subtly wrong.
"""

import math
import os

import bpy
from mathutils import Matrix, Vector

# Engine names have moved around (BLENDER_EEVEE -> BLENDER_EEVEE_NEXT ->
# back again across 4.x/5.x), so the name has to be checked rather than
# assumed. The check is a TRY, not a lookup in the RNA enum — and that
# distinction cost a wasted render.
#
# `bl_rna.properties["engine"].enum_items` lists only the engines compiled
# into Blender. Cycles is an ADD-ON: it registers itself at load time and
# appears in the property's runtime items, not its static ones. So the enum
# lookup reported that Cycles was unavailable in a build that has had it
# working all along — this project's bake.py has been setting
# `scene.render.engine = 'CYCLES'` for two runs — and the first hero render
# came out of EEVEE without saying so anywhere except a line of console
# output nobody was reading.
# ─── Replay render configuration ──────────────────────────────────────────
# A 900-action replay needs one place to say "render this pass with EEVEE" or
# "put Cycles on the GPU" without touching a single recorded action file.
#
# It is a CONFIG LAYER rather than a text rewrite of the corpus because both
# render() and render_sequence() *default* to engine="CYCLES": the call sites
# that pass nothing at all are asking for Cycles just as loudly as the ones
# that spell it out, and a rewrite can only see the ones that spell it out.
# set_engine() is the single choke point every one of them funnels through.
#
# Read from blendcua.env at the project root:
#     BLENDCUA_RENDER_ENGINE=AUTO     # EEVEE | CYCLES | AUTO
#     BLENDCUA_CYCLES_DEVICE=GPU      # CPU | GPU | AUTO
# AUTO (or absent) means the original recorded behaviour. Environment
# variables beat the file.

_CONFIG_FILE = "blendcua.env"


def _config_root():
    """Project root — this file is <root>/Tool_scripts/Tools_code/lighting.py."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def config_value(key, default=None):
    """Replay config lookup: environment first, then blendcua.env.

    Deliberately UNCACHED. The Blender server holds one interpreter open for
    a multi-hour replay, so a cached value could only be changed by
    restarting Blender and losing the scene; re-reading a two-line file per
    render is free by comparison.
    """
    val = os.environ.get(key)
    if val is not None and val.strip():
        return val.strip()
    try:
        with open(os.path.join(_config_root(), _CONFIG_FILE),
                  "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                if name.strip() == key:
                    return value.split("#")[0].strip() or default
    except OSError:
        pass
    return default


def engine_override():
    """Engine forced by config, or None to honour what the action asked for."""
    value = (config_value("BLENDCUA_RENDER_ENGINE") or "AUTO").upper()
    if "EEVEE" in value:
        return "BLENDER_EEVEE"
    if "CYCLE" in value:
        return "CYCLES"
    return None


def cycles_device():
    """'CPU' / 'GPU' forced by config, or None to honour the call's prefer_gpu."""
    value = (config_value("BLENDCUA_CYCLES_DEVICE") or "AUTO").upper()
    return value if value in ("CPU", "GPU") else None


def _apply_cycles_device(scene):
    """Force scene.cycles.device from config. No-op when unset or not Cycles."""
    device = cycles_device()
    if device is None:
        return
    cycles = getattr(scene, "cycles", None)
    if cycles is None:
        return
    try:
        cycles.device = device
    except (AttributeError, TypeError):
        pass


def set_engine(name):
    """Set the requested render engine, returning the one actually in effect.

    Blender has used both ``BLENDER_EEVEE_NEXT`` and ``BLENDER_EEVEE`` for the
    same realtime family.  If an EEVEE alias is requested, try the other EEVEE
    aliases before falling back to Cycles; the old global fallback order could
    silently turn an explicit EEVEE render into Cycles on a legacy build.
    """
    requested = str(name)
    # Config override, if any, replaces what the action asked for. Applied
    # here so it covers callers that pass no engine at all and inherit the
    # "CYCLES" default.
    _override = engine_override()
    if _override is not None:
        requested = _override
    if "EEVEE" in requested.upper():
        candidates = (requested, "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE",
                      "EEVEE", "CYCLES")
    elif "CYCLE" in requested.upper():
        candidates = (requested, "CYCLES", "BLENDER_EEVEE_NEXT",
                      "BLENDER_EEVEE", "EEVEE")
    else:
        candidates = (requested, "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE",
                      "EEVEE", "CYCLES")

    scene = bpy.context.scene
    tried = set()
    for candidate in candidates:
        if candidate in tried:
            continue
        tried.add(candidate)
        try:
            scene.render.engine = candidate
            return scene.render.engine
        except TypeError:
            continue
    return scene.render.engine


def _remove(prefix):
    for o in list(bpy.data.objects):
        if o.name.startswith(prefix):
            bpy.data.objects.remove(o, do_unlink=True)


def aim(obj, target):
    """Point `obj`'s -Z axis at `target`. Lights and cameras both."""
    d = Vector(target) - obj.location
    if d.length < 1e-9:
        return obj
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return obj


def spherical(target, distance, azimuth, elevation):
    """A point `distance` from `target`, at that azimuth and elevation.

    azimuth is degrees about Z with 0 at +X and 270 towards the camera side
    (-Y) — the same convention meshgen/plant_skeleton use, so a light can be
    described in the same terms as the branch it is lighting.
    """
    a, e = math.radians(azimuth), math.radians(elevation)
    return Vector(target) + Vector((math.cos(a) * math.cos(e) * distance,
                                    math.sin(a) * math.cos(e) * distance,
                                    math.sin(e) * distance))


def key_light(target, distance, azimuth, elevation, energy,
              colour=(1.0, 1.0, 1.0), size=0.25, kind='AREA',
              name="Key", spread=None):
    """An aimed light, positioned relative to what it is lighting."""
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    data = bpy.data.lights.new(name, type=kind)
    data.energy = energy
    data.color = colour
    if kind == 'AREA':
        data.size = size
        if spread is not None:
            data.spread = math.radians(spread)
    elif kind in ('POINT', 'SPOT'):
        data.shadow_soft_size = size
    obj = bpy.data.objects.new(name, data)
    obj.location = spherical(target, distance, azimuth, elevation)
    bpy.context.scene.collection.objects.link(obj)
    return aim(obj, target)


def world_colour(rgb, strength=1.0):
    """A flat world. Deliberately not an HDRI: the reference's background is
    a plain warm gradient with no environment in it at all, and an HDRI
    would put reflections of a room onto ten glossy chillies."""
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = tuple(rgb) + (1.0,)
        bg.inputs[1].default_value = strength
    return world


def backdrop(rgb, width=6.0, height=4.0, distance=1.4, z=-1.0,
             roughness=0.95, name="Backdrop"):
    """A big matte plane behind the subject.

    This is what produces the reference's background — not the world colour.
    The reference's backdrop is plainly a surface: it has a soft bright pool
    behind and to the right of the pot where the key light lands on it, and
    it falls off towards the corners. A flat world colour cannot do that,
    because a world is at infinity and receives no light.
    """
    _remove(name)
    mesh = bpy.data.meshes.new(name)
    verts = [(-width / 2, distance, z),
             (width / 2, distance, z),
             (width / 2, distance, z + height),
             (-width / 2, distance, z + height)]
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = tuple(rgb) + (1.0,)
        bsdf.inputs["Roughness"].default_value = roughness
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.05
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def light_frame(light):
    """(origin, axis, right, up) of a light, in world space.

    Blender lights point down their local -Z. `right` and `up` are the
    light's local X and Y, which for an aimed light come out roughly
    horizontal and roughly vertical — but only roughly, and the difference
    matters when a flag's edge has to end up plumb.

    DERIVED FROM rotation_euler, NOT FROM matrix_world. `matrix_world` is
    evaluated by the dependency graph, and inside the script that just
    created and aimed the light it is still the identity — so a flag placed
    with it went straight DOWN from the light instead of out along its beam,
    and cast its shadow into empty space. Nothing about the render said so;
    the picture just came back with no cut in it. The euler is the value
    that was assigned, so it is true immediately.
    """
    r = light.rotation_euler.to_matrix()
    return (light.location.copy(),
            (r @ Vector((0.0, 0.0, -1.0))).normalized(),
            (r @ Vector((1.0, 0.0, 0.0))).normalized(),
            (r @ Vector((0.0, 1.0, 0.0))).normalized())


def cut_through(light, point, distance):
    """Where a flag's edge must sit for its shadow to fall on `point`.

    Returns the value to pass as `flag(cut=...)`, in metres at the flag's
    own plane.

    SOLVE IT, DO NOT TUNE IT. The lever arm here is brutal: the flag sits a
    fraction of a metre from the light and the subject is a metre away, so
    the edge's offset is scaled by the ratio of those two — for the setup in
    this build, sweeping the shadow across the entire width of the plinth
    takes about five millimetres of flag. Tuning that by eye is a dozen
    renders; projecting the point back to the flag's plane is one line of
    similar triangles.
    """
    origin, axis, right, _up = light_frame(light)
    v = Vector(point) - origin
    axial = v.dot(axis)
    if axial <= 1e-6:
        raise ValueError("cut_through: that point is behind the light")
    return distance * v.dot(right) / axial


def plumb_angle(light, cut, distance):
    """The roll, in degrees, that makes a flag's shadow edge VERTICAL.

    A flag's edge running along the light's own local "up" does NOT give a
    vertical shadow. The shadow boundary is the intersection of two planes —
    the one through the light and the flag's edge, and whatever surface it
    lands on — and for that intersection to be plumb, the shadow plane has
    to contain the world vertical. With the light in this build's position
    an untilted flag came out 29 degrees off, which on a plinth with plumb
    corners is immediately visible as wrong.

    Solving it: with the edge at `cut` and distance D, the vector from the
    light to the edge is v = axis*D + right*cut, and the shadow plane's
    normal is v x e for edge direction e = cos(t)*up + sin(t)*right. The
    plane contains the vertical exactly when that normal has no vertical
    component, so n.z = 0, which is linear in cos t and sin t:

        tan(t) = -(v.x*up.y - v.y*up.x) / (v.x*right.y - v.y*right.x)

    For this scene it comes out at about -1.6 degrees — small, and nothing
    like the -4 that was guessed at first, which swung the cut clean across
    the subject. That is the point: at these lever arms a degree is a lot.
    """
    origin, axis, right, up = light_frame(light)
    v = axis * distance + right * cut
    num = v.x * up.y - v.y * up.x
    den = v.x * right.y - v.y * right.x
    if abs(den) < 1e-12:
        return 0.0
    # WRAPPED INTO (-90, 90]. An edge is a LINE, and a line's direction is
    # only defined up to 180 degrees - t and t+180 describe the same edge.
    # atan2 does not know that and returned 178.4 for this scene instead of
    # -1.6, which is the same line and a completely different flag: rotating
    # the half-plane by 178 degrees mirrors it to the other side of its own
    # edge, so it blocked the half of the beam that was lighting the
    # backdrop and left the subject untouched. The render showed a crisp
    # hard-edged shadow, on the wall, behind everything that was supposed to
    # be cut.
    deg = math.degrees(math.atan2(-num, den))
    while deg > 90.0:
        deg -= 180.0
    while deg <= -90.0:
        deg += 180.0
    return deg


def flag(light, cut=0.0, side=1, distance=0.30, size=2.0, angle=0.0,
         name="Flag"):
    """A cutter: an opaque plane between a light and its subject, blocking
    part of the beam so the shadow it throws has a HARD, STRAIGHT edge.

    WHY THIS IS NEEDED AND A TERMINATOR IS NOT.
    On a curved surface the boundary between lit and unlit is a terminator,
    and a terminator is a cosine falloff — it is always a gradient, however
    small the light. On a FLAT surface lit by one light there is no boundary
    at all: the whole face takes the same value. So a flat face that is
    bright on one side of a hard line and dark on the other cannot be
    explained by lighting alone; something is standing in the way. In the
    reference that is exactly what the plinth shows, and the same straight
    cut carries across the pot beside it.

    This is a `flag` (or cutter) in film terms — the same tool as a gobo or
    a cookie, just with one straight edge instead of a pattern.

    light     the light object to cut.
    cut       where the flag's edge sits, in metres at the flag's own
              plane, along the light's local X. Use `cut_through()` to get
              it from the world point you want the shadow to pass through —
              the lever arm makes this a millimetre-scale control and
              guessing at it is a dozen wasted renders.
    side      which half the flag occupies: +1 covers everything past `cut`,
              -1 covers everything short of it. This is not cosmetic. A
              flag on the wrong side of its own edge blocks the half of the
              beam that was lighting the background instead of the half
              that was lighting the subject, and the first attempt here did
              exactly that — the subject stayed lit and the backdrop went
              black.
    distance  how far in front of the light the flag sits. Near the light
              is a barn door: small, easily kept out of frame, and the
              hardness of the edge then depends only on the light's own
              size. Near the subject is a cookie: needs to be big, and will
              be in shot.

              It also sets how HARD the cut is, and this is the trap. The
              penumbra at the subject is the light's size scaled by
              (subject distance - flag distance) / flag distance. Put a
              0.10 m light 0.22 m in front of a subject 0.95 m away and the
              penumbra is a third of a metre — the whole subject is
              penumbra and there is no edge at all. Either move the flag
              out towards the subject or shrink the light; this build does
              both.
    angle     degrees to roll the flag about the light's axis, which tilts
              the cut. 0 puts a vertical edge in frame.

    The plane is made black and given no specular, so that any light that
    does reach it is absorbed rather than bounced back as a second source.
    """
    import bmesh

    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)

    bm = bmesh.new()
    # A half-plane with one edge at x = cut, running `side` -ward, so `cut`
    # names the EDGE — the only part of a flag that does anything.
    far = cut + size * (1.0 if side >= 0 else -1.0)
    for co in ((cut, -size * 0.5, 0.0), (far, -size * 0.5, 0.0),
               (far, size * 0.5, 0.0), (cut, size * 0.5, 0.0)):
        bm.verts.new(co)
    bm.verts.ensure_lookup_table()
    bm.faces.new(bm.verts)
    if abs(angle) > 1e-9:
        bmesh.ops.rotate(bm, verts=bm.verts[:], cent=(0.0, 0.0, 0.0),
                         matrix=Matrix.Rotation(math.radians(angle), 3, 'Z'))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()

    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)

    # Placed in the LIGHT's frame: same rotation, shifted down its own -Z,
    # which is the axis Blender lights point along. Doing it this way means
    # the flag follows the light if the light moves, instead of having to be
    # re-derived every time the key is re-aimed.
    origin, fwd, _right, _up = light_frame(light)
    obj.rotation_euler = light.rotation_euler.copy()
    obj.location = origin + fwd * distance

    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        bsdf.inputs["Roughness"].default_value = 1.0
        for key in ("Specular IOR Level", "Specular"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = 0.0
                break
    obj.data.materials.clear()
    obj.data.materials.append(mat)

    # Belt and braces on it never being seen: it is placed outside the
    # camera frustum anyway, but a flag that shows up in shot is a black
    # rectangle across the picture, which is not a subtle failure.
    for attr in ("visible_camera", "visible_diffuse", "visible_glossy"):
        if hasattr(obj, attr):
            try:
                setattr(obj, attr, False)
            except (AttributeError, TypeError):
                pass
    return obj


def point_at_screen(camera, u, v, max_dist=12.0):
    """The world point under a normalised screen position (u across, v down).

    Ray-casts from the camera into the scene and returns the first hit, or
    None. Origin top-left, y down — the same convention as every overlay in
    this toolkit and as PIL.

    WHY A CUT IS AIMED THIS WAY. A flag's boundary is far easier to state as
    "the cut should cross the plinth a bit left of centre, at x = 0.41 of
    the frame" than as a world coordinate, because that is how it was
    MEASURED off the reference. Converting the one to the other by hand
    means modelling where the plinth's front face is — and the plinth is
    yawed, so it is not where a first glance puts it, and being a centimetre
    out in depth moves the shadow ten centimetres sideways when the light is
    this side-on. Three attempts at that arithmetic missed. Asking the scene
    where its own surface is cannot.
    """
    scene = bpy.context.scene
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()

    corners = camera.data.view_frame(scene=scene)
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    left, right = min(xs), max(xs)
    bottom, top = min(ys), max(ys)
    z = corners[0].z
    local = Vector((left + (right - left) * u,
                    top - (top - bottom) * v,
                    z))

    mw = camera.matrix_world
    origin = mw.translation.copy()
    direction = ((mw @ local) - origin).normalized()

    # SKIP ANYTHING THE CAMERA CANNOT SEE, and keep going past it.
    #
    # This cost the longest debugging round in the build. The cutter itself
    # is marked invisible to camera, and it is left in the scene between
    # runs — so on every replay after the first, this ray-cast hit LAST
    # RUN'S cutter, a metre in front of the subject, and returned a point
    # floating in mid air. The new cutter was then aimed through that, its
    # shadow fell nowhere near anything, and four rounds of adjusting the
    # light, the side and the geometry all changed the picture without ever
    # touching the actual fault.
    #
    # ray_cast has no filter argument, so the skip is a loop: hit, check,
    # and if it is invisible to camera, restart from just past it.
    start = origin
    remaining = max_dist
    for _ in range(8):
        hit, loc, _n, _i, obj, _m = scene.ray_cast(deps, start, direction,
                                                   distance=remaining)
        if not hit:
            return None
        if getattr(obj, "visible_camera", True):
            return loc.copy()
        step = (loc - start).length + 1e-4
        start = loc + direction * 1e-4
        remaining -= step
        if remaining <= 0.0:
            return None
    return None


def cutter_plane(light, boundary, shadow_point, frac=0.5, width=0.8,
                 height=2.0, tilt=0.0, name="Flag"):
    """A VERTICAL blocker whose shadow edge passes through `boundary`.

    The second attempt at flagging this scene, and the one that works.

    `flag()` builds its plane perpendicular to the beam, which is how a real
    barn door works and is the wrong shape here. A cut that reads as
    vertical on the subject needs a shadow PLANE that contains the world
    vertical, and with a raking side light that plane is nearly parallel to
    the subject's front face — so getting it there by rolling a
    beam-perpendicular flag means solving for a roll of about a degree and a
    half, and being wrong by half a degree swings the cut clean off the
    subject. Two rounds of that were enough.

    Making the blocker's edge vertical BY CONSTRUCTION removes the problem:
    the shadow plane then contains the vertical whatever else moves.

    boundary      a world point the shadow's edge must pass through. Read it
                  off the reference: where the light/dark line crosses a
                  surface whose position you know.
    shadow_point  any world point that must end up IN shadow. This is how
                  the blocker knows which way to extend from its own edge,
                  and it exists because that sign has now been got wrong
                  twice — once as `side`, once as a 180-degree ambiguity in
                  an atan2 — and each time the render came back with a
                  crisp, confident, useless shadow somewhere else.
    frac          how far along the light-to-boundary ray the blocker sits.
                  0 is at the light, 1 is at the subject. It sets the
                  penumbra: light size x (1 - frac) / frac. At 0.5 the
                  penumbra equals the light's own size.
    tilt          degrees to lean the edge off plumb, about the light's own
                  ray, positive leaning the top towards +X. A vertical edge
                  gives a cut that is vertical on screen at every depth; the
                  reference's is not quite — it sits 0.05 of a frame further
                  right where it crosses the pot than where it crosses the
                  plinth 0.2 of a frame lower. Without this the cut can be
                  matched on one of the two and not both.
    """
    origin = light.location.copy()
    B = Vector(boundary)
    ray = B - origin
    edge = origin + ray * frac

    horiz = Vector((ray.x, ray.y, 0.0))
    if horiz.length < 1e-9:
        horiz = Vector((1.0, 0.0, 0.0))
    horiz.normalize()
    across = Vector((-horiz.y, horiz.x, 0.0))     # horizontal, across the ray
    up = Vector((0.0, 0.0, 1.0))

    # Which way to extend: follow the ray to `shadow_point`, see which side
    # of the edge it crosses the blocker's plane on, and cover that side.
    S = Vector(shadow_point)
    denom = (S - origin).dot(horiz)
    if abs(denom) < 1e-9:
        raise ValueError("cutter_plane: shadow_point is edge-on to the light")
    t = (edge - origin).dot(horiz) / denom
    crossing = origin + (S - origin) * t
    sgn = 1.0 if (crossing - edge).dot(across) > 0.0 else -1.0

    import bmesh
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)

    if abs(tilt) > 1e-9:
        up = (Matrix.Rotation(math.radians(tilt), 3, horiz) @ up).normalized()

    a = across * (sgn * width)
    h = up * (height * 0.5)
    bm = bmesh.new()
    for co in (edge - h, edge + a - h, edge + a + h, edge + h):
        bm.verts.new(co)
    bm.verts.ensure_lookup_table()
    bm.faces.new(bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()

    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)

    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        bsdf.inputs["Roughness"].default_value = 1.0
        for key in ("Specular IOR Level", "Specular"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = 0.0
                break
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for attr in ("visible_camera", "visible_diffuse", "visible_glossy"):
        if hasattr(obj, attr):
            try:
                setattr(obj, attr, False)
            except (AttributeError, TypeError):
                pass
    return obj


def camera(target, distance, azimuth, elevation, lens=50.0,
           name="Camera", dof_fstop=None, shift=(0.0, 0.0)):
    """A scene camera, aimed. Made active.

    `shift` moves the frame without moving the camera (Blender's lens
    shift), which is how you put a subject off-centre without introducing
    the keystoning that tilting the camera would.
    """
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    data = bpy.data.cameras.new(name)
    data.lens = lens
    data.shift_x, data.shift_y = shift
    obj = bpy.data.objects.new(name, data)
    obj.location = spherical(target, distance, azimuth, elevation)
    bpy.context.scene.collection.objects.link(obj)
    aim(obj, target)
    if dof_fstop:
        data.dof.use_dof = True
        data.dof.focus_distance = (Vector(target) - obj.location).length
        data.dof.aperture_fstop = dof_fstop
    bpy.context.scene.camera = obj
    return obj


def dust(count, centre, extent, radius=0.0016, energy=14.0, seed=7,
         colour=(1.0, 0.92, 0.78), name="Dust"):
    """Little glowing motes floating in front of the subject.

    Emissive spheres rather than a particle system or a compositor effect,
    because they have to be lit by nothing and occlude nothing, and because
    an emissive sphere is four lines. `seed` is an explicit LCG rather than
    `random` so the same call always puts the same motes in the same places
    — a scene that reshuffles its dust every rebuild cannot be compared
    with its previous render.
    """
    _remove(name)
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs[0].default_value = tuple(colour) + (1.0,)
    emit.inputs[1].default_value = energy
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emit.outputs[0], out.inputs[0])

    state = seed * 1103515245 + 12345
    def rnd():
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state / float(0x7FFFFFFF)

    made = []
    for i in range(count):
        loc = tuple(centre[k] + (rnd() - 0.5) * extent[k] for k in range(3))
        r = radius * (0.5 + rnd())
        mesh = bpy.data.meshes.new("%s_%02d" % (name, i))
        bm_obj = bpy.data.objects.new("%s_%02d" % (name, i), mesh)
        bpy.context.scene.collection.objects.link(bm_obj)
        import bmesh
        bm = bmesh.new()
        try:
            bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)
        except TypeError:
            bmesh.ops.create_icosphere(bm, subdivisions=1, diameter=r)
        bm.to_mesh(mesh)
        bm.free()
        bm_obj.location = loc
        mesh.materials.append(mat)
        made.append(bm_obj)
    return made


def render(path, width, height, samples=96, engine="CYCLES", exposure=0.0,
           look='None', view_transform='Standard', transparent=False,
           denoise=True, prefer_gpu=True):
    """Render the scene camera to `path`. Returns the engine actually used.

    Falls back to EEVEE under whatever name this Blender has for it if
    Cycles is not compiled in.
    """
    scene = bpy.context.scene
    engine = set_engine(engine)

    if engine == "CYCLES":
        scene.cycles.samples = samples
        scene.cycles.use_denoising = denoise
        scene.cycles.max_bounces = 8
        scene.cycles.transparent_max_bounces = 4
        if prefer_gpu:
            # Best effort: if no GPU device is configured, Cycles silently
            # renders on the CPU anyway, so this can only help.
            try:
                scene.cycles.device = 'GPU'
            except (AttributeError, TypeError):
                pass
        # Config has the last word, so a replay can pin every Cycles render
        # to one device regardless of what each call site asked for.
        _apply_cycles_device(scene)
    else:
        # EEVEE, set up to be worth using. Out of the box it does no
        # raytraced shadowing and its shadow maps are coarse enough that a
        # 2 mm stalk casts nothing at all, which on a plant is most of the
        # geometry. These are the switches that matter; each is guarded
        # because the names have churned across 4.x and 5.x and a missing
        # one should not take the render down.
        eevee = scene.eevee
        for attr, value in (("taa_render_samples", samples),
                            ("use_raytracing", True),
                            ("use_shadows", True),
                            ("use_volumetric_shadows", False),
                            ("shadow_ray_count", 2),
                            ("shadow_step_count", 6),
                            ("use_shadow_jitter_viewport", True),
                            ("shadow_cube_size", '2048'),
                            ("shadow_cascade_size", '2048'),
                            ("use_soft_shadows", True),
                            ("use_gtao", True),
                            ("gtao_distance", 0.12)):
            if hasattr(eevee, attr):
                try:
                    setattr(eevee, attr, value)
                except (TypeError, ValueError):
                    pass
        if hasattr(eevee, "ray_tracing_options"):
            rt = eevee.ray_tracing_options
            for attr, value in (("use_denoise", True),
                                ("resolution_scale", '1')):
                if hasattr(rt, attr):
                    try:
                        setattr(rt, attr, value)
                    except (TypeError, ValueError):
                        pass

    scene.render.resolution_x = int(width)
    scene.render.resolution_y = int(height)
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = transparent
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = path

    vs = scene.view_settings
    vs.exposure = exposure
    # The VIEW TRANSFORM has to be set before the look: looks are named
    # per transform ("AgX - Punchy" does not exist under Filmic), and
    # setting a look that the current transform does not have raises and
    # leaves whatever was there. Both are wrapped, because a silently
    # ignored tone mapping is the kind of thing that gets blamed on the
    # lights for an hour.
    for name in (view_transform, "Standard"):
        try:
            vs.view_transform = name
            break
        except TypeError:
            continue
    try:
        vs.look = look
    except TypeError:
        vs.look = 'None'

    bpy.ops.render.render(write_still=True)
    return engine


def _project_path(path):
    """Resolve a relative output path against the harness root."""
    if os.path.isabs(path):
        return path
    try:
        from geom_digest import resolve
        return resolve(path)
    except Exception:
        return os.path.abspath(path)


def _mesh_world_points(obj):
    """Return evaluated world-space mesh points without leaking a temp mesh."""
    if obj.type != "MESH":
        raise ValueError("lighting: camera-fit objects must be meshes: %s" % obj.name)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world.copy()
        return [matrix @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def fit_camera_to_sequence(camera_name, object_names, frames, *, margin=0.06,
                           target=None, max_iterations=12):
    """Fit a perspective camera around an evaluated multi-frame envelope.

    ``object_names`` is a collection of mesh names and ``frames`` is the
    inclusive set of poses that the presentation must contain.  The helper
    evaluates every requested pose, aims the named camera at ``target`` (or at
    the mean of the collected points), and moves it farther along that ray
    until every projected point lies inside ``margin`` of all four frame edges.
    It does not change the model, scene frame range, or animation; by default
    it restores the caller's current frame.  ``target`` and ``margin`` are
    world/NDC parameters, so the same call works for any animated assembly.

    The returned report includes before/after normalized bounds, the final
    camera distance, iteration count, and an ``inside_frame`` verdict.  This
    is deliberately a scale/margin fit, not an artistic perspective solver:
    choose the intended azimuth/elevation first, then fit across the full
    motion rather than trusting only a visually convenient midpoint.
    """
    if isinstance(object_names, str):
        names = [object_names]
    else:
        try:
            names = list(object_names)
        except TypeError:
            raise ValueError("fit_camera_to_sequence: object_names must be iterable") from None
    if not names or len(set(names)) != len(names):
        raise ValueError("fit_camera_to_sequence: object_names must be non-empty and unique")
    try:
        frame_list = sorted({int(frame) for frame in frames})
    except (TypeError, ValueError):
        raise ValueError("fit_camera_to_sequence: frames must be iterable integers") from None
    if not frame_list:
        raise ValueError("fit_camera_to_sequence: frames must not be empty")
    margin = float(margin)
    if not math.isfinite(margin) or not 0.0 <= margin < 0.5:
        raise ValueError("fit_camera_to_sequence: margin must be in [0, 0.5)")
    max_iterations = int(max_iterations)
    if max_iterations < 1:
        raise ValueError("fit_camera_to_sequence: max_iterations must be positive")

    camera_obj = bpy.data.objects.get(camera_name)
    if camera_obj is None or camera_obj.type != "CAMERA":
        raise KeyError("fit_camera_to_sequence: camera not found: %s" % camera_name)
    objects = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise KeyError("fit_camera_to_sequence: mesh not found: %s" % name)
        objects.append(obj)

    scene = bpy.context.scene
    saved_frame = int(scene.frame_current)
    points = []
    try:
        for frame in frame_list:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            for obj in objects:
                points.extend(_mesh_world_points(obj))
    finally:
        scene.frame_set(saved_frame)
        bpy.context.view_layer.update()
    if not points:
        raise ValueError("fit_camera_to_sequence: selected meshes have no vertices")

    target_vec = (Vector(target) if target is not None
                  else sum(points, Vector((0.0, 0.0, 0.0))) / len(points))
    direction = camera_obj.location - target_vec
    if direction.length < 1.0e-9:
        raise ValueError("fit_camera_to_sequence: camera and target coincide")
    direction.normalize()
    distance_before = (camera_obj.location - target_vec).length
    distance = distance_before
    aim(camera_obj, target_vec)

    from bpy_extras.object_utils import world_to_camera_view

    def bounds():
        projected = [world_to_camera_view(scene, camera_obj, point)
                     for point in points]
        return {
            "u": [min(float(point.x) for point in projected),
                  max(float(point.x) for point in projected)],
            "v": [min(float(point.y) for point in projected),
                  max(float(point.y) for point in projected)],
            "behind_camera_count": sum(1 for point in projected if point.z <= 0.0),
        }

    before = bounds()
    allowed = 0.5 - margin
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        current = bounds()
        max_offset = max(
            abs(current["u"][0] - 0.5), abs(current["u"][1] - 0.5),
            abs(current["v"][0] - 0.5), abs(current["v"][1] - 0.5),
        )
        if max_offset <= allowed + 1.0e-9 and current["behind_camera_count"] == 0:
            break
        scale = max(1.01, (max_offset / allowed) * 1.02)
        distance *= scale
        camera_obj.location = target_vec + direction * distance
        aim(camera_obj, target_vec)
        bpy.context.view_layer.update()
    after = bounds()
    inside = (
        after["behind_camera_count"] == 0
        and after["u"][0] >= margin
        and after["u"][1] <= 1.0 - margin
        and after["v"][0] >= margin
        and after["v"][1] <= 1.0 - margin
    )
    scene.frame_set(saved_frame)
    bpy.context.view_layer.update()
    return {
        "camera": camera_name,
        "objects": names,
        "frames": frame_list,
        "margin": margin,
        "target": [float(value) for value in target_vec],
        "distance_before": float(distance_before),
        "distance_after": float(distance),
        "iterations": iterations,
        "before": before,
        "after": after,
        "inside_frame": bool(inside),
        "current_frame": int(scene.frame_current),
    }


def fit_camera_to_target_sequence(camera_name, object_names, frames,
                                   target_bbox_px, *, target=(0.0, 0.0, 0.0),
                                   azimuth=270.0, elevation=0.0, distance=10.0,
                                   lens=50.0, resolution=None,
                                   fit_dimension="height", pose_candidates=None,
                                   shift_probe=0.01, max_iterations=12):
    """Fit one perspective camera to a target envelope over several frames.

    ``target_bbox_px`` is a continuous ``(left, top, right, bottom)`` box in
    top-left-origin pixels.  The selected mesh vertices are evaluated at every
    frame in ``frames`` and unioned, so the fit is not accidentally based on a
    convenient still pose.  The camera pose is described by the same spherical
    ``target``/``azimuth``/``elevation``/``distance`` convention as
    :func:`camera`; ``pose_candidates`` may contain ``(azimuth, distance)``
    pairs or dictionaries with those keys (and optional ``elevation``/``lens``).

    The helper fits ``fit_dimension`` (``"height"`` or ``"width"``) and chooses
    the candidate with the smallest residual on the other dimension.  It then
    measures the installed camera's lens-shift response and centres the union
    on the target box.  This makes a near-front perspective choice explicit
    without baking in an object-specific sensor formula.  It changes the named
    camera and the scene render resolution, never the meshes, and restores the
    caller's current frame before returning a JSON-ready report.
    """
    from bpy_extras.object_utils import world_to_camera_view

    if isinstance(object_names, str):
        names = [object_names]
    else:
        try:
            names = list(object_names)
        except TypeError:
            raise ValueError(
                "fit_camera_to_target_sequence: object_names must be iterable"
            ) from None
    if not names or len(set(names)) != len(names):
        raise ValueError(
            "fit_camera_to_target_sequence: object_names must be non-empty and unique"
        )
    try:
        frame_list = sorted({int(frame) for frame in frames})
    except (TypeError, ValueError):
        raise ValueError(
            "fit_camera_to_target_sequence: frames must be iterable integers"
        ) from None
    if not frame_list:
        raise ValueError("fit_camera_to_target_sequence: frames must not be empty")
    if len(target_bbox_px) != 4:
        raise ValueError(
            "fit_camera_to_target_sequence: target_bbox_px must be (left, top, right, bottom)"
        )
    left, top, right, bottom = (float(value) for value in target_bbox_px)
    if not (right > left and bottom > top):
        raise ValueError(
            "fit_camera_to_target_sequence: target_bbox_px must have positive size"
        )
    fit_dimension = str(fit_dimension).lower()
    if fit_dimension not in {"height", "width"}:
        raise ValueError(
            "fit_camera_to_target_sequence: fit_dimension must be 'height' or 'width'"
        )
    try:
        probe = abs(float(shift_probe))
    except (TypeError, ValueError):
        raise ValueError(
            "fit_camera_to_target_sequence: shift_probe must be non-zero"
        ) from None
    if probe < 1.0e-12:
        raise ValueError(
            "fit_camera_to_target_sequence: shift_probe must be non-zero"
        )
    max_iterations = int(max_iterations)
    if max_iterations < 1:
        raise ValueError(
            "fit_camera_to_target_sequence: max_iterations must be positive"
        )
    if resolution is None:
        width = int(bpy.context.scene.render.resolution_x)
        height = int(bpy.context.scene.render.resolution_y)
    else:
        if len(resolution) != 2:
            raise ValueError(
                "fit_camera_to_target_sequence: resolution must be (width, height)"
            )
        width, height = (int(value) for value in resolution)
    if width < 1 or height < 1:
        raise ValueError("fit_camera_to_target_sequence: resolution must be positive")
    if float(distance) <= 0.0 or float(lens) <= 0.0:
        raise ValueError(
            "fit_camera_to_target_sequence: distance and lens must be positive"
        )

    camera_obj = bpy.data.objects.get(camera_name)
    if camera_obj is None or camera_obj.type != "CAMERA":
        raise KeyError(
            "fit_camera_to_target_sequence: camera not found: %s" % camera_name
        )
    objects = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise KeyError(
                "fit_camera_to_target_sequence: mesh not found: %s" % name
            )
        objects.append(obj)

    scene = bpy.context.scene
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    focus = Vector(target)
    saved_frame = int(scene.frame_current)
    points = []
    try:
        for frame in frame_list:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            for obj in objects:
                points.extend(_mesh_world_points(obj))
    finally:
        scene.frame_set(saved_frame)
        bpy.context.view_layer.update()
    if not points:
        raise ValueError(
            "fit_camera_to_target_sequence: selected meshes have no vertices"
        )

    if pose_candidates is None:
        raw_candidates = [{
            "azimuth": float(azimuth),
            "elevation": float(elevation),
            "distance": float(distance),
            "lens": float(lens),
        }]
    else:
        raw_candidates = []
        try:
            candidate_items = list(pose_candidates)
        except TypeError:
            raise ValueError(
                "fit_camera_to_target_sequence: pose_candidates must be iterable"
            ) from None
        for item in candidate_items:
            if isinstance(item, dict):
                spec = {
                    "azimuth": float(item["azimuth"]),
                    "elevation": float(item.get("elevation", elevation)),
                    "distance": float(item["distance"]),
                    "lens": float(item.get("lens", lens)),
                }
            else:
                values = list(item)
                if len(values) not in (2, 3):
                    raise ValueError(
                        "fit_camera_to_target_sequence: pose candidates need "
                        "(azimuth, distance) or (azimuth, distance, elevation)"
                    )
                spec = {
                    "azimuth": float(values[0]),
                    "distance": float(values[1]),
                    "elevation": float(values[2]) if len(values) == 3
                    else float(elevation),
                    "lens": float(lens),
                }
            if spec["distance"] <= 0.0 or spec["lens"] <= 0.0:
                raise ValueError(
                    "fit_camera_to_target_sequence: candidate distance/lens must be positive"
                )
            raw_candidates.append(spec)
        if not raw_candidates:
            raise ValueError(
                "fit_camera_to_target_sequence: pose_candidates must not be empty"
            )

    target_width = right - left
    target_height = bottom - top
    target_center = ((left + right) * 0.5 / width,
                     (top + bottom) * 0.5 / height)

    def place(spec, chosen_lens):
        camera_obj.location = spherical(
            focus, spec["distance"], spec["azimuth"], spec["elevation"]
        )
        camera_obj.rotation_mode = "XYZ"
        camera_obj.rotation_euler = (
            focus - camera_obj.location
        ).to_track_quat("-Z", "Y").to_euler()
        camera_obj.data.lens = float(chosen_lens)
        camera_obj.data.shift_x = 0.0
        camera_obj.data.shift_y = 0.0
        scene.camera = camera_obj
        bpy.context.view_layer.update()

    def projected():
        scene.view_layers[0].update()
        return [world_to_camera_view(scene, camera_obj, point)
                for point in points]

    def bbox(values):
        if not values:
            raise ValueError(
                "fit_camera_to_target_sequence: projection produced no points"
            )
        return {
            "px": [
                min(float(point.x) for point in values) * width,
                (1.0 - max(float(point.y) for point in values)) * height,
                max(float(point.x) for point in values) * width,
                (1.0 - min(float(point.y) for point in values)) * height,
            ],
            "behind_camera_count": sum(
                1 for point in values if float(point.z) <= 0.0
            ),
        }

    def fit_one(spec):
        place(spec, spec["lens"])
        chosen_lens = float(spec["lens"])
        target_size = target_height if fit_dimension == "height" else target_width
        for _ in range(max_iterations):
            current = bbox(projected())
            current_size = (current["px"][3] - current["px"][1]
                            if fit_dimension == "height"
                            else current["px"][2] - current["px"][0])
            if current_size <= 1.0e-12:
                raise RuntimeError(
                    "fit_camera_to_target_sequence: projected size is zero"
                )
            chosen_lens *= target_size / current_size
            camera_obj.data.lens = chosen_lens
            bpy.context.view_layer.update()
            if abs(current_size - target_size) <= 1.0e-7:
                break

        base = projected()
        base_box = bbox(base)
        x_base = base_box["px"][0:4:2]
        y_base = base_box["px"][1:4:2]
        base_center = ((x_base[0] + x_base[1]) * 0.5 / width,
                       (y_base[0] + y_base[1]) * 0.5 / height)

        camera_obj.data.shift_x = probe
        x_shifted = projected()
        camera_obj.data.shift_x = 0.0
        camera_obj.data.shift_y = probe
        y_shifted = projected()
        camera_obj.data.shift_y = 0.0
        x_response = sum(
            (float(x_shifted[index].x) - float(base[index].x)) / probe
            for index in range(len(points))
        ) / len(points)
        y_response = sum(
            (1.0 - float(y_shifted[index].y) -
             (1.0 - float(base[index].y))) / probe
            for index in range(len(points))
        ) / len(points)
        if abs(x_response) < 1.0e-12 or abs(y_response) < 1.0e-12:
            raise RuntimeError(
                "fit_camera_to_target_sequence: camera shift response is degenerate"
            )
        camera_obj.data.shift_x = (
            target_center[0] - base_center[0]
        ) / x_response
        camera_obj.data.shift_y = (
            target_center[1] - base_center[1]
        ) / y_response
        final = bbox(projected())
        final_width = final["px"][2] - final["px"][0]
        final_height = final["px"][3] - final["px"][1]
        error = abs((final_height if fit_dimension == "width" else final_width)
                    - (target_height if fit_dimension == "width" else target_width))
        return {
            "azimuth": spec["azimuth"],
            "elevation": spec["elevation"],
            "distance": spec["distance"],
            "lens": float(chosen_lens),
            "bbox_px": [float(value) for value in final["px"]],
            "width_px": float(final_width),
            "height_px": float(final_height),
            "fit_dimension": fit_dimension,
            "other_dimension_error_px": float(error),
            "behind_camera_count": int(final["behind_camera_count"]),
            "shift": [float(camera_obj.data.shift_x),
                      float(camera_obj.data.shift_y)],
            "shift_response_px_per_unit": [float(x_response * width),
                                            float(y_response * height)],
        }

    candidates = []
    for spec in raw_candidates:
        result = fit_one(spec)
        candidates.append(result)
    valid = [item for item in candidates if item["behind_camera_count"] == 0]
    if not valid:
        raise RuntimeError(
            "fit_camera_to_target_sequence: every candidate has points behind the camera"
        )
    chosen = min(valid, key=lambda item: item["other_dimension_error_px"])
    chosen_spec = {
        "azimuth": chosen["azimuth"],
        "elevation": chosen["elevation"],
        "distance": chosen["distance"],
        "lens": chosen["lens"],
    }
    final = fit_one(chosen_spec)
    scene.frame_set(saved_frame)
    bpy.context.view_layer.update()
    return {
        "camera": camera_name,
        "objects": names,
        "frames": frame_list,
        "resolution": [width, height],
        "target_bbox_px": [left, top, right, bottom],
        "target_size_px": [target_width, target_height],
        "target_center_px": [target_center[0] * width,
                             target_center[1] * height],
        "fit_dimension": fit_dimension,
        "candidates": candidates,
        "chosen": final,
        "camera_location": [float(value) for value in camera_obj.location],
        "camera_lens": float(camera_obj.data.lens),
        "camera_shift": [float(camera_obj.data.shift_x),
                         float(camera_obj.data.shift_y)],
        "current_frame": int(scene.frame_current),
    }


def render_sequence(output_dir, frames, *, prefix="frame_", digits=4,
                    width=480, height=270, samples=12, engine="CYCLES",
                    exposure=0.0, look="None", view_transform="Standard",
                    transparent=False, denoise=True, prefer_gpu=True,
                    max_bounces=4, clear=True):
    """Render selected scene frames as a deterministic PNG sequence.

    ``frames`` may be any ordered iterable of frame numbers.  Each frame is
    written directly to ``output_dir/prefix + zero-padded frame + .png``;
    existing files with the same prefix are removed when ``clear`` is true.
    The scene frame range, current frame, render settings, engine, and tone
    mapping are restored even when the sequence is complete, so this is safe
    to call from a handoff action.  Engine selection follows :func:`render`.
    PNG is intentional: it is available in Blender builds that do not ship an
    FFMPEG encoder, while still giving a scrub-able and shell-auditable movie
    substitute.
    """
    try:
        frame_list = [int(frame) for frame in frames]
    except (TypeError, ValueError):
        raise ValueError("render_sequence: frames must be iterable integers") from None
    if not frame_list:
        raise ValueError("render_sequence: frames must not be empty")
    if len(set(frame_list)) != len(frame_list):
        raise ValueError("render_sequence: frames must be unique")
    if int(digits) < 1:
        raise ValueError("render_sequence: digits must be positive")
    output_dir = _project_path(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    if clear:
        for name in os.listdir(output_dir):
            if name.startswith(prefix) and name.lower().endswith(".png"):
                try:
                    os.remove(os.path.join(output_dir, name))
                except OSError:
                    pass

    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("render_sequence: scene has no active camera")
    render_settings = scene.render
    view_settings = scene.view_settings
    saved = {
        "frame": int(scene.frame_current),
        "frame_start": int(scene.frame_start),
        "frame_end": int(scene.frame_end),
        "filepath": render_settings.filepath,
        "resolution_x": render_settings.resolution_x,
        "resolution_y": render_settings.resolution_y,
        "resolution_percentage": render_settings.resolution_percentage,
        "file_format": render_settings.image_settings.file_format,
        "film_transparent": render_settings.film_transparent,
        "engine": render_settings.engine,
        "exposure": view_settings.exposure,
        "view_transform": view_settings.view_transform,
        "look": view_settings.look,
    }
    cycles = getattr(scene, "cycles", None)
    cycles_saved = {}
    if cycles is not None:
        for attr in ("samples", "max_bounces", "use_denoising", "device"):
            if hasattr(cycles, attr):
                cycles_saved[attr] = getattr(cycles, attr)

    files = []
    actual_engine = None
    try:
        actual_engine = set_engine(engine)
        render_settings.resolution_x = int(width)
        render_settings.resolution_y = int(height)
        render_settings.resolution_percentage = 100
        render_settings.image_settings.file_format = "PNG"
        render_settings.film_transparent = bool(transparent)
        view_settings.exposure = float(exposure)
        for candidate in (view_transform, "Standard"):
            try:
                view_settings.view_transform = candidate
                break
            except TypeError:
                continue
        try:
            view_settings.look = look
        except TypeError:
            view_settings.look = "None"
        if actual_engine == "CYCLES" and cycles is not None:
            cycles.samples = int(samples)
            cycles.use_denoising = bool(denoise)
            cycles.max_bounces = int(max_bounces)
            if prefer_gpu:
                try:
                    cycles.device = "GPU"
                except (AttributeError, TypeError):
                    pass
            _apply_cycles_device(scene)

        for frame in frame_list:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            path = os.path.join(output_dir, "%s%0*d.png" % (prefix, int(digits), frame))
            render_settings.filepath = path
            bpy.ops.render.render(write_still=True)
            files.append(path)
    finally:
        scene.frame_start = saved["frame_start"]
        scene.frame_end = saved["frame_end"]
        render_settings.filepath = saved["filepath"]
        render_settings.resolution_x = saved["resolution_x"]
        render_settings.resolution_y = saved["resolution_y"]
        render_settings.resolution_percentage = saved["resolution_percentage"]
        render_settings.image_settings.file_format = saved["file_format"]
        render_settings.film_transparent = saved["film_transparent"]
        try:
            render_settings.engine = saved["engine"]
        except TypeError:
            pass
        view_settings.exposure = saved["exposure"]
        try:
            view_settings.view_transform = saved["view_transform"]
        except TypeError:
            pass
        try:
            view_settings.look = saved["look"]
        except TypeError:
            pass
        if cycles is not None:
            for attr, value in cycles_saved.items():
                try:
                    setattr(cycles, attr, value)
                except (AttributeError, TypeError):
                    pass
        scene.frame_set(saved["frame"])
        bpy.context.view_layer.update()

    return {
        "output_dir": output_dir,
        "frames": frame_list,
        "files": files,
        "engine": actual_engine,
        "count": len(files),
        "bytes_total": sum(os.path.getsize(path) for path in files
                            if os.path.exists(path)),
        "restored_frame": int(scene.frame_current),
        "restored_scene_range": [int(scene.frame_start), int(scene.frame_end)],
    }
