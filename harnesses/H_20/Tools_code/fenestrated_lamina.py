"""Generic folded thin-surface construction with real openings.

This module builds a connected lamina from caller-owned two-dimensional contour
samples.  The outer contour owns the silhouette, opening contours own genuine
cut-through boundaries, and a fold field supplies the shallow three-dimensional
form.  The operation is deliberately independent of a subject: the same API can
be used for a perforated sheet, petal, wing, membrane, or any other broad thin
part whose openings must survive a solid-shading inspection.

The builder keeps the caller's contour/path data untouched.  Profile parameters
are copied into the construction audit, a stable attachment vertex group is
created, and the object receives scalar metadata so a later review can inspect
how it was made rather than inferring it from a textured render.
"""

from __future__ import annotations

import json
import math


_EPSILON = 1.0e-9
_KEY_DIGITS = 8


def _as_uv(point, label):
    """Return a finite two-dimensional point without mutating caller data."""
    try:
        values = tuple(float(value) for value in point)
    except (TypeError, ValueError):
        raise ValueError("%s must contain numeric coordinates" % label) from None
    if len(values) < 2:
        raise ValueError("%s must contain at least two coordinates" % label)
    if not all(math.isfinite(value) for value in values[:2]):
        raise ValueError("%s coordinates must be finite" % label)
    return (values[0], values[1])


def _clean_contour(contour, label):
    """Copy a contour, remove a repeated closing point, and validate its area."""
    if contour is None:
        raise ValueError("%s is required" % label)
    points = [_as_uv(point, "%s point" % label) for point in contour]
    if len(points) >= 2 and _distance(points[0], points[-1]) <= _EPSILON:
        points.pop()
    if len(points) < 3:
        raise ValueError("%s needs at least three distinct points" % label)
    cleaned = [points[0]]
    for point in points[1:]:
        if _distance(point, cleaned[-1]) > _EPSILON:
            cleaned.append(point)
    if len(cleaned) >= 2 and _distance(cleaned[0], cleaned[-1]) <= _EPSILON:
        cleaned.pop()
    if len(cleaned) < 3 or abs(_signed_area(cleaned)) <= _EPSILON:
        raise ValueError("%s must enclose a non-zero area" % label)
    return cleaned


def _distance(first, second):
    """Return Euclidean distance between two 2-D points."""
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _signed_area(points):
    """Return the signed shoelace area of a 2-D contour."""
    return 0.5 * sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )


def _cross(a, b, c):
    """Return the signed turn at ``b`` for three 2-D points."""
    return ((b[0] - a[0]) * (c[1] - b[1])
            - (b[1] - a[1]) * (c[0] - b[0]))


def _key(point):
    """Return a stable coordinate key for tessellation output."""
    return tuple(round(float(value), _KEY_DIGITS) for value in point[:2])


def _bbox(contour):
    """Return ``min_x, max_x, min_y, max_y`` for a contour."""
    return (
        min(point[0] for point in contour),
        max(point[0] for point in contour),
        min(point[1] for point in contour),
        max(point[1] for point in contour),
    )


def _point_on_segment(point, first, second, tolerance=1.0e-7):
    """Return whether a point lies on a finite 2-D segment."""
    if abs(_cross(first, second, point)) > tolerance:
        return False
    return (
        min(first[0], second[0]) - tolerance <= point[0] <= max(first[0], second[0]) + tolerance
        and min(first[1], second[1]) - tolerance <= point[1] <= max(first[1], second[1]) + tolerance
    )


def _point_in_polygon(point, polygon):
    """Return inside/boundary membership using a ray crossing test."""
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        if _point_on_segment(point, first, second):
            return True
    inside = False
    x, y = point
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        yi, yj = first[1], second[1]
        if (yi > y) != (yj > y):
            at_x = ((second[0] - first[0]) * (y - yi) / (yj - yi)) + first[0]
            if x < at_x:
                inside = not inside
    return inside


