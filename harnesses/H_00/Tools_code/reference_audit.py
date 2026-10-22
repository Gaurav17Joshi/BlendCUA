"""Reference-space image and mesh-mask audits.

The existing silhouette helpers answer an envelope question: where are the
outermost projected vertices?  A branched or open ornament can share that
bbox while putting its strokes in the wrong places.  This module adds a
reference-space occupancy check.  It is deliberately subject-neutral:
callers supply the mesh names, the reference image/Empty, threshold, ROIs,
and row probes.

``compare_image_masks`` is shell-safe and compares two already-rendered
images.  ``audit_projected_mesh`` is the Blender-side half: it rasterizes the
projected evaluated mesh polygons into the reference image's pixel grid and
then calls the same comparison routine.  It can also return per-object or
caller-defined group bboxes and row spans from the same projection pass, so an
outlying row can be assigned to its owning mesh without another custom loop.
Neither function edits the scene.
"""

import colorsys
import json
import math
import os
import statistics
import sys


_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# These values are format/layout constants, not subject measurements: Pillow
# images here use 8-bit RGB channels, and comparison crops reserve a small
# fixed gutter and label band for their two-up captions.
_RGB_CHANNEL_MAX = 255.0
_CROP_GUTTER_PX = 20
_CROP_LABEL_BAND_PX = 36
_CROP_TEXT_PAD_PX = 8
_CROP_BACKGROUND = (245, 245, 245)
_BLACK = (0, 0, 0)


def _resolve(path):
    """Resolve a relative path against the harness root, not Blender's cwd."""
    path = os.fspath(path)
    return path if os.path.isabs(path) else os.path.join(_ROOT, path)


def _pil():
    """Import Pillow, adding the Blender-matched vendored copy when needed."""
    try:
        from PIL import Image, ImageDraw
        return Image, ImageDraw
    except ModuleNotFoundError:
        vendor = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "_vendor")
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        from PIL import Image, ImageDraw
        return Image, ImageDraw


def _load_rgb(path):
    """Load `path` as an RGB Pillow image and return it with its resolved path."""
    Image, _ = _pil()
    full = _resolve(path)
    image = Image.open(full).convert("RGB")
    return image, full


def _luminance_mask(image, threshold):
    """Return a flat byte mask for pixels darker than `threshold`."""
    pixels = image.getdata()
    return bytearray(
        1 if 0.2126 * r + 0.7152 * g + 0.0722 * b < threshold else 0
        for r, g, b in pixels
    )


def _mask_bbox(mask, width, height):
    """Return an inclusive [x0,y0,x1,y1,w,h] bbox, or None for an empty mask."""
    x0, y0 = width, height
    x1 = y1 = -1
    for index, value in enumerate(mask):
        if not value:
            continue
        y, x = divmod(index, width)
        x0 = min(x0, x)
        x1 = max(x1, x)
        y0 = min(y0, y)
        y1 = max(y1, y)
    if x1 < 0:
        return None
    return [x0, y0, x1, y1, x1 - x0 + 1, y1 - y0 + 1]


def _runs(values, min_width=1):
    """Return inclusive [start,end,width,center] runs in a sorted index list."""
    values = [int(v) for v in values]
    if not values:
        return []
    out = []
    start = previous = values[0]
    for value in values[1:]:
        if value > previous + 1:
            width = previous - start + 1
            if width >= min_width:
                out.append([start, previous, width, round((start + previous) / 2.0, 1)])
            start = value
        previous = value
    width = previous - start + 1
    if width >= min_width:
        out.append([start, previous, width, round((start + previous) / 2.0, 1)])
    return out


def _row_runs(mask, width, height, y, x0, x1, min_width):
    """Return dark runs on image row `y` over the half-open x interval."""
    y = int(y)
    x0 = max(0, int(x0))
    x1 = min(width, int(x1))
    if y < 0 or y >= height or x1 <= x0:
        return []
    start = y * width
    return _runs((x for x in range(x0, x1) if mask[start + x]), min_width)


def _parse_row_query(query):
    """Return (row, x0, x1, min_width) for the public row-query forms."""
    if isinstance(query, dict):
        y = query["y"]
        x0 = query["x0"]
        x1 = query["x1"]
        min_width = query.get("min_width", 1)
    else:
        if len(query) == 3:
            y, x0, x1 = query
            min_width = 1
        elif len(query) == 4:
            y, x0, x1, min_width = query
        else:
            raise ValueError("row query must have 3 or 4 values")
    return int(y), int(x0), int(x1), int(min_width)


