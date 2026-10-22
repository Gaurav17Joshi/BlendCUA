"""Procedural mesh primitives: a sweeper, a lathe, a chamfered box, and the
placement helpers that go with them.

General-purpose, and deliberately so. There is nothing here about any
particular subject — these are the shapes you reach for when a thing has to
be built from 3D control points rather than traced in screen space, which is
the case whenever the reference is a perspective render, or the subject has
depth that one view cannot show, or there simply is no reference.

    catmull3(anchors, n)        3D Catmull-Rom. lib.pathgen's is 2D only.
    tube(points, radii, ...)    sweep a ring along a 3D polyline
    spin_profile(profile, ...)  solid of revolution from (radius, z) pairs
    bevel_box(size, bevel, ...) a chamfered cube
    smooth_by_angle(obj, deg)   smooth shading with sharp edges kept sharp
    place / point_on / join     put a part somewhere and tidy up after

For the subject-specific shapes built ON TOP of these — a chilli plant's
leaf and fruit, say — see the run's own step folders. Those belong to one
build and have no business in a shared toolkit.

WHY THIS EXISTS RATHER THAN `handle.apply_chain`
------------------------------------------------
`apply_chain` extrudes a face through NORMALISED SCREEN points, which is
exactly right for tracing a silhouette off a reference photograph and
exactly wrong for anything whose shape lives in three dimensions. A plant is
the clearest case: a dozen branches leaving one stem at a dozen azimuths,
where the whole point is that some come towards the camera and some go away.
Traced in screen coordinates every one of them lands in the same plane and
the result is a pressed flower.

THE ONE THING THAT IS EASY TO GET WRONG: TWIST
----------------------------------------------
Sweeping a ring along a curve needs a reference direction at every point,
and the obvious choice — "up crossed with the tangent" — flips over when the
tangent passes through vertical. A drooping branch does pass through
vertical, and the ring flips 180 degrees in one segment, which shows up as a
pinched, folded joint. `frames()` below uses parallel transport instead:
each frame is the previous one rotated by the minimal rotation between
consecutive tangents, so it never flips and never accumulates spin.
"""

import math

import bpy
import bmesh
from mathutils import Vector, Matrix


def finish(bm, name, location=(0.0, 0.0, 0.0), smooth=False):
    """bmesh -> a linked, flat-shaded object at `location`.

    Replaces any object of the same name. Actions get re-run constantly in
    this harness (edit the file, replay the step), so anything that ADDS
    rather than REPLACES leaves a second copy of the whole plant one
    millimetre from the first — which renders almost identically and is
    invisible until the vertex count is read.
    """
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = smooth
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


# ─── curves and frames ──────────────────────────────────────────────────────


def catmull3(anchors, n_per_seg=8):
    """3D Catmull-Rom through `anchors`, ends clamped.

    lib.pathgen has this in 2D and it is used by the stroke generators; a
    branch needs the same curve in three dimensions, and widening the 2D
    one would change a function four sculpt tools already depend on.
    """
    pts = [Vector(p) for p in anchors]
    if len(pts) < 3:
        if len(pts) < 2:
            return pts
        a, b = pts
        return [a.lerp(b, i / float(n_per_seg)) for i in range(n_per_seg + 1)]

    ext = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        last = (i == len(pts) - 2)
        for s in range(n_per_seg + (1 if last else 0)):
            t = s / float(n_per_seg)
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2.0 * p1) + (-p0 + p2) * t
                              + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
                              + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3))
    return out


def tangents(points):
    """Unit tangent at each point — central differences, one-sided at the
    ends. A zero-length segment (a repeated control point) borrows its
    neighbour rather than normalising a zero vector."""
    n = len(points)
    out = []
    for i in range(n):
        if i == 0:
            d = points[1] - points[0]
        elif i == n - 1:
            d = points[-1] - points[-2]
        else:
            d = points[i + 1] - points[i - 1]
        if d.length < 1e-9:
            d = out[-1] if out else Vector((0.0, 0.0, 1.0))
        out.append(d.normalized())
    return out