def _triangle_area(first, second, third):
    """Return the absolute area of a 2-D triangle."""
    return abs((second[0] - first[0]) * (third[1] - first[1])
               - (second[1] - first[1]) * (third[0] - first[0])) * 0.5


def _normalise_profile(profile):
    """Copy and validate optional per-instance profile/deformation parameters."""
    if profile is None:
        profile = {}
    if not hasattr(profile, "items"):
        raise TypeError("profile must be a mapping of variant parameters")
    result = dict(profile)

    scale = result.get("scale", (1.0, 1.0))
    if isinstance(scale, (int, float)):
        scale = (float(scale), float(scale))
    else:
        try:
            scale = tuple(float(value) for value in scale)
        except (TypeError, ValueError):
            raise ValueError("profile scale must be a scalar or a two-value sequence") from None
        if len(scale) != 2:
            raise ValueError("profile scale must be a scalar or a two-value sequence")
    if not all(math.isfinite(value) and value > 0.0 for value in scale):
        raise ValueError("profile scale values must be finite and positive")
    result["scale"] = scale

    for key in ("rotation_deg", "shear", "fold_scale", "midrib_bend", "tip_curl"):
        if key in result:
            result[key] = float(result[key])
            if not math.isfinite(result[key]):
                raise ValueError("profile %s must be finite" % key)
    result.setdefault("rotation_deg", 0.0)
    result.setdefault("shear", 0.0)
    result.setdefault("fold_scale", 1.0)
    result.setdefault("midrib_bend", 0.0)
    result.setdefault("tip_curl", 0.0)
    return result


def _transform_uv(point, anchor_uv, profile):
    """Apply a caller-owned profile around the persistent attachment coordinate."""
    x = (point[0] - anchor_uv[0]) * profile["scale"][0]
    y = (point[1] - anchor_uv[1]) * profile["scale"][1]
    x += profile["shear"] * y
    angle = math.radians(profile["rotation_deg"])
    cos_angle, sin_angle = math.cos(angle), math.sin(angle)
    return (
        anchor_uv[0] + cos_angle * x - sin_angle * y,
        anchor_uv[1] + sin_angle * x + cos_angle * y,
    )


def _fold_callable(fold_field):
    """Resolve a callable or declarative fold field into a numeric evaluator."""
    if callable(fold_field):
        return lambda u, v: float(fold_field(float(u), float(v)))

    values = dict(fold_field or {})
    aliases = {"center_dip": "centre_dip", "midrib": "midrib_height"}
    for old, new in aliases.items():
        if old in values and new not in values:
            values[new] = values[old]

    # A modest default fold keeps an omitted field from silently producing a
    # sticker.  All values remain caller-overridable and are object-neutral.
    midrib_height = float(values.get("midrib_height", 0.05))
    centre_dip = float(values.get("centre_dip", -0.018))
    edge_lift = float(values.get("edge_lift", 0.012))
    midrib_v = float(values.get("midrib_v", 0.5))
    midrib_width = max(float(values.get("midrib_width", 0.18)), 1.0e-6)
    dip_u = float(values.get("dip_u", 0.55))
    dip_width = max(float(values.get("dip_width", 0.45)), 1.0e-6)
    tip_start = float(values.get("tip_start", 0.7))
    tip_curl = float(values.get("tip_curl", 0.0))
    for name, value in (
        ("midrib_height", midrib_height), ("centre_dip", centre_dip),
        ("edge_lift", edge_lift), ("midrib_v", midrib_v),
        ("midrib_width", midrib_width), ("dip_u", dip_u),
        ("dip_width", dip_width), ("tip_start", tip_start),
        ("tip_curl", tip_curl),
    ):
        if not math.isfinite(value):
            raise ValueError("fold field %s must be finite" % name)

    def evaluate(u, v):
        midrib = midrib_height * math.exp(-((v - midrib_v) / midrib_width) ** 2)
        midrib *= 0.35 + 0.65 * max(0.0, min(1.0, u))
        dip = centre_dip * math.exp(-((u - dip_u) / dip_width) ** 2)
        edge = edge_lift * abs(2.0 * v - 1.0)
        curl = tip_curl * max(0.0, u - tip_start) ** 2 * math.sin(math.pi * v)
        return midrib + dip + edge + curl

    return evaluate


