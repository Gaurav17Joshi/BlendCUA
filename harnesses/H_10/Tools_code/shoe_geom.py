"""Snapshot of the run-local helper, retained only for the original replay."""
import math
import bpy
from mathutils import Vector


def make_material(name, color, roughness=0.5, metallic=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        rgba = tuple(color) if len(tuple(color)) == 4 else tuple(color) + (1.0,)
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = roughness
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.28
    return mat


def assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def _finish(name, verts, faces, mat=None, smooth=True):
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate(verbose=False)
    me.update(calc_edges=True)
    for poly in me.polygons:
        poly.use_smooth = smooth
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    if mat is not None:
        assign(obj, mat)
    return obj


def loft_volume(name, xs, widths, bottoms, tops, mat=None, smooth=True):
    if not (len(xs) == len(widths) == len(bottoms) == len(tops)):
        raise ValueError("loft_volume arrays must have equal lengths")
    verts, rings = [], []
    for x, w, zb, zt in zip(xs, widths, bottoms, tops):
        h = max(zt - zb, 1.0e-4)
        yz = [
            (-0.68*w, zb), (0.68*w, zb),
            (0.94*w, zb + 0.10*h), (1.00*w, zb + 0.32*h),
            (1.00*w, zt - 0.28*h), (0.80*w, zt - 0.06*h),
            (0.00*w, zt), (-0.80*w, zt - 0.06*h),
            (-1.00*w, zt - 0.28*h), (-1.00*w, zb + 0.32*h),
            (-0.94*w, zb + 0.10*h),
        ]
        ring = []
        for y, z in yz:
            ring.append(len(verts))
            verts.append((x, y, z))
        rings.append(ring)
    faces = []
    for a, b in zip(rings[:-1], rings[1:]):
        for j in range(len(a)):
            k = (j + 1) % len(a)
            faces.append((a[j], a[k], b[k], b[j]))
    faces.append(tuple(reversed(rings[0])))
    faces.append(tuple(rings[-1]))
    return _finish(name, verts, faces, mat=mat, smooth=smooth)


def profile_prism(name, profile_xz, y_front, y_back, mat=None, smooth=True):
    verts = [(x, y_front, z) for x, z in profile_xz]
    verts += [(x, y_back, z) for x, z in profile_xz]
    n = len(profile_xz)
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2*n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return _finish(name, verts, faces, mat=mat, smooth=smooth)


def loop_tube(name, points, radius, sides=8, mat=None, smooth=True):
    pts = [Vector(p) for p in points]
    if len(pts) < 3:
        raise ValueError("loop_tube needs at least 3 points")
    radii = [radius] * len(pts) if not hasattr(radius, '__len__') else list(radius)
    verts, rings = [], []
    up = Vector((0.0, 0.0, 1.0))
    for i, p in enumerate(pts):
        tangent = (pts[(i + 1) % len(pts)] - pts[(i - 1) % len(pts)]).normalized()
        n = tangent.cross(up)
        if n.length < 1.0e-6:
            n = tangent.cross(Vector((0.0, 1.0, 0.0)))
        n.normalize()
        b = tangent.cross(n).normalized()
        ring = []
        r = radii[i]
        for k in range(sides):
            a = 2.0 * math.pi * k / sides
            ring.append(len(verts))
            verts.append(tuple(p + r * (math.cos(a)*n + math.sin(a)*b)))
        rings.append(ring)
    faces = []
    for i, a in enumerate(rings):
        b = rings[(i + 1) % len(rings)]
        for k in range(sides):
            j = (k + 1) % sides
            faces.append((a[k], a[j], b[j], b[k]))
    return _finish(name, verts, faces, mat=mat, smooth=smooth)


def add_bevel(obj, width=0.03, segments=2, angle=0.52):
    old = obj.modifiers.get("EdgeSoftness")
    if old is not None:
        obj.modifiers.remove(old)
    bev = obj.modifiers.new("EdgeSoftness", "BEVEL")
    bev.width = width
    bev.segments = int(segments)
    bev.limit_method = 'ANGLE'
    bev.angle_limit = angle
    bev.harden_normals = True
    bev.use_clamp_overlap = True
    return bev


def make_inner_pad(name, xs, widths, z_bottom, z_top, mat=None):
    bottoms = [z_bottom] * len(xs) if not hasattr(z_bottom, '__len__') else list(z_bottom)
    tops = [z_top] * len(xs) if not hasattr(z_top, '__len__') else list(z_top)
    return loft_volume(name, xs, widths, bottoms, tops, mat=mat, smooth=True)