def _roi_metrics(reference_mask, candidate_mask, width, height, box):
    """Compute occupancy counts and IoU for one half-open ROI."""
    x0, y0, x1, y1 = (int(v) for v in box)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    ref_count = candidate_count = intersection = union = 0
    for y in range(y0, y1):
        start = y * width
        for x in range(x0, x1):
            a = bool(reference_mask[start + x])
            b = bool(candidate_mask[start + x])
            ref_count += int(a)
            candidate_count += int(b)
            intersection += int(a and b)
            union += int(a or b)
    return {
        "box": [x0, y0, x1, y1],
        "reference_pixels": ref_count,
        "candidate_pixels": candidate_count,
        "intersection": intersection,
        "union": union,
        "iou": round(intersection / union, 6) if union else None,
        "candidate_precision": round(intersection / candidate_count, 6) if candidate_count else None,
        "candidate_recall": round(intersection / ref_count, 6) if ref_count else None,
    }


def _overlay_image(reference, reference_mask, candidate_mask, width, height,
                   output_path):
    """Write a red/blue false-colour occupancy overlay."""
    Image, _ = _pil()
    source = list(reference.getdata())
    pixels = []
    for index, original in enumerate(source):
        ref_hit = bool(reference_mask[index])
        candidate_hit = bool(candidate_mask[index])
        if ref_hit and candidate_hit:
            pixels.append((35, 35, 35))
        elif ref_hit:
            pixels.append((255, 75, 55))       # reference-only occupancy
        elif candidate_hit:
            pixels.append((45, 125, 255))      # candidate-only occupancy
        else:
            pixels.append(original)
    out = Image.new("RGB", (width, height))
    out.putdata(pixels)
    full = _resolve(output_path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    out.save(full)
    return full


def compare_image_masks(reference_path, candidate_path, threshold=145,
                        rois=None, row_queries=None, output_path=None):
    """Compare dark occupancy in two same-sized images.

    ``reference_path`` and ``candidate_path`` can be absolute or harness-root
    relative.  A pixel is occupied when its sRGB luminance is below
    ``threshold``; the threshold is explicit because material and lighting
    determine what a render mask means.

    ``rois`` is an optional mapping of labels to half-open
    ``(x0, y0, x1, y1)`` boxes.  If omitted, one full-image ROI is reported.
    ``row_queries`` is an optional iterable of either
    ``(y, x0, x1)`` / ``(y, x0, x1, min_width)`` tuples or dictionaries with
    those keys.  Each query returns the reference and candidate dark runs,
    which exposes a wrong branch even when its overall bbox is correct.

    When ``output_path`` is supplied, a false-colour overlay is written with
    red reference-only pixels and blue candidate-only pixels.  The return
    value contains the two bboxes, total counts, per-ROI IoU/precision/recall,
    and the requested row evidence.  This function does not use ``bpy`` and
    is safe to call from a shell analysis script.
    """
    reference, reference_full = _load_rgb(reference_path)
    candidate, candidate_full = _load_rgb(candidate_path)
    if reference.size != candidate.size:
        raise ValueError(
            "compare_image_masks: image sizes differ: %s vs %s"
            % (reference.size, candidate.size)
        )
    width, height = reference.size
    threshold = float(threshold)
    reference_mask = _luminance_mask(reference, threshold)
    candidate_mask = _luminance_mask(candidate, threshold)

    if rois is None:
        rois = {"full_image": [0, 0, width, height]}
    roi_report = {
        str(label): _roi_metrics(reference_mask, candidate_mask, width, height, box)
        for label, box in rois.items()
    }

    query_report = []
    for query in row_queries or []:
        y, x0, x1, min_width = _parse_row_query(query)
        query_report.append({
            "y": y,
            "x_range": [x0, x1],
            "min_width": min_width,
            "reference_runs": _row_runs(reference_mask, width, height, y, x0, x1, min_width),
            "candidate_runs": _row_runs(candidate_mask, width, height, y, x0, x1, min_width),
        })

    result = {
        "reference_path": reference_full,
        "candidate_path": candidate_full,
        "image_size": [width, height],
        "threshold": threshold,
        "reference_bbox": _mask_bbox(reference_mask, width, height),
        "candidate_bbox": _mask_bbox(candidate_mask, width, height),
        "reference_pixels": sum(reference_mask),
        "candidate_pixels": sum(candidate_mask),
        "rois": roi_report,
        "row_queries": query_report,
    }
    if output_path:
        result["overlay_path"] = _overlay_image(
            reference, reference_mask, candidate_mask, width, height, output_path
        )
    return result


def _reference_world_matrix(ref):
    """Return the usable world transform for an image Empty.

    Blender 5.2 can leave an unparented Empty's RNA ``matrix_world`` stale
    after a direct ``rotation_euler`` assignment until a later UI operation.
    ``matrix_basis`` already contains that authored transform, so prefer it
    when the two disagree.  Parent/constraint cases retain Blender's evaluated
    world matrix rather than guessing a hierarchy.
    """
    world = ref.matrix_world.copy()
    if ref.parent is None:
        basis = ref.matrix_basis.copy()
        if max(
            abs(float(world[row][column] - basis[row][column]))
            for row in range(4)
            for column in range(4)
        ) > 1.0e-6:
            world = basis
    return world


def _reference_projector(ref):
    """Return (width, height, world_to_image_px) for an image Empty."""
    from mathutils import Vector

    if ref is None or ref.type != "EMPTY" or ref.empty_display_type != "IMAGE":
        raise ValueError("audit_projected_mesh: ref_name must name an image Empty")
    if ref.data is None:
        raise ValueError("audit_projected_mesh: image Empty has no image data")
    image_width, image_height = (int(v) for v in ref.data.size)
    if image_width < 1 or image_height < 1:
        raise ValueError("audit_projected_mesh: reference image has no pixels")

    size = float(ref.empty_display_size)
    if size <= 0.0:
        raise ValueError("audit_projected_mesh: Empty display size must be positive")
    if image_width >= image_height:
        rect_width = size
        rect_height = size * image_height / image_width
    else:
        rect_width = size * image_width / image_height
        rect_height = size
    offset_x, offset_y = (float(v) for v in ref.empty_image_offset)
    inverse = _reference_world_matrix(ref).inverted()

    def project(world_point):
        local = inverse @ Vector(world_point)
        u = local.x / rect_width - offset_x
        v = 1.0 - (local.y / rect_height - offset_y)
        return (u * image_width, v * image_height)

    return image_width, image_height, project


def _probe_specs(values, label):
    """Normalize a sequence or label->pixel mapping into ordered probes."""
    if values is None:
        return []
    items = list(values.items()) if isinstance(values, dict) else [
        (str(value), value) for value in values
    ]
    out = []
    for name, value in items:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError("%s coordinates must be numeric" % label) from None
        if not math.isfinite(number):
            raise ValueError("%s coordinates must be finite" % label)
        out.append((str(name), number))
    return out


def _cluster_values(values, gap):
    """Merge nearby line crossings caused by adjacent polygon edges."""
    values = sorted(float(value) for value in values)
    if not values:
        return []
    groups = [[values[0]]]
    for value in values[1:]:
        if value - groups[-1][-1] > gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [sum(group) / len(group) for group in groups]


def _line_intersections(segments, axis, value):
    """Intersect projected segments with an x (axis 0) or y (axis 1) line."""
    # This epsilon is only for coincident floating-point endpoints after
    # transforming an Image Empty; it is far below one source pixel.
    endpoint_tolerance = 1.0e-6
    other = 1 - axis
    hits = []
    for p0, p1, _object_name in segments:
        c0, c1 = p0[axis], p1[axis]
        delta = c1 - c0
        if abs(delta) <= endpoint_tolerance:
            if abs(c0 - value) <= endpoint_tolerance:
                hits.extend((p0[other], p1[other]))
            continue
        if min(c0, c1) - endpoint_tolerance <= value <= max(c0, c1) + endpoint_tolerance:
            t = (value - c0) / delta
            if -endpoint_tolerance <= t <= 1.0 + endpoint_tolerance:
                hits.append(p0[other] + t * (p1[other] - p0[other]))
    return hits


def _line_span(values, gap):
    """Return clustered crossings and an exact outer span in pixels."""
    raw_count = len(values)
    crossings = _cluster_values(values, gap)
    result = {
        "intersections_px": [round(value, 5) for value in crossings],
        "raw_intersection_count": raw_count,
        "span_px": None,
    }
    if len(crossings) >= 2:
        result.update({
            "min_px": round(crossings[0], 5),
            "max_px": round(crossings[-1], 5),
            "span_px": round(crossings[-1] - crossings[0], 5),
        })
    return result


def _landmark_target(spec):
    """Read a normalized ``(u, v)`` target and optional group label."""
    group = None
    value = spec
    if isinstance(spec, dict):
        group = spec.get("group")
        if "uv" in spec:
            value = spec["uv"]
        elif "u" in spec and "v" in spec:
            value = (spec["u"], spec["v"])
        elif "point" in spec:
            value = spec["point"]
        else:
            raise ValueError(
                "landmark dict must contain uv, u/v, or point"
            )
    if len(value) != 2:
        raise ValueError("landmark targets must contain normalized (u, v)")
    u, v = (float(component) for component in value)
    if not math.isfinite(u) or not math.isfinite(v):
        raise ValueError("landmark targets must be finite")
    return (u, v), (str(group) if group is not None else None)


def _nearest_segment(target_px, segments, width, height):
    """Find a pixel-space closest point on a projected segment list."""
    if not segments:
        return None
    tx, ty = target_px
    best = None
    for p0, p1, object_name in segments:
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        denominator = dx * dx + dy * dy
        t = 0.0 if denominator <= 1.0e-12 else (
            ((tx - p0[0]) * dx + (ty - p0[1]) * dy) / denominator
        )
        t = max(0.0, min(1.0, t))
        point = (p0[0] + t * dx, p0[1] + t * dy)
        distance = math.hypot(point[0] - tx, point[1] - ty)
        candidate = (distance, point[0], point[1], object_name, t)
        if best is None or candidate[0] < best[0]:
            best = candidate
    distance, x, y, object_name, fraction = best
    return {
        "projected_px": [round(x, 5), round(y, 5)],
        "projected_uv": [round(x / width, 7), round(y / height, 7)],
        "delta_px": [round(x - tx, 5), round(y - ty, 5)],
        "distance_px": round(distance, 5),
        "segment_object": object_name,
        "segment_fraction": round(fraction, 6),
    }


def _projected_edge_report(projected_by_name, segments_by_name, group_specs,
                           width, height, edge_rows, edge_columns,
                           landmarks, cluster_gap_norm):
    """Build exact edge probes after the evaluated meshes have been projected."""
    row_specs = _probe_specs(edge_rows, "edge row")
    column_specs = _probe_specs(edge_columns, "edge column")
    gap_x = float(cluster_gap_norm) * width
    gap_y = float(cluster_gap_norm) * height

    all_segments = [
        segment
        for name in projected_by_name
        for segment in segments_by_name.get(name, ())
    ]
    group_reports = {}
    for label, group_names in group_specs.items():
        segments = [
            segment
            for name in group_names
            for segment in segments_by_name.get(name, ())
        ]
        points = [
            point
            for name in group_names
            for point in projected_by_name.get(name, ())
        ]
        report = {
            "objects": list(group_names),
            "segment_count": len(segments),
            "rows": {},
            "columns": {},
        }
        if points:
            report["vertex_bbox_px"] = [
                round(min(point[0] for point in points), 5),
                round(min(point[1] for point in points), 5),
                round(max(point[0] for point in points), 5),
                round(max(point[1] for point in points), 5),
            ]
        for label_name, row in row_specs:
            hit = _line_span(_line_intersections(segments, 1, row), gap_x)
            hit["source_row_px"] = row
            report["rows"][label_name] = hit
        for label_name, column in column_specs:
            hit = _line_span(_line_intersections(segments, 0, column), gap_y)
            hit["source_column_px"] = column
            report["columns"][label_name] = hit
        group_reports[str(label)] = report

    landmark_reports = {}
    for label, spec in (landmarks or {}).items():
        (u, v), group = _landmark_target(spec)
        if group is not None:
            if group not in group_specs:
                raise ValueError("landmark %r names unknown group %r" % (label, group))
            candidates = [
                segment
                for name in group_specs[group]
                for segment in segments_by_name.get(name, ())
            ]
        else:
            candidates = all_segments
        target_px = (u * width, v * height)
        nearest = _nearest_segment(target_px, candidates, width, height)
        record = {
            "target_uv": [round(u, 7), round(v, 7)],
            "target_px": [round(target_px[0], 5), round(target_px[1], 5)],
            "group": group,
        }
        if nearest is None:
            record["projected_px"] = None
        else:
            record.update(nearest)
        landmark_reports[str(label)] = record

    return {
        "image_size": [width, height],
        "view_direction_world": None,
        "cluster_gap_norm": float(cluster_gap_norm),
        "groups": group_reports,
        "landmarks": landmark_reports,
    }


def audit_projected_mesh(obj_names, reference_path, ref_name="Reference",
                         threshold=145, rois=None, row_queries=None,
                         output_prefix=None, groups=None, row_band=5.0,
                         edge_rows=None, edge_columns=None, landmarks=None,
                         view_direction=None, cluster_gap_norm=0.004):
    """Rasterize evaluated mesh polygons in reference pixels and compare them.

    ``obj_names`` is one mesh name or an iterable of mesh names.  Their
    evaluated world-space faces are projected through the image Empty named by
    ``ref_name`` and unioned into a black-on-white candidate image at the
    reference's native resolution.  ``reference_path`` is the source image to
    compare against.  ``rois`` and ``row_queries`` have the same contracts as
    :func:`compare_image_masks` and should isolate the feature being judged
    instead of mixing unrelated frame/rail pixels into one score.

    ``output_prefix`` is optional.  When set, the function writes
    ``<prefix>_model.png``, ``<prefix>_overlay.png``, and ``<prefix>.json``.
    ``groups`` is an optional mapping from an arbitrary report label to one
    selected mesh name or an iterable of selected mesh names.  Each group gets
    an evaluated source-pixel bbox and a span report at every requested row.
    When omitted, one group is made for each selected object, which exposes the
    owning mesh without a second hand-written projection loop.  ``row_band`` is
    the half-width in source pixels used for those vertex span reports.

    ``edge_rows`` and ``edge_columns`` optionally request exact intersections of
    the projected front/back silhouette edges with source-image rows and
    columns.  They accept a sequence of pixel coordinates or a mapping from
    caller labels to coordinates.  Unlike the older vertex-band ``row_queries``
    report, these probes interpolate along evaluated mesh edges, which is
    important for a sparse low-poly profile whose measured row falls between
    rings.  ``cluster_gap_norm`` merges duplicate intersections from adjacent
    faces in normalized image units.  ``view_direction`` is the world-space
    direction from the camera toward the mesh; when omitted, the negative normal
    of the reference Image Empty is used.

    ``landmarks`` optionally maps labels to normalized ``(u, v)`` target points
    (top-left image origin).  The returned nearest projected silhouette point,
    owning object, and pixel residual make endpoint placement and full-envelope
    errors independently visible.  The exact edge report is read-only and does
    not replace the occupancy comparison or the existing vertex-band report.

    The return value is the full JSON-ready report.  This is a read-only
    inspection: no object, material, camera, or visibility state is changed.
    """
    import bpy

    if isinstance(obj_names, str):
        names = [obj_names]
    else:
        names = list(obj_names)
    if not names:
        raise ValueError("audit_projected_mesh: at least one mesh name is required")
    row_band = float(row_band)
    if row_band < 0.0:
        raise ValueError("audit_projected_mesh: row_band must be non-negative")
    cluster_gap_norm = float(cluster_gap_norm)
    if cluster_gap_norm < 0.0:
        raise ValueError(
            "audit_projected_mesh: cluster_gap_norm must be non-negative"
        )
    queries = list(row_queries or [])
    parsed_queries = [_parse_row_query(query) for query in queries]

    if groups is None:
        group_specs = {name: [name] for name in names}
    else:
        if not isinstance(groups, dict) or not groups:
            raise ValueError("audit_projected_mesh: groups must be a non-empty mapping")
        group_specs = {}
        for label, members in groups.items():
            group_names = [members] if isinstance(members, str) else list(members)
            if not group_names:
                raise ValueError("audit_projected_mesh: group %r has no meshes" % label)
            missing = [name for name in group_names if name not in names]
            if missing:
                raise ValueError(
                    "audit_projected_mesh: group %r contains unselected meshes %s"
                    % (label, missing)
                )
            group_specs[str(label)] = group_names

    ref = bpy.data.objects.get(ref_name)
    width, height, project = _reference_projector(ref)
    from mathutils import Vector
    if view_direction is None:
        image_normal = _reference_world_matrix(ref).to_3x3() @ Vector((0.0, 0.0, 1.0))
        if image_normal.length <= 1.0e-12:
            raise ValueError("audit_projected_mesh: reference normal is degenerate")
        view_direction_world = -image_normal.normalized()
    else:
        view_direction_world = Vector(view_direction)
        if view_direction_world.length <= 1.0e-12:
            raise ValueError(
                "audit_projected_mesh: view_direction must be non-zero"
            )
        view_direction_world.normalize()

    Image, ImageDraw = _pil()
    model = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(model)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    projected_by_name = {}
    segments_by_name = {}

    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise ValueError("audit_projected_mesh: mesh %r does not exist" % name)
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            world_matrix = evaluated.matrix_world
            projected = [project(world_matrix @ vertex.co)
                         for vertex in mesh.vertices]
            projected_by_name[name] = projected

            # A projected edge is part of this object's profile when it is a
            # mesh boundary or its adjacent face normals change from toward to
            # away from the caller's view direction.  This is the exact
            # low-poly analogue of the visible silhouette, rather than a sparse
            # vertex-bin approximation.
            normal_matrix = world_matrix.to_3x3().inverted().transposed()
            front_facing = []
            for polygon in mesh.polygons:
                normal = normal_matrix @ polygon.normal
                front_facing.append(
                    normal.length > 1.0e-12
                    and normal.normalized().dot(view_direction_world) < 0.0
                )
            edge_faces = {}
            for polygon_index, polygon in enumerate(mesh.polygons):
                for edge_key in polygon.edge_keys:
                    edge = tuple(sorted(edge_key))
                    edge_faces.setdefault(edge, []).append(polygon_index)
            segments = []
            for edge, face_ids in edge_faces.items():
                is_silhouette = len(face_ids) == 1 or (
                    len(face_ids) >= 2
                    and any(
                        front_facing[left] != front_facing[right]
                        for index, left in enumerate(face_ids)
                        for right in face_ids[index + 1:]
                    )
                )
                if is_silhouette:
                    a, b = edge
                    segments.append((projected[a], projected[b], name))
            segments_by_name[name] = segments

            for poly in mesh.polygons:
                if len(poly.vertices) < 3:
                    continue
                points = [
                    (int(round(projected[index][0])),
                     int(round(projected[index][1])))
                    for index in poly.vertices
                ]
                draw.polygon(points, fill=(0, 0, 0))
        finally:
            evaluated.to_mesh_clear()

    def source_group_report(group_names):
        points = [point for name in group_names
                  for point in projected_by_name[name]]
        if not points:
            raise ValueError("audit_projected_mesh: group has no projected vertices")
        rows = []
        for y, x0, x1, min_width in parsed_queries:
            values = [point[0] for point in points
                      if x0 <= point[0] < x1 and abs(point[1] - y) <= row_band]
            span = None
            if len(values) >= 2:
                lo, hi = min(values), max(values)
                span = {
                    "x_range": [round(lo, 3), round(hi, 3)],
                    "width_px": round(hi - lo, 3),
                    "vertex_count": len(values),
                }
            rows.append({
                "y": y,
                "x_range": [x0, x1],
                "min_width": min_width,
                "span": span,
            })
        return {
            "objects": list(group_names),
            "vertex_count": len(points),
            "bbox_px": [
                round(min(point[0] for point in points), 3),
                round(min(point[1] for point in points), 3),
                round(max(point[0] for point in points), 3),
                round(max(point[1] for point in points), 3),
            ],
            "row_spans": rows,
        }

    if output_prefix:
        prefix = _resolve(output_prefix)
        os.makedirs(os.path.dirname(prefix) or ".", exist_ok=True)
        model_path = prefix + "_model.png"
        overlay_path = prefix + "_overlay.png"
        model.save(model_path)
    else:
        model_path = None
        overlay_path = None

    report = compare_image_masks(
        reference_path,
        model_path or _write_temp_model(model),
        threshold=threshold,
        rois=rois,
        row_queries=queries,
        output_path=overlay_path,
    )
    report["reference_empty"] = ref_name
    report["objects"] = names
    report["model_mask_path"] = model_path
    report["output_prefix"] = _resolve(output_prefix) if output_prefix else None
    report["row_band_px"] = row_band
    report["projected_groups"] = {
        label: source_group_report(group_names)
        for label, group_names in group_specs.items()
    }
    exact_edges = _projected_edge_report(
        projected_by_name,
        segments_by_name,
        group_specs,
        width,
        height,
        edge_rows,
        edge_columns,
        landmarks,
        cluster_gap_norm,
    )
    exact_edges["view_direction_world"] = [
        round(float(value), 8) for value in view_direction_world
    ]
    report["projected_edge_probes"] = exact_edges

    if output_prefix:
        report_path = _resolve(output_prefix) + ".json"
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        report["report_path"] = report_path
    return report


def _role_mask(image, spec):
    """Build a byte mask from a small, JSON-friendly RGB/HSV role spec."""
    if not isinstance(spec, dict):
        raise TypeError("role spec must be a dict")
    channels = {"r": 0, "g": 1, "b": 2}
    hue_range = spec.get("hue_range", spec.get("hue"))
    if hue_range is not None and len(hue_range) != 2:
        raise ValueError("role hue_range must contain two values")

    def channel_value(rgb, name):
        try:
            return rgb[channels[str(name).lower()]]
        except (KeyError, IndexError):
            raise ValueError("unknown channel %r; use r, g, or b" % name) from None

    def hit(rgb):
        r, g, b = rgb
        h, s, v = colorsys.rgb_to_hsv(r / _RGB_CHANNEL_MAX,
                                      g / _RGB_CHANNEL_MAX,
                                      b / _RGB_CHANNEL_MAX)
        if hue_range is not None:
            lo, hi = (float(x) for x in hue_range)
            in_hue = (lo < h < hi) if lo <= hi else (h > lo or h < hi)
            if not in_hue:
                return False
        if "saturation_min" in spec and s <= float(spec["saturation_min"]):
            return False
        if "saturation_max" in spec and s >= float(spec["saturation_max"]):
            return False
        if "value_min" in spec and v <= float(spec["value_min"]):
            return False
        if "value_max" in spec and v >= float(spec["value_max"]):
            return False
        for name, minimum in spec.get("channel_min", {}).items():
            if channel_value(rgb, name) <= float(minimum):
                return False
        for name, maximum in spec.get("channel_max", {}).items():
            if channel_value(rgb, name) >= float(maximum):
                return False
        for rule in spec.get("channel_ratios", ()):
            if isinstance(rule, dict):
                numerator = rule.get("numerator")
                denominator = rule.get("denominator")
                minimum = rule.get("minimum", rule.get("min"))
            else:
                if len(rule) != 3:
                    raise ValueError(
                        "channel ratio tuples must be (numerator, denominator, minimum)"
                    )
                numerator, denominator, minimum = rule
            if numerator is None or denominator is None or minimum is None:
                raise ValueError(
                    "channel ratio needs numerator, denominator, and minimum"
                )
            den = channel_value(rgb, denominator)
            if den == 0.0 or channel_value(rgb, numerator) <= den * float(minimum):
                return False
        return True

    return bytearray(1 if hit(rgb) else 0 for rgb in image.getdata())


def _role_stats(image, mask):
    """Return bbox, count, and RGB percentiles for one role mask."""
    width, height = image.size
    values = [rgb for rgb, flag in zip(image.getdata(), mask) if flag]
    box = _mask_bbox(mask, width, height)
    stats = None
    if values:
        stats = {"n": len(values)}
        for percentile, label in ((10, "p10"), (50, "p50"), (90, "p90")):
            index = min(len(values) - 1, len(values) * percentile // 100)
            stats[label] = tuple(
                sorted(rgb[channel] for rgb in values)[index]
                for channel in range(3)
            )
    return {"bbox": box, "pixels": len(values), "stats": stats}


def _patch_median(image, box):
    """Return the per-channel median of a half-open image patch."""
    x0, y0, x1, y1 = (int(v) for v in box)
    values = list(image.crop((x0, y0, x1, y1)).getdata())
    if not values:
        return None
    return tuple(
        int(statistics.median(rgb[channel] for rgb in values))
        for channel in range(3)
    )


def _safe_label(label):
    """Make a report label safe to use as a filename component."""
    out = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(label))
    return out or "item"


def _save_crop_pair(reference, candidate, label, box, output_path, scale):
    """Write one candidate-left/reference-right comparison crop."""
    Image, ImageDraw = _pil()
    x0, y0, x1, y1 = (int(v) for v in box)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("crop boxes must have positive width and height")
    left = candidate.crop((x0, y0, x1, y1))
    right = reference.crop((x0, y0, x1, y1))
    scale = int(scale)
    if scale < 1:
        raise ValueError("crop scale must be at least 1")
    if scale != 1:
        left = left.resize((left.width * scale, left.height * scale), Image.Resampling.LANCZOS)
        right = right.resize((right.width * scale, right.height * scale), Image.Resampling.LANCZOS)
    canvas = Image.new(
        "RGB",
        (left.width + right.width + _CROP_GUTTER_PX,
         max(left.height, right.height) + _CROP_LABEL_BAND_PX),
        _CROP_BACKGROUND,
    )
    canvas.paste(left, (0, _CROP_LABEL_BAND_PX))
    canvas.paste(right, (left.width + _CROP_GUTTER_PX, _CROP_LABEL_BAND_PX))
    draw = ImageDraw.Draw(canvas)
    draw.text((_CROP_TEXT_PAD_PX, _CROP_TEXT_PAD_PX), "CANDIDATE", fill=_BLACK)
    draw.text((left.width + _CROP_GUTTER_PX + _CROP_TEXT_PAD_PX,
               _CROP_TEXT_PAD_PX), "REFERENCE", fill=_BLACK)
    full = _resolve(output_path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    canvas.save(full)
    return full


def audit_render(reference_path, candidate_path, roles, rois=None,
                 row_queries=None, patches=None, crops=None,
                 output_prefix=None, crop_scale=2, write_overlays=True):
    """Audit same-sized reference/candidate renders with explicit colour roles.

    ``roles`` maps a neutral role label to a JSON-friendly spec.  A spec may
    contain ``hue_range`` (normalised HSV), ``saturation_min/max``,
    ``value_min/max``, ``channel_min/max`` mappings, and ``channel_ratios``.
    A ratio is either ``(numerator, denominator, minimum)`` or a dict with
    ``numerator``, ``denominator``, and ``minimum``.  For example, a green role
    can require ``g > r * 1.02`` without baking a subject name into this tool.

    The report contains per-role RGB percentiles and inclusive bboxes for both
    images, optional per-role ROI precision/recall/IoU, row runs, patch
    medians, and (when ``output_prefix`` is set) false-colour overlays and
    candidate-left/reference-right crops.  This is read-only and uses the
    same image pixels for measurement and visual evidence; it is safe to call
    from a shell script or from a Blender action after a real render.
    """
    if not isinstance(roles, dict) or not roles:
        raise ValueError("audit_render: roles must be a non-empty mapping")
    reference, reference_full = _load_rgb(reference_path)
    candidate, candidate_full = _load_rgb(candidate_path)
    if reference.size != candidate.size:
        raise ValueError(
            "audit_render: image sizes differ: %s vs %s"
            % (reference.size, candidate.size)
        )
    width, height = reference.size
    reference_masks = {str(name): _role_mask(reference, spec)
                       for name, spec in roles.items()}
    candidate_masks = {str(name): _role_mask(candidate, spec)
                       for name, spec in roles.items()}

    report = {
        "reference_path": reference_full,
        "candidate_path": candidate_full,
        "image_size": [width, height],
        "roles": {},
        "rois": {},
        "row_queries": [],
        "patches": {},
        "crops": {},
        "output_files": {},
    }
    for name, spec in roles.items():
        key = str(name)
        report["roles"][key] = {
            "spec": spec,
            "reference": _role_stats(reference, reference_masks[key]),
            "candidate": _role_stats(candidate, candidate_masks[key]),
        }

    for label, box in (rois or {}).items():
        report["rois"][str(label)] = {
            key: _roi_metrics(reference_masks[key], candidate_masks[key],
                              width, height, box)
            for key in report["roles"]
        }

    for query in row_queries or ():
        if not isinstance(query, dict):
            raise TypeError("audit_render row queries must be dicts with a role")
        key = str(query["role"])
        if key not in report["roles"]:
            raise KeyError("audit_render row query names unknown role %r" % key)
        y = int(query["y"])
        x0 = int(query.get("x0", 0))
        x1 = int(query.get("x1", width))
        min_width = int(query.get("min_width", 1))
        report["row_queries"].append({
            "role": key,
            "y": y,
            "x_range": [x0, x1],
            "min_width": min_width,
            "reference_runs": _row_runs(reference_masks[key], width, height,
                                         y, x0, x1, min_width),
            "candidate_runs": _row_runs(candidate_masks[key], width, height,
                                         y, x0, x1, min_width),
        })

    for label, box in (patches or {}).items():
        report["patches"][str(label)] = {
            "box": [int(v) for v in box],
            "reference_median": _patch_median(reference, box),
            "candidate_median": _patch_median(candidate, box),
        }

    prefix = _resolve(output_prefix) if output_prefix else None
    if prefix:
        os.makedirs(os.path.dirname(prefix) or ".", exist_ok=True)
        if write_overlays:
            for key in report["roles"]:
                path = prefix + "_" + _safe_label(key) + "_overlay.png"
                report["output_files"][key + "_overlay"] = _overlay_image(
                    reference, reference_masks[key], candidate_masks[key],
                    width, height, path
                )
        for label, box in (crops or {}).items():
            path = prefix + "_" + _safe_label(label) + ".png"
            report["crops"][str(label)] = _save_crop_pair(
                reference, candidate, label, box, path, crop_scale
            )
        report_path = prefix + ".json"
        report["output_files"]["report"] = report_path
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    else:
        report["crops"] = {str(label): {"box": [int(v) for v in box]}
                           for label, box in (crops or {}).items()}
    return report


def _write_temp_model(image):
    """Save a no-prefix model image under the harness temp directory."""
    path = os.path.join(_ROOT, "mem", "_reference_audit_model.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path)
    return path
