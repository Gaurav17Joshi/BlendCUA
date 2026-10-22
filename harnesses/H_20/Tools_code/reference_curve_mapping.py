"""Reference-crop tracing for branched linework and shared construction nodes.

This module is deliberately subject-neutral.  It thresholds a caller-selected
image crop, thins the occupied pixels to a centreline graph, and returns ordered
polylines whose endpoints refer to shared graph nodes.  It does not replace a
branched motif with a bounding box or a parametric curve.  The pure-Python
image path is usable from a shell or from Blender; the projection helper is
Blender-side and maps the returned reference pixels through an image Empty.
Its occupancy-report conventions follow `Tool_scripts/Tools_code/reference_audit.py`.
"""

from __future__ import annotations

import math
import os
import sys


_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_NEIGHBOUR_OFFSETS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0),            (1, 0),
    (-1, 1),  (0, 1),  (1, 1),
)


def _resolve(path):
    path = os.fspath(path)
    return path if os.path.isabs(path) else os.path.join(_ROOT, path)


def _pil():
    # ImportError, not just ModuleNotFoundError, and drop a half-imported PIL first: see the
    # same function in reference_audit.py for why (2026-09-16).
    try:
        from PIL import Image, ImageDraw
        return Image, ImageDraw
    except ImportError:
        for name in [m for m in sys.modules if m == "PIL" or m.startswith("PIL.")]:
            del sys.modules[name]
        vendor = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor")
        if vendor in sys.path:
            sys.path.remove(vendor)
        sys.path.insert(0, vendor)
        from PIL import Image, ImageDraw
        return Image, ImageDraw


def _load_rgb(path):
    Image, _ = _pil()
    full = _resolve(path)
    return Image.open(full).convert("RGB"), full


