"""Read-only measurements for a batch of world-space surface paths.

The measurements are deliberately independent of any object or feature name.
They answer the questions that a screen-space sculpt report cannot answer by
itself: how deep a path is on the intended face, and how wide its central
cross-section is at one or more inward-depth thresholds.
"""

import numpy as np
from mathutils import Vector

import sculpt_native as sn


def _normalise(value, label):
    out = Vector(value)
    if out.length < 1e-12:
        raise ValueError("%s must be non-zero" % label)
    return out.normalized()


def _path_frame(path, normal):
    points = [Vector(p) for p in path]
    if len(points) < 2:
        raise ValueError("every path needs at least 2 points")
    tangent = points[-1] - points[0]
    # Remove any component along the surface normal so the section axes stay
    # in the measured face plane even when a path was sampled on a shallow ramp.
    tangent -= normal * tangent.dot(normal)
    if tangent.length < 1e-12:
        raise ValueError("path direction is parallel to face normal")
    tangent.normalize()
    lateral = normal.cross(tangent)
    if lateral.length < 1e-12:
        raise ValueError("could not construct a lateral section axis")
    lateral.normalize()
    return points, tangent, lateral


def _threshold_width(x, depth, threshold):
    """Width of the central depth run, with linear threshold crossings."""
    if len(x) < 2:
        return 0.0
    order = np.argsort(x)
    x = np.asarray(x, dtype=np.float64)[order]
    depth = np.asarray(depth, dtype=np.float64)[order]

    # Collapse duplicate samples from adjacent mesh rows while retaining the
    # deepest sample at each lateral coordinate.
    unique_x = []
    unique_d = []
    for coord, value in zip(x, depth):
        if unique_x and abs(coord - unique_x[-1]) < 1e-10:
            unique_d[-1] = max(unique_d[-1], value)
        else:
            unique_x.append(float(coord))
            unique_d.append(float(value))
    x = np.asarray(unique_x, dtype=np.float64)
    depth = np.asarray(unique_d, dtype=np.float64)
    if len(x) < 2:
        return 0.0

    active = np.flatnonzero(depth >= threshold)
    if len(active) == 0:
        return 0.0
    # Prefer the deepest active sample nearest the nominated path centre. This
    # avoids measuring an unrelated pitted patch elsewhere in the section.
    centre_candidates = active[np.argsort(np.abs(x[active]))]
    centre = int(centre_candidates[0])

    left = centre
    if left == 0:
        left_x = x[0]
    else:
        while left > 0 and depth[left - 1] >= threshold:
            left -= 1
        if left == 0:
            left_x = x[0]
        else:
            xa, xb = x[left - 1], x[left]
            da, db = depth[left - 1], depth[left]
            left_x = xb if abs(db - da) < 1e-12 else xa + (threshold - da) * (xb - xa) / (db - da)

    right = centre
    if right == len(x) - 1:
        right_x = x[-1]
    else:
        while right < len(x) - 1 and depth[right + 1] >= threshold:
            right += 1
        if right == len(x) - 1:
            right_x = x[-1]
        else:
            xa, xb = x[right], x[right + 1]
            da, db = depth[right], depth[right + 1]
            right_x = xa if abs(db - da) < 1e-12 else xa + (threshold - da) * (xb - xa) / (db - da)

    return max(0.0, float(right_x - left_x))


