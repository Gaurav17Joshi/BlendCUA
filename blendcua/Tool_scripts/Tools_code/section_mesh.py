"""Subject-neutral closed low-poly forms built from measured sections.

The public builders take caller-supplied coordinates and replace objects by name,
so an action can be rerun without accumulating duplicate geometry.  They cover
three recurring forms: a loft through cross-sections, a prism from a 2-D profile,
and a closed tube around a 3-D path.  ``build_parts`` batches those independent
forms without embedding any subject, axis convention, or material choice.
"""

import math

import bpy
import bmesh
from mathutils import Vector


# ---------------------------------------------------------------------------
# materials and object finalisation
# ---------------------------------------------------------------------------


def make_material(name, color, roughness=0.5, metallic=0.0, specular=0.28):
    """Create or update a node material from an RGB or RGBA colour."""
    values = tuple(float(v) for v in color)
    if len(values) == 3:
        rgba = values + (1.0,)
    elif len(values) == 4:
        rgba = values
    else:
        raise ValueError("color must contain 3 (RGB) or 4 (RGBA) values")
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = float(roughness)
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = float(metallic)
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = float(specular)
        elif "Specular" in bsdf.inputs:
            bsdf.inputs["Specular"].default_value = float(specular)
    return mat


def assign_material(obj, material):
    """Give a mesh exactly one material slot and return the mesh object."""
    if obj.type != 'MESH':
        raise ValueError("assign_material requires a mesh object")
    obj.data.materials.clear()
    obj.data.materials.append(material)
    return obj


def _finish(name, verts, faces, material=None, smooth=True):
    """Replace a named mesh from raw vertices/faces and optionally assign material."""
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate(verbose=False)
    mesh.update(calc_edges=True)
    for poly in mesh.polygons:
        poly.use_smooth = bool(smooth)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if material is not None:
        assign_material(obj, material)
    return obj


# ---------------------------------------------------------------------------
# section and profile forms
# ---------------------------------------------------------------------------


def rounded_section(width, bottom, top, bottom_span=0.68, lower_span=0.94,
                    lower_z=0.10, side_z=0.32, upper_side_z=0.28,
                    crown_span=0.80, crown_z=0.06):
    """Return a clockwise chamfered/crowned 2-D section as ``(lateral, height)`` pairs.

    All shape ratios are arguments so this is a reusable section recipe rather
    than a hidden object-specific profile.  The defaults are a broad, shallow
    manufactured section: two bottom flats, chamfered lower and upper sides,
    and a single top crown.  ``width`` is a half-width and ``bottom``/``top``
    are absolute heights.
    """
    w = float(width)
    zb = float(bottom)
    zt = float(top)
    h = max(zt - zb, 1.0e-4)
    bs = float(bottom_span)
    ls = float(lower_span)
    lz = float(lower_z)
    sz = float(side_z)
    uz = float(upper_side_z)
    cs = float(crown_span)
    cz = float(crown_z)
    return [
        (-bs * w, zb),
        ( bs * w, zb),
        ( ls * w, zb + lz * h),
        ( w,      zb + sz * h),
        ( w,      zt - uz * h),
        ( cs * w, zt - cz * h),
        ( 0.0,    zt),
        (-cs * w, zt - cz * h),
        (-w,      zt - uz * h),
        (-w,      zb + sz * h),
        (-ls * w, zb + lz * h),
    ]


def loft_sections(name, stations, sections, material=None, smooth=True):
    """Build a closed loft along X from caller-supplied lateral/height sections.

    ``stations`` gives one X coordinate per section and ``sections`` gives one
    ordered ``(lateral, height)`` polygon per station.  Every section must have
    the same number of points; adjacent sections are joined with quads and the
    two ends are capped.  The input coordinates are not modified.
    """
    xs = [float(x) for x in stations]
    rings_2d = [list(section) for section in sections]
    if len(xs) < 2 or len(xs) != len(rings_2d):
        raise ValueError("loft_sections needs at least two matching stations")
    count = len(rings_2d[0])
    if count < 3 or any(len(section) != count for section in rings_2d):
        raise ValueError("loft_sections sections must have equal length >= 3")

    verts = []
    rings = []
    for x, section in zip(xs, rings_2d):
        ring = []
        for lateral, height in section:
            ring.append(len(verts))
            verts.append((x, float(lateral), float(height)))
        rings.append(ring)

    faces = []
    for first, second in zip(rings[:-1], rings[1:]):
        for j in range(count):
            k = (j + 1) % count
            faces.append((first[j], first[k], second[k], second[j]))
    faces.append(tuple(reversed(rings[0])))
    faces.append(tuple(rings[-1]))
    return _finish(name, verts, faces, material=material, smooth=smooth)


