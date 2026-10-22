"""Perspective projection utilities for measured image landmarks.

The helpers here are deliberately independent of any model or subject.  They
fit a camera's pose that the caller has chosen, then calibrate Blender's lens
shift against the actual ``world_to_camera_view`` response instead of relying
on a sensor convention remembered from elsewhere.
"""

import math

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Quaternion, Vector



def fit_landmarks(world_points, target_pixels, location, forward, lens,
                  roll_deg=0.0, resolution=(1024, 1024), camera_name=None,
                  shift_probe=0.01):
    """Fit an active perspective camera to named world/image landmarks.

    ``world_points`` and ``target_pixels`` may be dictionaries with the same
    keys (the key order is used in the report), or equal-length sequences.  A
    target pixel uses the image convention: origin at the top-left, Y down.
    ``location`` and ``forward`` are world-space values.  ``forward`` is the
    direction the camera's local ``-Z`` axis must point along; it is a
    direction, not a point to pass to ``to_track_quat``.

    The function applies ``location``, the tracked orientation, ``lens`` and
    ``roll_deg`` to the selected camera.  It probes both lens-shift axes at
    ``shift_probe`` and solves the constant pixel offset from the measured
    response.  It returns unshifted/projected landmarks, both RMS conventions,
    the pixel bbox, and a local-``-Z`` direction check.  No render is needed.
    """
    scene = bpy.context.scene
    cam = (bpy.data.objects.get(camera_name) if camera_name else scene.camera)
    if cam is None or cam.type != 'CAMERA':
        raise ValueError("fit_landmarks: selected camera does not exist")
    if abs(float(shift_probe)) < 1e-12:
        raise ValueError("fit_landmarks: shift_probe must be non-zero")

    if isinstance(world_points, dict):
        names = list(world_points)
        if not isinstance(target_pixels, dict):
            raise TypeError("fit_landmarks: both landmark arguments must be dicts")
        missing = [n for n in names if n not in target_pixels]
        if missing:
            raise ValueError("fit_landmarks: target_pixels missing %s" % missing)
        points = [world_points[n] for n in names]
        targets = [target_pixels[n] for n in names]
    else:
        points = list(world_points)
        targets = list(target_pixels)
        if len(points) != len(targets):
            raise ValueError("fit_landmarks: world/target landmark count differs")
        names = [str(i) for i in range(len(points))]
    if len(points) < 2:
        raise ValueError("fit_landmarks: at least two landmarks are required")

    width, height = (int(resolution[0]), int(resolution[1]))
    if width < 1 or height < 1:
        raise ValueError("fit_landmarks: resolution must be positive")
    fwd = Vector(forward)
    if fwd.length < 1e-12:
        raise ValueError("fit_landmarks: forward direction must be non-zero")
    fwd.normalize()

    cam.location = Vector(location)
    cam.rotation_mode = 'QUATERNION'
    # The roll axis is the camera's local viewing axis.  Multiplying after the
    # track quaternion matches Blender's local-axis roll convention.
    q_track = fwd.to_track_quat('-Z', 'Y')
    cam.rotation_quaternion = q_track @ Quaternion(
        (0.0, 0.0, 1.0), math.radians(float(roll_deg)))
    cam.data.lens = float(lens)

    def project():
        scene.view_layers[0].update()
        out = []
        for co in points:
            p = world_to_camera_view(scene, cam, Vector(co))
            out.append((float(p.x) * width, (1.0 - float(p.y)) * height))
        return out

    # Lens shift is affine in image space, but its scale/sign depends on the
    # active camera sensor and render aspect.  Measure it in this scene rather
    # than baking a generic conversion into every caller.
    cam.data.shift_x = 0.0
    cam.data.shift_y = 0.0
    base = project()
    probe = float(shift_probe)
    cam.data.shift_x = probe
    x_probe = project()
    cam.data.shift_x = 0.0
    cam.data.shift_y = probe
    y_probe = project()
    ax = sum((x_probe[i][0] - base[i][0]) / probe
             for i in range(len(points))) / len(points)
    ay = sum((y_probe[i][1] - base[i][1]) / probe
             for i in range(len(points))) / len(points)
    if abs(ax) < 1e-12 or abs(ay) < 1e-12:
        raise RuntimeError("fit_landmarks: camera shift response is degenerate")

    cam.data.shift_x = sum(float(targets[i][0]) - base[i][0]
                           for i in range(len(points))) / len(points) / ax
    cam.data.shift_y = sum(float(targets[i][1]) - base[i][1]
                           for i in range(len(points))) / len(points) / ay
    pred = project()
    residual = [(pred[i][0] - float(targets[i][0]),
                 pred[i][1] - float(targets[i][1]))
                for i in range(len(points))]

    bbox = [min(p[0] for p in pred), min(p[1] for p in pred),
            max(p[0] for p in pred), max(p[1] for p in pred)]
    coordinate_rmse = math.sqrt(
        sum(dx * dx + dy * dy for dx, dy in residual) /
        (2.0 * len(residual)))
    corner_rmse = math.sqrt(
        sum(dx * dx + dy * dy for dx, dy in residual) /
        len(residual))
    actual_forward = cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
    actual_forward.normalize()

    return {
        "camera_name": cam.name,
        "resolution": [width, height],
        "landmarks": names,
        "camera_location": [float(v) for v in cam.location],
        "lens_mm": float(cam.data.lens),
        "roll_deg": float(roll_deg),
        "shift": [float(cam.data.shift_x), float(cam.data.shift_y)],
        "shift_response_px_per_unit": [float(ax), float(ay)],
        "forward_requested_world": [float(v) for v in fwd],
        "forward_minus_z_world": [float(v) for v in actual_forward],
        "forward_error": float((actual_forward - fwd).length),
        "unshifted_projection_px": {
            n: [base[i][0], base[i][1]] for i, n in enumerate(names)},
        "target_px": {
            n: [float(targets[i][0]), float(targets[i][1])]
            for i, n in enumerate(names)},
        "projected_px": {
            n: [pred[i][0], pred[i][1]] for i, n in enumerate(names)},
        "residual_px": {
            n: [residual[i][0], residual[i][1]]
            for i, n in enumerate(names)},
        "coordinate_rmse_px": float(coordinate_rmse),
        "corner_euclidean_rmse_px": float(corner_rmse),
        "rmse_px": float(coordinate_rmse),
        "bbox_px": [float(v) for v in bbox],
    }