def frames(points, seed_up=(0.0, 0.0, 1.0)):
    """Parallel-transported (normal, binormal) at each point.

    Returns two lists the same length as `points`. See the module docstring
    for why this is not "up cross tangent": that flips when the tangent
    passes vertical, and a branch that droops below horizontal does exactly
    that.
    """
    ts = tangents(points)
    up = Vector(seed_up)
    if abs(ts[0].dot(up)) > 0.98:          # first tangent is (anti)parallel
        up = Vector((1.0, 0.0, 0.0))       # to the seed — pick another
    n = (up - ts[0] * up.dot(ts[0])).normalized()

    normals, binormals = [n], [ts[0].cross(n).normalized()]
    for i in range(1, len(points)):
        q = ts[i - 1].rotation_difference(ts[i])   # minimal rotation
        n = (q @ normals[-1])
        n = (n - ts[i] * n.dot(ts[i])).normalized()   # re-orthogonalise
        normals.append(n)
        binormals.append(ts[i].cross(n).normalized())
    return normals, binormals


# ─── the sweeper ────────────────────────────────────────────────────────────


def tube(points, radii, sides=6, name="Tube", cap_start=True, cap_end=True,
         smooth=False, phase=0.0):
    """Sweep a `sides`-gon along the 3D polyline `points`.

    points   list of 3-tuples / Vectors, in WORLD space.
    radii    one radius per point (a scalar broadcasts to all of them). A
             radius of exactly 0 collapses that end to a single vertex, so
             a stem that tapers to nothing is a cone tip and not a tiny
             flat disc catching the light — which is what a 0.5 mm end cap
             does under a hard key light.
    phase    rotate the cross-section about the axis, in turns. Useful when
             two tubes meet: matching phase makes the facets line up.

    Returns the object. Origin is at world zero and the geometry carries
    the world coordinates, so several tubes can be joined without anything
    having to be re-based.
    """
    pts = [Vector(p) for p in points]
    if len(pts) < 2:
        raise ValueError("tube needs at least two points")
    if not hasattr(radii, "__len__"):
        radii = [radii] * len(pts)
    if len(radii) != len(pts):
        raise ValueError("tube: %d points but %d radii"
                         % (len(pts), len(radii)))

    normals, binormals = frames(pts)
    bm = bmesh.new()

    rings = []          # per point: list of verts, or a single vert for a tip
    for i, p in enumerate(pts):
        r = radii[i]
        if r <= 1e-7:
            rings.append([bm.verts.new(p)])
            continue
        ring = []
        for k in range(sides):
            a = 2.0 * math.pi * (k / float(sides) + phase)
            off = normals[i] * (math.cos(a) * r) + binormals[i] * (math.sin(a) * r)
            ring.append(bm.verts.new(p + off))
        rings.append(ring)

    for i in range(len(rings) - 1):
        a, b = rings[i], rings[i + 1]
        if len(a) == 1 and len(b) == 1:
            continue
        if len(a) == 1:                      # cone out of a point
            for k in range(sides):
                bm.faces.new((a[0], b[k], b[(k + 1) % sides]))
        elif len(b) == 1:                    # cone into a point
            for k in range(sides):
                bm.faces.new((a[k], a[(k + 1) % sides], b[0]))
        else:
            for k in range(sides):
                j = (k + 1) % sides
                bm.faces.new((a[k], a[j], b[j], b[k]))

    if cap_start and len(rings[0]) > 1:
        bm.faces.new(list(reversed(rings[0])))
    if cap_end and len(rings[-1]) > 1:
        bm.faces.new(rings[-1])

    return finish(bm, name, smooth=smooth)


# ─── the lathe ──────────────────────────────────────────────────────────────


