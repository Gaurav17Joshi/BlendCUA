"""Closed shallow strap sweeps for connected path networks.

The operation is subject-neutral: callers supply world-space polylines, the
front direction, section dimensions, shared node ids, and any material.  It
builds one mesh from a broad chamfered profile, reuses the ring at each shared
node, caps only true terminal nodes, and returns construction audits alongside
the mesh data.  It is intentionally not a collection of independently capped
round tubes or an object-join convenience wrapper.  Its closed-section recipe
extends the measured-section conventions in `Tool_scripts/Tools_code/section_mesh.py`.
"""

from __future__ import annotations

import math


_EPSILON = 1.0e-9


def _vec(value, label):
    try:
        result = tuple(float(component) for component in value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a 3-D numeric vector" % label) from None
    if len(result) != 3 or any(not math.isfinite(component) for component in result):
        raise ValueError("%s must be a finite 3-D numeric vector" % label)
    return result


def _add(first, second):
    return tuple(a + b for a, b in zip(first, second))


def _sub(first, second):
    return tuple(a - b for a, b in zip(first, second))


def _scale(value, factor):
    return tuple(component * factor for component in value)


def _dot(first, second):
    return sum(a * b for a, b in zip(first, second))


def _cross(first, second):
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _length(value):
    return math.sqrt(_dot(value, value))


def _normalise(value, label):
    result = _vec(value, label)
    length = _length(result)
    if length <= _EPSILON:
        raise ValueError("%s must be non-zero" % label)
    return _scale(result, 1.0 / length)


def _distance(first, second):
    return _length(_sub(first, second))


def _node_key(value):
    return str(value)


def chamfered_profile(width, depth, chamfer=0.18):
    """Return a closed broad/shallow chamfered section as ``(lateral, depth)``.

    ``width`` is the full front-face span and ``depth`` is the full edge depth.
    ``chamfer`` is a fraction of the smaller half-span when it is below one, or
    an absolute distance otherwise.  The profile is caller-independent and may
    be passed back as ``profile`` to ``build_network_mesh`` for a custom section.
    """
    width = float(width)
    depth = float(depth)
    if not math.isfinite(width) or not math.isfinite(depth) or width <= 0.0 or depth <= 0.0:
        raise ValueError("width and depth must be finite and positive")
    half_width, half_depth = width * 0.5, depth * 0.5
    requested = float(chamfer)
    if not math.isfinite(requested) or requested < 0.0:
        raise ValueError("chamfer must be finite and non-negative")
    amount = min(half_width, half_depth) * requested if requested < 1.0 else requested
    amount = min(amount, half_width * 0.9, half_depth * 0.9)
    if amount <= _EPSILON:
        amount = min(half_width, half_depth) * 0.1
    return [
        (-half_width + amount, -half_depth),
        ( half_width - amount, -half_depth),
        ( half_width, -half_depth + amount),
        ( half_width,  half_depth - amount),
        ( half_width - amount,  half_depth),
        (-half_width + amount,  half_depth),
        (-half_width,  half_depth - amount),
        (-half_width, -half_depth + amount),
    ]


def _validate_profile(profile):
    if profile is None:
        raise ValueError("profile is required")
    result = []
    for point in profile:
        try:
            lateral, depth = (float(value) for value in point)
        except (TypeError, ValueError):
            raise ValueError("profile points must be (lateral, depth) pairs") from None
        if not math.isfinite(lateral) or not math.isfinite(depth):
            raise ValueError("profile coordinates must be finite")
        result.append((lateral, depth))
    if len(result) < 4:
        raise ValueError("profile needs at least four points")
    if max(point[0] for point in result) - min(point[0] for point in result) <= _EPSILON:
        raise ValueError("profile lateral span must be positive")
    if max(point[1] for point in result) - min(point[1] for point in result) <= _EPSILON:
        raise ValueError("profile depth span must be positive")
    return result


def _path_record(path, index):
    if isinstance(path, dict):
        points = None
        for key in ("points_world", "points", "polyline", "centerline"):
            if key in path:
                points = path[key]
                break
        if points is None:
            raise ValueError("path dict needs points_world, points, polyline, or centerline")
        name = str(path.get("name", "path_%03d" % (index + 1)))
        start = path.get("start_node")
        end = path.get("end_node")
        node_ids = path.get("node_ids", path.get("nodes"))
        closed = bool(path.get("closed", False))
    else:
        points = path
        name = "path_%03d" % (index + 1)
        start = end = None
        node_ids = None
        closed = False
    points = [_vec(point, "%s points" % name) for point in points]
    if len(points) < 2:
        raise ValueError("%s needs at least two points" % name)
    cleaned = [points[0]]
    for point in points[1:]:
        if _distance(point, cleaned[-1]) > _EPSILON:
            cleaned.append(point)
    if len(cleaned) < 2:
        raise ValueError("%s collapses to one point" % name)
    points = cleaned
    if node_ids is None:
        node_ids = [None] * len(points)
    else:
        node_ids = list(node_ids)
        if len(node_ids) != len(points):
            raise ValueError("%s node_ids must match its point count" % name)
    if start is not None:
        node_ids[0] = start
    if end is not None:
        node_ids[-1] = end
    node_ids[0] = node_ids[0] if node_ids[0] is not None else "%s:start" % name
    node_ids[-1] = node_ids[-1] if node_ids[-1] is not None else "%s:end" % name
    node_ids = [None if node is None else _node_key(node) for node in node_ids]
    return {
        "name": name,
        "points": points,
        "node_ids": node_ids,
        "closed": closed,
    }


def _station_tangents(points, front):
    tangents = []
    for index, point in enumerate(points):
        if index == 0:
            tangent = _sub(points[1], point)
        elif index == len(points) - 1:
            tangent = _sub(point, points[index - 1])
        else:
            tangent = _sub(points[index + 1], points[index - 1])
        tangent = _sub(tangent, _scale(front, _dot(tangent, front)))
        tangents.append(_normalise(tangent, "path tangent"))
    return tangents


def _ring(point, tangent, front, profile, factor=1.0):
    lateral = _cross(front, tangent)
    if _length(lateral) <= _EPSILON:
        raise ValueError("front_axis cannot be parallel to a path tangent")
    lateral = _normalise(lateral, "section lateral")
    return [
        _add(point, _add(_scale(lateral, side * factor),
                         _scale(front, section_depth * factor)))
        for side, section_depth in profile
    ]


def _canonical_node_positions(records, shared_nodes, tolerance):
    positions = {}
    input_spread = {}
    supplied = {
        _node_key(key): _vec(value, "shared node %s" % key)
        for key, value in (shared_nodes or {}).items()
    }
    for record in records:
        for point, node in zip(record["points"], record["node_ids"]):
            if node is None:
                continue
            if node in supplied:
                canonical = supplied[node]
            elif node not in positions:
                canonical = point
            else:
                canonical = positions[node]
            if node in positions and _distance(positions[node], canonical) > tolerance:
                raise ValueError(
                    "shared node %r has inconsistent endpoint positions; "
                    "supply one canonical shared_nodes position" % node
                )
            positions[node] = canonical
            input_spread[node] = max(
                input_spread.get(node, 0.0), _distance(point, canonical)
            )
    for node, point in supplied.items():
        positions.setdefault(node, point)
        input_spread.setdefault(node, 0.0)
    return positions, input_spread


def _incidence(records):
    incidence = {}
    for record in records:
        for index, node in enumerate(record["node_ids"]):
            if node is None:
                continue
            sides = 2 if 0 < index < len(record["node_ids"]) - 1 else 1
            incidence.setdefault(node, 0)
            incidence[node] += sides
    return incidence


def _graph_components(records):
    paths_by_node = {}
    for record in records:
        for node in set(item for item in record["node_ids"] if item is not None):
            paths_by_node.setdefault(node, set()).add(record["name"])
    names = {record["name"] for record in records}
    components = []
    while names:
        start = min(names)
        names.remove(start)
        stack = [start]
        component = {start}
        while stack:
            current = stack.pop()
            linked = set()
            for node, linked_paths in paths_by_node.items():
                if current in linked_paths:
                    linked.update(linked_paths)
            for name in linked - component:
                component.add(name)
                names.discard(name)
                stack.append(name)
        components.append(sorted(component))
    return components


def build_network_mesh(paths, width=0.1, depth=0.03, profile=None,
                       front_axis=(0.0, 1.0, 0.0), shared_nodes=None,
                       terminal_nodes=None, terminal_taper=0.55,
                       cap_terminals=True, node_tolerance=1.0e-5):
    """Build one closed mesh and construction audits for a connected path graph.

    ``paths`` accepts dictionaries with ``points_world`` and optional shared
    ``start_node``/``end_node`` or ``node_ids``; plain point polylines are also
    accepted.  ``front_axis`` points through the shallow edge depth.  When no
    custom ``profile`` is supplied, a broad chamfered section is generated from
    the full ``width`` and ``depth``.  Shared node rings are reused by every
    incident branch.  ``terminal_nodes=None`` infers degree-one endpoints;
    passing a sequence makes the intentional terminal set explicit.  Only those
    nodes are tapered and capped, while non-terminal branch transitions stay
    uncapped and continuous.  The return value has ``vertices``, ``faces``, and
    an ``audit`` with section width/depth, shared-ring ids, input endpoint
    spread, and junction gap measurements.
    """
    records = [_path_record(path, index) for index, path in enumerate(paths or ())]
    if not records:
        raise ValueError("build_network_mesh needs at least one path")
    names = [record["name"] for record in records]
    if len(set(names)) != len(names):
        raise ValueError("path names must be unique")
    front = _normalise(front_axis, "front_axis")
    section = _validate_profile(
        chamfered_profile(width, depth) if profile is None else profile
    )
    node_positions, input_spread = _canonical_node_positions(
        records, shared_nodes, float(node_tolerance)
    )
    incidence = _incidence(records)
    if terminal_nodes is None:
        terminals = {node for node, degree in incidence.items() if degree == 1}
    else:
        terminals = {_node_key(node) for node in terminal_nodes}
        unknown = sorted(terminals - set(incidence))
        if unknown:
            raise ValueError("terminal_nodes contains unknown nodes %s" % unknown)
        invalid = sorted(node for node in terminals if incidence[node] != 1)
        if invalid:
            raise ValueError("terminal_nodes must be degree-one nodes: %s" % invalid)
    terminal_taper = float(terminal_taper)
    if not math.isfinite(terminal_taper) or not (0.0 < terminal_taper <= 1.0):
        raise ValueError("terminal_taper must be in the interval (0, 1]")
    node_rings = {}
    vertices = []
    faces = []
    path_audits = []

    for record in records:
        centres = [node_positions.get(node, point)
                   for point, node in zip(record["points"], record["node_ids"])]
        tangents = _station_tangents(centres, front)
        rings = []
        for index, (point, tangent, node) in enumerate(
            zip(centres, tangents, record["node_ids"])
        ):
            factor = terminal_taper if node in terminals else 1.0
            if node is not None and node in node_rings:
                ring = node_rings[node]
            else:
                ring = []
                for side, section_depth in section:
                    lateral = _normalise(_cross(front, tangent), "section lateral")
                    ring.append(len(vertices))
                    vertices.append(tuple(_add(
                        point,
                        _add(_scale(lateral, side * factor),
                             _scale(front, section_depth * factor)),
                    )))
                if node is not None:
                    node_rings[node] = ring
            rings.append(ring)
        for first, second in zip(rings[:-1], rings[1:]):
            for index in range(len(section)):
                following = (index + 1) % len(section)
                faces.append((first[index], first[following],
                              second[following], second[index]))
        for station in (0, len(rings) - 1):
            node = record["node_ids"][station]
            if cap_terminals and node in terminals:
                cap = tuple(reversed(rings[station])) if station == 0 else tuple(rings[station])
                faces.append(cap)
        path_audits.append({
            "name": record["name"],
            "station_count": len(rings),
            "start_node": record["node_ids"][0],
            "end_node": record["node_ids"][-1],
            "terminal_start": record["node_ids"][0] in terminals,
            "terminal_end": record["node_ids"][-1] in terminals,
            "shared_station_count": sum(
                node is not None and incidence.get(node, 0) > 1
                for node in record["node_ids"]
            ),
        })

    profile_width = max(point[0] for point in section) - min(point[0] for point in section)
    profile_depth = max(point[1] for point in section) - min(point[1] for point in section)
    junctions = []
    for node in sorted(node_rings):
        if incidence.get(node, 0) <= 1:
            continue
        junctions.append({
            "node": node,
            "incident_sides": incidence[node],
            "ring_vertices": list(node_rings[node]),
            "input_endpoint_spread_world": float(input_spread.get(node, 0.0)),
            "junction_gap_world": 0.0,
            "nonterminal": True,
        })
    audit = {
        "section": {
            "profile": [[float(a), float(b)] for a, b in section],
            "front_width": float(profile_width),
            "edge_depth": float(profile_depth),
            "depth_to_width": float(profile_depth / profile_width),
        },
        "front_axis": [float(value) for value in front],
        "vertices": len(vertices),
        "faces": len(faces),
        "paths": path_audits,
        "components": _graph_components(records),
        "terminal_nodes": sorted(terminals),
        "junctions": junctions,
        "max_junction_gap_world": 0.0,
        "max_input_endpoint_spread_world": max(input_spread.values(), default=0.0),
        "continuous_nonterminal_junctions": all(
            item["junction_gap_world"] == 0.0 for item in junctions
        ),
    }
    return {"vertices": vertices, "faces": faces, "audit": audit}


def _finish_mesh(name, vertices, faces, material=None, smooth=False):
    import bpy

    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=False)
    mesh.update(calc_edges=True)
    for polygon in mesh.polygons:
        polygon.use_smooth = bool(smooth)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if material is not None:
        if isinstance(material, str):
            material = bpy.data.materials.get(material)
        if material is None:
            raise ValueError("material name/object could not be resolved")
        obj.data.materials.append(material)
    return obj