def _crop_box(crop, width, height):
    if crop is None:
        return (0, 0, int(width), int(height))
    if isinstance(crop, dict):
        try:
            crop = (crop["x0"], crop["y0"], crop["x1"], crop["y1"])
        except KeyError:
            raise ValueError("crop dict needs x0, y0, x1, and y1") from None
    if len(crop) != 4:
        raise ValueError("crop must be (x0, y0, x1, y1)")
    x0, y0, x1, y1 = (int(round(float(value))) for value in crop)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(int(width), x1), min(int(height), y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("crop must have positive area inside the image")
    return (x0, y0, x1, y1)


def _dark_mask(image, threshold, box):
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    pixels = image.load()
    mask = bytearray(width * height)
    threshold = float(threshold)
    for y in range(height):
        source_y = y0 + y
        row = y * width
        for x in range(width):
            r, g, b = pixels[x0 + x, source_y]
            value = 0.2126 * r + 0.7152 * g + 0.0722 * b
            mask[row + x] = 1 if value < threshold else 0
    return mask, width, height


def _component_filter(mask, width, height, minimum):
    """Keep connected dark components large enough to contain linework."""
    minimum = int(minimum)
    if minimum <= 1:
        return bytearray(mask)
    kept = bytearray(width * height)
    seen = bytearray(width * height)
    for start in range(width * height):
        if not mask[start] or seen[start]:
            continue
        sx, sy = start % width, start // width
        stack = [(sx, sy)]
        seen[start] = 1
        component = []
        while stack:
            x, y = stack.pop()
            component.append((x, y))
            for dx, dy in _NEIGHBOUR_OFFSETS:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                index = ny * width + nx
                if mask[index] and not seen[index]:
                    seen[index] = 1
                    stack.append((nx, ny))
        if len(component) >= minimum:
            for x, y in component:
                kept[y * width + x] = 1
    return kept


def _skeletonize(mask, width, height, max_iterations):
    """Thin a binary mask with the Zhang-Suen two-phase deletion rule."""
    # A zero border lets strokes touching the requested crop be treated just as
    # naturally as strokes in the interior while keeping all indexing simple.
    padded_width = width + 2
    padded_height = height + 2
    data = bytearray(padded_width * padded_height)
    for y in range(height):
        source = y * width
        target = (y + 1) * padded_width + 1
        data[target:target + width] = mask[source:source + width]

    def value(x, y):
        return data[y * padded_width + x]

    def transitions(values):
        return sum(
            1 for index, item in enumerate(values)
            if not item and values[(index + 1) % len(values)]
        )

    for _ in range(max(1, int(max_iterations))):
        changed = False
        for phase in (0, 1):
            remove = []
            for y in range(1, padded_height - 1):
                for x in range(1, padded_width - 1):
                    index = y * padded_width + x
                    if not data[index]:
                        continue
                    neighbours = [
                        value(x, y - 1), value(x + 1, y - 1),
                        value(x + 1, y), value(x + 1, y + 1),
                        value(x, y + 1), value(x - 1, y + 1),
                        value(x - 1, y), value(x - 1, y - 1),
                    ]
                    count = sum(neighbours)
                    if count < 2 or count > 6 or transitions(neighbours) != 1:
                        continue
                    p2, p3, p4, p5, p6, p7, p8, p9 = neighbours
                    if phase == 0:
                        if p2 * p4 * p6 or p4 * p6 * p8:
                            continue
                    elif p2 * p4 * p8 or p2 * p6 * p8:
                        continue
                    remove.append(index)
            if remove:
                changed = True
                for index in remove:
                    data[index] = 0
        if not changed:
            break

    output = bytearray(width * height)
    for y in range(height):
        source = (y + 1) * padded_width + 1
        target = y * width
        output[target:target + width] = data[source:source + width]
    return output


def _pixel_neighbours(point, pixels):
    x, y = point
    return [
        (x + dx, y + dy)
        for dx, dy in _NEIGHBOUR_OFFSETS
        if (x + dx, y + dy) in pixels
    ]


def _connected_groups(points):
    remaining = set(points)
    groups = []
    while remaining:
        start = min(remaining, key=lambda item: (item[1], item[0]))
        remaining.remove(start)
        stack = [start]
        group = [start]
        while stack:
            point = stack.pop()
            for neighbour in _pixel_neighbours(point, remaining):
                remaining.remove(neighbour)
                stack.append(neighbour)
                group.append(neighbour)
        groups.append(group)
    return groups


def _edge_key(first, second):
    return tuple(sorted((tuple(first), tuple(second))))


def _node_centre(group):
    x = sum(point[0] for point in group) / float(len(group))
    y = sum(point[1] for point in group) / float(len(group))
    return (x, y)


def _rdp(points, tolerance):
    """Ramer-Douglas-Peucker simplification that keeps graph endpoints."""
    points = [tuple(float(value) for value in point) for point in points]
    if len(points) <= 2 or tolerance <= 0.0:
        return points

    def distance(point, first, second):
        dx = second[0] - first[0]
        dy = second[1] - first[1]
        denominator = dx * dx + dy * dy
        if denominator <= 1.0e-12:
            return math.hypot(point[0] - first[0], point[1] - first[1])
        t = ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy) / denominator
        t = max(0.0, min(1.0, t))
        return math.hypot(
            point[0] - (first[0] + t * dx),
            point[1] - (first[1] + t * dy),
        )

    farthest = 0.0
    split = -1
    first, second = points[0], points[-1]
    for index, point in enumerate(points[1:-1], start=1):
        distance_value = distance(point, first, second)
        if distance_value > farthest:
            farthest, split = distance_value, index
    if split < 0 or farthest <= tolerance:
        return [first, second]
    return _rdp(points[:split + 1], tolerance)[:-1] + _rdp(points[split:], tolerance)


def _path_points(path):
    if isinstance(path, dict):
        for key in ("points_px", "points", "polyline", "centerline"):
            if key in path:
                return [tuple(float(value) for value in point) for point in path[key]]
        raise ValueError("path dict needs points_px, points, polyline, or centerline")
    return [tuple(float(value) for value in point) for point in path]


def _path_name(path_names, index):
    if path_names is None:
        return "path_%03d" % (index + 1)
    if isinstance(path_names, dict):
        value = path_names.get(index, path_names.get(str(index)))
    else:
        values = list(path_names)
        value = values[index] if index < len(values) else None
    if value is None or not str(value).strip():
        raise ValueError("path_names must provide a non-empty name for every path")
    return str(value)