def replace_closed_elliptical_loft(name, stations, centers_yz=None,
                                   radii_y=0.5, radii_z=None, sides=32,
                                   end_skew=(0.0, 0.0),
                                   skew_half="positive_y", smooth_side=True,
                                   mesh_name=None):
    """Replace a mesh object's data with a closed axial elliptical loft.

    ``stations`` are ordered local-X positions. ``centers_yz`` supplies one
    ``(Y, Z)`` centre offset per station, or defaults to the origin.  The two
    radius arguments accept either one scalar or one value per station and
    define the local-Y/local-Z ellipse.  The result has one ring per station,
    quad sides, and two polygon end caps; the target object's parent, transform,
    custom properties, and object identity are preserved.

    ``end_skew=(start, finish)`` optionally integrates a diagonal end cut into
    the closed envelope without moving either ring centre.  On the first ring
    its axial offset is ``-start*sin(theta)`` and on the last it is
    ``+finish*sin(theta)``.  ``skew_half`` selects which half of each ellipse
    receives that offset: ``"positive_y"`` (the default), ``"negative_y"``,
    ``"all"``, or ``"none"``.  This is a cross-section convention, not a
    subject measurement; all dimensions and station data remain caller-owned.

    The function is deliberately a replacement operation because retrying a
    named build action must not discard its existing parent hierarchy or leave
    a suffixed duplicate object behind.  It does not assign a material; the
    caller owns material roles just as it does for any other mesh replacement.
    """
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != 'MESH':
        raise ValueError("replace_closed_elliptical_loft requires mesh %r" % name)

    xs = [float(x) for x in stations]
    if len(xs) < 2:
        raise ValueError("replace_closed_elliptical_loft needs at least two stations")
    if any(not math.isfinite(x) for x in xs):
        raise ValueError("replace_closed_elliptical_loft stations must be finite")

    count = len(xs)

    def values(value, label):
        if isinstance(value, (str, bytes)):
            raise TypeError("%s must be a scalar or sequence of numbers" % label)
        try:
            out = list(value)
        except TypeError:
            out = [value] * count
        if len(out) != count:
            raise ValueError("%s must have one value per station" % label)
        out = [float(v) for v in out]
        if any(not math.isfinite(v) for v in out):
            raise ValueError("%s must contain finite values" % label)
        return out

    ry = values(radii_y, "radii_y")
    rz = values(radii_y if radii_z is None else radii_z, "radii_z")
    if any(v <= 0.0 for v in ry + rz):
        raise ValueError("replace_closed_elliptical_loft radii must be positive")

    if centers_yz is None:
        centres = [(0.0, 0.0)] * count
    else:
        centres = [tuple(float(v) for v in centre) for centre in centers_yz]
        if len(centres) != count or any(len(c) != 2 for c in centres):
            raise ValueError("centers_yz must contain one (Y, Z) pair per station")
        if any(not math.isfinite(v) for c in centres for v in c):
            raise ValueError("centers_yz must contain finite values")

    try:
        start_skew, finish_skew = (float(v) for v in end_skew)
    except (TypeError, ValueError):
        raise ValueError("end_skew must be a pair (start, finish)") from None
    if not math.isfinite(start_skew) or not math.isfinite(finish_skew):
        raise ValueError("end_skew must contain finite values")
    if skew_half not in {"positive_y", "negative_y", "all", "none"}:
        raise ValueError("skew_half must be positive_y, negative_y, all, or none")

    sides = int(sides)
    if sides < 3:
        raise ValueError("replace_closed_elliptical_loft needs at least three sides")

    vertices = []
    for i, (x0, (cy, cz), ry_i, rz_i) in enumerate(zip(xs, centres, ry, rz)):
        for j in range(sides):
            theta = 2.0 * math.pi * j / float(sides)
            sin_theta = math.sin(theta)
            cos_theta = math.cos(theta)
            on_skew_half = (
                skew_half == "all"
                or (skew_half == "positive_y" and cos_theta > 0.0)
                or (skew_half == "negative_y" and cos_theta < 0.0)
            )
            axial = 0.0
            if on_skew_half:
                if i == 0:
                    axial = -start_skew * sin_theta
                elif i == count - 1:
                    axial = finish_skew * sin_theta
            vertices.append((x0 + axial,
                             cy + ry_i * cos_theta,
                             cz + rz_i * sin_theta))

    faces = []
    for i in range(count - 1):
        for j in range(sides):
            a = i * sides + j
            b = i * sides + ((j + 1) % sides)
            c = (i + 1) * sides + ((j + 1) % sides)
            d = (i + 1) * sides + j
            faces.append((a, b, c, d))
    faces.append(tuple(reversed(range(sides))))
    faces.append(tuple((count - 1) * sides + j for j in range(sides)))

    old_mesh = obj.data
    mesh = bpy.data.meshes.new(mesh_name or (name + "_EllipticalLoftMesh"))
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    side_faces = (count - 1) * sides
    for poly in mesh.polygons:
        poly.use_smooth = bool(smooth_side and poly.index < side_faces)

    obj.data = mesh
    if old_mesh is not None and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    return obj


