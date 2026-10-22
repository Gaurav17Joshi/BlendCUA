"""Low-sided tapered opening geometry for measured skull recesses.

The helper deliberately separates disposable cutters from retained open-cup
liners. A cutter is a closed frustum for Boolean DIFFERENCE. A liner is an
intentional open-boundary cup: its front lip seats into the cut surface, its
inner wall slopes rearward, and a faceted rear cap gives the recess visible
depth without putting a flat face across the opening.
"""

import math
import bpy
from mathutils import Vector


def _remove(name):
    old = bpy.data.objects.get(name)
    if old is None:
        return
    data = getattr(old, "data", None)
    bpy.data.objects.remove(old, do_unlink=True)
    if data is not None and getattr(data, "users", 0) == 0 and data.name in bpy.data.meshes:
        bpy.data.meshes.remove(data)


def _ring(center, right, up, out, depth, rx, rz, scale, sides, phase=0.0):
    c = Vector(center) + Vector(out) * float(depth)
    r = Vector(right)
    u = Vector(up)
    return [tuple(c + r * (float(rx) * scale * math.cos(2.0 * math.pi * i / sides + phase))
                  + u * (float(rz) * scale * math.sin(2.0 * math.pi * i / sides + phase)))
            for i in range(sides)]


def create_tapered_cutter(name, center, right=(1, 0, 0), up=(0, 0, 1),
                          out=(0, 1, 0), rx=0.2, rz=0.2,
                          front_depth=0.1, back_depth=1.0,
                          front_scale=1.0, back_scale=0.72,
                          sides=12, phase=0.0):
    """Create and return a hidden-render closed tapered Boolean cutter."""
    front = _ring(center, right, up, out, front_depth, rx, rz, front_scale, sides, phase)
    back = _ring(center, right, up, out, -back_depth, rx, rz, back_scale, sides, phase)
    verts = front + back
    faces = [list(reversed(range(sides))), list(range(sides, 2 * sides))]
    for i in range(sides):
        j = (i + 1) % sides
        faces.append([i, j, sides + j, sides + i])
    _remove(name)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.hide_render = True
    return obj


def create_open_cup_liner(name, center, material, right=(1, 0, 0), up=(0, 0, 1),
                           out=(0, 1, 0), rx=0.2, rz=0.2,
                           lip_depth=0.0, rear_depth=-0.42, cap_depth=-0.62,
                           inner_scale=0.80, rear_scale=0.43,
                           sides=12, phase=0.0, role="intentional-open-boundary cavity liner",
                           owner="Cranium+Midface"):
    """Create a faceted cup with a named intentional front-lip boundary.

    The front outer ring is the only boundary. The inner wall and rear cap are
    manifold; the open lip is what lets this liner seat into a Boolean opening
    without a coplanar cap hiding the cavity.
    """
    a = _ring(center, right, up, out, lip_depth, rx, rz, 0.98, sides, phase)
    b = _ring(center, right, up, out, lip_depth, rx, rz, inner_scale, sides, phase)
    c = _ring(center, right, up, out, rear_depth, rx, rz, rear_scale, sides, phase)
    e = Vector(center) + Vector(out) * float(cap_depth)
    verts = a + b + c + [tuple(e)]
    cap = 3 * sides
    faces = []
    for i in range(sides):
        j = (i + 1) % sides
        faces.extend([
            [i, j, sides + j, sides + i],
            [sides + i, sides + j, 2 * sides + j, 2 * sides + i],
            [2 * sides + i, cap, 2 * sides + j],
        ])
    _remove(name)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(material)
    for poly in mesh.polygons:
        poly.use_smooth = False
    obj["role"] = role
    obj["owner"] = owner
    obj["scale_H"] = 2.0
    return obj
