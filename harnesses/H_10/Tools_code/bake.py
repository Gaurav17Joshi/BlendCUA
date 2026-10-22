"""Low-poly + UV + texture baking. Not specific to any model.

THE POINT OF THE WHOLE EXERCISE
    A sculpt is 660,000 vertices. Nothing ships that. The deliverable is a
    low-poly cage carrying image maps that make it LOOK like the sculpt: the
    normal map fakes the lighting of geometry that is no longer there, and
    the colour map carries the surface. Everything here exists to get from
    one to the other and to prove it worked.

THE LOW POLY IS NOT A DECIMATION
    It is the cage the sculpt was made from. Step 2 keeps a copy before it
    subdivides, so the two share a silhouette EXACTLY and every bake ray has
    somewhere to land. Decimating the finished sculpt instead gives a mesh
    whose silhouette wanders a few millimetres either side of the original,
    and those millimetres show up as black speckle across the normal map.

WHAT COSTS TIME IF YOU GET IT WRONG
    * Baking needs CYCLES. In EEVEE bpy.ops.object.bake either errors or
      silently produces nothing useful, so this module sets the engine and
      puts it back.
    * The bake target is the ACTIVE IMAGE TEXTURE NODE of the low poly's
      material. Not a parameter of the operator — a piece of node state. If
      no node is active, Blender bakes into whatever was active last.
    * Colour space is not cosmetic. A normal map read as sRGB is wrong in a
      way that looks like "the lighting is a bit off" rather than like an
      error: set Non-Color on normals/roughness/AO and sRGB on colour.
    * cage_extrusion has to cover the DEEPEST cut. A 35 mm crack with a
      20 mm cage bakes as a flat patch, because the ray stopped short.
"""

import os

import bpy
import numpy as np


# --------------------------------------------------------------------------
# the low poly and its UVs
# --------------------------------------------------------------------------

def stash_cage(obj_name, cage_name):
    """Copy `obj_name` aside as the low-poly cage, hidden, no modifiers.

    Call this BEFORE densifying. Hidden in both viewport and render so every
    later step's screenshots are unaffected — the cage is luggage until the
    bake needs it.
    """
    src = bpy.data.objects[obj_name]
    if cage_name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[cage_name], do_unlink=True)
    low = src.copy()
    low.data = src.data.copy()
    low.name = cage_name
    low.data.name = cage_name
    for m in list(low.modifiers):
        low.modifiers.remove(m)
    bpy.context.scene.collection.objects.link(low)
    low.hide_viewport = True
    low.hide_render = True
    return low


def show(obj_name, visible=True):
    """Show or hide an object in the viewport AND the render.

    Three separate flags have to agree (`hide_viewport`, `hide_render`,
    `hide_set`) — setting one and not the others is how an object stays
    out of your screenshot but still turns up in the bake.
    """
    o = bpy.data.objects[obj_name]
    o.hide_viewport = not visible
    o.hide_render = not visible
    o.hide_set(not visible)
    return o


def unwrap(obj_name, angle_limit=66.0, island_margin=0.02, method="SMART"):
    """UV the object. Returns (islands, uv_area, faces).

    SMART is Smart UV Project: it cuts on angle, so on a boxy model every
    flat face becomes its own island and nothing is stretched. `uv_area` is
    how much of the 0-1 square the islands actually cover — the number that
    decides how much of a 2048 map is texture and how much is wasted
    background.
    """
    import math
    obj = bpy.data.objects[obj_name]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name="UVMap")

    win, area, region, _ = _viewport()
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        bpy.ops.mesh.select_all(action='SELECT')
        with bpy.context.temp_override(window=win, area=area, region=region):
            if method == "SMART":
                bpy.ops.uv.smart_project(
                    angle_limit=math.radians(angle_limit),
                    island_margin=island_margin,
                    correct_aspect=True, scale_to_bounds=False)
            else:
                bpy.ops.uv.unwrap(method='ANGLE_BASED',
                                  margin=island_margin)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    return uv_stats(obj_name)