def _trace_skeleton(mask, width, height, crop, simplify_tolerance, path_names):
    pixels = {
        (index % width, index // width)
        for index, value in enumerate(mask) if value
    }
    if not pixels:
        return [], [], []

    neighbours = {point: _pixel_neighbours(point, pixels) for point in pixels}
    degrees = {point: len(items) for point, items in neighbours.items()}
    branch_pixels = {point for point, degree in degrees.items() if degree >= 3}
    endpoint_pixels = {point for point, degree in degrees.items() if degree == 1}

    branch_groups = _connected_groups(branch_pixels) if branch_pixels else []
    endpoint_groups = _connected_groups(endpoint_pixels) if endpoint_pixels else []
    node_groups = [("branch", group) for group in branch_groups]
    node_groups += [("endpoint", group) for group in endpoint_groups]
    node_groups.sort(key=lambda item: (
        _node_centre(item[1])[1], _node_centre(item[1])[0], item[0]
    ))

    nodes = []
    node_for_pixel = {}
    for ordinal, (kind, group) in enumerate(node_groups, start=1):
        node_id = "node_%03d" % ordinal
        centre = _node_centre(group)
        record = {
            "id": node_id,
            "kind": kind,
            "point_px": [round(crop[0] + centre[0], 4),
                         round(crop[1] + centre[1], 4)],
            "pixel_count": len(group),
            "degree": max(degrees[point] for point in group),
        }
        nodes.append(record)
        for point in group:
            node_for_pixel[point] = node_id

    node_centres = {record["id"]: tuple(record["point_px"]) for record in nodes}
    visited_edges = set()
    raw_paths = []

    def emit(points, start_node=None, end_node=None, closed=False):
        if len(points) < 2:
            return
        full_points = [
            (crop[0] + point[0], crop[1] + point[1])
            for point in points
        ]
        simplified = _rdp(full_points, float(simplify_tolerance))
        if len(simplified) < 2:
            return
        raw_paths.append({
            "points_px": [[round(x, 4), round(y, 4)] for x, y in simplified],
            "start_node": start_node,
            "end_node": end_node,
            "closed": bool(closed),
        })

    # Walk every edge leaving a graph node.  Pixels inside a thick junction
    # cluster are intentionally collapsed to one shared node, so each emitted
    # path refers to the same node id at a branch rather than inventing a gap.
    for node_id, group in ((record["id"], group)
                           for record, (_, group) in zip(nodes, node_groups)):
        centre = node_centres[node_id]
        for point in group:
            for neighbour in neighbours[point]:
                if node_for_pixel.get(neighbour) == node_id:
                    continue
                edge = _edge_key(point, neighbour)
                if edge in visited_edges:
                    continue
                visited_edges.add(edge)
                line = [point, neighbour]
                previous, current = point, neighbour
                end_node = None
                while True:
                    if current in node_for_pixel:
                        end_node = node_for_pixel[current]
                        line.append(current)
                        break
                    options = [candidate for candidate in neighbours[current]
                               if candidate != previous]
                    if not options:
                        line.append(current)
                        break
                    unvisited = [candidate for candidate in options
                                 if _edge_key(current, candidate) not in visited_edges]
                    next_point = (unvisited or options)[0]
                    next_edge = _edge_key(current, next_point)
                    if next_edge in visited_edges:
                        line.append(current)
                        break
                    visited_edges.add(next_edge)
                    previous, current = current, next_point
                    line.append(current)
                start_point = (centre[0] - crop[0], centre[1] - crop[1])
                line[0] = start_point
                if end_node is not None:
                    end_centre = node_centres[end_node]
                    line[-1] = (end_centre[0] - crop[0], end_centre[1] - crop[1])
                emit(line, node_id, end_node)

    # A closed centreline component can contain no endpoint or branch pixel.
    # Trace each unvisited cycle once and preserve its closed topology.
    for start in sorted(pixels, key=lambda item: (item[1], item[0])):
        if all(_edge_key(start, neighbour) in visited_edges
               for neighbour in neighbours[start]):
            continue
        options = neighbours[start]
        if not options:
            continue
        first = options[0]
        visited_edges.add(_edge_key(start, first))
        line = [start, first]
        previous, current = start, first
        while current != start:
            candidates = [candidate for candidate in neighbours[current]
                          if candidate != previous]
            if not candidates:
                break
            next_point = candidates[0]
            edge = _edge_key(current, next_point)
            if edge in visited_edges:
                if next_point == start:
                    line.append(start)
                break
            visited_edges.add(edge)
            previous, current = current, next_point
            line.append(current)
        if line[-1] == start:
            emit(line, closed=True)

    if path_names is not None:
        supplied = list(path_names.values()) if isinstance(path_names, dict) else list(path_names)
        if len(supplied) != len(raw_paths):
            raise ValueError(
                "path_names count %d does not match traced path count %d"
                % (len(supplied), len(raw_paths))
            )
    for index, path in enumerate(raw_paths):
        path["name"] = _path_name(path_names, index)
    return raw_paths, nodes, [record for record in nodes if record["kind"] == "branch"]


def trace_reference_curves(reference_path, crop=None, threshold=145,
                           minimum_component_pixels=4, max_skeleton_iterations=128,
                           simplify_tolerance=0.75, path_names=None,
                           overlay_path=None):
    """Trace ordered centreline paths and shared nodes from a reference crop.

    ``reference_path`` is the caller-selected image.  ``crop`` is an optional
    full-image half-open ``(x0, y0, x1, y1)`` box; all returned points are put
    back into the full reference-pixel frame.  Dark pixels use the explicit
    luminance ``threshold`` and small connected components can be rejected with
    ``minimum_component_pixels``.  The result contains ``paths`` with ordered
    ``points_px`` plus ``start_node``/``end_node`` ids, all graph ``nodes``,
    and ``branch_nodes``.  ``path_names`` is caller-owned and is never inferred
    from a subject.  If ``overlay_path`` is supplied, an annotated overlay is
    written without changing the source image.

    This is a centreline graph extraction, not a bbox or parametric-spiral
    approximation.  Use the returned shared node ids when constructing a
    branched mesh and inspect the overlay before mirroring.
    """
    image, full = _load_rgb(reference_path)
    box = _crop_box(crop, image.width, image.height)
    mask, width, height = _dark_mask(image, threshold, box)
    filtered = _component_filter(mask, width, height, minimum_component_pixels)
    skeleton = _skeletonize(filtered, width, height, max_skeleton_iterations)
    paths, nodes, branch_nodes = _trace_skeleton(
        skeleton, width, height, box, simplify_tolerance, path_names
    )
    result = {
        "reference_path": full,
        "image_size": [int(image.width), int(image.height)],
        "crop": list(box),
        "threshold": float(threshold),
        "minimum_component_pixels": int(minimum_component_pixels),
        "paths": paths,
        "centerline_polylines": paths,
        "nodes": nodes,
        "branch_nodes": branch_nodes,
        "dark_pixels": int(sum(filtered)),
        "skeleton_pixels": int(sum(skeleton)),
    }
    if overlay_path:
        result["overlay_path"] = emit_curve_overlay(
            full, paths, branch_nodes, overlay_path, crop=box
        )
    return result


def map_reference_curves(reference_path, crop=None, threshold=145,
                         minimum_component_pixels=4, max_skeleton_iterations=128,
                         simplify_tolerance=0.75, path_names=None,
                         overlay_path=None):
    """Convenience alias for :func:`trace_reference_curves`.

    The longer name is useful in an action plan where the operation is described
    as mapping a crop into construction paths; all arguments remain caller-owned
    and the returned data is identical to ``trace_reference_curves``.
    """
    return trace_reference_curves(
        reference_path,
        crop=crop,
        threshold=threshold,
        minimum_component_pixels=minimum_component_pixels,
        max_skeleton_iterations=max_skeleton_iterations,
        simplify_tolerance=simplify_tolerance,
        path_names=path_names,
        overlay_path=overlay_path,
    )


def emit_curve_overlay(reference_path, paths, branch_nodes=(), output_path=None,
                       crop=None, mirror_axis_px=None, line_width=2):
    """Write a source-image overlay showing centreline paths and shared nodes.

    ``paths`` accepts the dictionaries returned by ``trace_reference_curves`` or
    plain point sequences in full-image pixels.  The source is left visible;
    blue paths, yellow branch nodes, the optional crop rectangle, and an
    optional mirror axis make a trace auditable before it is used for geometry.
    """
    if output_path is None:
        raise ValueError("emit_curve_overlay requires output_path")
    image, _ = _load_rgb(reference_path)
    _, ImageDraw = _pil()
    draw = ImageDraw.Draw(image)
    width = max(1, int(round(float(line_width))))
    for path in paths or ():
        points = _path_points(path)
        if len(points) < 2:
            continue
        if isinstance(path, dict) and path.get("closed") and points[0] != points[-1]:
            points = points + [points[0]]
        points = [(int(round(x)), int(round(y))) for x, y in points]
        try:
            draw.line(points, fill=(35, 120, 255), width=width, joint="curve")
        except TypeError:
            draw.line(points, fill=(35, 120, 255), width=width)
    radius = max(3, width + 1)
    for node in branch_nodes or ():
        point = node.get("point_px", node) if isinstance(node, dict) else node
        x, y = (int(round(float(value))) for value in point[:2])
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     outline=(255, 210, 35), width=max(1, width))
    if crop is not None:
        x0, y0, x1, y1 = _crop_box(crop, image.width, image.height)
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline=(255, 70, 35), width=width)
    if mirror_axis_px is not None:
        axis = int(round(float(mirror_axis_px)))
        draw.line((axis, 0, axis, image.height - 1), fill=(190, 60, 255), width=width)
    full = _resolve(output_path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    image.save(full)
    return full


def _reference_empty_transform(ref):
    from mathutils import Vector

    if ref is None or ref.type != "EMPTY" or ref.empty_display_type != "IMAGE":
        raise ValueError("project_paths_to_world: ref_name must name an image Empty")
    if ref.data is None:
        raise ValueError("project_paths_to_world: image Empty has no image data")
    image_width, image_height = (int(value) for value in ref.data.size)
    if image_width < 1 or image_height < 1:
        raise ValueError("project_paths_to_world: reference image has no pixels")
    size = float(ref.empty_display_size)
    if size <= 0.0:
        raise ValueError("project_paths_to_world: Empty display size must be positive")
    if image_width >= image_height:
        rect_width = size
        rect_height = size * image_height / image_width
    else:
        rect_width = size * image_width / image_height
        rect_height = size
    offset_x, offset_y = (float(value) for value in ref.empty_image_offset)
    matrix = ref.matrix_world.copy()
    if ref.parent is None:
        basis = ref.matrix_basis.copy()
        if max(abs(float(matrix[row][column] - basis[row][column]))
               for row in range(4) for column in range(4)) > 1.0e-6:
            matrix = basis

    def world_from_pixel(point, depth_offset):
        x, y = (float(value) for value in point[:2])
        local = Vector((
            (x / image_width + offset_x) * rect_width,
            (1.0 - y / image_height + offset_y) * rect_height,
            float(depth_offset),
        ))
        return matrix @ local

    return image_width, image_height, world_from_pixel


def project_paths_to_world(paths, ref_name="Reference", branch_nodes=(),
                           mirror=False, mirror_axis_px=None, depth_offset=0.0,
                           path_names=None):
    """Project reference-pixel paths through a Blender image Empty.

    The image Empty owns the pixel-to-world scale and orientation.  ``paths``
    may be the trace result's path dictionaries or plain point sequences.  If
    ``mirror`` is true, x coordinates are reflected around the caller-supplied
    ``mirror_axis_px`` (the image centre when omitted) before projection; no
    mirroring is done implicitly by tracing.  ``depth_offset`` is in the
    Empty's local normal direction.  The returned world paths retain node ids
    so a network builder can weld shared transitions.
    """
    import bpy

    ref = bpy.data.objects.get(ref_name)
    width, height, world_from_pixel = _reference_empty_transform(ref)
    axis = width * 0.5 if mirror_axis_px is None else float(mirror_axis_px)

    def reflected(point):
        x, y = (float(value) for value in point[:2])
        return ((2.0 * axis - x, y) if mirror else (x, y))

    names = list(path_names) if path_names is not None else None
    projected = []
    for index, path in enumerate(paths or ()):
        points = [reflected(point) for point in _path_points(path)]
        name = (
            str(names[index]) if names is not None and index < len(names)
            else (str(path.get("name", "path_%03d" % (index + 1)))
                  if isinstance(path, dict) else "path_%03d" % (index + 1))
        )
        projected.append({
            "name": name,
            "points_world": [
                [float(value) for value in world_from_pixel(point, depth_offset)]
                for point in points
            ],
            "start_node": path.get("start_node") if isinstance(path, dict) else None,
            "end_node": path.get("end_node") if isinstance(path, dict) else None,
            "closed": bool(path.get("closed", False)) if isinstance(path, dict) else False,
        })

    projected_nodes = []
    for node in branch_nodes or ():
        point = node.get("point_px", node) if isinstance(node, dict) else node
        world = world_from_pixel(reflected(point), depth_offset)
        record = {
            "id": node.get("id") if isinstance(node, dict) else None,
            "point_world": [float(value) for value in world],
        }
        if isinstance(node, dict) and "kind" in node:
            record["kind"] = node["kind"]
        projected_nodes.append(record)
    return {
        "reference_empty": ref_name,
        "image_size": [width, height],
        "mirror": bool(mirror),
        "mirror_axis_px": float(axis),
        "depth_offset": float(depth_offset),
        "paths": projected,
        "branch_nodes": projected_nodes,
    }


def _mask_bbox(mask, width, height):
    points = [index for index, value in enumerate(mask) if value]
    if not points:
        return None
    xs = [index % width for index in points]
    ys = [index // width for index in points]
    return [min(xs), min(ys), max(xs), max(ys), max(xs) - min(xs) + 1,
            max(ys) - min(ys) + 1]


def _runs(values, minimum=1):
    values = sorted(int(value) for value in values)
    if not values:
        return []
    output = []
    start = previous = values[0]
    for value in values[1:]:
        if value > previous + 1:
            if previous - start + 1 >= int(minimum):
                output.append([start, previous, previous - start + 1,
                               round((start + previous) / 2.0, 1)])
            start = value
        previous = value
    if previous - start + 1 >= int(minimum):
        output.append([start, previous, previous - start + 1,
                       round((start + previous) / 2.0, 1)])
    return output


def _query(query, direction):
    if isinstance(query, dict):
        coordinate = int(query["y" if direction == "row" else "x"])
        first = int(query["x0" if direction == "row" else "y0"])
        last = int(query["x1" if direction == "row" else "y1"])
        minimum = int(query.get("min_width", query.get("min_run", 1)))
    else:
        if len(query) not in (3, 4):
            raise ValueError("%s query must have 3 or 4 values" % direction)
        coordinate, first, last = (int(value) for value in query[:3])
        minimum = int(query[3]) if len(query) == 4 else 1
    if minimum < 1:
        raise ValueError("query minimum run must be positive")
    return coordinate, first, last, minimum


def _query_runs(mask, width, height, query, direction):
    coordinate, first, last, minimum = _query(query, direction)
    if direction == "row":
        if not (0 <= coordinate < height):
            values = []
        else:
            first, last = max(0, first), min(width, last)
            base = coordinate * width
            values = [x for x in range(first, last) if mask[base + x]]
    else:
        if not (0 <= coordinate < width):
            values = []
        else:
            first, last = max(0, first), min(height, last)
            values = [y for y in range(first, last) if mask[y * width + coordinate]]
    return {
        "coordinate": coordinate,
        "range": [first, last],
        "min_width": minimum,
        "reference_runs": _runs(values, minimum),
    }


def _mask_metrics(reference_mask, candidate_mask, width, height, box):
    x0, y0, x1, y1 = (int(value) for value in box)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
    reference_pixels = candidate_pixels = intersection = union = xor = 0
    for y in range(y0, y1):
        base = y * width
        for x in range(x0, x1):
            reference = bool(reference_mask[base + x])
            candidate = bool(candidate_mask[base + x])
            reference_pixels += int(reference)
            candidate_pixels += int(candidate)
            intersection += int(reference and candidate)
            union += int(reference or candidate)
            xor += int(reference != candidate)
    area = max(0, x1 - x0) * max(0, y1 - y0)
    return {
        "box": [x0, y0, x1, y1],
        "reference_pixels": reference_pixels,
        "candidate_pixels": candidate_pixels,
        "intersection": intersection,
        "union": union,
        "iou": round(intersection / union, 6) if union else None,
        "xor_pixels": xor,
        "xor_fraction": round(xor / area, 6) if area else None,
        "xor_over_union": round(xor / union, 6) if union else None,
        "candidate_precision": round(intersection / candidate_pixels, 6)
        if candidate_pixels else None,
        "candidate_recall": round(intersection / reference_pixels, 6)
        if reference_pixels else None,
    }


def _path_mask(size, paths, stroke_width_px):
    Image, ImageDraw = _pil()
    image = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(image)
    width = max(1, int(round(float(stroke_width_px))))
    for path in paths or ():
        points = _path_points(path)
        if len(points) < 2:
            continue
        points = [(int(round(x)), int(round(y))) for x, y in points]
        if isinstance(path, dict) and path.get("closed") and points[0] != points[-1]:
            points.append(points[0])
        try:
            draw.line(points, fill=(0, 0, 0), width=width, joint="curve")
        except TypeError:
            draw.line(points, fill=(0, 0, 0), width=width)
    return image


def _mask_overlay(reference, reference_mask, candidate_mask, output_path):
    Image, _ = _pil()
    pixels = []
    for original, reference_hit, candidate_hit in zip(
        reference.getdata(), reference_mask, candidate_mask
    ):
        if reference_hit and candidate_hit:
            pixels.append((35, 35, 35))
        elif reference_hit:
            pixels.append((255, 75, 55))
        elif candidate_hit:
            pixels.append((45, 125, 255))
        else:
            pixels.append(original)
    output = Image.new("RGB", reference.size)
    output.putdata(pixels)
    full = _resolve(output_path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    output.save(full)
    return full


def audit_curve_masks(reference_path, candidate_path=None, paths=None,
                      threshold=145, stroke_width_px=12, rois=None,
                      row_queries=None, column_queries=None, output_path=None):
    """Report per-ROI IoU, XOR, and row/column runs for traced linework.

    Supply either a rendered ``candidate_path`` or reference-pixel ``paths``;
    paths are rasterized at the caller-owned ``stroke_width_px``.  The reference
    and candidate use the same explicit luminance ``threshold``.  ``rois`` is a
    mapping of labels to half-open full-image boxes, while row and column
    queries accept tuples or dictionaries with a ``min_width``/``min_run``.
    The report exposes precision/recall, dark-mask IoU, XOR fraction, and the
    reference/candidate runs that reveal a missing or merged internal branch.
    ``output_path`` writes a red/blue false-colour overlay.
    """
    reference, reference_full = _load_rgb(reference_path)
    if candidate_path is not None and paths is not None:
        raise ValueError("supply candidate_path or paths, not both")
    if candidate_path is not None:
        candidate, candidate_full = _load_rgb(candidate_path)
    elif paths is not None:
        candidate = _path_mask(reference.size, paths, stroke_width_px)
        candidate_full = None
    else:
        raise ValueError("audit_curve_masks needs candidate_path or paths")
    if candidate.size != reference.size:
        raise ValueError(
            "audit_curve_masks: image sizes differ: %s vs %s"
            % (reference.size, candidate.size)
        )
    width, height = reference.size
    reference_mask, _, _ = _dark_mask(reference, threshold, (0, 0, width, height))
    candidate_mask, _, _ = _dark_mask(candidate, threshold, (0, 0, width, height))
    boxes = rois or {"full_image": [0, 0, width, height]}
    roi_report = {
        str(label): _mask_metrics(reference_mask, candidate_mask, width, height, box)
        for label, box in boxes.items()
    }
    rows = []
    for query in row_queries or ():
        record = _query_runs(reference_mask, width, height, query, "row")
        candidate_record = _query_runs(candidate_mask, width, height, query, "row")
        record["candidate_runs"] = candidate_record["reference_runs"]
        rows.append(record)
    columns = []
    for query in column_queries or ():
        record = _query_runs(reference_mask, width, height, query, "column")
        candidate_record = _query_runs(candidate_mask, width, height, query, "column")
        record["candidate_runs"] = candidate_record["reference_runs"]
        columns.append(record)
    result = {
        "reference_path": reference_full,
        "candidate_path": candidate_full,
        "candidate_source": "image" if candidate_path is not None else "paths",
        "image_size": [width, height],
        "threshold": float(threshold),
        "stroke_width_px": float(stroke_width_px),
        "reference_bbox": _mask_bbox(reference_mask, width, height),
        "candidate_bbox": _mask_bbox(candidate_mask, width, height),
        "rois": roi_report,
        "row_queries": rows,
        "column_queries": columns,
    }
    if output_path:
        result["overlay_path"] = _mask_overlay(
            reference, reference_mask, candidate_mask, output_path
        )
    return result