def _normalise_axis(axis, label):
    """Return a finite unit 3-D vector as a tuple."""
    try:
        values = tuple(float(value) for value in axis)
    except (TypeError, ValueError):
        raise ValueError("%s must be a 3-D vector" % label) from None
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError("%s must be a finite 3-D vector" % label)
    length = math.sqrt(sum(value * value for value in values))
    if length <= _EPSILON:
        raise ValueError("%s must be non-zero" % label)
    return tuple(value / length for value in values)


def _dot(first, second):
    """Return a 3-D dot product."""
    return sum(a * b for a, b in zip(first, second))


def _cross3(first, second):
    """Return a 3-D cross product."""
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _orthonormal_basis(basis):
    """Validate caller axes and return an orthonormal local U/V/N basis."""
    if basis is None:
        basis = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    if len(basis) != 3:
        raise ValueError("basis must contain U, V, and normal axes")
    u = _normalise_axis(basis[0], "basis U")
    v = _normalise_axis(basis[1], "basis V")
    n = _normalise_axis(basis[2], "basis normal")
    if abs(_dot(u, v)) > 1.0e-5 or abs(_dot(u, n)) > 1.0e-5 or abs(_dot(v, n)) > 1.0e-5:
        raise ValueError("basis axes must be mutually perpendicular")
    handed = _cross3(u, v)
    if _dot(handed, n) < 0.0:
        n = tuple(-value for value in n)
    return u, v, n


def _point_world(anchor, basis, uv, depth):
    """Embed a local lamina point relative to the world attachment anchor."""
    u_axis, v_axis, normal = basis
    return tuple(
        float(anchor[index]) + u_axis[index] * uv[0]
        + v_axis[index] * uv[1] + normal[index] * depth
        for index in range(3)
    )


def _is_rectangular(contour, tolerance=1.0e-6):
    """Return whether the contour is only the four corners of its bounding box."""
    if len(contour) != 4:
        return False
    min_x, max_x, min_y, max_y = _bbox(contour)
    corners = {
        (round(min_x, 6), round(min_y, 6)),
        (round(min_x, 6), round(max_y, 6)),
        (round(max_x, 6), round(min_y, 6)),
        (round(max_x, 6), round(max_y, 6)),
    }
    actual = {(round(point[0], 6), round(point[1], 6)) for point in contour}
    return actual == corners and all(
        abs(value - round(value, 6)) <= tolerance
        for point in contour for value in point
    )


def _ear_clip_simple(points):
    """Fallback triangulation for one simple contour when Blender tessellation is unavailable."""
    contour = list(points)
    if _signed_area(contour) < 0.0:
        contour.reverse()
    remaining = list(range(len(contour)))
    triangles = []
    guard = 0
    while len(remaining) > 3 and guard < len(contour) * len(contour) * 2:
        guard += 1
        ear_found = False
        for position, current in enumerate(remaining):
            previous = remaining[position - 1]
            following = remaining[(position + 1) % len(remaining)]
            a, b, c = contour[previous], contour[current], contour[following]
            if _cross(a, b, c) <= _EPSILON:
                continue
            if any(
                other not in (previous, current, following)
                and _point_in_triangle(contour[other], a, b, c)
                for other in remaining
            ):
                continue
            triangles.append((previous, current, following))
            remaining.pop(position)
            ear_found = True
            break
        if not ear_found:
            break
    if len(remaining) == 3:
        triangles.append(tuple(remaining))
    if not triangles:
        raise ValueError("could not triangulate the supplied contour")
    return triangles


