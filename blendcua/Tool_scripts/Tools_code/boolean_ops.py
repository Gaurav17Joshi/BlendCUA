"""Apply ordered Boolean differences without repeating Blender context boilerplate.

The operation is deliberately about a sequence of disposable cutter objects, not
about any one subject.  It is useful for radial sectors, vents, slots, trim
boxes, or any other set of cutters that must be applied in a known order and
then removed from the scene.
"""

import bpy
import bmesh



def apply_boolean_differences(obj_name, cutter_names, solver="EXACT",
                               modifier_prefix="difference",
                               delete_cutters=True):
    """Apply ordered DIFFERENCE modifiers for named disposable cutters.

    ``obj_name`` is the mesh being cut.  ``cutter_names`` is an ordered
    sequence of object names; each name must resolve to a mesh object.  The
    order is intentional because Boolean topology can depend on the sequence.
    The default ``EXACT`` solver is the geometry-safe choice for intersecting
    planar cutters; callers may select another Blender Boolean solver when
    their scene specifically needs it.

    Every cutter is re-fetched immediately before its modifier is applied, and
    is deleted afterward when ``delete_cutters`` is true.  This makes the call
    safe after topology-changing operations and prevents a hidden helper from
    surviving into a render.  The return value contains per-cut counts plus a
    final boundary/isolated-vertex audit.
    """
    names = list(cutter_names)
    if not names:
        raise ValueError("apply_boolean_differences: at least one cutter is required")
    if len(set(names)) != len(names):
        raise ValueError("apply_boolean_differences: cutter names must be unique")

    target = bpy.data.objects.get(obj_name)
    if target is None or target.type != 'MESH':
        raise ValueError("apply_boolean_differences: target mesh does not exist: %s"
                         % obj_name)

    missing = [name for name in names
               if bpy.data.objects.get(name) is None]
    if missing:
        raise ValueError("apply_boolean_differences: missing cutter(s): %s" % missing)
    non_mesh = [name for name in names
                if bpy.data.objects[name].type != 'MESH']
    if non_mesh:
        raise TypeError("apply_boolean_differences: cutter(s) are not meshes: %s"
                        % non_mesh)

    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    cuts = []
    for index, cutter_name in enumerate(names, 1):
        # Re-fetch both datablocks after every Boolean: applying a modifier
        # rebuilds the target mesh and invalidates assumptions about its prior
        # evaluated topology.
        target = bpy.data.objects.get(obj_name)
        cutter = bpy.data.objects.get(cutter_name)
        if target is None or target.type != 'MESH':
            raise RuntimeError("target disappeared before cutter %s" % cutter_name)
        if cutter is None or cutter.type != 'MESH':
            raise RuntimeError("cutter disappeared before application: %s"
                               % cutter_name)
        if cutter is target:
            raise ValueError("apply_boolean_differences: target cannot cut itself")

        cutter_data = cutter.data
        cutter.hide_set(False)
        cutter.hide_viewport = False
        cutter.hide_render = False

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        bpy.context.view_layer.objects.active = target

        modifier = target.modifiers.new(
            "%s_%d" % (modifier_prefix, index), 'BOOLEAN')
        modifier.operation = 'DIFFERENCE'
        modifier.solver = solver
        modifier.object = cutter
        bpy.ops.object.modifier_apply(modifier=modifier.name)

        cuts.append({
            "cutter": cutter_name,
            "vertices": len(target.data.vertices),
            "faces": len(target.data.polygons),
        })

        if delete_cutters:
            bpy.data.objects.remove(cutter, do_unlink=True)
            if cutter_data.users == 0:
                bpy.data.meshes.remove(cutter_data)

    target = bpy.data.objects.get(obj_name)
    bm = bmesh.new()
    bm.from_mesh(target.data)
    boundary_edges = sum(1 for edge in bm.edges if not edge.is_manifold)
    isolated_vertices = sum(1 for vert in bm.verts if not vert.link_edges)
    bm.free()

    return {
        "object": target.name,
        "cuts": cuts,
        "vertices": len(target.data.vertices),
        "faces": len(target.data.polygons),
        "boundary_edges": boundary_edges,
        "isolated_vertices": isolated_vertices,
        "cutters_removed": delete_cutters,
        "remaining_cutters": [name for name in names
                               if bpy.data.objects.get(name) is not None],
        "modifiers": [modifier.name for modifier in target.modifiers],
    }
