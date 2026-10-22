"""Subject-neutral rigid IK calibration helpers.

The builder can provide measured world-space joint landmarks and a finite set of
pole controls/angles; :func:`solve_ik_landmarks` evaluates Blender's actual IK
solver from a repeatable pose seed, chooses the best control, and leaves it live.
It is intentionally a calibration helper, not an object-specific rig builder.

Inside Blender:

    from rig import solve_ik_landmarks
    result = solve_ik_landmarks(
        rig_name="Rig", constraint_name="IK_Target",
        target_name="IK_Target", pole_name="IK_Pole",
        chain_bones=("upper", "middle", "lower"),
        landmarks=(root, elbow, wrist, target),
        pole_candidates=((0, -0.02, 0), (0, -0.05, 0)),
        pole_angles_deg=range(-180, 181, 5),
        seed_mode="landmarks",
    )

All points and pole candidates are world-space. The function does not create
objects or edit mesh data; it changes only the named target/pole, constraint,
and pose-bone state needed to evaluate and apply the winning control.
"""

from __future__ import annotations

import math


def _vector(value):
    from mathutils import Vector

    return value.copy() if isinstance(value, Vector) else Vector(value)


def _list_vector(value):
    return [float(c) for c in _vector(value)]


def _set_world_location(obj, point):
    """Move an object in world space while preserving its other matrix terms."""
    matrix = obj.matrix_world.copy()
    matrix.translation = _vector(point)
    obj.matrix_world = matrix


def _world_point(rig, pose_bone, end):
    return rig.matrix_world @ (pose_bone.head if end == "head" else pose_bone.tail)


def _segment_matrix(rig, head_world, tail_world):
    """Return an armature-space pose matrix for a world-space segment."""
    from mathutils import Matrix

    inverse = rig.matrix_world.inverted_safe()
    head = inverse @ _vector(head_world)
    tail = inverse @ _vector(tail_world)
    direction = tail - head
    if direction.length <= 1.0e-10:
        raise ValueError("landmark segment has zero length")
    rotation = direction.normalized().to_track_quat("Y", "Z").to_matrix().to_4x4()
    return Matrix.Translation(head) @ rotation


def _reset_seed(rig, ik, landmarks, chain_bones, seed_mode):
    """Reset every pose bone and optionally author the measured seed pose."""
    from mathutils import Matrix
    import bpy

    ik.influence = 0.0
    for pose_bone in rig.pose.bones:
        pose_bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()

    if seed_mode == "rest":
        return
    if seed_mode != "landmarks":
        raise ValueError("seed_mode must be 'rest' or 'landmarks'")

    for name, head, tail in zip(chain_bones, landmarks[:-1], landmarks[1:]):
        rig.pose.bones[name].matrix = _segment_matrix(rig, head, tail)
        bpy.context.view_layer.update()


def _axis_snapshot(axis_checks):
    """Read configured object axes and return (json values, squared error, tilt)."""
    from mathutils import Vector
    import bpy

    values = {}
    total_error = 0.0
    total_tilt = 0.0
    for check in axis_checks:
        name = check.get("object_name", check.get("object"))
        if not name:
            raise ValueError("each axis check needs object_name")
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise KeyError("axis-check object not found: %s" % name)
        local_axis = _vector(check.get("local_axis", (0.0, 0.0, 1.0)))
        target_axis = _vector(check.get("target_axis", (0.0, 0.0, 1.0)))
        if local_axis.length <= 1.0e-10 or target_axis.length <= 1.0e-10:
            raise ValueError("axis-check vectors must be non-zero")
        local_axis.normalize()
        target_axis.normalize()
        world_axis = (obj.matrix_world.to_3x3() @ local_axis).normalized()
        error = (world_axis - target_axis).length_squared
        dot = max(-1.0, min(1.0, world_axis.dot(target_axis)))
        tilt = math.degrees(math.acos(dot))
        weight = float(check.get("weight", 1.0))
        total_error += weight * error
        total_tilt += weight * tilt
        values[name] = {
            "axis": _list_vector(world_axis),
            "target_axis": _list_vector(target_axis),
            "tilt_deg": float(tilt),
            "squared_error": float(error),
        }
    return values, total_error, total_tilt