def projected_group_bounds(groups, camera_name=None, resolution=None):
    """Measure evaluated mesh groups in the active camera's pixel space.

    ``groups`` is a non-empty mapping from an arbitrary report label to one
    mesh name or an iterable of mesh names.  Each group's evaluated vertices
    are projected with :func:`world_to_camera_view` and reported as a
    continuous ``[left, top, right, bottom]`` box in image pixels (origin at
    the top-left).  The report also includes the evaluated world-space box,
    vertex count, and camera-space depth range, so a caller can distinguish an
    off-frame/behind-camera result from a genuinely small mesh.  A group may
    contain several separate objects; their envelopes are unioned.

    ``resolution`` defaults to the active scene render resolution and is a
    ``(width, height)`` pair when supplied.  The function is read-only: it
    updates the dependency graph to obtain modifier-evaluated geometry but
    does not change objects, camera data, or render settings.  Names, labels,
    camera, and resolution are all parameters; no subject-specific convention
    is embedded here.
    """
    if not isinstance(groups, dict) or not groups:
        raise ValueError("projected_group_bounds: groups must be a non-empty mapping")

    scene = bpy.context.scene
    cam = (bpy.data.objects.get(camera_name) if camera_name else scene.camera)
    if cam is None or cam.type != "CAMERA":
        raise ValueError("projected_group_bounds: selected camera does not exist")

    if resolution is None:
        width, height = int(scene.render.resolution_x), int(scene.render.resolution_y)
    else:
        if len(resolution) != 2:
            raise ValueError("projected_group_bounds: resolution must be (width, height)")
        width, height = (int(resolution[0]), int(resolution[1]))
    if width < 1 or height < 1:
        raise ValueError("projected_group_bounds: resolution must be positive")

    scene.view_layers[0].update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    point_cache = {}

    def world_points(name):
        if name in point_cache:
            return point_cache[name]
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise ValueError("projected_group_bounds: mesh %r does not exist" % name)
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        finally:
            evaluated.to_mesh_clear()
        if not points:
            raise ValueError("projected_group_bounds: mesh %r has no vertices" % name)
        point_cache[name] = points
        return points

    report_groups = {}
    for label, members in groups.items():
        names = [members] if isinstance(members, str) else list(members)
        if not names:
            raise ValueError("projected_group_bounds: group %r has no meshes" % label)
        points = [point for name in names for point in world_points(name)]
        projected = [world_to_camera_view(scene, cam, point) for point in points]
        px = [(float(q.x) * width, (1.0 - float(q.y)) * height)
              for q in projected]
        report_groups[str(label)] = {
            "objects": [str(name) for name in names],
            "vertex_count": len(points),
            "in_front_count": sum(1 for q in projected if float(q.z) >= 0.0),
            "depth_range": [min(float(q.z) for q in projected),
                            max(float(q.z) for q in projected)],
            "world_bbox": {
                "min": [min(float(point[i]) for point in points) for i in range(3)],
                "max": [max(float(point[i]) for point in points) for i in range(3)],
            },
            "bbox_px": [min(point[0] for point in px),
                        min(point[1] for point in px),
                        max(point[0] for point in px),
                        max(point[1] for point in px)],
        }

    return {
        "camera_name": cam.name,
        "resolution": [width, height],
        "groups": report_groups,
    }