def spin_profile(profile, sides=16, name="Spun", location=(0.0, 0.0, 0.0),
                 smooth=False):
    """Solid of revolution about Z from a list of (radius, z).

    A silhouette IS the profile of a solid of revolution, which is why the
    pot could be measured off the reference instead of guessed: the
    half-width of the pot at each height is the radius of its ring there.

    A radius of 0 at either end becomes a pole vertex. The profile is NOT
    closed for you — to make a bowl (an outside wall, a rim, and an inside
    wall) give the whole section as one open path from the outer bottom,
    up the outside, over the rim, and back down the inside. The result is
    a real vessel with a wall of real thickness, which matters here because
    the reference plainly shows the rim's thickness and the soil below it.
    """
    if len(profile) < 2:
        raise ValueError("spin_profile needs at least two (radius, z) pairs")
    bm = bmesh.new()

    rings = []
    for r, z in profile:
        if abs(r) <= 1e-7:
            rings.append([bm.verts.new((0.0, 0.0, z))])
            continue
        ring = []
        for k in range(sides):
            a = 2.0 * math.pi * k / float(sides)
            ring.append(bm.verts.new((r * math.cos(a), r * math.sin(a), z)))
        rings.append(ring)

    for i in range(len(rings) - 1):
        a, b = rings[i], rings[i + 1]
        if len(a) == 1 and len(b) == 1:
            continue
        if len(a) == 1:
            for k in range(sides):
                bm.faces.new((a[0], b[k], b[(k + 1) % sides]))
        elif len(b) == 1:
            for k in range(sides):
                bm.faces.new((a[k], a[(k + 1) % sides], b[0]))
        else:
            for k in range(sides):
                j = (k + 1) % sides
                bm.faces.new((a[k], a[j], b[j], b[k]))

    if len(rings[0]) > 1:
        bm.faces.new(list(reversed(rings[0])))
    if len(rings[-1]) > 1:
        bm.faces.new(rings[-1])

    return finish(bm, name, location=location, smooth=smooth)


def spin_profiles(specs, default_sides=16, default_smooth=False):
    """Build a batch of named solids of revolution from profile specifications.

    Each item is a mapping with ``name`` and ``profile`` (ordered ``(radius, z)``
    pairs).  Optional ``sides``, ``location`` and ``smooth`` values are forwarded
    to :func:`spin_profile`; the returned objects preserve the input order.
    The profiles, locations and names remain caller data, so this helper is
    equally useful for a set of turned supports, beads, vessels, or other
    rotational parts and does not impose a subject-specific assembly.
    """
    if not isinstance(specs, (list, tuple)) or not specs:
        raise ValueError("spin_profiles needs a non-empty list of specifications")
    default_sides = int(default_sides)
    if default_sides < 3:
        raise ValueError("spin_profiles default_sides must be at least 3")
    built = []
    for spec in specs:
        if not isinstance(spec, dict):
            raise TypeError("each spin_profiles specification must be a dict")
        if not spec.get("name") or "profile" not in spec:
            raise ValueError("each spin_profiles specification needs name and profile")
        sides = int(spec.get("sides", default_sides))
        if sides < 3:
            raise ValueError("spin_profiles sides must be at least 3")
        location = spec.get("location", (0.0, 0.0, 0.0))
        built.append(spin_profile(
            spec["profile"], sides=sides, name=spec["name"],
            location=location, smooth=bool(spec.get("smooth", default_smooth))))
    return built