def _state(rig, chain_bones, landmarks, axis_checks):
    """Read evaluated chain endpoints and configured orientation checks."""
    from mathutils import Vector

    first = rig.pose.bones[chain_bones[0]]
    actual = [_world_point(rig, first, "head")]
    for name in chain_bones:
        actual.append(_world_point(rig, rig.pose.bones[name], "tail"))
    joint_errors = [
        (got - want).length for got, want in zip(actual[1:], landmarks[1:])
    ]
    axis_values, axis_error, axis_tilt = _axis_snapshot(axis_checks)
    return {
        "landmarks": [_list_vector(point) for point in actual],
        "joint_errors": [float(error) for error in joint_errors],
        "root_error": float((actual[0] - landmarks[0]).length),
        "head_target_error": float((actual[-1] - landmarks[-1]).length),
        "axis_checks": axis_values,
        "axis_error": float(axis_error),
        "axis_tilt_deg": float(axis_tilt),
    }


def _candidate_label(item, index):
    if isinstance(item, dict):
        label = item.get("label", "pole_%03d" % index)
        point = item.get("world", item.get("location"))
        if point is None:
            raise ValueError("pole candidate dict needs world or location")
        return str(label), _vector(point)
    if isinstance(item, (tuple, list)) and len(item) == 2 and isinstance(item[0], str):
        return item[0], _vector(item[1])
    return "pole_%03d" % index, _vector(item)


def _row(label, pole, angle_deg, score, state):
    return {
        "candidate": label,
        "pole": _list_vector(pole),
        "pole_angle_deg": float(angle_deg),
        "score": float(score),
        "landmarks": state["landmarks"],
        "joint_errors": state["joint_errors"],
        "root_error": state["root_error"],
        "head_target_error": state["head_target_error"],
        "axis_checks": state["axis_checks"],
        "axis_error": state["axis_error"],
        "axis_tilt_deg": state["axis_tilt_deg"],
    }


def _within_limits(errors, limits):
    if limits is None:
        return True
    for error, limit in zip(errors, limits):
        if limit is not None and error > float(limit):
            return False
    return True


def _restore_pose(rig, ik, target, pole, chain_bones, landmarks,
                  seed_mode, pole_world, angle_deg):
    import bpy

    _reset_seed(rig, ik, landmarks, chain_bones, seed_mode)
    _set_world_location(pole, pole_world)
    ik.pole_angle = math.radians(float(angle_deg))
    ik.influence = 1.0
    bpy.context.view_layer.update()