def _ear_clip_nodes(nodes, points):
    """Ear-clip a simple node cycle while retaining original point indices."""
    node_list = list(nodes)
    if _signed_area([points[node] for node in node_list]) < 0.0:
        node_list.reverse()
    remaining = list(range(len(node_list)))
    triangles = []
    guard = 0
    while len(remaining) > 3 and guard < len(node_list) * len(node_list) * 3:
        guard += 1
        ear_found = False
        for position, current in enumerate(remaining):
            previous = remaining[position - 1]
            following = remaining[(position + 1) % len(remaining)]
            a = points[node_list[previous]]
            b = points[node_list[current]]
            c = points[node_list[following]]
            if _cross(a, b, c) <= _EPSILON:
                continue
            if any(
                other not in (previous, current, following)
                and _point_in_triangle(
                    points[node_list[other]], a, b, c
                )
                for other in remaining
            ):
                continue
            triangles.append((
                node_list[previous], node_list[current], node_list[following]
            ))
            remaining.pop(position)
            ear_found = True
            break
        if not ear_found:
            break
    if len(remaining) == 3:
        triangles.append(tuple(node_list[index] for index in remaining))
    return triangles


def _segments_cross(first, second, third, fourth):
    """Return whether two 2-D segments cross away from shared endpoints."""
    def orientation(a, b, c):
        value = _cross(a, b, c)
        if abs(value) <= _EPSILON:
            return 0
        return 1 if value > 0.0 else -1

    first_pair = orientation(first, second, third), orientation(first, second, fourth)
    second_pair = orientation(third, fourth, first), orientation(third, fourth, second)
    if first_pair[0] == 0 and _point_on_segment(third, first, second):
        return True
    if first_pair[1] == 0 and _point_on_segment(fourth, first, second):
        return True
    if second_pair[0] == 0 and _point_on_segment(first, third, fourth):
        return True
    if second_pair[1] == 0 and _point_on_segment(second, third, fourth):
        return True
    return first_pair[0] != first_pair[1] and second_pair[0] != second_pair[1]


def _bridge_holes(points, outer, openings):
    """Connect hole cycles to a simple outer cycle for the pure-Python fallback."""
    outer_nodes = list(range(len(outer)))
    hole_nodes = []
    offset = len(outer)
    for opening in openings:
        hole_nodes.append(list(range(offset, offset + len(opening))))
        offset += len(opening)

    if _signed_area(outer) < 0.0:
        outer_nodes.reverse()
    for index, opening in enumerate(openings):
        if _signed_area(opening) > 0.0:
            hole_nodes[index].reverse()

    for hole_ids in hole_nodes:
        hole_index = max(
            range(len(hole_ids)),
            key=lambda index: (points[hole_ids[index]][0], -points[hole_ids[index]][1]),
        )
        hole_id = hole_ids[hole_index]
        candidates = sorted(
            range(len(outer_nodes)),
            key=lambda index: _distance(points[outer_nodes[index]], points[hole_id]),
        )
        chosen = None
        for outer_index in candidates:
            outer_id = outer_nodes[outer_index]
            first, second = points[hole_id], points[outer_id]
            midpoint = ((first[0] + second[0]) * 0.5,
                        (first[1] + second[1]) * 0.5)
            if not _point_in_polygon(midpoint, [points[node] for node in outer_nodes]):
                continue
            if any(_point_in_polygon(midpoint, opening) for opening in openings):
                continue
            blocked = False
            for cycle in [outer_nodes] + hole_nodes:
                for edge_index, edge_start in enumerate(cycle):
                    edge_end = cycle[(edge_index + 1) % len(cycle)]
                    a, b = points[edge_start], points[edge_end]
                    if outer_id in (edge_start, edge_end) or hole_id in (edge_start, edge_end):
                        continue
                    if _segments_cross(first, second, a, b):
                        blocked = True
                        break
                if blocked:
                    break
            if not blocked:
                chosen = outer_index
                break
        if chosen is None:
            raise RuntimeError("could not find a visible bridge for an opening contour")
        hole_cycle = hole_ids[hole_index:] + hole_ids[:hole_index]
        outer_id = outer_nodes[chosen]
        outer_nodes = (
            outer_nodes[:chosen + 1]
            + hole_cycle
            + [hole_id, outer_id]
            + outer_nodes[chosen + 1:]
        )
    return outer_nodes


