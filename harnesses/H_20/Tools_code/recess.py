"""Batch construction of measured, tapered recessed openings.

A recessed opening in a provisional model usually has the same mechanical
sequence: make a closed tapered cutter in a chosen screen/world basis, apply a
Boolean difference to every loose solid in a joined core, remove the disposable
cutter, rejoin the core, and add a smaller closed liner behind the opening.

``apply_recess_batch`` packages that sequence for several measured openings.
It is deliberately subject-neutral: all centres, basis vectors, 2-D outlines,
radii, depths, names, and materials are supplied by the caller.  It is useful
for sockets, vents, ports, apertures, and other openings in an assembled mesh.
The core is split by loose component before each operation so overlapping
provisional solids are not presented to Blender's Boolean solver as one
self-intersecting target.
"""

import math

import bpy
from mathutils import Vector


_EPS = 1.0e-9


def _remove_object(name):
    """Remove an object and its unused geometry datablock, if any."""
    old = bpy.data.objects.get(name)
    if old is None:
        return False
    data = getattr(old, "data", None)
    kind = old.type
    bpy.data.objects.remove(old, do_unlink=True)
    if data is not None and getattr(data, "users", 0) == 0:
        collection = {
            "MESH": bpy.data.meshes,
            "CURVE": bpy.data.curves,
            "CAMERA": bpy.data.cameras,
            "LIGHT": bpy.data.lights,
        }.get(kind)
        if collection is not None:
            collection.remove(data)
    return True


def _basis(operation):
    """Read the caller's world-space right/up/out basis without guessing it."""
    try:
        right = Vector(operation["right"])
        up = Vector(operation["up"])
        out = Vector(operation["out"])
    except KeyError as exc:
        raise ValueError("recess operation is missing basis vector %r" % exc.args[0])
    if min(right.length, up.length, out.length) < _EPS:
        raise ValueError("recess basis vectors must be non-zero")
    return right, up, out


def _outline(operation):
    try:
        shape = [tuple(float(v) for v in point)
                 for point in operation["shape"]]
    except KeyError:
        raise ValueError("recess operation is missing shape") from None
    if len(shape) < 3 or any(len(point) != 2 for point in shape):
        raise ValueError("recess shape needs at least three (x, z) points")
    return shape


def _shape_power(value, exponent):
    """Preserve the sign while applying an optional superellipse exponent."""
    if exponent is None:
        return float(value)
    value = float(value)
    return math.copysign(abs(value) ** float(exponent), value)


def _world_ring(center, right, up, shape, rx, rz, scale, exponent=None):
    """Return a world-space ring from a normalized 2-D outline."""
    return [tuple(center + right * (float(rx) * _shape_power(x, exponent) * scale)
                   + up * (float(rz) * _shape_power(z, exponent) * scale))
            for x, z in shape]


def _make_cutter(operation, name):
    """Create the closed, tapered cutter described by one operation."""
    center = Vector(operation["center"])
    right, up, out = _basis(operation)
    shape = _outline(operation)
    rx = float(operation["rx"])
    rz = float(operation["rz"])
    front_depth = float(operation.get("cutter_front", 0.0))
    back_depth = float(operation.get("cutter_back", 0.0))
    if front_depth < 0.0 or back_depth < 0.0:
        raise ValueError("cutter depths must be non-negative")
    front_scale = float(operation.get("cutter_front_scale", 1.0))
    back_scale = float(operation.get("cutter_back_scale", 1.0))
    exponent = operation.get("cutter_exponent")
    front = center + out * front_depth
    back = center - out * back_depth
    verts = _world_ring(front, right, up, shape, rx, rz, front_scale, exponent)
    verts += _world_ring(back, right, up, shape, rx, rz, back_scale, exponent)
    n = len(shape)
    faces = [list(reversed(range(n))), list(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j, n + i])
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    cutter = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(cutter)
    cutter.display_type = "WIRE"
    cutter.hide_render = True
    cutter.hide_set(True)
    return cutter