def cylindrical_uv(obj_name, uv_name="CylindricalUV", axis=(0.0, 0.0, 1.0),
                   front_direction=(0.0, -1.0, 0.0),
                   right_direction=(1.0, 0.0, 0.0),
                   axis_origin=(0.0, 0.0, 0.0), axis_min=None,
                   axis_max=None, replace=True, space="LOCAL"):
    """Assign a deliberate cylindrical UV layer around an arbitrary axis.

    The mapping is defined by a point on the cylinder's axis, an axial unit
    direction, and two perpendicular directions.  ``front_direction`` is the
    angle-zero direction (therefore ``U=0.5``); ``right_direction`` is the
    positive-angle direction.  The seam is opposite the front at ``U=0``/``1``.
    ``axis_min`` and ``axis_max`` are the axial values mapped to ``V=0`` and
    ``V=1``.  If omitted they are derived from the mesh, but an explicit range
    is preferable when the texture has a shared world datum.  ``space`` is
    ``LOCAL`` by default and may be ``WORLD`` for a transformed object.

    A named existing layer is replaced by default so retries are deterministic.
    The return value is ``{"layer", "islands", "coverage", "faces"}``, using
    the same statistics as :func:`uv_stats`.  No mesh vertex is moved.
    """
    import math
    from mathutils import Vector

    obj = bpy.data.objects.get(obj_name)
    if obj is None or obj.type != 'MESH':
        raise ValueError("cylindrical_uv: mesh %r does not exist" % obj_name)
    if space not in {"LOCAL", "WORLD"}:
        raise ValueError("cylindrical_uv: space must be LOCAL or WORLD")

    axis_v = Vector(axis)
    if axis_v.length < 1.0e-12:
        raise ValueError("cylindrical_uv: axis must be non-zero")
    axis_v.normalize()
    origin = Vector(axis_origin)

    # Remove any axial component before normalising the basis.  This accepts
    # convenient directions that are only approximately perpendicular while
    # rejecting a genuinely degenerate front/right specification.
    front_v = Vector(front_direction) - axis_v * Vector(front_direction).dot(axis_v)
    if front_v.length < 1.0e-12:
        raise ValueError("cylindrical_uv: front_direction is parallel to axis")
    front_v.normalize()
    right_v = Vector(right_direction) - axis_v * Vector(right_direction).dot(axis_v)
    right_v = right_v - front_v * right_v.dot(front_v)
    if right_v.length < 1.0e-12:
        raise ValueError("cylindrical_uv: right_direction is parallel to front_direction")
    right_v.normalize()

    def position(vertex):
        return (obj.matrix_world @ vertex.co) if space == "WORLD" else vertex.co.copy()

    positions = [position(vertex) for vertex in obj.data.vertices]
    axial = [(point - origin).dot(axis_v) for point in positions]
    lo = min(axial) if axis_min is None else float(axis_min)
    hi = max(axial) if axis_max is None else float(axis_max)
    if hi - lo < 1.0e-12:
        raise ValueError("cylindrical_uv: axis_min and axis_max must differ")

    me = obj.data
    existing = me.uv_layers.get(uv_name)
    if existing is not None:
        if replace:
            me.uv_layers.remove(existing)
        else:
            me.uv_layers.active = existing
            islands, coverage, faces = uv_stats(obj_name)
            return {"layer": existing.name, "islands": islands,
                    "coverage": coverage, "faces": faces}
    uv = me.uv_layers.new(name=uv_name)

    for loop in me.loops:
        point = positions[loop.vertex_index]
        delta = point - origin
        t = delta.dot(axis_v)
        radial = delta - axis_v * t
        if radial.length < 1.0e-7:
            u = 0.5
        else:
            phi = math.atan2(radial.dot(right_v), radial.dot(front_v))
            u = 0.5 + phi / (2.0 * math.pi)
        v = max(0.0, min(1.0, (t - lo) / (hi - lo)))
        uv.data[loop.index].uv = (u, v)

    me.uv_layers.active = uv
    me.update()
    islands, coverage, faces = uv_stats(obj_name)
    return {"layer": uv.name, "islands": islands,
            "coverage": coverage, "faces": faces}