def audit_world_paths(obj_name, paths_world, labels=None,
                      face_normal=(0.0, 1.0, 0.0), face_dot=0.55,
                      path_radius=0.045, end_margin=None,
                      section_half_width=0.13, section_half_tangent=0.006,
                      thresholds=(0.001, 0.003, 0.005, 0.008),
                      bin_size=0.001, reference_points=None):
    """Measure depth and central cross-sections for world-space surface paths.

    ``paths_world`` is a sequence of 3-D polylines. Each path is measured
    against its own flat reference plane: by default the plane passes through
    the path midpoint, or callers may supply parallel ``reference_points``.
    ``face_normal`` selects the intended surface and defines positive inward
    depth as movement opposite that normal. ``path_radius`` selects vertices
    near a path for the maximum-depth sample. The cross-section is taken at
    the path midpoint, within ``section_half_tangent``, and reports the width
    of the central run at each inward ``threshold`` in metres.

    The face-normal gate is intentional: a solid slab has a second shell on
    the back, and a depth query that ignores orientation can report the full
    thickness instead of the sculpted relief. The function only reads the
    mesh and returns JSON-ready dictionaries; it never changes geometry or
    viewport state.
    """
    if paths_world is None:
        raise ValueError("audit_world_paths: paths_world is required")
    paths = [list(path) for path in paths_world]
    if not paths:
        raise ValueError("audit_world_paths: at least one path is required")
    if labels is not None and len(labels) != len(paths):
        raise ValueError("audit_world_paths: labels/path count differs")
    if reference_points is not None and len(reference_points) != len(paths):
        raise ValueError("audit_world_paths: reference/path count differs")
    if float(path_radius) <= 0.0:
        raise ValueError("audit_world_paths: path_radius must be positive")
    if float(section_half_width) <= 0.0 or float(section_half_tangent) <= 0.0:
        raise ValueError("audit_world_paths: section extents must be positive")
    if float(bin_size) <= 0.0:
        raise ValueError("audit_world_paths: bin_size must be positive")
    thresholds = tuple(float(t) for t in thresholds)
    if any(t < 0.0 for t in thresholds):
        raise ValueError("audit_world_paths: thresholds cannot be negative")

    normal = _normalise(face_normal, "face_normal")
    obj = __import__("bpy").data.objects.get(obj_name)
    if obj is None:
        raise KeyError("audit_world_paths: object %r not found" % obj_name)
    world, normals = sn.world_arrays(obj)
    normal_np = np.asarray(tuple(normal), dtype=np.float64)
    normal_dot = normals @ normal_np
    end_margin = float(path_radius) if end_margin is None else float(end_margin)
    if end_margin < 0.0:
        raise ValueError("audit_world_paths: end_margin cannot be negative")

    rows = []
    for index, path in enumerate(paths):
        points, tangent, lateral = _path_frame(path, normal)
        start = np.asarray(points[0], dtype=np.float64)
        finish = np.asarray(points[-1], dtype=np.float64)
        path_vec = finish - start
        length = float(Vector(path_vec).dot(tangent))
        if length <= 1e-12:
            raise ValueError("audit_world_paths: path length is zero")
        ref = (Vector(reference_points[index]) if reference_points is not None
               else (points[0] + points[-1]) * 0.5)
        ref_np = np.asarray(tuple(ref), dtype=np.float64)
        delta = world - ref_np
        along = delta @ np.asarray(tuple(tangent), dtype=np.float64)
        across = delta @ np.asarray(tuple(lateral), dtype=np.float64)
        inward = -(delta @ normal_np)

        projected = np.clip(along, 0.0, length)
        distance = np.hypot(across, along - projected)
        gate = normal_dot >= float(face_dot)
        path_mask = gate & (distance <= float(path_radius))
        # The maximum depth is allowed a small end margin, matching a round
        # brush's footprint without allowing a neighbouring feature to enter.
        path_mask &= (along >= -end_margin) & (along <= length + end_margin)
        path_depths = inward[path_mask]
        positive_path_depths = path_depths[path_depths > 0.0]
        depth_m = float(positive_path_depths.max()) if len(positive_path_depths) else 0.0

        mid = length * 0.5
        section_mask = gate & (np.abs(along - mid) <= float(section_half_tangent))
        section_mask &= np.abs(across) <= float(section_half_width)
        section_x = across[section_mask]
        section_depth = np.maximum(inward[section_mask], 0.0)
        widths = {
            "%gmm" % (threshold * 1000.0): _threshold_width(
                section_x, section_depth, threshold)
            for threshold in thresholds
        }
        mid_depth = float(section_depth.max()) if len(section_depth) else 0.0
        label = labels[index] if labels is not None else "path_%d" % (index + 1)
        rows.append({
            "label": str(label),
            "sampled": int(path_mask.sum()),
            "depth_m": depth_m,
            "depth_mm": depth_m * 1000.0,
            "mid_depth_m": mid_depth,
            "mid_depth_mm": mid_depth * 1000.0,
            "section_width_m": widths,
            "section_width_mm": {k: value * 1000.0 for k, value in widths.items()},
            "reference_point": [float(v) for v in ref],
            "tangent": [float(v) for v in tangent],
            "lateral": [float(v) for v in lateral],
        })

    depth_values = [row["depth_mm"] for row in rows]
    return {
        "object": obj_name,
        "face_normal": [float(v) for v in normal],
        "face_dot": float(face_dot),
        "settings": {
            "path_radius_m": float(path_radius),
            "end_margin_m": end_margin,
            "section_half_width_m": float(section_half_width),
            "section_half_tangent_m": float(section_half_tangent),
            "thresholds_m": list(thresholds),
            "bin_size_m": float(bin_size),
        },
        "rows": rows,
        "summary": {
            "count": len(rows),
            "depth_mm": [min(depth_values), max(depth_values)],
            "section_width_mm": {
                key: [min(row["section_width_mm"][key] for row in rows),
                      max(row["section_width_mm"][key] for row in rows)]
                for key in rows[0]["section_width_mm"]
            },
        },
    }
