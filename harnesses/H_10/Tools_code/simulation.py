"""Deterministic timeline evaluation and rigid-body audit helpers.

Point caches are history-dependent: these helpers make contiguous evaluation,
contact reports, and cache state explicit without knowing anything about the
subject or editing mesh data.
"""

import bpy
import math
from mathutils import Vector


def _mesh_points(obj):
    """Return evaluated world-space vertices for one mesh object."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        return [matrix @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def _snapshot(frame, points, sample_indices):
    """Build a JSON-ready snapshot for one evaluated frame."""
    if not points:
        raise ValueError("evaluate_sequence: evaluated mesh has no vertices")
    return {
        "frame": int(frame),
        "vertex_count": len(points),
        "bounds": [
            min(float(point.x) for point in points),
            max(float(point.x) for point in points),
            min(float(point.y) for point in points),
            max(float(point.y) for point in points),
            min(float(point.z) for point in points),
            max(float(point.z) for point in points),
        ],
        "sample_vertices": [
            [float(points[index].x), float(points[index].y), float(points[index].z)]
            for index in sample_indices
            if 0 <= index < len(points)
        ],
    }


def configure_collision_surfaces(object_names, *, use_culling=False,
                                  use_normal=True, thickness_outer=None,
                                  thickness_inner=None):
    """Set common collision flags on named mesh supports.

    ``object_names`` is a mesh name or iterable of mesh names.  The collision
    modifier must already exist; this helper only changes its collision settings
    and never creates a proxy or edits geometry.  ``thickness_outer`` and
    ``thickness_inner`` are optional so callers can preserve the current shell
    when only the collision direction needs correction.  The default
    ``use_culling=False`` is deliberate: a closed support is normally expected
    to collide from either side, and callers can opt into one-sided culling.

    The return value records the applied settings for each support.  Updating
    collision settings does not invalidate a caller's choice of solver; callers
    should use :func:`evaluate_sequence` from the cache start after changing
    them.
    """
    if isinstance(object_names, str):
        names = [object_names]
    else:
        names = list(object_names)
    if not names:
        raise ValueError("configure_collision_surfaces: object_names is empty")

    report = {}
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise KeyError("configure_collision_surfaces: mesh not found: %s" % name)
        if obj.collision is None:
            raise ValueError(
                "configure_collision_surfaces: mesh has no collision modifier: %s"
                % name
            )
        settings = obj.collision
        settings.use_culling = bool(use_culling)
        settings.use_normal = bool(use_normal)
        if thickness_outer is not None:
            settings.thickness_outer = float(thickness_outer)
        if thickness_inner is not None:
            settings.thickness_inner = float(thickness_inner)
        report[name] = {
            "use_culling": bool(settings.use_culling),
            "use_normal": bool(settings.use_normal),
            "thickness_outer": float(settings.thickness_outer),
            "thickness_inner": float(settings.thickness_inner),
        }
    bpy.context.view_layer.update()
    return {"objects": report}


def evaluate_sequence(object_name, frame_start, frame_end, *,
                      sample_frames=None, sample_indices=(),
                      include_final_vertices=False):
    """Evaluate a mesh through every frame in an inclusive contiguous range.

    ``object_name`` identifies any mesh whose evaluated state depends on timeline
    history, such as a cloth, particle, or modifier cache.  The scene frame is
    set to ``frame_start``, then advanced one frame at a time through
    ``frame_end``; the function leaves the scene at ``frame_end``.  It does not
    change the scene frame range, cache range, modifiers, or mesh data.

    ``sample_frames`` selects which frames receive bounds and optional vertex
    samples in the report; it defaults to the endpoints.  ``sample_indices``
    are evaluated-mesh vertex indices and are ignored when out of range.  Set
    ``include_final_vertices=True`` when the caller needs the complete final
    world-space vertex list for a second measurement.  The report also includes
    the maximum start-to-end displacement and the number of changed vertices,
    making a static or stale cache visible without a render.
    """
    if not isinstance(object_name, str) or not object_name:
        raise ValueError("evaluate_sequence: object_name must be non-empty")
    try:
        start = int(frame_start)
        end = int(frame_end)
    except (TypeError, ValueError):
        raise ValueError("evaluate_sequence: frame bounds must be integers") from None
    if end < start:
        raise ValueError("evaluate_sequence: frame_end must be >= frame_start")

    obj = bpy.data.objects.get(object_name)
    if obj is None or obj.type != "MESH":
        raise KeyError("evaluate_sequence: mesh not found: %s" % object_name)

    if sample_frames is None:
        wanted = {start, end}
    else:
        wanted = {int(frame) for frame in sample_frames}
        outside = sorted(frame for frame in wanted if frame < start or frame > end)
        if outside:
            raise ValueError(
                "evaluate_sequence: sample frame(s) outside range: %s" % outside
            )
        wanted.update((start, end))
    indices = tuple(int(index) for index in sample_indices)

    scene = bpy.context.scene
    snapshots = {}
    first_points = None
    final_points = None
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        points = _mesh_points(obj)
        if frame == start:
            first_points = points
        if frame in wanted:
            snapshots[str(frame)] = _snapshot(frame, points, indices)
        if frame == end:
            final_points = points

    if first_points is None or final_points is None:
        raise RuntimeError("evaluate_sequence: no frames were evaluated")
    paired = zip(first_points, final_points)
    deltas = [(after - before).length for before, after in paired]
    changed = sum(1 for delta in deltas if delta > 1.0e-7)
    result = {
        "object": object_name,
        "frame_start": start,
        "frame_end": end,
        "current_frame": int(scene.frame_current),
        "sample_frames": sorted(int(frame) for frame in wanted),
        "samples": snapshots,
        "vertex_count_start": len(first_points),
        "vertex_count_end": len(final_points),
        "max_vertex_delta_start_to_end": max(deltas) if deltas else 0.0,
        "changed_vertex_count_start_to_end": changed,
    }
    if include_final_vertices:
        result["final_world_vertices"] = [
            [float(point.x), float(point.y), float(point.z)]
            for point in final_points
        ]
    return result


def _sequence_object_names(object_names, label):
    """Normalize a name or ordered iterable of mesh names."""
    if isinstance(object_names, str):
        names = [object_names]
    else:
        try:
            names = list(object_names)
        except TypeError:
            raise ValueError("%s: object_names must be a name or iterable" % label) from None
    if not names or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("%s: object_names must contain non-empty names" % label)
    if len(set(names)) != len(names):
        raise ValueError("%s: object_names must be unique and ordered" % label)
    return names


def _validate_frame_range(frame_start, frame_end, label):
    """Return integer inclusive frame bounds with a useful error."""
    try:
        start = int(frame_start)
        end = int(frame_end)
    except (TypeError, ValueError):
        raise ValueError("%s: frame bounds must be integers" % label) from None
    if end < start:
        raise ValueError("%s: frame_end must be >= frame_start" % label)
    return start, end


def bake_rigid_body_cache(frame_start, frame_end, *, scene=None):
    """Bake the active rigid-body point cache over an inclusive frame range.

    The scene and its point-cache bounds are set explicitly, the timeline is
    reset to ``frame_start``, and Blender's context-safe ``bake_all`` operator
    is used because the single-cache operator is not available in every
    VIEW_3D context.  An already baked cache is not cleared or rebaked.  The
    return value is JSON-ready and records the actual cache flags and range.
    This helper changes simulation cache state, not mesh geometry.
    """
    scene = scene or bpy.context.scene
    start, end = _validate_frame_range(frame_start, frame_end,
                                       "bake_rigid_body_cache")
    world = scene.rigidbody_world
    if world is None:
        raise RuntimeError("bake_rigid_body_cache: scene has no rigid-body world")
    cache = world.point_cache
    scene.frame_start = start
    scene.frame_end = end
    cache.frame_start = start
    cache.frame_end = end
    scene.frame_set(start)
    bpy.context.view_layer.update()

    skipped = bool(cache.is_baked)
    if not skipped:
        if not bpy.ops.ptcache.bake_all.poll():
            raise RuntimeError(
                "bake_rigid_body_cache: bpy.ops.ptcache.bake_all is unavailable"
            )
        operator_result = bpy.ops.ptcache.bake_all(bake=True)
    else:
        operator_result = {"SKIPPED_ALREADY_BAKED"}

    scene.frame_set(end)
    bpy.context.view_layer.update()
    return {
        "operator_result": sorted(str(value) for value in operator_result),
        "skipped_already_baked": skipped,
        "baked": bool(cache.is_baked),
        "outdated": getattr(cache, "is_outdated", None),
        "frame_start": int(cache.frame_start),
        "frame_end": int(cache.frame_end),
        "scene_frame_start": int(scene.frame_start),
        "scene_frame_end": int(scene.frame_end),
        "current_frame": int(scene.frame_current),
    }


def _local_box_spec(obj, override=None):
    """Return ``(local_bbox_center, local_half_extents)`` for a BOX proxy."""
    if not getattr(obj, "data", None) or len(obj.data.vertices) == 0:
        raise ValueError("rigid_body_sequence_report: mesh has no vertices: %s" % obj.name)
    coords = [vertex.co for vertex in obj.data.vertices]
    lo = Vector((min(point[i] for point in coords) for i in range(3)))
    hi = Vector((max(point[i] for point in coords) for i in range(3)))
    center = (lo + hi) * 0.5
    half = (hi - lo) * 0.5 if override is None else Vector(override)
    if any(float(value) <= 0.0 for value in half):
        raise ValueError("rigid_body_sequence_report: box half extents must be positive")
    return center, half


def _oriented_box_gap(obj_a, spec_a, obj_b, spec_b):
    """Return the maximum separating gap between two oriented BOX proxies."""
    center_a, half_a = spec_a
    center_b, half_b = spec_b
    matrix_a = obj_a.matrix_world.to_3x3()
    matrix_b = obj_b.matrix_world.to_3x3()

    axes_a = []
    axes_b = []
    scale_a = []
    scale_b = []
    for index in range(3):
        col_a = matrix_a.col[index]
        col_b = matrix_b.col[index]
        if col_a.length < 1.0e-12 or col_b.length < 1.0e-12:
            raise ValueError("rigid_body_sequence_report: zero object scale")
        axes_a.append(col_a.normalized())
        axes_b.append(col_b.normalized())
        scale_a.append(col_a.length)
        scale_b.append(col_b.length)

    world_center_a = obj_a.matrix_world @ center_a
    world_center_b = obj_b.matrix_world @ center_b
    world_half_a = [half_a[index] * scale_a[index] for index in range(3)]
    world_half_b = [half_b[index] * scale_b[index] for index in range(3)]
    axes = list(axes_a) + list(axes_b)
    for axis_a in axes_a:
        for axis_b in axes_b:
            cross = axis_a.cross(axis_b)
            if cross.length > 1.0e-8:
                axes.append(cross.normalized())

    separation = world_center_b - world_center_a
    gaps = []
    for axis in axes:
        axis = axis.normalized()
        radius_a = sum(world_half_a[index] * abs(axis.dot(axes_a[index]))
                       for index in range(3))
        radius_b = sum(world_half_b[index] * abs(axis.dot(axes_b[index]))
                       for index in range(3))
        gaps.append(abs(separation.dot(axis)) - radius_a - radius_b)
    return max(gaps)


def _signed_object_angle(obj, rotation_axis, reference_axis, sign_axis,
                         local_reference_axis):
    """Measure a signed object orientation around a world-space axis."""
    axis = Vector(rotation_axis)
    if axis.length < 1.0e-12:
        raise ValueError("rigid_body_sequence_report: rotation axis is zero")
    axis.normalize()
    reference = Vector(reference_axis)
    sign = Vector(sign_axis)
    reference -= axis * reference.dot(axis)
    sign -= axis * sign.dot(axis)
    if reference.length < 1.0e-12 or sign.length < 1.0e-12:
        raise ValueError("rigid_body_sequence_report: angle basis is parallel to axis")
    reference.normalize()
    sign.normalize()
    transformed = obj.matrix_world.to_3x3() @ Vector(local_reference_axis)
    return math.degrees(math.atan2(transformed.dot(sign),
                                   transformed.dot(reference)))


def _bounds_record(points):
    """Return compact XYZ bounds and center for world-space points."""
    if not points:
        raise ValueError("rigid_body_sequence_report: evaluated mesh has no vertices")
    bounds = [
        min(float(point.x) for point in points),
        max(float(point.x) for point in points),
        min(float(point.y) for point in points),
        max(float(point.y) for point in points),
        min(float(point.z) for point in points),
        max(float(point.z) for point in points),
    ]
    return {
        "bounds": bounds,
        "center": [
            (bounds[0] + bounds[1]) * 0.5,
            (bounds[2] + bounds[3]) * 0.5,
            (bounds[4] + bounds[5]) * 0.5,
        ],
        "minz": bounds[4],
        "maxz": bounds[5],
    }


def rigid_body_sequence_report(object_names, frame_start, frame_end, *,
                               sample_frames=None, clear_lean_degrees=20.0,
                               pair_gap_threshold=0.005,
                               rotation_axis=(0.0, 1.0, 0.0),
                               reference_axis=(0.0, 0.0, 1.0),
                               sign_axis=(1.0, 0.0, 0.0),
                               local_reference_axis=(0.0, 0.0, 1.0),
                               floor_name=None, box_half_extents=None,
                               child_names=None, attachment_frame=None,
                               leave_frame=None):
    """Audit an ordered rigid-body chain in one contiguous timeline traversal.

    ``object_names`` is the ordered chain; each named object must be a mesh.
    The function advances the scene one frame at a time from ``frame_start``
    through ``frame_end`` and reports sampled transforms, the first frame each
    object exceeds ``clear_lean_degrees`` about the supplied angle basis, and
    adjacent oriented-BOX gaps.  A positive gap is separation and a negative
    value is overlap; ``pair_gap_threshold`` defines the near-touch window.
    BOX half extents are derived from each mesh's local bounds by default, or
    can be one 3-vector for every object or a name-to-3-vector mapping when a
    collision proxy is intentionally different from the visible mesh.

    Optional ``floor_name`` adds final support clearance/footprint checks.
    Optional ``child_names`` measures parent-relative transform drift at
    ``attachment_frame`` (default: ``frame_end``).  ``leave_frame`` keeps a
    chosen inspected frame active; otherwise the end frame remains active.
    The helper is read-only apart from timeline evaluation and returns a
    JSON-ready report, so it can replace duplicated per-subject SAT/audit
    loops without changing geometry.
    """
    start, end = _validate_frame_range(frame_start, frame_end,
                                       "rigid_body_sequence_report")
    names = _sequence_object_names(object_names, "rigid_body_sequence_report")
    if not (0.0 <= float(pair_gap_threshold)):
        raise ValueError("rigid_body_sequence_report: pair_gap_threshold must be non-negative")
    clear_threshold = float(clear_lean_degrees)
    if not math.isfinite(clear_threshold) or clear_threshold < 0.0:
        raise ValueError("rigid_body_sequence_report: clear_lean_degrees must be finite and non-negative")
    if leave_frame is None:
        final_frame = end
    else:
        final_frame = int(leave_frame)
        if final_frame < start or final_frame > end:
            raise ValueError("rigid_body_sequence_report: leave_frame is outside range")

    objects = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise KeyError("rigid_body_sequence_report: mesh not found: %s" % name)
        objects.append(obj)

    if box_half_extents is None:
        overrides = {}
        shared_half = None
    elif isinstance(box_half_extents, dict):
        overrides = dict(box_half_extents)
        unknown = sorted(set(overrides) - set(names))
        if unknown:
            raise KeyError("rigid_body_sequence_report: extents for unknown object(s): %s" % unknown)
        shared_half = None
    else:
        overrides = {}
        shared_half = tuple(box_half_extents)
    specs = {}
    for obj in objects:
        override = overrides.get(obj.name, shared_half)
        specs[obj.name] = _local_box_spec(obj, override)

    if sample_frames is None:
        wanted = {start, end}
    else:
        try:
            wanted = {int(frame) for frame in sample_frames}
        except (TypeError, ValueError):
            raise ValueError("rigid_body_sequence_report: sample_frames must be iterable integers") from None
        outside = sorted(frame for frame in wanted if frame < start or frame > end)
        if outside:
            raise ValueError("rigid_body_sequence_report: sample frame(s) outside range: %s" % outside)
        wanted.update((start, end))

    child_objs = []
    if child_names is not None:
        child_list = _sequence_object_names(child_names, "rigid_body_sequence_report")
        child_objs = []
        for name in child_list:
            obj = bpy.data.objects.get(name)
            if obj is None:
                raise KeyError("rigid_body_sequence_report: child not found: %s" % name)
            child_objs.append(obj)
    if attachment_frame is None:
        child_frame = end
    else:
        child_frame = int(attachment_frame)
        if child_frame < start or child_frame > end:
            raise ValueError("rigid_body_sequence_report: attachment_frame is outside range")

    scene = bpy.context.scene
    angles_by_frame = {}
    sample_data = {}
    pair_values = [[] for _ in range(max(0, len(objects) - 1))]
    final_bounds = {}
    relative_start = {}
    max_child_delta = 0.0
    child_deltas_checked = False

    for frame in range(start, end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        angles = []
        bounds = {}
        for obj in objects:
            points = _mesh_points(obj)
            bounds[obj.name] = _bounds_record(points)
            angles.append(_signed_object_angle(
                obj, rotation_axis, reference_axis, sign_axis,
                local_reference_axis))
        angles_by_frame[frame] = angles
        if frame == start and child_objs:
            relative_start = {
                child.name: child.parent.matrix_world.inverted() @ child.matrix_world
                for child in child_objs if child.parent is not None
            }
        if frame == child_frame and child_objs:
            for child in child_objs:
                if child.parent is not None and child.name in relative_start:
                    now = child.parent.matrix_world.inverted() @ child.matrix_world
                    before = relative_start[child.name]
                    max_child_delta = max(
                        max_child_delta,
                        max(abs(now[row][col] - before[row][col])
                            for row in range(4) for col in range(4)),
                    )
            child_deltas_checked = True
        for index in range(len(objects) - 1):
            pair_values[index].append(_oriented_box_gap(
                objects[index], specs[objects[index].name],
                objects[index + 1], specs[objects[index + 1].name]))
        if frame in wanted:
            sample_data[str(frame)] = {
                "angles_deg": [float(value) for value in angles],
                "bounds": bounds,
            }
        if frame == end:
            final_bounds = bounds

    first_clear = [
        next((frame for frame in range(start, end + 1)
              if abs(angles_by_frame[frame][index]) > clear_threshold), None)
        for index in range(len(objects))
    ]
    contacts = []
    for index, values in enumerate(pair_values):
        touching = [
            frame for frame, gap in zip(range(start, end + 1), values)
            if gap <= float(pair_gap_threshold)
        ]
        contacts.append({
            "pair": "%s->%s" % (names[index], names[index + 1]),
            "first_touch_window": touching[0] if touching else None,
            "last_touch_window": touching[-1] if touching else None,
            "min_gap": min(values) if values else None,
            "max_overlap": max(0.0, -min(values)) if values else None,
        })

    support_report = None
    if floor_name is not None:
        support = bpy.data.objects.get(floor_name)
        if support is None or support.type != "MESH":
            raise KeyError("rigid_body_sequence_report: support mesh not found: %s" % floor_name)
        support_bounds = _bounds_record(_mesh_points(support))
        for name in names:
            record = final_bounds[name]
            cx, cy = record["center"][0], record["center"][1]
            record["floor_clearance"] = record["minz"] - support_bounds["maxz"]
            record["inside_support_xy"] = (
                support_bounds["bounds"][0] <= cx <= support_bounds["bounds"][1]
                and support_bounds["bounds"][2] <= cy <= support_bounds["bounds"][3]
            )
        support_report = {
            "object": floor_name,
            "top_z": support_bounds["maxz"],
            "bounds": support_bounds["bounds"],
        }

    rigid_inventory = []
    for obj in objects:
        rb = obj.rigid_body
        action = obj.animation_data.action if obj.animation_data else None
        rigid_inventory.append({
            "name": obj.name,
            "rigid_body_type": rb.type if rb else None,
            "collision_shape": rb.collision_shape if rb else None,
            "use_margin": bool(rb.use_margin) if rb else None,
            "keyframe_count": sum(len(fc.keyframe_points) for fc in action.fcurves)
            if action else 0,
        })

    world = scene.rigidbody_world
    cache = world.point_cache if world else None
    scene.frame_set(final_frame)
    bpy.context.view_layer.update()
    return {
        "object_names": names,
        "frame_start": start,
        "frame_end": end,
        "current_frame": int(scene.frame_current),
        "sample_frames": sorted(int(frame) for frame in wanted),
        "samples": sample_data,
        "clear_lean_degrees": clear_threshold,
        "first_clear_lean_frames": first_clear,
        "pair_gap_threshold": float(pair_gap_threshold),
        "contacts": contacts,
        "final_bounds": final_bounds,
        "support": support_report,
        "rigid_body_inventory": rigid_inventory,
        "cache": {
            "present": bool(world),
            "baked": bool(cache and cache.is_baked),
            "outdated": getattr(cache, "is_outdated", None) if cache else None,
            "frame_start": int(cache.frame_start) if cache else None,
            "frame_end": int(cache.frame_end) if cache else None,
        },
        "child_attachment": {
            "child_count": len(child_objs),
            "checked_frame": child_frame if child_objs else None,
            "max_parent_relative_delta": max_child_delta if child_objs else None,
            "all_children_had_parent": (
                len(relative_start) == len(child_objs)
                if child_objs else None
            ),
            "checked": child_deltas_checked,
        },
    }


def _animation_fcurves(action):
    """Yield classic or layered Action FCurves across Blender API versions."""
    classic = getattr(action, "fcurves", None)
    if classic is not None and len(classic):
        yield from classic
        return
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for bag in getattr(strip, "channelbags", ()):
                yield from bag.fcurves


def _world_centroid(points):
    """Return a JSON-ready centroid for a non-empty world-point list."""
    if not points:
        return None
    total = Vector((0.0, 0.0, 0.0))
    for point in points:
        total += point
    return [float(value) for value in total / len(points)]


def _vector_delta(after, before):
    """Subtract two JSON-ready vectors, preserving ``None`` for missing data."""
    if after is None or before is None:
        return None
    return [float(a) - float(b) for a, b in zip(after, before)]


def _animation_region_points(points, spec):
    """Select points for an optional world-X region specification."""
    if not isinstance(spec, dict):
        raise TypeError("animation_sequence_report region specs must be dicts")
    selected = points
    if "indices" in spec:
        selected = [points[int(index)] for index in spec["indices"]
                    if 0 <= int(index) < len(points)]
    if "x_lt" in spec:
        selected = [point for point in selected if point.x < float(spec["x_lt"])]
    if "x_lte" in spec:
        selected = [point for point in selected if point.x <= float(spec["x_lte"])]
    if "x_gt" in spec:
        selected = [point for point in selected if point.x > float(spec["x_gt"])]
    if "x_gte" in spec:
        selected = [point for point in selected if point.x >= float(spec["x_gte"])]
    if "x_range" in spec:
        lo, hi = (float(value) for value in spec["x_range"])
        if hi < lo:
            raise ValueError("animation_sequence_report x_range must be ascending")
        selected = [point for point in selected if lo <= point.x <= hi]
    return selected


def _animation_contact_distance(source_points, target_points):
    """Nearest-vertex distance, matching the cheap contact audit used by reviews."""
    if not source_points or not target_points:
        return None
    from mathutils.kdtree import KDTree

    tree = KDTree(len(target_points))
    for index, point in enumerate(target_points):
        tree.insert(point, index)
    tree.balance()
    return min(float(tree.find(point)[2]) for point in source_points)


def _animation_pair(pair):
    """Normalize a contact pair to (source_name, target_name)."""
    if isinstance(pair, dict):
        source = pair.get("source", pair.get("part", pair.get("object")))
        target = pair.get("target", pair.get("against", pair.get("body")))
    else:
        try:
            source, target = pair
        except (TypeError, ValueError):
            raise ValueError(
                "animation_sequence_report contact pairs need source and target"
            ) from None
    if not isinstance(source, str) or not source or not isinstance(target, str) or not target:
        raise ValueError("animation_sequence_report contact names must be non-empty")
    return source, target


def animation_sequence_report(
    object_names,
    frame_start,
    frame_end,
    *,
    sample_frames=None,
    reference_frame=None,
    centroid_regions=None,
    armature_name=None,
    chain_bones=(),
    bone_inventory_names=None,
    contact_pairs=(),
    binding_names=None,
    binding_modifier="SharkRig_Armature",
    binding_uv_layer=None,
    binding_texture_node=None,
    action_name=None,
    curve_frames=None,
    endpoint_frames=None,
    project=False,
    leave_frame=None,
):
    """Audit a deforming assembly in one contiguous timeline traversal.

    ``object_names`` is an ordered set of mesh names to evaluate.  The scene is
    advanced one frame at a time from ``frame_start`` through ``frame_end``;
    sampled frames receive world bounds, centroids, optional X-region
    centroids, contacts, bone-joint gaps, and screen projections.  This is the
    general replacement for separate motion, curve, contact, and projection
    probe scripts: it does not know the subject or its axis convention.

    ``centroid_regions`` maps a label to ``{"object": name, ...}``.  Optional
    ``x_lt``, ``x_lte``, ``x_gt``, ``x_gte``, ``x_range``, and stable ``indices``
    fields select a subset before its centroid is calculated.  ``reference_frame``
    adds world and screen deltas against that sample (default: ``frame_start``).

    ``armature_name`` plus ordered ``chain_bones`` reports every adjacent pose
    bone gap at sampled frames.  ``bone_inventory_names`` optionally adds
    non-chain control bones to the structural inventory.  ``contact_pairs``
    contains ``(source, target)``
    names and reports nearest evaluated-vertex distances at the same samples.
    ``binding_names`` checks for ``binding_modifier`` without evaluating extra
    meshes.  Optional ``binding_uv_layer`` and ``binding_texture_node`` add
    active-data checks for textured deforming parts.  ``action_name`` audits
    classic or Blender layered FCurves, their
    values at ``curve_frames``, endpoint error, and CYCLES modifier counts.
    ``project=True`` projects the sampled object/region centroids and first
    chain-bone head through the CURRENT viewport; the caller must establish the
    view before calling, because the helper deliberately never changes it.

    The helper warms the dependency graph by evaluating every traversed frame,
    leaves only the requested ``leave_frame`` as a scene-state change, and does
    not edit mesh data, modifiers, objects, actions, or animation curves.  The
    returned dictionary is JSON-ready and contains the complete evidence from
    all requested checks.
    """
    start, end = _validate_frame_range(frame_start, frame_end,
                                       "animation_sequence_report")
    names = _sequence_object_names(object_names, "animation_sequence_report")

    regions = dict(centroid_regions or {})
    for label, spec in regions.items():
        if not isinstance(spec, dict) or not spec.get("object"):
            raise ValueError(
                "animation_sequence_report region %r needs an object" % label
            )
        if spec["object"] not in names:
            raise KeyError(
                "animation_sequence_report region %r uses untracked mesh %s"
                % (label, spec["object"])
            )

    pairs = [_animation_pair(pair) for pair in contact_pairs]
    needed = set(names)
    for source, target in pairs:
        needed.update((source, target))
    missing_tracking = sorted(needed - set(names))
    if missing_tracking:
        raise KeyError(
            "animation_sequence_report contact mesh(es) not in object_names: %s"
            % missing_tracking
        )

    if sample_frames is None:
        wanted = {start, end}
    else:
        try:
            wanted = {int(frame) for frame in sample_frames}
        except (TypeError, ValueError):
            raise ValueError(
                "animation_sequence_report sample_frames must be iterable integers"
            ) from None
        outside = sorted(frame for frame in wanted if frame < start or frame > end)
        if outside:
            raise ValueError(
                "animation_sequence_report sample frame(s) outside range: %s"
                % outside
            )
        wanted.update((start, end))

    if reference_frame is None:
        reference = start
    else:
        reference = int(reference_frame)
        if reference < start or reference > end:
            raise ValueError(
                "animation_sequence_report reference_frame is outside range"
            )
    wanted.add(reference)

    final_frame = end if leave_frame is None else int(leave_frame)
    if final_frame < start or final_frame > end:
        raise ValueError("animation_sequence_report leave_frame is outside range")

    if armature_name is not None:
        rig = bpy.data.objects.get(armature_name)
        if rig is None or rig.type != "ARMATURE":
            raise KeyError("animation_sequence_report armature not found: %s" % armature_name)
        bones = tuple(chain_bones)
        inventory_bones = tuple(
            bones if bone_inventory_names is None else bone_inventory_names
        )
        for bone_name in bones:
            if rig.pose.bones.get(bone_name) is None:
                raise KeyError(
                    "animation_sequence_report chain bone not found: %s" % bone_name
                )
        for bone_name in inventory_bones:
            if rig.pose.bones.get(bone_name) is None:
                raise KeyError(
                    "animation_sequence_report inventory bone not found: %s" % bone_name
                )
    else:
        rig = None
        bones = tuple(chain_bones)
        inventory_bones = tuple(
            bones if bone_inventory_names is None else bone_inventory_names
        )
        if bones or inventory_bones:
            raise ValueError(
                "animation_sequence_report bone names require armature_name"
            )

    bone_inventory = {}
    if rig is not None:
        for bone_name in inventory_bones:
            data_bone = rig.data.bones.get(bone_name)
            pose_bone = rig.pose.bones.get(bone_name)
            bone_inventory[bone_name] = {
                "parent": data_bone.parent.name if data_bone and data_bone.parent else None,
                "use_deform": bool(data_bone.use_deform) if data_bone else None,
                "head_local": [float(value) for value in data_bone.head_local] if data_bone else None,
                "tail_local": [float(value) for value in data_bone.tail_local] if data_bone else None,
                "pose_rotation_mode": pose_bone.rotation_mode if pose_bone else None,
            }

    binding_report = None
    if binding_names is not None:
        binding_list = _sequence_object_names(
            binding_names, "animation_sequence_report binding_names"
        )
        binding_rows = []
        for name in binding_list:
            obj = bpy.data.objects.get(name)
            if obj is None or obj.type != "MESH":
                raise KeyError(
                    "animation_sequence_report binding mesh not found: %s" % name
                )
            modifier = obj.modifiers.get(binding_modifier)
            material = obj.data.materials[0] if obj.data.materials else None
            texture = None
            if binding_texture_node and material and material.use_nodes and material.node_tree:
                node = material.node_tree.nodes.get(binding_texture_node)
                texture = node.image.name if node and node.image else None
            binding_rows.append({
                "name": name,
                "modifier": binding_modifier,
                "present": modifier is not None,
                "target": modifier.object.name if modifier and modifier.object else None,
                "material": material.name if material else None,
                "uv_layer": binding_uv_layer,
                "has_uv_layer": bool(
                    binding_uv_layer and obj.data.uv_layers.get(binding_uv_layer)
                ),
                "texture_node": binding_texture_node,
                "texture_image": texture,
            })
        binding_report = {
            "modifier": binding_modifier,
            "uv_layer": binding_uv_layer,
            "texture_node": binding_texture_node,
            "objects": binding_rows,
            "missing": [row["name"] for row in binding_rows if not row["present"]],
            "wrong_target": [
                row["name"] for row in binding_rows
                if row["present"] and rig is not None and row["target"] != rig.name
            ],
            "missing_uv_layer": [
                row["name"] for row in binding_rows
                if binding_uv_layer and not row["has_uv_layer"]
            ],
            "missing_texture_image": [
                row["name"] for row in binding_rows
                if binding_texture_node and not row["texture_image"]
            ],
        }

    projection_view = None
    if project:
        from lib.view import get_viewport, project_to_norm

        _area, region, rv3d = get_viewport()
        if region is None or rv3d is None:
            raise RuntimeError(
                "animation_sequence_report project=True needs a VIEW_3D viewport"
            )
        projection_view = {
            "region_px": [int(region.width), int(region.height)],
            "view_perspective": str(rv3d.view_perspective),
        }
    else:
        region = rv3d = None

    scene = bpy.context.scene
    samples = {}
    point_samples = {}
    chain_gaps = {}
    contacts = {}
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        # Evaluate every traversed frame, not just the saved samples: this is
        # what makes the report useful for history-dependent modifiers too.
        points_by_name = {name: _mesh_points(bpy.data.objects[name]) for name in names}
        if frame not in wanted:
            continue

        objects = {}
        for name in names:
            points = points_by_name[name]
            objects[name] = {
                "vertex_count": len(points),
                "bounds": _bounds_record(points),
                "centroid_world": _world_centroid(points),
            }
        region_rows = {}
        for label, spec in regions.items():
            selected = _animation_region_points(
                points_by_name[spec["object"]], spec
            )
            region_rows[label] = {
                "object": spec["object"],
                "vertex_count": len(selected),
                "centroid_world": _world_centroid(selected),
            }

        sample = {
            "frame": int(frame),
            "objects": objects,
            "regions": region_rows,
        }

        if pairs:
            contact_rows = {}
            for source, target in pairs:
                distance = _animation_contact_distance(
                    points_by_name[source], points_by_name[target]
                )
                contact_rows["%s->%s" % (source, target)] = distance
            contacts[str(frame)] = contact_rows
            sample["contact_distances_world"] = contact_rows

        if rig is not None and bones:
            joint_rows = {}
            endpoints = {}
            for bone_name in bones:
                pose_bone = rig.pose.bones[bone_name]
                endpoints[bone_name] = {
                    "head_world": [float(value) for value in rig.matrix_world @ pose_bone.head],
                    "tail_world": [float(value) for value in rig.matrix_world @ pose_bone.tail],
                }
            for previous, current in zip(bones[:-1], bones[1:]):
                a = Vector(endpoints[previous]["tail_world"])
                b = Vector(endpoints[current]["head_world"])
                joint_rows["%s->%s" % (previous, current)] = float((a - b).length)
            chain_gaps[str(frame)] = joint_rows
            sample["chain_joint_gaps_world"] = joint_rows
            sample["chain_endpoints_world"] = endpoints

        if project:
            projected = {}
            for name, row in objects.items():
                projected[name] = {
                    "world": row["centroid_world"],
                    "screen_norm": list(
                        project_to_norm(row["centroid_world"], region, rv3d)
                    ) if row["centroid_world"] is not None else [None, None],
                }
            for label, row in region_rows.items():
                projected[label] = {
                    "world": row["centroid_world"],
                    "screen_norm": list(
                        project_to_norm(row["centroid_world"], region, rv3d)
                    ) if row["centroid_world"] is not None else [None, None],
                }
            if rig is not None and bones:
                root = Vector(endpoints[bones[0]]["head_world"])
                projected["chain_root"] = {
                    "world": [float(value) for value in root],
                    "screen_norm": list(project_to_norm(root, region, rv3d)),
                }
            sample["projection"] = projected

        samples[str(frame)] = sample
        point_samples[frame] = points_by_name

    if str(reference) not in samples:
        raise RuntimeError("animation_sequence_report reference sample was not captured")

    reference_sample = samples[str(reference)]
    for sample in samples.values():
        for name, row in sample["objects"].items():
            row["centroid_delta_from_reference"] = _vector_delta(
                row["centroid_world"],
                reference_sample["objects"][name]["centroid_world"],
            )
        for label, row in sample["regions"].items():
            row["centroid_delta_from_reference"] = _vector_delta(
                row["centroid_world"],
                reference_sample["regions"][label]["centroid_world"],
            )
        if "projection" in sample:
            ref_projection = reference_sample.get("projection", {})
            for label, row in sample["projection"].items():
                row["screen_delta_from_reference"] = _vector_delta(
                    row["screen_norm"],
                    ref_projection.get(label, {}).get("screen_norm"),
                )

    curve_report = None
    if action_name is not None:
        if rig is None:
            raise ValueError("animation_sequence_report action_name requires armature_name")
        action = rig.animation_data.action if rig.animation_data else None
        if action is None or action.name != str(action_name):
            raise ValueError(
                "animation_sequence_report expected active action %s, got %s"
                % (action_name, action.name if action else None)
            )
        if endpoint_frames is None:
            endpoints = (start, end)
        else:
            endpoints = tuple(int(frame) for frame in endpoint_frames)
        if len(endpoints) != 2 or endpoints[1] < endpoints[0]:
            raise ValueError(
                "animation_sequence_report endpoint_frames must be (start, end)"
            )
        for frame in endpoints:
            if frame < start or frame > end:
                raise ValueError(
                    "animation_sequence_report endpoint frame is outside traversal"
                )
        if curve_frames is None:
            curve_samples = list(endpoints)
        else:
            curve_samples = [int(frame) for frame in curve_frames]
        curves = list(_animation_fcurves(action))
        rows = []
        endpoint_errors = []
        cycles = 0
        for fcurve in curves:
            values = {str(frame): float(fcurve.evaluate(float(frame)))
                      for frame in curve_samples}
            first = float(fcurve.evaluate(float(endpoints[0])))
            last = float(fcurve.evaluate(float(endpoints[1])))
            error = abs(last - first)
            endpoint_errors.append(error)
            count = sum(1 for modifier in fcurve.modifiers if modifier.type == "CYCLES")
            cycles += count
            rows.append({
                "data_path": fcurve.data_path,
                "array_index": int(fcurve.array_index),
                "group": fcurve.group.name if fcurve.group else None,
                "key_count": len(fcurve.keyframe_points),
                "values": values,
                "endpoint_frames": list(endpoints),
                "endpoint_error": error,
                "cycles_modifiers": count,
            })
        curve_report = {
            "action": action.name,
            "is_action_layered": bool(action.is_action_layered)
            if hasattr(action, "is_action_layered") else None,
            "action_use_cyclic": bool(action.use_cyclic)
            if hasattr(action, "use_cyclic") else None,
            "action_frame_range": [float(action.frame_start), float(action.frame_end)],
            "curve_frames": curve_samples,
            "endpoint_frames": list(endpoints),
            "fcurve_count": len(curves),
            "cycles_modifier_count": cycles,
            "max_endpoint_error": max(endpoint_errors) if endpoint_errors else None,
            "curves": rows,
            "scene_range": [int(scene.frame_start), int(scene.frame_end)],
            "scene_fps": float(scene.render.fps),
        }

    if rig is not None and bones:
        max_joint_gap = max(
            (gap for rows in chain_gaps.values() for gap in rows.values()),
            default=0.0,
        )
    else:
        max_joint_gap = None

    scene.frame_set(final_frame)
    bpy.context.view_layer.update()
    return {
        "object_names": names,
        "frame_start": start,
        "frame_end": end,
        "current_frame": int(scene.frame_current),
        "sample_frames": sorted(int(frame) for frame in wanted),
        "reference_frame": reference,
        "samples": samples,
        "contact_pairs": [list(pair) for pair in pairs],
        "contacts": contacts,
        "chain_bones": list(bones),
        "bone_inventory_names": list(inventory_bones),
        "bone_inventory": bone_inventory,
        "chain_joint_gaps_world": chain_gaps,
        "max_chain_joint_gap": max_joint_gap,
        "bindings": binding_report,
        "curve_audit": curve_report,
        "projection_view": projection_view,
    }