def extrude_profile(name, profile, span_axis="Y", span_start=-0.5,
                    span_end=0.5, material=None, smooth=True):
    """Build a closed prism from a 2-D profile across a named coordinate axis.

    For ``span_axis='Y'`` the profile pairs are ``(X, Z)``; for ``'X'`` they
    are ``(Y, Z)``; for ``'Z'`` they are ``(X, Y)``.  ``span_start`` is emitted
    before ``span_end`` so caller ordering is preserved exactly.
    """
    axis = str(span_axis).upper()
    if axis not in {'X', 'Y', 'Z'}:
        raise ValueError("span_axis must be X, Y, or Z")
    pairs = [(float(a), float(b)) for a, b in profile]
    if len(pairs) < 3:
        raise ValueError("extrude_profile needs at least three profile points")

    def embed(pair, span):
        a, b = pair
        s = float(span)
        if axis == 'X':
            return (s, a, b)
        if axis == 'Y':
            return (a, s, b)
        return (a, b, s)

    verts = [embed(pair, span_start) for pair in pairs]
    verts += [embed(pair, span_end) for pair in pairs]
    n = len(pairs)
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return _finish(name, verts, faces, material=material, smooth=smooth)


# ---------------------------------------------------------------------------
# closed path sweep
# ---------------------------------------------------------------------------


def closed_path_tube(name, points, radius, sides=8, frame_up=(0.0, 0.0, 1.0),
                     material=None, smooth=True):
    """Build a closed low-sided tube around a 3-D polyline.

    The path is closed by joining the final ring to the first.  A scalar
    ``radius`` broadcasts; a sequence supplies one radius per point.  Frames
    use the supplied reference direction and a lateral cross product, with a
    fixed alternate axis only for the universal parallel/degenerate case.
    """
    pts = [Vector(point) for point in points]
    if len(pts) < 3:
        raise ValueError("closed_path_tube needs at least three points")
    if int(sides) < 3:
        raise ValueError("closed_path_tube needs at least three sides")
    radii = ([float(radius)] * len(pts)
             if not hasattr(radius, '__len__') else [float(r) for r in radius])
    if len(radii) != len(pts):
        raise ValueError("closed_path_tube radius count must match point count")

    up = Vector(frame_up)
    if up.length < 1.0e-12:
        raise ValueError("frame_up must be non-zero")
    up.normalize()
    verts = []
    rings = []
    for i, point in enumerate(pts):
        tangent = (pts[(i + 1) % len(pts)] - pts[(i - 1) % len(pts)]).normalized()
        normal = tangent.cross(up)
        if normal.length < 1.0e-6:
            # A fixed world axis is only the fallback when the requested frame
            # direction is parallel to the path tangent.
            normal = tangent.cross(Vector((0.0, 1.0, 0.0)))
        if normal.length < 1.0e-12:
            raise ValueError("closed_path_tube encountered a degenerate tangent")
        normal.normalize()
        binormal = tangent.cross(normal).normalized()
        ring = []
        for k in range(int(sides)):
            angle = 2.0 * math.pi * k / int(sides)
            ring.append(len(verts))
            verts.append(tuple(point + radii[i] * (
                math.cos(angle) * normal + math.sin(angle) * binormal)))
        rings.append(ring)

    faces = []
    for i, first in enumerate(rings):
        second = rings[(i + 1) % len(rings)]
        for k in range(int(sides)):
            j = (k + 1) % int(sides)
            faces.append((first[k], first[j], second[j], second[k]))
    return _finish(name, verts, faces, material=material, smooth=smooth)