def _point_in_triangle(point, first, second, third):
    """Return inclusive point-in-triangle membership."""
    signs = (
        _cross(first, second, point),
        _cross(second, third, point),
        _cross(third, first, point),
    )
    return min(signs) >= -_EPSILON and max(signs) <= _EPSILON or (
        min(signs) >= -_EPSILON or max(signs) <= _EPSILON
    )


def _tessellate(outer, openings):
    """Tessellate an outer loop and holes, using Blender's hole-aware utility when present."""
    loops = [outer] + list(openings)
    points = []
    point_index = {}
    for loop in loops:
        for point in loop:
            key = _key(point)
            if key not in point_index:
                point_index[key] = len(points)
                points.append(point)

    triangles = []
    try:
        from mathutils import Vector
        from mathutils.geometry import tessellate_polygon

        blender_loops = [
            [Vector((point[0], point[1], 0.0)) for point in loop]
            for loop in loops
        ]
        tessellated = tessellate_polygon(blender_loops)
        for triangle in tessellated:
            ids = tuple(point_index[_key(point)] for point in triangle)
            if len(set(ids)) == 3:
                centroid = tuple(
                    sum(points[index][axis] for index in ids) / 3.0
                    for axis in range(2)
                )
                if _point_in_polygon(centroid, outer) and not any(
                    _point_in_polygon(centroid, opening) for opening in openings
                ):
                    triangles.append(ids)
    except (ImportError, RuntimeError, TypeError, ValueError):
        triangles = []

    if not triangles:
        if openings:
            # Keep the public pure-Python builder useful in unit tests and in
            # planning-side previews.  The Blender path above remains the
            # preferred hole-aware tessellator, while this fallback explicitly
            # bridges each hole and then removes triangles whose centroids fall
            # inside an opening.
            fallback_points = list(outer)
            fallback_points.extend(point for opening in openings for point in opening)
            merged_nodes = _bridge_holes(
                fallback_points,
                outer,
                openings,
            )
            fallback_triangles = _ear_clip_nodes(merged_nodes, fallback_points)
            points = fallback_points
            point_index = {_key(point): index for index, point in enumerate(points)}
            triangles = []
            for triangle in fallback_triangles:
                centroid = tuple(
                    sum(points[index][axis] for index in triangle) / 3.0
                    for axis in range(2)
                )
                if _point_in_polygon(centroid, outer) and not any(
                    _point_in_polygon(centroid, opening) for opening in openings
                ):
                    triangles.append(triangle)
        else:
            triangles = _ear_clip_simple(outer)
            points = list(outer)
            point_index = {_key(point): index for index, point in enumerate(points)}

    # Keep only non-degenerate faces.  This also removes a duplicate bridge
    # triangle from tessellators that return a boundary point twice.
    triangles = [
        triangle for triangle in triangles
        if _triangle_area(*(points[index] for index in triangle)) > _EPSILON
    ]
    if not triangles:
        raise ValueError("contours produced no non-degenerate lamina faces")
    return points, triangles, point_index


def _contour_edge_keys(contour, point_index):
    """Return mesh-index pairs for a contour's ordered boundary edges."""
    edges = []
    for index, point in enumerate(contour):
        first = point_index[_key(point)]
        second = point_index[_key(contour[(index + 1) % len(contour)])]
        if first != second:
            edges.append((first, second))
    return edges