def solve_ik_landmarks(
    rig_name,
    constraint_name,
    target_name,
    pole_name,
    chain_bones,
    landmarks,
    pole_candidates,
    pole_angles_deg,
    *,
    seed_mode="landmarks",
    reset_each=True,
    joint_weights=None,
    axis_checks=(),
    axis_weight=0.0,
    selection="min_score",
    joint_error_limits=None,
    front_y_lt=None,
    top_n=10,
):
    """Search a rigid IK control against measured world-space landmarks.

    ``chain_bones`` is ordered from the root-side bone to the target-side bone,
    and ``landmarks`` contains one more point than that list: the shared root
    followed by each successive tail. The target is set to the last landmark.
    ``pole_candidates`` and ``pole_angles_deg`` are finite search inputs; pole
    positions are world-space and angles are degrees.

    ``seed_mode='landmarks'`` mutes IK, resets every pose bone, authors the
    requested landmark chain directly, and repeats that seed before each
    candidate. This is the safe mode for alternate Blender IK branches.
    ``seed_mode='rest'`` uses identity pose bones instead. ``reset_each=False``
    is available for diagnostic experiments, but should not be used to compare
    independent candidates.

    ``joint_weights`` weights squared errors for the chain tails; its default is
    one per tail. ``axis_checks`` optionally adds orientation observations such
    as ``{"object_name": "Handle", "local_axis": (0,0,1),
    "target_axis": (0,0,1)}``. ``axis_weight`` adds their weighted squared
    vector error to the score, while the orientation values are also reported.

    With ``selection='min_score'`` the lowest score wins; when ``front_y_lt`` is
    supplied, the lowest score on that side wins if any candidate satisfies it.
    With ``selection='axis_within_joint_limits'``, the lowest total axis tilt
    among candidates satisfying ``joint_error_limits`` and ``front_y_lt`` wins; if
    none qualifies, the best front-side score, then the best overall score, is
    used. ``front_y_lt`` is an optional strict world-Y pole-side rule.

    The return value is JSON-serializable and includes the best overall, best
    filtered, best axis-qualified, top-ranked, and final evaluated states. The
    winning target/pole/angle and IK influence are left live. No mesh data,
    objects, or modifiers are created or edited.
    """
    import bpy

    from mathutils import Vector

    rig = bpy.data.objects.get(rig_name)
    target = bpy.data.objects.get(target_name)
    pole = bpy.data.objects.get(pole_name)
    if rig is None or rig.type != "ARMATURE":
        raise KeyError("armature not found: %s" % rig_name)
    if target is None:
        raise KeyError("IK target not found: %s" % target_name)
    if pole is None:
        raise KeyError("IK pole not found: %s" % pole_name)

    chain_bones = tuple(chain_bones)
    landmarks = tuple(_vector(point) for point in landmarks)
    if not chain_bones or len(landmarks) != len(chain_bones) + 1:
        raise ValueError("landmarks must contain len(chain_bones)+1 points")
    for name in chain_bones:
        if rig.pose.bones.get(name) is None:
            raise KeyError("chain bone not found: %s" % name)

    matches = []
    for pose_bone in rig.pose.bones:
        for constraint in pose_bone.constraints:
            if constraint.name == constraint_name:
                matches.append((pose_bone, constraint))
    if len(matches) != 1:
        raise ValueError("expected one constraint named %s, found %d" %
                         (constraint_name, len(matches)))
    constraint_bone, ik = matches[0]
    if ik.type != "IK":
        raise TypeError("constraint %s is not IK" % constraint_name)

    candidates = [_candidate_label(item, index)
                  for index, item in enumerate(pole_candidates)]
    angles = [float(angle) for angle in pole_angles_deg]
    if not candidates or not angles:
        raise ValueError("pole_candidates and pole_angles_deg must be non-empty")
    if seed_mode not in ("rest", "landmarks"):
        raise ValueError("seed_mode must be 'rest' or 'landmarks'")
    if selection not in ("min_score", "axis_within_joint_limits"):
        raise ValueError("unknown selection mode: %s" % selection)

    if joint_weights is None:
        weights = [1.0] * len(chain_bones)
    else:
        weights = [float(weight) for weight in joint_weights]
        if len(weights) != len(chain_bones):
            raise ValueError("joint_weights must match chain_bones")
    if joint_error_limits is not None:
        limits = tuple(joint_error_limits)
        if len(limits) > len(chain_bones):
            raise ValueError("joint_error_limits cannot exceed chain_bones")
        limits = limits + (None,) * (len(chain_bones) - len(limits))
    else:
        limits = None
    axis_checks = tuple(dict(check) for check in axis_checks)
    axis_weight = float(axis_weight)
    top_n = max(0, int(top_n))

    original_basis = {pose_bone.name: pose_bone.matrix_basis.copy()
                      for pose_bone in rig.pose.bones}
    original_influence = float(ik.influence)
    original_target = ik.target
    original_pole_target = ik.pole_target
    original_chain_count = int(ik.chain_count)
    original_pole_angle = float(ik.pole_angle)
    original_target_world = target.matrix_world.translation.copy()
    original_pole_world = pole.matrix_world.translation.copy()

    def restore_original():
        for pose_bone in rig.pose.bones:
            pose_bone.matrix_basis = original_basis[pose_bone.name]
        _set_world_location(target, original_target_world)
        _set_world_location(pole, original_pole_world)
        ik.target = original_target
        ik.pole_target = original_pole_target
        ik.chain_count = original_chain_count
        ik.pole_angle = original_pole_angle
        ik.influence = original_influence
        bpy.context.view_layer.update()

    try:
        _set_world_location(target, landmarks[-1])
        ik.target = target
        ik.pole_target = pole
        ik.chain_count = len(chain_bones)

        best_any = None
        best_front = None
        best_axis = None
        rows = []
        evaluations = 0
        for label, pole_world in candidates:
            for angle_deg in angles:
                if reset_each:
                    _reset_seed(rig, ik, landmarks, chain_bones, seed_mode)
                _set_world_location(pole, pole_world)
                ik.pole_angle = math.radians(angle_deg)
                ik.influence = 1.0
                bpy.context.view_layer.update()
                measured = _state(rig, chain_bones, landmarks, axis_checks)
                joint_score = sum(weight * error * error
                                  for weight, error in zip(weights, measured["joint_errors"]))
                score = joint_score + axis_weight * measured["axis_error"]
                candidate_row = _row(label, pole_world, angle_deg, score, measured)
                evaluations += 1
                if best_any is None or score < best_any["score"]:
                    best_any = candidate_row
                is_front = (front_y_lt is None or
                             pole_world.y < float(front_y_lt))
                if is_front and (best_front is None or score < best_front["score"]):
                    best_front = candidate_row
                qualifies = (is_front and
                             _within_limits(measured["joint_errors"], limits))
                if qualifies and (best_axis is None or
                                  measured["axis_tilt_deg"] < best_axis["axis_tilt_deg"]):
                    best_axis = candidate_row
                if top_n:
                    rows.append(candidate_row)

        if selection == "axis_within_joint_limits":
            chosen = best_axis or best_front or best_any
        elif front_y_lt is not None:
            # A min-score caller that specifies a side still gets that side when
            # available; otherwise the search remains useful and falls back.
            chosen = best_front or best_any
        else:
            chosen = best_any

        if chosen is None:
            raise RuntimeError("IK search produced no evaluated state")
        _restore_pose(rig, ik, target, pole, chain_bones, landmarks,
                      seed_mode, chosen["pole"], chosen["pole_angle_deg"])
        final_state = _state(rig, chain_bones, landmarks, axis_checks)
        ranked = sorted(rows, key=lambda row: row["score"])
        return {
            "rig_name": rig.name,
            "constraint_name": constraint_name,
            "constraint_bone": constraint_bone.name,
            "target_name": target.name,
            "pole_name": pole.name,
            "chain_bones": list(chain_bones),
            "desired_landmarks": [_list_vector(point) for point in landmarks],
            "seed_mode": seed_mode,
            "reset_each": bool(reset_each),
            "joint_weights": weights,
            "axis_weight": axis_weight,
            "selection": selection,
            "joint_error_limits": list(limits) if limits is not None else None,
            "front_y_lt": front_y_lt,
            "candidate_count": len(candidates),
            "angle_count": len(angles),
            "evaluations": evaluations,
            "best_any": best_any,
            "best_front": best_front,
            "best_axis": best_axis,
            "chosen": chosen,
            "top_candidates": ranked[:top_n],
            "final_pole": _list_vector(pole.matrix_world.translation),
            "final_pole_angle_deg": float(math.degrees(ik.pole_angle)),
            "final_state": final_state,
        }
    except Exception:
        restore_original()
        raise