# ---------------------------------------------------------------------------
# shared finishing and batching
# ---------------------------------------------------------------------------


def add_bevel(obj, width=0.03, segments=2, angle=0.52):
    """Replace the named angle-limited bevel modifier on a mesh object."""
    if obj.type != 'MESH':
        raise ValueError("add_bevel requires a mesh object")
    old = obj.modifiers.get("EdgeSoftness")
    if old is not None:
        obj.modifiers.remove(old)
    bevel = obj.modifiers.new("EdgeSoftness", "BEVEL")
    bevel.width = float(width)
    bevel.segments = int(segments)
    bevel.limit_method = 'ANGLE'
    bevel.angle_limit = float(angle)
    bevel.harden_normals = True
    bevel.use_clamp_overlap = True
    return bevel


def build_parts(parts):
    """Build a batch of independent named forms from generic shape specifications.

    Each dict needs ``kind`` and ``name``.  Supported kinds are ``rounded_loft``
    (``stations``, ``widths``, ``bottoms``, ``tops``), ``loft`` (``stations`` and
    ``sections``), ``profile`` (``profile``, ``span_axis``, ``span_start``,
    ``span_end``), and ``closed_path`` (``points`` plus ``radius``).  Optional
    ``material``, ``smooth``, and form-specific keyword values are forwarded to
    the primitive.  The returned list follows input order.
    """
    if not isinstance(parts, (list, tuple)) or not parts:
        raise ValueError("build_parts needs a non-empty list of specifications")
    built = []
    for spec in parts:
        if not isinstance(spec, dict):
            raise TypeError("each build_parts specification must be a dict")
        kind = spec.get("kind")
        name = spec.get("name")
        if not kind or not name:
            raise ValueError("each build_parts specification needs kind and name")
        material = spec.get("material")
        smooth = bool(spec.get("smooth", True))
        if kind == "rounded_loft":
            widths = spec["widths"]
            bottoms = spec["bottoms"]
            tops = spec["tops"]
            if not (len(widths) == len(bottoms) == len(tops) == len(spec["stations"])):
                raise ValueError("rounded_loft arrays must have equal lengths")
            section_keys = (
                "bottom_span", "lower_span", "lower_z", "side_z",
                "upper_side_z", "crown_span", "crown_z")
            shape = {key: spec[key] for key in section_keys if key in spec}
            sections = [rounded_section(w, b, t, **shape)
                        for w, b, t in zip(widths, bottoms, tops)]
            obj = loft_sections(name, spec["stations"], sections,
                                material=material, smooth=smooth)
        elif kind == "loft":
            obj = loft_sections(name, spec["stations"], spec["sections"],
                                material=material, smooth=smooth)
        elif kind == "profile":
            obj = extrude_profile(
                name, spec["profile"], spec.get("span_axis", "Y"),
                spec["span_start"], spec["span_end"],
                material=material, smooth=smooth)
        elif kind == "closed_path":
            obj = closed_path_tube(
                name, spec["points"], spec["radius"],
                sides=spec.get("sides", 8),
                frame_up=spec.get("frame_up", (0.0, 0.0, 1.0)),
                material=material, smooth=smooth)
        else:
            raise ValueError("unsupported build_parts kind: %s" % kind)
        built.append(obj)
    return built