def _json_safe_profile(profile):
    """Convert a profile mapping to JSON-safe scalar/list data for audit metadata."""
    result = {}
    for key, value in profile.items():
        if isinstance(value, tuple):
            result[str(key)] = [float(item) for item in value]
        elif isinstance(value, (int, float, str, bool)) or value is None:
            result[str(key)] = value
        else:
            result[str(key)] = str(value)
    return result


def build_lamina_mesh(outer_contour, opening_contours=(), fold_field=None,
                      attachment_uv=None, thickness=0.0, profile=None,
                      require_non_rectangular=True):
    """Return vertices, faces, and an audit for a folded lamina mesh.

    ``outer_contour`` and ``opening_contours`` are caller-owned 2-D samples;
    they are copied and never reordered in place.  ``fold_field`` is either a
    ``(u, v) -> depth`` callable or a mapping with generic ``midrib_height``,
    ``centre_dip``, ``edge_lift``, and curl parameters.  ``profile`` supplies
    per-instance scale, rotation, shear, and fold controls around
    ``attachment_uv``.  The returned vertices are local coordinates with the
    attachment point at the origin; the builder adds world placement and basis
    later.  Openings are represented by missing top/bottom faces and retain
    their own boundary edges.  Positive ``thickness`` adds side faces only along
    the supplied outer and opening contours.
    """
    outer = _clean_contour(outer_contour, "outer_contour")
    openings = [
        _clean_contour(contour, "opening_contour_%02d" % index)
        for index, contour in enumerate(opening_contours or ())
    ]
    if require_non_rectangular and _is_rectangular(outer):
        raise ValueError(
            "outer_contour is a rectangular carrier; supply an evaluated non-rectangular boundary"
        )
    for index, opening in enumerate(openings):
        if not _point_in_polygon(opening[0], outer):
            raise ValueError("opening_contour_%02d lies outside outer_contour" % index)
        if any(_point_in_polygon(point, other) for other_index, other in enumerate(openings)
               for point in opening if other_index != index):
            raise ValueError("opening contours may not overlap")

    if attachment_uv is None:
        anchor_uv = tuple(outer[0])
    else:
        anchor_uv = _as_uv(attachment_uv, "attachment_uv")
        if not _point_in_polygon(anchor_uv, outer):
            raise ValueError("attachment_uv must lie on or inside outer_contour")
        if any(_point_in_polygon(anchor_uv, opening) for opening in openings):
            raise ValueError("attachment_uv may not lie inside an opening")

    try:
        thickness = float(thickness)
    except (TypeError, ValueError):
        raise ValueError("thickness must be numeric") from None
    if not math.isfinite(thickness) or thickness < 0.0:
        raise ValueError("thickness must be finite and non-negative")

    resolved_profile = _normalise_profile(profile)
    raw_points, raw_triangles, raw_index = _tessellate(outer, openings)
    transformed_points = [
        _transform_uv(point, anchor_uv, resolved_profile)
        for point in raw_points
    ]
    transformed_outer = [
        _transform_uv(point, anchor_uv, resolved_profile) for point in outer
    ]
    transformed_openings = [
        [_transform_uv(point, anchor_uv, resolved_profile) for point in opening]
        for opening in openings
    ]

    min_x, max_x, min_y, max_y = _bbox(transformed_outer)
    span_x = max(max_x - min_x, _EPSILON)
    span_y = max(max_y - min_y, _EPSILON)
    fold = _fold_callable(fold_field)
    fold_scale = resolved_profile["fold_scale"]
    base_anchor_depth = fold(
        (anchor_uv[0] - min_x) / span_x,
        (anchor_uv[1] - min_y) / span_y,
    )

    local_top = []
    for point in transformed_points:
        u = (point[0] - min_x) / span_x
        v = (point[1] - min_y) / span_y
        depth = (fold(u, v) - base_anchor_depth) * fold_scale
        depth += resolved_profile["midrib_bend"] * (u - 0.5) * (v - 0.5)
        depth += resolved_profile["tip_curl"] * max(0.0, u - 0.7) ** 2 * math.sin(math.pi * v)
        local_top.append((point[0] - anchor_uv[0], point[1] - anchor_uv[1], depth))

    faces = [tuple(triangle) for triangle in raw_triangles]
    outer_edges = _contour_edge_keys(transformed_outer, {
        _key(point): index for index, point in enumerate(transformed_points)
    })
    opening_edges = [
        _contour_edge_keys(contour, {_key(point): index for index, point in enumerate(transformed_points)})
        for contour in transformed_openings
    ]

    vertices = list(local_top)
    boundary_edges = list(outer_edges)
    for edges in opening_edges:
        boundary_edges.extend(edges)

    if thickness > _EPSILON:
        bottom_start = len(vertices)
        vertices.extend(
            (x, y, z - thickness) for x, y, z in local_top
        )
        faces.extend(
            tuple(bottom_start + index for index in reversed(triangle))
            for triangle in raw_triangles
        )
        for first, second in boundary_edges:
            faces.append((first, second, bottom_start + second, bottom_start + first))

    attachment_candidates = [
        index for index, point in enumerate(local_top)
        if _distance((point[0], point[1]), (0.0, 0.0)) <= 1.0e-6
    ]
    attachment_index = attachment_candidates[0] if attachment_candidates else min(
        range(len(local_top)),
        key=lambda index: math.hypot(local_top[index][0], local_top[index][1]),
    )
    z_values = [vertex[2] for vertex in vertices]
    boundary_vertex_count = len(set(index for edge in boundary_edges for index in edge))
    audit = {
        "vertices": len(vertices),
        "faces": len(faces),
        "top_triangles": len(raw_triangles),
        "opening_count": len(openings),
        "opening_boundary_edges": [len(edges) for edges in opening_edges],
        "outer_boundary_edges": len(outer_edges),
        "boundary_vertex_count": boundary_vertex_count,
        "thickness": float(thickness),
        "fold_depth_world": float(max(z_values) - min(z_values)),
        "non_rectangular_outer": not _is_rectangular(outer),
        "attachment_index": int(attachment_index),
        "attachment_local": [float(value) for value in vertices[attachment_index]],
        "profile": _json_safe_profile(resolved_profile),
    }
    return vertices, faces, audit