def pose_landmark_report(rig_name, landmarks, *, world_points=None,
                         camera_name=None, resolution=None, target_norm=None,
                         target_pixels=None, tolerance=None, relationships=None,
                         distances=None, mesh_gaps=None, mesh_groups=None):
    """Report named bone/world landmarks in one consistent camera frame.

    ``landmarks`` is an ordered mapping from report labels to either
    ``(bone_name, 'head'|'tail')`` or ``{'bone': ..., 'end': ...}``.  The
    optional ``world_points`` mapping adds caller-defined points, such as a
    support corner, without assuming anything about the subject.  All points
    are returned in world space and projected through the selected camera as
    top-left normalized coordinates and pixels.  ``resolution`` defaults to
    the scene render resolution and does not change it.

    ``target_norm`` and ``target_pixels`` are mutually exclusive target maps;
    targets use the same labels as the points.  Targets are image-space with
    Y down.  ``tolerance`` is an optional normalized Euclidean tolerance, or a
    mapping of label to tolerance.  The report includes per-point residuals
    plus normalized coordinate and Euclidean RMS summaries.

    ``relationships`` maps a report label to a pair of point labels, or to a
    dict with ``start``/``end`` (``from``/``to`` are accepted aliases).  A
    dict may also supply ``numerator_axis`` and ``denominator_axis`` (one of
    ``x``, ``y`` or ``z``), in which case the absolute component ratio is
    reported.  ``distances`` maps labels to point pairs and reports world
    distances.  ``mesh_gaps`` maps labels to pairs of mesh object names and
    reports the minimum evaluated-vertex distance.  ``mesh_groups`` is an
    optional mapping passed to :func:`projection.projected_group_bounds`, so
    evaluated world and camera envelopes can be collected in the same audit.

    This is read-only: it updates the dependency graph for evaluated reads but
    changes no pose, camera, mesh, material, constraint, or render state.  The
    caller owns all names, measurements, and acceptance thresholds; no
    subject-specific landmark or dimension is embedded here.
    """
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector

    rig = bpy.data.objects.get(rig_name)
    if rig is None or rig.type != "ARMATURE":
        raise KeyError("armature not found: %s" % rig_name)
    if not isinstance(landmarks, dict) or not landmarks:
        raise ValueError("landmarks must be a non-empty mapping")
    if target_norm is not None and target_pixels is not None:
        raise ValueError("target_norm and target_pixels are mutually exclusive")
    if world_points is not None and not isinstance(world_points, dict):
        raise TypeError("world_points must be a mapping")

    scene = bpy.context.scene
    cam = (bpy.data.objects.get(camera_name) if camera_name else scene.camera)
    if cam is None or cam.type != "CAMERA":
        raise KeyError("camera not found: %s" % (camera_name or "scene.camera"))
    if resolution is None:
        width, height = int(scene.render.resolution_x), int(scene.render.resolution_y)
    else:
        if len(resolution) != 2:
            raise ValueError("resolution must be (width, height)")
        width, height = int(resolution[0]), int(resolution[1])
    if width < 1 or height < 1:
        raise ValueError("resolution must be positive")

    def point_spec(spec):
        if isinstance(spec, dict):
            bone_name = spec.get("bone")
            end = spec.get("end", "head")
        elif isinstance(spec, (tuple, list)) and len(spec) == 2:
            bone_name, end = spec
        else:
            raise TypeError("landmark specs must be (bone, end) or a dict")
        if not bone_name:
            raise ValueError("landmark spec is missing bone")
        if end not in ("head", "tail"):
            raise ValueError("landmark end must be 'head' or 'tail'")
        pose_bone = rig.pose.bones.get(str(bone_name))
        if pose_bone is None:
            raise KeyError("bone not found: %s" % bone_name)
        return rig.matrix_world @ getattr(pose_bone, end), {
            "bone": str(bone_name), "end": str(end)
        }

    points = {}
    sources = {}
    for label, spec in landmarks.items():
        key = str(label)
        if key in points:
            raise ValueError("duplicate landmark label: %s" % key)
        points[key], sources[key] = point_spec(spec)
    for label, value in (world_points or {}).items():
        key = str(label)
        if key in points:
            raise ValueError("world point duplicates landmark: %s" % key)
        points[key] = Vector(value)
        sources[key] = {"world_point": True}

    def target_value(mapping, label):
        if mapping is None or label not in mapping:
            return None
        value = mapping[label]
        if len(value) != 2:
            raise ValueError("target for %s must contain two values" % label)
        return (float(value[0]), float(value[1]))

    normalized_targets = {}
    if target_norm is not None:
        normalized_targets = {
            str(label): target_value(target_norm, label)
            for label in target_norm
        }
    elif target_pixels is not None:
        for label in target_pixels:
            px = target_value(target_pixels, label)
            normalized_targets[str(label)] = (px[0] / width, px[1] / height)
    unknown_targets = sorted(set(normalized_targets) - set(points))
    if unknown_targets:
        raise KeyError("targets reference unknown points: %s" % unknown_targets)

    scene.view_layers[0].update()
    projection = {}
    residuals = []
    for label, point in points.items():
        q = world_to_camera_view(scene, cam, point)
        uv = (float(q.x), float(1.0 - q.y))
        px = (uv[0] * width, uv[1] * height)
        row = {
            "source": sources[label],
            "world": [float(v) for v in point],
            "uv_top_left": [uv[0], uv[1]],
            "px": [px[0], px[1]],
            "camera_depth": float(q.z),
            "in_front": bool(float(q.z) >= 0.0),
        }
        target = normalized_targets.get(label)
        if target is not None:
            du, dv = uv[0] - target[0], uv[1] - target[1]
            euclidean = math.sqrt(du * du + dv * dv)
            row.update({
                "target_uv_top_left": [target[0], target[1]],
                "error_uv": [du, dv],
                "error_euclidean": euclidean,
                "error_px": [du * width, dv * height],
            })
            if tolerance is not None:
                limit = (tolerance.get(label) if isinstance(tolerance, dict)
                         else tolerance)
                if limit is not None:
                    row["within_tolerance"] = euclidean <= float(limit)
            residuals.append((du, dv))
        projection[label] = row

    def pair_spec(spec, kind):
        if isinstance(spec, dict):
            first = spec.get("start", spec.get("from", spec.get("a")))
            second = spec.get("end", spec.get("to", spec.get("b")))
        elif isinstance(spec, (tuple, list)) and len(spec) == 2:
            first, second = spec
        else:
            raise TypeError("%s specs must be a pair or a dict" % kind)
        if str(first) not in points or str(second) not in points:
            raise KeyError("%s references an unknown point" % kind)
        return str(first), str(second)

    axis_index = {"x": 0, "y": 1, "z": 2}
    relationship_report = {}
    for label, spec in (relationships or {}).items():
        start, end = pair_spec(spec, "relationship")
        delta = points[end] - points[start]
        row = {
            "start": start,
            "end": end,
            "delta_world": [float(v) for v in delta],
            "length_world": float(delta.length),
        }
        if isinstance(spec, dict):
            numerator = spec.get("numerator_axis", spec.get("numerator"))
            denominator = spec.get("denominator_axis", spec.get("denominator"))
            if numerator is not None or denominator is not None:
                if numerator not in axis_index or denominator not in axis_index:
                    raise ValueError("relationship axes must be x, y, or z")
                denominator_value = abs(float(delta[axis_index[denominator]]))
                row.update({
                    "numerator_axis": numerator,
                    "denominator_axis": denominator,
                    "ratio": abs(float(delta[axis_index[numerator]])) /
                             max(denominator_value, 1.0e-12),
                })
        relationship_report[str(label)] = row

    distance_report = {}
    for label, spec in (distances or {}).items():
        start, end = pair_spec(spec, "distance")
        distance_report[str(label)] = {
            "start": start,
            "end": end,
            "distance_world": float((points[end] - points[start]).length),
        }

    def evaluated_vertices(name):
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise KeyError("mesh not found: %s" % name)
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            return [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        finally:
            evaluated.to_mesh_clear()

    gap_report = {}
    for label, spec in (mesh_gaps or {}).items():
        if isinstance(spec, dict):
            first = spec.get("object_a", spec.get("a"))
            second = spec.get("object_b", spec.get("b"))
        elif isinstance(spec, (tuple, list)) and len(spec) == 2:
            first, second = spec
        else:
            raise TypeError("mesh gap specs must be a pair or a dict")
        if not first or not second:
            raise ValueError("mesh gap spec needs two object names")
        first_points = evaluated_vertices(str(first))
        second_points = evaluated_vertices(str(second))
        if not first_points or not second_points:
            raise ValueError("mesh gap objects must contain vertices")
        minimum = min((a - b).length for a in first_points for b in second_points)
        gap_report[str(label)] = {
            "object_a": str(first),
            "object_b": str(second),
            "vertex_count_a": len(first_points),
            "vertex_count_b": len(second_points),
            "distance_world": float(minimum),
        }

    report = {
        "rig_name": rig.name,
        "camera_name": cam.name,
        "resolution": [width, height],
        "projection": projection,
        "target_labels": sorted(normalized_targets),
        "target_summary": None,
        "relationships": relationship_report,
        "distances": distance_report,
        "mesh_gaps": gap_report,
    }
    if residuals:
        coord_rms = math.sqrt(sum(dx * dx + dy * dy for dx, dy in residuals) /
                              (2.0 * len(residuals)))
        euclidean_rms = math.sqrt(sum(dx * dx + dy * dy for dx, dy in residuals) /
                                  len(residuals))
        summary = {
            "count": len(residuals),
            "coordinate_rmse_norm": float(coord_rms),
            "corner_euclidean_rmse_norm": float(euclidean_rms),
            "max_euclidean_norm": max(
                math.sqrt(dx * dx + dy * dy) for dx, dy in residuals
            ),
        }
        if tolerance is not None:
            summary["all_within_tolerance"] = all(
                row.get("within_tolerance", False)
                for row in projection.values()
                if "within_tolerance" in row
            )
        report["target_summary"] = summary

    if mesh_groups is not None:
        from projection import projected_group_bounds
        report["mesh_groups"] = projected_group_bounds(
            mesh_groups, camera_name=cam.name, resolution=(width, height)
        )
    return report