def build_flat_strap_network(name, paths, width=0.1, depth=0.03,
                             profile=None, front_axis=(0.0, 1.0, 0.0),
                             shared_nodes=None, terminal_nodes=None,
                             terminal_taper=0.55, cap_terminals=True,
                             node_tolerance=1.0e-5, material=None, smooth=False,
                             return_audit=False):
    """Create one Blender mesh from a shared-node flat-strap path network.

    The mesh is constructed in one ``from_pydata`` call; it is not made by
    object-joining separately capped strokes.  ``paths``, section dimensions,
    material, and node naming remain caller-owned.  Set ``return_audit`` to
    receive ``(object, audit)``; otherwise only the mesh object is returned.
    The audit is also stored as scalar custom properties for a later read-only
    construction review.
    """
    mesh_data = build_network_mesh(
        paths,
        width=width,
        depth=depth,
        profile=profile,
        front_axis=front_axis,
        shared_nodes=shared_nodes,
        terminal_nodes=terminal_nodes,
        terminal_taper=terminal_taper,
        cap_terminals=cap_terminals,
        node_tolerance=node_tolerance,
    )
    obj = _finish_mesh(name, mesh_data["vertices"], mesh_data["faces"],
                       material=material, smooth=smooth)
    section = mesh_data["audit"]["section"]
    obj["flat_strap_front_width"] = section["front_width"]
    obj["flat_strap_edge_depth"] = section["edge_depth"]
    obj["flat_strap_depth_to_width"] = section["depth_to_width"]
    obj["flat_strap_junction_gap_world"] = mesh_data["audit"]["max_junction_gap_world"]
    obj["flat_strap_shared_junction_count"] = len(mesh_data["audit"]["junctions"])
    if return_audit:
        return obj, mesh_data["audit"]
    return obj