def _remove_object(name):
    """Remove a prior object and unused mesh data before a replace-style build."""
    import bpy

    old = bpy.data.objects.get(name)
    if old is None:
        return
    old_mesh = old.data if old.type == "MESH" else None
    bpy.data.objects.remove(old, do_unlink=True)
    if old_mesh is not None and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def build_fenestrated_lamina(name, outer_contour, opening_contours=(),
                             fold_field=None, attachment_anchor=(0.0, 0.0, 0.0),
                             attachment_uv=None, basis=None, thickness=0.0,
                             profile=None, material=None,
                             require_non_rectangular=True, return_audit=False):
    """Create one replace-style Blender mesh for a folded lamina with real holes.

    The input contours, fold field, and profile remain caller-owned.  The world
    ``attachment_anchor`` is the receiving-surface datum: the local attachment
    coordinate is placed exactly there, while ``basis`` maps local U/V/normal
    axes into world space.  Positive ``thickness`` adds side treatment around
    the real outer/opening boundaries only; it never adds a rectangular backing.
    ``material`` may be a Blender material or its name.  The return is the mesh
    object, or ``(object, audit)`` when ``return_audit`` is true.
    """
    import bpy

    try:
        world_anchor = tuple(float(value) for value in attachment_anchor)
    except (TypeError, ValueError):
        raise ValueError("attachment_anchor must be a 3-D coordinate") from None
    if len(world_anchor) != 3 or not all(math.isfinite(value) for value in world_anchor):
        raise ValueError("attachment_anchor must be a finite 3-D coordinate")
    local_vertices, faces, audit = build_lamina_mesh(
        outer_contour,
        opening_contours=opening_contours,
        fold_field=fold_field,
        attachment_uv=attachment_uv,
        thickness=thickness,
        profile=profile,
        require_non_rectangular=require_non_rectangular,
    )
    local_basis = _orthonormal_basis(basis)
    world_vertices = [
        _point_world(world_anchor, local_basis, (vertex[0], vertex[1]), vertex[2])
        for vertex in local_vertices
    ]

    _remove_object(name)
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(world_vertices, [], faces)
    mesh.validate(verbose=False)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    if material is not None:
        resolved_material = material
        if isinstance(material, str):
            resolved_material = bpy.data.materials.get(material)
        if resolved_material is None:
            raise ValueError("material name/object could not be resolved")
        obj.data.materials.append(resolved_material)

    attachment_index = int(audit["attachment_index"])
    group = obj.vertex_groups.new(name="fenestrated_attachment")
    group.add([attachment_index], 1.0, "REPLACE")
    audit = dict(audit)
    audit["object"] = name
    audit["attachment_anchor_world"] = [float(value) for value in world_anchor]
    audit["basis"] = [[float(value) for value in axis] for axis in local_basis]
    audit["material"] = getattr(resolved_material, "name", None) if material is not None else None

    obj["fenestrated_lamina_version"] = 1
    obj["fenestrated_lamina_opening_count"] = int(audit["opening_count"])
    obj["fenestrated_lamina_fold_depth_world"] = float(audit["fold_depth_world"])
    obj["fenestrated_lamina_thickness"] = float(audit["thickness"])
    obj["fenestrated_lamina_non_rectangular"] = bool(audit["non_rectangular_outer"])
    obj["fenestrated_lamina_attachment_index"] = attachment_index
    obj["fenestrated_lamina_attachment_anchor"] = list(world_anchor)
    obj["fenestrated_lamina_profile"] = json.dumps(audit["profile"], sort_keys=True)
    if return_audit:
        return obj, audit
    return obj