def fit_envelope(obj_names, target_bbox_px, target=(0.0, 0.0, 0.0),
                 distance=10.0, azimuth=270.0, elevation=0.0, lens=50.0,
                 resolution=(1024, 1024), camera_name=None,
                 shift_probe=0.01, fit_width=False,
                 fit_shift=(True, True)):
    """Fit an active perspective camera to an evaluated mesh envelope.

    ``obj_names`` may be one mesh name or a sequence of names.  The target
    envelope is ``(left, top, right, bottom)`` in continuous image pixels
    (origin at the top-left); it is not an inclusive pixel-count tuple.
    ``target``, ``distance``, ``azimuth`` and ``elevation`` describe the
    camera pose using the same spherical convention as ``lighting.spherical``.
    ``lens`` is kept when ``fit_width`` is false.  When ``fit_width`` is true,
    it is the positive starting lens and is scaled from the measured
    unshifted envelope until its width matches the requested width.  In both
    modes the function measures Blender's actual lens-shift response and
    solves the horizontal and vertical frame offsets rather than assuming a
    sensor convention.  ``fit_shift=(True, False)`` is useful when the
    vertical fit is intentionally left at the existing zero shift.

    The camera pose and render resolution are applied to the scene.  The mesh
    is only read in its evaluated world-space form, so this helper never edits
    geometry.  The return value contains the unshifted and final envelopes,
    size/centre errors, lens-shift response, and a local ``-Z`` direction check.
    ``distance`` and ``elevation`` remain caller parameters because a target
    envelope alone cannot decide how much perspective depth distortion is
    acceptable for a particular object.
    """
    scene = bpy.context.scene
    if isinstance(obj_names, str):
        names = [obj_names]
    else:
        names = list(obj_names)
    if not names:
        raise ValueError("fit_envelope: at least one mesh name is required")

    if len(target_bbox_px) != 4:
        raise ValueError("fit_envelope: target_bbox_px must be (left, top, right, bottom)")
    x0, y0, x1, y1 = (float(v) for v in target_bbox_px)
    if not (x1 > x0 and y1 > y0):
        raise ValueError("fit_envelope: target_bbox_px must have positive width and height")

    width, height = (int(resolution[0]), int(resolution[1]))
    if width < 1 or height < 1:
        raise ValueError("fit_envelope: resolution must be positive")
    if distance <= 0.0:
        raise ValueError("fit_envelope: distance must be positive")
    if abs(float(shift_probe)) < 1.0e-12:
        raise ValueError("fit_envelope: shift_probe must be non-zero")
    if lens <= 0.0:
        raise ValueError("fit_envelope: lens must be positive")
    if len(fit_shift) != 2:
        raise ValueError("fit_envelope: fit_shift must be (horizontal, vertical)")

    cam = (bpy.data.objects.get(camera_name) if camera_name else scene.camera)
    if cam is None or cam.type != 'CAMERA':
        raise ValueError("fit_envelope: selected camera does not exist")

    # Resolution is part of the projection contract: world_to_camera_view uses
    # the active scene settings when its normalized result becomes pixels.
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100

    from mathutils import Vector
    focus = Vector(target)
    a = math.radians(float(azimuth))
    e = math.radians(float(elevation))
    cam.location = focus + Vector((
        math.cos(a) * math.cos(e) * float(distance),
        math.sin(a) * math.cos(e) * float(distance),
        math.sin(e) * float(distance),
    ))
    cam.rotation_mode = 'XYZ'
    cam.rotation_euler = (focus - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = float(lens)
    scene.camera = cam

    # Snapshot evaluated world vertices once.  This makes every projection
    # comparison below use the same mesh even if a caller has modifiers.
    scene.view_layers[0].update()
    points = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != 'MESH':
            raise ValueError("fit_envelope: mesh %r does not exist" % name)
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            world = evaluated.matrix_world
            points.extend(world @ vertex.co for vertex in mesh.vertices)
        finally:
            evaluated.to_mesh_clear()
    if not points:
        raise ValueError("fit_envelope: selected meshes have no vertices")

    def project():
        scene.view_layers[0].update()
        return [
            (float(p.x) * width, (1.0 - float(p.y)) * height)
            for p in (world_to_camera_view(scene, cam, point) for point in points)
        ]

    def bbox(projected):
        xs = [p[0] for p in projected]
        ys = [p[1] for p in projected]
        return [min(xs), min(ys), max(xs), max(ys)]

    # Shift is affine in image space, while width is controlled by the lens.
    # Solving width from the actual projection is exact for a perspective
    # camera and avoids importing a portrait-sensor formula.
    cam.data.shift_x = 0.0
    cam.data.shift_y = 0.0
    unshifted = project()
    unshifted_bbox = bbox(unshifted)
    if fit_width:
        measured_width = unshifted_bbox[2] - unshifted_bbox[0]
        if measured_width <= 1.0e-12:
            raise RuntimeError("fit_envelope: projected mesh has zero width")
        cam.data.lens *= (x1 - x0) / measured_width
        unshifted = project()
        unshifted_bbox = bbox(unshifted)

    probe = abs(float(shift_probe))
    cam.data.shift_x = probe
    x_shifted = project()
    cam.data.shift_x = 0.0
    cam.data.shift_y = probe
    y_shifted = project()
    cam.data.shift_y = 0.0
    x_response = sum((x_shifted[i][0] - unshifted[i][0]) / probe
                     for i in range(len(points))) / len(points)
    y_response = sum((y_shifted[i][1] - unshifted[i][1]) / probe
                     for i in range(len(points))) / len(points)
    if abs(x_response) < 1.0e-12 or abs(y_response) < 1.0e-12:
        raise RuntimeError("fit_envelope: camera shift response is degenerate")

    target_center = ((x0 + x1) * 0.5, (y0 + y1) * 0.5)
    unshifted_center = (
        (unshifted_bbox[0] + unshifted_bbox[2]) * 0.5,
        (unshifted_bbox[1] + unshifted_bbox[3]) * 0.5,
    )
    if fit_shift[0]:
        cam.data.shift_x = (target_center[0] - unshifted_center[0]) / x_response
    if fit_shift[1]:
        cam.data.shift_y = (target_center[1] - unshifted_center[1]) / y_response
    projected = project()
    final_bbox = bbox(projected)
    final_center = (
        (final_bbox[0] + final_bbox[2]) * 0.5,
        (final_bbox[1] + final_bbox[3]) * 0.5,
    )
    target_size = (x1 - x0, y1 - y0)
    final_size = (final_bbox[2] - final_bbox[0], final_bbox[3] - final_bbox[1])
    actual_forward = cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
    actual_forward.normalize()
    requested_forward = (focus - cam.location).normalized()

    return {
        "camera_name": cam.name,
        "objects": names,
        "resolution": [width, height],
        "target_bbox_px": [x0, y0, x1, y1],
        "unshifted_bbox_px": [float(v) for v in unshifted_bbox],
        "bbox_px": [float(v) for v in final_bbox],
        "target_size_px": [float(v) for v in target_size],
        "projected_size_px": [float(v) for v in final_size],
        "bbox_error_px": [final_bbox[i] - (x0, y0, x1, y1)[i] for i in range(4)],
        "center_error_px": [final_center[i] - target_center[i] for i in range(2)],
        "lens_mm": float(cam.data.lens),
        "fit_width": bool(fit_width),
        "fit_shift": [bool(fit_shift[0]), bool(fit_shift[1])],
        "distance": float(distance),
        "azimuth_deg": float(azimuth),
        "elevation_deg": float(elevation),
        "shift": [float(cam.data.shift_x), float(cam.data.shift_y)],
        "shift_response_px_per_unit": [float(x_response), float(y_response)],
        "forward_requested_world": [float(v) for v in requested_forward],
        "forward_minus_z_world": [float(v) for v in actual_forward],
        "forward_error": float((actual_forward - requested_forward).length),
    }