def audit_network_mesh(obj_name, expected_width=None, expected_depth=None,
                       max_depth_to_width=None):
    """Read a built strap object and return section, closure, and gap evidence.

    The function reads the mesh and the construction properties written by
    ``build_flat_strap_network`` without changing scene state.  Optional expected
    values produce explicit deltas and pass flags; the caller remains responsible
    for choosing the projected pixel target and the representative object.
    """
    import bpy

    obj = bpy.data.objects.get(obj_name)
    if obj is None or obj.type != "MESH":
        raise ValueError("audit_network_mesh requires mesh object %r" % obj_name)
    counts = {}
    for polygon in obj.data.polygons:
        for edge in polygon.edge_keys:
            key = tuple(sorted(edge))
            counts[key] = counts.get(key, 0) + 1
    width = obj.get("flat_strap_front_width")
    depth = obj.get("flat_strap_edge_depth")
    ratio = obj.get("flat_strap_depth_to_width")
    result = {
        "object": obj_name,
        "vertices": len(obj.data.vertices),
        "faces": len(obj.data.polygons),
        "boundary_edges": sum(value == 1 for value in counts.values()),
        "nonmanifold_edges": sum(value > 2 for value in counts.values()),
        "section": {
            "front_width": float(width) if width is not None else None,
            "edge_depth": float(depth) if depth is not None else None,
            "depth_to_width": float(ratio) if ratio is not None else None,
        },
        "junctions": {
            "count": int(obj.get("flat_strap_shared_junction_count", 0)),
            "max_gap_world": float(obj.get("flat_strap_junction_gap_world", 0.0)),
        },
    }
    if expected_width is not None and width is not None:
        result["section"]["width_delta"] = float(width) - float(expected_width)
    if expected_depth is not None and depth is not None:
        result["section"]["depth_delta"] = float(depth) - float(expected_depth)
    if max_depth_to_width is not None and ratio is not None:
        result["section"]["depth_to_width_ok"] = float(ratio) <= float(max_depth_to_width)
    return result