def _make_liner(operation, name, material_name=None, parent_name=None):
    """Create the closed tapered liner behind one measured opening."""
    center = Vector(operation["center"])
    right, up, out = _basis(operation)
    shape = _outline(operation)
    rx = float(operation["rx"])
    rz = float(operation["rz"])
    liner = dict(operation.get("liner") or {})
    liner_rx = float(liner.get("rx", rx))
    liner_rz = float(liner.get("rz", rz))
    lip_depth = float(liner.get("lip_depth", 0.0))
    inner_depth = float(liner.get("inner_depth", 0.2))
    outer_depth = float(liner.get("outer_depth", inner_depth))
    cap_depth = float(liner.get("cap_depth", outer_depth))
    lip_scale = float(liner.get("lip_scale", 1.0))
    inner_scale = float(liner.get("inner_scale", 0.5))
    outer_scale = float(liner.get("outer_scale", lip_scale))
    exponent = liner.get("shape_exponent", operation.get("cutter_exponent"))

    a = _world_ring(center + out * lip_depth, right, up, shape,
                    liner_rx, liner_rz, lip_scale, exponent)
    b = _world_ring(center - out * inner_depth, right, up, shape,
                    liner_rx, liner_rz, inner_scale, exponent)
    d = _world_ring(center - out * outer_depth, right, up, shape,
                    liner_rx, liner_rz, outer_scale, exponent)
    cap_point = tuple(center - out * cap_depth)
    verts = a + b + d + [cap_point]
    n = len(shape)
    cap = 3 * n
    faces = []
    for i in range(n):
        j = (i + 1) % n
        # Front lip -> inner wall -> outer/rear wall -> posterior cap.  The
        # four face families share every edge, so the liner is closed.
        faces.extend([
            [i, j, n + j, n + i],
            [n + i, n + j, 2 * n + j, 2 * n + i],
            [i, 2 * n + i, 2 * n + j, j],
            [n + i, cap, n + j],
        ])
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if material_name:
        material = bpy.data.materials.get(material_name)
        if material is None:
            raise ValueError("liner material does not exist: %s" % material_name)
        obj.data.materials.append(material)
    if parent_name:
        parent = bpy.data.objects.get(parent_name)
        if parent is None:
            raise ValueError("liner parent does not exist: %s" % parent_name)
        world_matrix = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_parent_inverse = parent.matrix_world.inverted()
        obj.matrix_world = world_matrix
    if liner.get("smooth", True):
        for polygon in mesh.polygons:
            polygon.use_smooth = True
    return obj


def _split_named_object(name):
    """Separate one mesh by loose parts and return all resulting objects."""
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        raise ValueError("recess core object is not a mesh: %s" % name)
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    return [candidate for candidate in bpy.context.scene.objects
            if candidate.type == "MESH" and
            (candidate.name == name or candidate.name.startswith(name + "."))]


def _components_for_prefix(prefix):
    return [obj for obj in bpy.context.scene.objects
            if obj.type == "MESH" and
            (obj.name == prefix or obj.name.startswith(prefix + "."))]


def _apply_to_components(components, cutter, solver, modifier_prefix):
    """Apply one cutter to every component, in scene order."""
    report = []
    for index, target in enumerate(list(components), 1):
        if target.name not in bpy.data.objects:
            continue
        before = (len(target.data.vertices), len(target.data.polygons))
        bpy.ops.object.select_all(action="DESELECT")
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        cutter.hide_set(False)
        cutter.hide_viewport = False
        cutter.hide_render = False
        modifier = target.modifiers.new(
            "%s_%d" % (modifier_prefix, index), "BOOLEAN")
        modifier.operation = "DIFFERENCE"
        modifier.solver = solver
        modifier.object = cutter
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        after = (len(target.data.vertices), len(target.data.polygons))
        report.append({
            "object": target.name,
            "before_vertices": before[0],
            "before_faces": before[1],
            "after_vertices": after[0],
            "after_faces": after[1],
            "changed": before != after,
        })
    return report


def _join_components(components, name):
    """Join components through the shared general mesh join helper."""
    from meshgen import join
    joined = join(list(components), name)
    if joined is None:
        raise RuntimeError("recess could not rejoin core as %s" % name)
    return joined