def smooth_by_angle(obj, degrees=32.0):
    """Smooth shading, but keep every edge sharper than `degrees` sharp.

    A lathe is the case that needs this. Flat shading a 24-sided pot leaves
    visible vertical bands down its belly; plain smooth shading removes them
    and also smears the rim, whose flat top meets its outer wall at a right
    angle and should stay a crisp edge. Smooth-by-angle gives both: the
    belly, where consecutive faces differ by a few degrees, shades
    continuously, and the rim, where they differ by ninety, does not.

    Blender moved this three times — an operator now, a mesh property
    before 4.1, and a modifier in between — so all three are tried. It is
    only cosmetic, so failing all three is not worth raising over.
    """
    import bpy
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for p in obj.data.polygons:
        p.use_smooth = True

    prev = bpy.context.view_layer.objects.active
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(degrees))
    except (AttributeError, RuntimeError, TypeError):
        me = obj.data
        if hasattr(me, "use_auto_smooth"):          # pre-4.1
            me.use_auto_smooth = True
            me.auto_smooth_angle = math.radians(degrees)
        else:
            try:
                bpy.ops.object.modifier_add_node_group(
                    asset_library_type='ESSENTIALS',
                    relative_asset_identifier=(
                        "geometry_nodes/smooth_by_angle.blend/NodeTree/"
                        "Smooth by Angle"))
            except (AttributeError, RuntimeError, TypeError):
                pass
    if prev is not None:
        bpy.context.view_layer.objects.active = prev
    return obj


def bevel_box(size, bevel=0.0, segments=1, name="Box",
              location=(0.0, 0.0, 0.0), rotation_z=0.0):
    """A chamfered cube. `size` is (x, y, z) FULL dimensions.

    Built as a cube plus bmesh.ops.bevel rather than a modifier, so what
    the file says is what the mesh is — a modifier would leave the vertex
    count reported by every later check describing a cube.
    """
    sx, sy, sz = size
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= sx
        v.co.y *= sy
        v.co.z *= sz
    if bevel > 0.0:
        bmesh.ops.bevel(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                        offset=bevel, segments=int(segments),
                        profile=0.5, affect='EDGES', clamp_overlap=True)
    if abs(rotation_z) > 1e-9:
        bmesh.ops.rotate(bm, verts=bm.verts[:], cent=(0.0, 0.0, 0.0),
                         matrix=Matrix.Rotation(math.radians(rotation_z), 3, 'Z'))
    return finish(bm, name, location=location)


# ─── a leaf ─────────────────────────────────────────────────────────────────

# Half-width along the blade, as (t from base to tip, fraction of `width`).
# Read off crop_leaves_left.png: a chilli leaf is lanceolate — it reaches
# its full width early, about a third of the way up, then runs out to a
# long point. A shape that is widest in the MIDDLE reads as a bay leaf,
# which is the sort of error that looks fine on its own and wrong the
# moment there are twenty of them.


def icosphere(bm, radius, subdivisions=1):
    """create_icosphere with a fallback for the argument rename.

    The keyword went from `diameter` to `radius` in the 2.8x/3.x era. This
    build runs against 5.2, but the module is meant to outlive one Blender,
    and an eye that silently comes out twice the intended size is a
    particularly annoying thing to chase.
    """
    try:
        bmesh.ops.create_icosphere(bm, subdivisions=subdivisions,
                                   radius=radius)
    except TypeError:
        bmesh.ops.create_icosphere(bm, subdivisions=subdivisions,
                                   diameter=radius)


def append_bmesh(bm, other):
    """Copy `other`'s geometry into `bm` and free it. bmesh has no join, and
    building each feature in its own bmesh keeps the index bookkeeping local."""
    other.verts.ensure_lookup_table()
    vmap = {v: bm.verts.new(v.co) for v in other.verts}
    for f in other.faces:
        try:
            bm.faces.new([vmap[v] for v in f.verts])
        except ValueError:
            pass            # duplicate face — harmless, and only possible
                            # where two features touch exactly
    other.free()


def tube_into(bm, pts, radius, sides):
    """tube() without the object plumbing, for building a feature inside an
    existing bmesh."""
    normals, binormals = frames(pts)
    rings = []
    for i, p in enumerate(pts):
        ring = []
        for k in range(sides):
            a = 2.0 * math.pi * k / float(sides)
            ring.append(bm.verts.new(
                p + normals[i] * (math.cos(a) * radius)
                  + binormals[i] * (math.sin(a) * radius)))
        rings.append(ring)
    for i in range(len(rings) - 1):
        a, b = rings[i], rings[i + 1]
        for k in range(sides):
            j = (k + 1) % sides
            bm.faces.new((a[k], a[j], b[j], b[k]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])