def uv_stats(obj_name):
    """(islands, coverage 0-1, faces). Islands counted by connected UV
    vertices, which is what a packer means by an island."""
    me = bpy.data.objects[obj_name].data
    uv = me.uv_layers.active.data
    coords = np.array([tuple(d.uv) for d in uv], dtype=np.float64)

    # union-find over loops that share a UV position
    key = {}
    parent = list(range(len(me.polygons)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for pi, poly in enumerate(me.polygons):
        for li in poly.loop_indices:
            k = (round(coords[li][0], 6), round(coords[li][1], 6))
            if k in key:
                a, b = find(key[k]), find(pi)
                if a != b:
                    parent[a] = b
            else:
                key[k] = pi
    islands = len({find(i) for i in range(len(me.polygons))})

    area = 0.0
    for poly in me.polygons:
        pts = [coords[li] for li in poly.loop_indices]
        for i in range(1, len(pts) - 1):
            a, b, c = pts[0], pts[i], pts[i + 1]
            area += abs((b[0] - a[0]) * (c[1] - a[1])
                        - (c[0] - a[0]) * (b[1] - a[1])) * 0.5
    return islands, area, len(me.polygons)


def uv_layout_png(obj_name, path, size=1024, line=(1.0, 0.85, 0.2)):
    """Draw the UV islands to a PNG, so the layout can be looked at.

    Rasterized here rather than through bpy.ops.uv.export_layout, which
    needs an IMAGE_EDITOR area that this harness has no reason to open.
    """
    me = bpy.data.objects[obj_name].data
    uv = me.uv_layers.active.data
    buf = np.zeros((size, size, 4), dtype=np.float32)
    buf[..., 3] = 1.0

    def draw(p, q):
        x0, y0 = p[0] * (size - 1), p[1] * (size - 1)
        x1, y1 = q[0] * (size - 1), q[1] * (size - 1)
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        xs = np.linspace(x0, x1, n).astype(int).clip(0, size - 1)
        ys = np.linspace(y0, y1, n).astype(int).clip(0, size - 1)
        buf[ys, xs, 0:3] = line

    for poly in me.polygons:
        li = list(poly.loop_indices)
        for a, b in zip(li, li[1:] + li[:1]):
            draw(uv[a].uv, uv[b].uv)

    img = bpy.data.images.new("uv_layout", size, size, alpha=True)
    img.pixels.foreach_set(buf.reshape(-1))
    _save(img, path)
    bpy.data.images.remove(img)
    return path


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

def new_image(name, size=2048, colorspace='Non-Color', fill=(0, 0, 0, 1),
              float_buffer=False):
    """Create a square image to bake into, replacing any of the same name.

    `colorspace` is the one that matters: bake targets carrying DATA
    (normal, AO, roughness, displacement) must be 'Non-Color', and only a
    base-colour map should be 'sRGB'. Getting it wrong does not error —
    the map just comes out subtly wrong in a way that survives to the
    final render. `float_buffer=True` for displacement, which needs the
    range 8 bits cannot hold.
    """
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    img = bpy.data.images.new(name, size, size, alpha=False,
                              float_buffer=float_buffer)
    img.generated_color = fill
    img.colorspace_settings.name = colorspace
    return img


def _save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    return path


def save_image(image_name, path):
    """Write a baked image to `path` as PNG, creating parent dirs."""
    return _save(bpy.data.images[image_name], path)


def load_image(path, colorspace='sRGB'):
    """Load an image file, reusing it if already loaded.

    Same colorspace rule as `new_image`: 'sRGB' for colour, 'Non-Color'
    for anything that is data rather than something you look at.
    """
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = colorspace
    return img


def multiply_images(a_name, b_name, out_name, out_path, b_gain=1.0,
                    b_floor=0.0, tint=(1.0, 1.0, 1.0)):
    """out = a * clamp(b * gain, floor, 1) * tint, saved as sRGB.

    Used to fold a baked AO map into the colour map so the final asset needs
    one texture for base colour instead of a shader that multiplies two.
    `b_floor` stops the crevices going to pure black, which no stone does.
    """
    a = bpy.data.images[a_name]
    b = bpy.data.images[b_name]
    if tuple(a.size) != tuple(b.size):
        raise ValueError("size mismatch %s vs %s" % (a.size[:], b.size[:]))

    pa = np.empty(len(a.pixels), dtype=np.float32)
    pb = np.empty(len(b.pixels), dtype=np.float32)
    a.pixels.foreach_get(pa)
    b.pixels.foreach_get(pb)
    pa = pa.reshape(-1, 4)
    pb = pb.reshape(-1, 4)

    occ = np.clip(pb[:, 0] * b_gain, b_floor, 1.0)[:, None]
    out = pa.copy()
    out[:, 0:3] = np.clip(pa[:, 0:3] * occ * np.array(tint, dtype=np.float32),
                          0.0, 1.0)
    out[:, 3] = 1.0

    img = new_image(out_name, a.size[0], colorspace='sRGB')
    img.pixels.foreach_set(out.reshape(-1))
    _save(img, out_path)
    return img


def tile_from_crop(src_path, out_path, x, y, size, mirror=True,
                   colorspace='sRGB'):
    """Cut a square out of a photographed texture and make it tile.

    Photographed texture sets are usually a picture of a THING — a tiled
    floor, a brick wall — and the thing's own layout comes along with the
    material. A granite floor has exactly the grey speckled stone you want
    and a grid of grout lines you do not. Cropping one tile's interior
    keeps the stone and drops the layout.

    A crop does not tile, so `mirror` builds a 2x2 of the crop and its
    reflections, which does. That trades the seam for a symmetry, and on a
    surface with no features large enough to recognise, a symmetry is
    invisible while a seam is not.

    x, y are TOP-DOWN pixel coordinates, the way an image viewer shows them;
    Blender stores images bottom-up and the flip is handled here.
    """
    src = bpy.data.images.load(src_path, check_existing=False)
    src.colorspace_settings.name = colorspace
    w, h = src.size
    if x + size > w or y + size > h:
        raise ValueError("crop %d+%d, %d+%d does not fit in %dx%d"
                         % (x, size, y, size, w, h))

    buf = np.empty(w * h * 4, dtype=np.float32)
    src.pixels.foreach_get(buf)
    buf = buf.reshape(h, w, 4)[::-1]           # -> top-down
    patch = buf[y:y + size, x:x + size].copy()

    if mirror:
        top = np.concatenate([patch, patch[:, ::-1]], axis=1)
        out = np.concatenate([top, top[::-1]], axis=0)
    else:
        out = patch
    oh, ow = out.shape[:2]

    img = new_image(os.path.splitext(os.path.basename(out_path))[0], ow,
                    colorspace=colorspace)
    if tuple(img.size) != (ow, oh):
        img.scale(ow, oh)
    img.pixels.foreach_set(out[::-1].reshape(-1))   # back to bottom-up
    _save(img, out_path)
    bpy.data.images.remove(src)
    return out_path, (ow, oh)


def image_stats(image_name):
    """(mean, min, max) of RGB — the cheapest proof a bake produced anything
    other than the fill colour it started as."""
    img = bpy.data.images[image_name]
    p = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(p)
    rgb = p.reshape(-1, 4)[:, 0:3]
    return float(rgb.mean()), float(rgb.min()), float(rgb.max())


# --------------------------------------------------------------------------
# materials
# --------------------------------------------------------------------------

def ensure_material(obj_name, mat_name):
    """Give the object exactly one node-based material, named `mat_name`.

    Clears any existing slots first, so the object cannot end up with the
    bake writing into a leftover material from an earlier attempt.
    """
    obj = bpy.data.objects[obj_name]
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return mat


def set_bake_target(obj_name, image_name, mat_name=None):
    """Point the object's material at `image_name` as the bake destination.

    The operator has no image argument: it writes to whichever Image Texture
    node is ACTIVE. Making that explicit here is the difference between a
    bake landing in the map you meant and landing in the previous one.
    """
    obj = bpy.data.objects[obj_name]
    if not obj.data.materials:
        ensure_material(obj_name, mat_name or (obj_name + "_mat"))
    mat = obj.data.materials[0]
    mat.use_nodes = True
    nt = mat.node_tree

    node = nt.nodes.get("BAKE_TARGET")
    if node is None:
        node = nt.nodes.new('ShaderNodeTexImage')
        node.name = "BAKE_TARGET"
        node.location = (-900, 500)
    node.image = bpy.data.images[image_name]
    node.select = True
    nt.nodes.active = node
    return node


# --------------------------------------------------------------------------
# the bake
# --------------------------------------------------------------------------

def _viewport():
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return win, area, region, area.spaces.active.region_3d


def bake(low_name, image_name, high_name=None, bake_type='NORMAL',
         samples=16, cage_extrusion=0.06, max_ray_distance=0.0,
         margin=16, pass_filter=None, device='CPU'):
    """Bake `bake_type` onto `low_name`'s active image.

    With `high_name`, this is a selected-to-active projection bake: rays
    leave the low poly's surface, travel `cage_extrusion` outwards, and look
    back in for the high poly. Without it, the low poly bakes its own
    material.

    Returns the mean/min/max of the result, because a bake that silently did
    nothing looks exactly like a bake that worked until you open the image.
    """
    scene = bpy.context.scene
    prev_engine = scene.render.engine
    scene.render.engine = 'CYCLES'
    prev_samples = scene.cycles.samples
    scene.cycles.samples = samples
    scene.cycles.device = device

    low = show(low_name, True)
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')

    set_bake_target(low_name, image_name)

    if high_name:
        high = bpy.data.objects[high_name]
        show(high_name, True)
        high.select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low     # active = destination

    bs = scene.render.bake
    bs.use_selected_to_active = bool(high_name)
    bs.cage_extrusion = cage_extrusion
    bs.max_ray_distance = max_ray_distance
    bs.margin = margin
    bs.use_clear = True
    if hasattr(bs, "target"):
        bs.target = 'IMAGE_TEXTURES'

    kw = dict(type=bake_type)
    if pass_filter:
        kw["pass_filter"] = set(pass_filter)
    try:
        win, area, region, _ = _viewport()
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.object.bake(**kw)
    finally:
        scene.render.engine = prev_engine
        scene.cycles.samples = prev_samples

    return image_stats(image_name)
