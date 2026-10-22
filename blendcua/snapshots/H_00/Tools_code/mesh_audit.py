"""Read-only structural reports for named evaluated mesh objects.

This is the report layer above :mod:`geom_digest`.  A digest answers whether a
whole scene changed; this module answers why a mesh is acceptable: counts,
triangles, closure, flat shading, modifiers, materials, evaluated world bounds,
and caller-requested semantic properties.  It deliberately does not know about
an object type, collection, or subject.
"""

from __future__ import annotations

from collections import Counter

import bpy


def _edge_incidence(mesh):
    """Return face-incidence counts for the edges represented by mesh faces."""
    return Counter(
        tuple(sorted(edge_key))
        for polygon in mesh.polygons
        for edge_key in polygon.edge_keys
    )


def _bounds(points):
    """Return a JSON-ready world-space min/max box, or None for no vertices."""
    if not points:
        return None
    return {
        "min": [min(float(point[i]) for point in points) for i in range(3)],
        "max": [max(float(point[i]) for point in points) for i in range(3)],
    }


def _material_names(obj):
    return [
        slot.material.name
        for slot in obj.material_slots
        if slot.material is not None
    ]


def _material_face_counts(mesh, obj):
    """Count base polygons by resolved material name, including unassigned ones."""
    counts = Counter()
    for polygon in mesh.polygons:
        index = int(polygon.material_index)
        material = (
            obj.material_slots[index].material
            if 0 <= index < len(obj.material_slots)
            else None
        )
        counts[material.name if material is not None else "<UNASSIGNED>"] += 1
    return dict(sorted(counts.items()))


def _record(obj, depsgraph, property_keys):
    """Build one report record without changing the object or its mesh data."""
    base = obj.data
    base.calc_loop_triangles()
    base_incidence = _edge_incidence(base)

    evaluated = obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated.to_mesh()
    try:
        evaluated_mesh.calc_loop_triangles()
        world_points = [
            evaluated.matrix_world @ vertex.co
            for vertex in evaluated_mesh.vertices
        ]
        evaluated_incidence = _edge_incidence(evaluated_mesh)
        evaluated_smooth = sum(
            bool(polygon.use_smooth) for polygon in evaluated_mesh.polygons
        )
        evaluated_vertices = len(evaluated_mesh.vertices)
        evaluated_polygons = len(evaluated_mesh.polygons)
        evaluated_triangles = len(evaluated_mesh.loop_triangles)
    finally:
        evaluated.to_mesh_clear()

    properties = {
        str(key): obj.get(key)
        for key in property_keys
        if obj.get(key) is not None
    }
    return {
        "type": obj.type,
        "vertices": len(base.vertices),
        "polygons": len(base.polygons),
        "triangles": len(base.loop_triangles),
        "edges": len(base.edges),
        "evaluated_vertices": evaluated_vertices,
        "evaluated_polygons": evaluated_polygons,
        "evaluated_triangles": evaluated_triangles,
        "boundary_edges": sum(count == 1 for count in base_incidence.values()),
        "nonmanifold_edges": sum(count > 2 for count in base_incidence.values()),
        "evaluated_boundary_edges": sum(
            count == 1 for count in evaluated_incidence.values()
        ),
        "evaluated_nonmanifold_edges": sum(
            count > 2 for count in evaluated_incidence.values()
        ),
        "smooth_polygons": sum(bool(polygon.use_smooth) for polygon in base.polygons),
        "evaluated_smooth_polygons": evaluated_smooth,
        "modifiers": [
            {"name": modifier.name, "type": modifier.type}
            for modifier in obj.modifiers
        ],
        "materials": _material_names(obj),
        "material_polygon_counts": _material_face_counts(base, obj),
        "world_bounds": _bounds(world_points),
        "properties": properties,
    }


def inspect_meshes(obj_names, *, property_keys=()):
    """Report evaluated structure for one or more named mesh objects.

    ``obj_names`` is one object name or an iterable of names.  Missing names and
    names that exist but are not meshes are reported instead of being silently
    skipped, so a review cannot pass against an incomplete selection.

    Each present mesh includes base and evaluated vertex/polygon/triangle counts,
    edge-face incidence (boundary and non-manifold edges), smooth-polygon count,
    modifier names/types, material slots and polygon counts by material, and an
    evaluated world-space vertex bounding box.  ``property_keys`` is an optional
    iterable of custom-property names to copy into the report; it is useful for
    caller-owned metadata such as an attachment owner without baking any subject
    vocabulary into this tool.

    The top-level totals sum the per-object evaluated values and expose
    ``all_closed_manifold``, ``all_flat_shaded``, and ``no_modifiers``.  The
    function only reads the scene (apart from Blender's normal evaluated-mesh
    cache updates) and never changes geometry, transforms, selection, materials,
    or visibility.
    """
    if isinstance(obj_names, str):
        names = [obj_names]
    else:
        names = list(obj_names)
    if not names:
        raise ValueError("inspect_meshes: at least one object name is required")
    if len(set(names)) != len(names):
        raise ValueError("inspect_meshes: object names must be unique")

    keys = tuple(property_keys)
    if any(not isinstance(key, str) for key in keys):
        raise TypeError("inspect_meshes: property_keys must contain strings")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects = {}
    missing = []
    non_mesh = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            missing.append(name)
            continue
        if obj.type != "MESH":
            non_mesh.append(name)
            continue
        objects[name] = _record(obj, depsgraph, keys)

    totals = {
        key: sum(record[key] for record in objects.values())
        for key in (
            "vertices",
            "polygons",
            "triangles",
            "evaluated_vertices",
            "evaluated_polygons",
            "evaluated_triangles",
            "boundary_edges",
            "nonmanifold_edges",
            "evaluated_boundary_edges",
            "evaluated_nonmanifold_edges",
            "smooth_polygons",
            "evaluated_smooth_polygons",
        )
    }
    complete = bool(objects) and not missing and not non_mesh
    return {
        "requested_names": names,
        "missing_names": missing,
        "non_mesh_names": non_mesh,
        "objects": objects,
        "totals": totals,
        "all_closed_manifold": complete and all(
            record["evaluated_boundary_edges"] == 0
            and record["evaluated_nonmanifold_edges"] == 0
            for record in objects.values()
        ),
        "all_flat_shaded": complete and all(
            record["evaluated_smooth_polygons"] == 0
            for record in objects.values()
        ),
        "no_modifiers": complete and all(
            not record["modifiers"] for record in objects.values()
        ),
    }