# ─── placing things ─────────────────────────────────────────────────────────


def place(obj, location, azimuth=0.0, pitch=0.0, roll=0.0, scale=1.0):
    """Put a locally-built part into the plant.

    azimuth  degrees about Z — which way round the stem it points.
    pitch    degrees about the part's own Y, AFTER the azimuth. For a leaf
             built along +X this is the tilt of the blade: positive lifts
             the tip.
    roll     degrees about the part's own X — the twist of the blade about
             its own midrib.

    The order matters and is the usual one for anything growing off an
    axis: turn to face outwards, then tilt up or down, then twist. Applied
    in the other order the pitch would be about a world axis and every
    branch on the far side of the plant would tilt the wrong way.
    """
    obj.location = Vector(location)
    obj.rotation_euler = (Matrix.Rotation(math.radians(azimuth), 3, 'Z')
                          @ Matrix.Rotation(math.radians(pitch), 3, 'Y')
                          @ Matrix.Rotation(math.radians(roll), 3, 'X')
                          ).to_euler()
    obj.scale = (scale, scale, scale)
    return obj


def point_on(points, t):
    """The world point a fraction `t` along a polyline, by arc length.

    Branch attachments are given as "60% of the way along branch 3", which
    only means what it should if it is measured by LENGTH. Indexing into
    the sample array instead bunches attachments up wherever the curve is
    tightly sampled, which on a Catmull-Rom is exactly where it bends —
    so every leaf ends up crowded into the corners.
    """
    pts = [Vector(p) for p in points]
    seg = [(pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)]
    total = sum(seg)
    if total <= 1e-9:
        return pts[0], Vector((0.0, 0.0, 1.0))
    want = max(0.0, min(1.0, t)) * total
    run = 0.0
    for i, s in enumerate(seg):
        if run + s >= want or i == len(seg) - 1:
            f = (want - run) / max(1e-9, s)
            d = (pts[i + 1] - pts[i]).normalized()
            return pts[i].lerp(pts[i + 1], f), d
        run += s
    return pts[-1], (pts[-1] - pts[-2]).normalized()


def azimuth_of(direction):
    """Degrees about Z of a world direction — the number `place` wants."""
    d = Vector(direction)
    return math.degrees(math.atan2(d.y, d.x))


def pitch_of(direction):
    """Degrees above horizontal of a world direction."""
    d = Vector(direction)
    flat = math.hypot(d.x, d.y)
    return math.degrees(math.atan2(d.z, flat))


def join(objects, name):
    """Join a list of objects into the first one and rename it.

    Used at the very end of a step, not during it. A plant built as one
    object per part is far easier to reason about while it is being placed
    — every part can be moved, measured and deleted on its own — and far
    worse to light, because several hundred objects is several hundred
    draw calls and a material assignment each.
    """
    objs = [o for o in objects if o is not None and o.name in bpy.data.objects]
    if not objs:
        return None
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # CLEAR THE TARGET NAME FIRST. This cost a debugging round: the leaves
    # action deleted every "Leaf_*" object and rebuilt them, but the joined
    # result from the previous run was called "Leaves" and matched no
    # prefix, so it survived. The new join then took the name "Leaves.001",
    # every later lookup of bpy.data.objects["Leaves"] returned the OLD
    # geometry, and the measurement script cheerfully reported that changing
    # every leaf length in the file had changed nothing at all.
    #
    # The guard matters: join(objects=[stem, ...], name="Stem") is a normal
    # call, and deleting the object being joined INTO would be worse than
    # the bug this fixes.
    keep = {o.name for o in objs}
    for other in list(bpy.data.objects):
        if other.name not in keep and (other.name == name or
                                       other.name.startswith(name + ".")):
            bpy.data.objects.remove(other, do_unlink=True)
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    objs[0].name = name
    objs[0].data.name = name
    return objs[0]