def _audit_mesh(obj):
    """Small post-operation topology report for the returned liner/core."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = sum(1 for edge in bm.edges if not edge.is_manifold)
    isolated = sum(1 for vert in bm.verts if not vert.link_edges)
    bm.free()
    return {
        "object": obj.name,
        "vertices": len(obj.data.vertices),
        "faces": len(obj.data.polygons),
        "boundary_edges": boundary,
        "isolated_vertices": isolated,
    }


def apply_recess_batch(core_objects, operations, *, join_name,
                       split_initial=None, parent_name=None,
                       solver="EXACT", delete_cutters=True):
    """Apply and line up several measured tapered recesses in one call.

    ``core_objects`` is a sequence of mesh names that make up the initial
    assembled core.  ``join_name`` is the stable name for the rejoined core.
    ``split_initial`` optionally names the initial joined meshes that must be
    separated by loose component before the first operation (normally only the
    meshes that contain multiple disconnected solids).  Whenever a previous
    operation rejoins the core, the next operation splits it again before
    cutting; a ``join_after=False`` operation stays in the current loose group.

    Each item in ``operations`` is a mapping with these required fields:

    ``name``
        Stable liner object name.  ``cutter_name`` is optional and defaults to
        ``CUT_<name>``; the cutter is always removed by default.
    ``center``, ``right``, ``up``, ``out``
        World-space screen/depth basis.  ``out`` points toward the camera.
    ``shape``, ``rx``, ``rz``
        Normalized 2-D outline and its world radii.
    ``cutter_front``, ``cutter_back``
        Non-negative depths from the measured centre; the back is placed in the
        negative ``out`` direction.  Optional front/back scales and a signed
        ``cutter_exponent`` create a superellipse-like outline.
    ``liner``
        Optional ``lip_depth``, ``inner_depth``, ``outer_depth``, ``cap_depth``
        and ring-scale values.  The default is a closed tapered cup.  ``rx``
        and ``rz`` may be overridden inside this mapping when the liner is
        narrower than its cutter.
    ``join_after``
        Defaults to true.  Set false to keep the current loose-component group
        so the next cutter is applied before one shared rejoin, preserving an
        intentional per-component cutter order.

    ``material_name`` may be supplied per operation and ``parent_name`` may be
    supplied globally or per operation.  The return value contains the
    per-operation Boolean changes, core topology, liner topology, and any
    remaining cutter names.  The scene is mutated; this is a build tool, not a
    preview.

    The important safety property is that Boolean evaluation occurs on the
    loose closed components separately.  A joined collection of overlapping
    provisional solids can otherwise be self-intersecting even when its outer
    boundary audit is clean.
    """
    names = list(core_objects)
    ops = [dict(operation) for operation in operations]
    if not names:
        raise ValueError("apply_recess_batch: core_objects is empty")
    if not ops:
        raise ValueError("apply_recess_batch: operations is empty")
    if not join_name:
        raise ValueError("apply_recess_batch: join_name is required")
    if split_initial is None:
        split_initial = []
    split_initial = list(split_initial)

    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise ValueError("apply_recess_batch: missing core mesh %s" % name)
    for operation in ops:
        if "name" not in operation:
            raise ValueError("each recess operation needs a stable name")
        if "material_name" not in operation:
            operation["material_name"] = None
        if "parent_name" not in operation:
            operation["parent_name"] = parent_name

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    # Match the normal local-Boolean workflow: split only explicitly requested
    # multi-part sources, then collect all initial core meshes in scene order.
    for source_name in split_initial:
        _split_named_object(source_name)
    allowed = set()
    for name in names:
        allowed.add(name)
        allowed.update(obj.name for obj in _components_for_prefix(name))
    initial = [obj for obj in bpy.context.scene.objects
               if obj.type == "MESH" and obj.name in allowed]
    if not initial:
        raise RuntimeError("apply_recess_batch: no initial core components")

    reports = []
    core = initial
    core_is_joined = False
    for op_index, operation in enumerate(ops, 1):
        if core_is_joined:
            # Rejoining after a completed operation is convenient for stable
            # naming, but the next Boolean must again see loose components,
            # never the overlapping joined collection.
            _split_named_object(join_name)
            core = _components_for_prefix(join_name)
            core_is_joined = False
        cutter_name = operation.get("cutter_name", "CUT_" + str(operation["name"]))
        _remove_object(cutter_name)
        cutter = _make_cutter(operation, cutter_name)
        cut_report = _apply_to_components(
            core, cutter, solver,
            operation.get("modifier_prefix", "recess_difference_%d" % op_index))
        cutter_data = cutter.data
        if delete_cutters:
            bpy.data.objects.remove(cutter, do_unlink=True)
            if cutter_data.users == 0:
                bpy.data.meshes.remove(cutter_data)

        # A retry should replace a prior liner rather than silently create a
        # suffixed duplicate, just like the disposable cutter above.
        _remove_object(str(operation["name"]))

        # ``join_after=False`` lets a group of cutters follow the source
        # workflow's per-component order before one topology-changing join.
        # This is important for deterministic downstream face order as well as
        # for the Boolean safety rule.
        joined = None
        if operation.get("join_after", True):
            joined = _join_components(core, join_name)
            for polygon in joined.data.polygons:
                polygon.use_smooth = True
            core = [joined]
            core_is_joined = True

        liner = _make_liner(
            operation, str(operation["name"]),
            material_name=operation.get("material_name"),
            parent_name=operation.get("parent_name"))
        reports.append({
            "name": str(operation["name"]),
            "cutter": cutter_name,
            "cuts": cut_report,
            "core": _audit_mesh(joined) if joined is not None else None,
            "liner": _audit_mesh(liner),
        })

    if not core_is_joined:
        joined = _join_components(core, join_name)
        for polygon in joined.data.polygons:
            polygon.use_smooth = True
        core = [joined]
    return {
        "core": _audit_mesh(core[0]),
        "operations": reports,
        "cutters_removed": bool(delete_cutters),
        "remaining_cutters": sorted(
            obj.name for obj in bpy.context.scene.objects
            if obj.name.startswith("CUT_")),
    }