def audit_fenestrated_lamina(obj_name):
    """Read construction metadata and boundary evidence from a lamina object.

    The audit is read-only.  Boundary edges are counted from the actual mesh,
    while opening/fold/attachment values come from the metadata written by
    ``build_fenestrated_lamina``.  A reviewer can therefore inspect the object
    in Solid shading and compare physical evidence with the construction record.
    """
    import bpy

    obj = bpy.data.objects.get(obj_name)
    if obj is None or obj.type != "MESH":
        raise ValueError("audit_fenestrated_lamina requires mesh object %r" % obj_name)
    incidence = {}
    for polygon in obj.data.polygons:
        for edge in polygon.edge_keys:
            key = tuple(sorted(edge))
            incidence[key] = incidence.get(key, 0) + 1
    profile_text = obj.get("fenestrated_lamina_profile", "{}")
    try:
        profile = json.loads(profile_text)
    except (TypeError, ValueError):
        profile = {"unreadable": str(profile_text)}
    return {
        "object": obj_name,
        "vertices": len(obj.data.vertices),
        "faces": len(obj.data.polygons),
        "boundary_edges": sum(value == 1 for value in incidence.values()),
        "nonmanifold_edges": sum(value > 2 for value in incidence.values()),
        "opening_count": int(obj.get("fenestrated_lamina_opening_count", 0)),
        "fold_depth_world": float(obj.get("fenestrated_lamina_fold_depth_world", 0.0)),
        "thickness": float(obj.get("fenestrated_lamina_thickness", 0.0)),
        "non_rectangular_outer": bool(obj.get("fenestrated_lamina_non_rectangular", False)),
        "attachment_index": int(obj.get("fenestrated_lamina_attachment_index", -1)),
        "attachment_anchor_world": list(obj.get("fenestrated_lamina_attachment_anchor", ())),
        "profile": profile,
    }
