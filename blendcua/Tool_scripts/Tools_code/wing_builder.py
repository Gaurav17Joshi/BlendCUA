"""Small deterministic helpers for the Step 4 membrane strip."""

import bmesh
from mathutils import Vector


def positive_silhouette(obj_name, label, samples=128):
    """Measure the authored +X sheet alone, without hiding it permanently."""
    from perceive import silhouette_vs_reference
    import bpy
    obj = bpy.data.objects[obj_name]
    mirror_mods = [m for m in obj.modifiers if m.type == 'MIRROR']
    states = [(m, m.show_viewport) for m in mirror_mods]
    for m, _ in states:
        m.show_viewport = False
    try:
        return silhouette_vs_reference(obj_name, axis='X', samples=samples, label=label)
    finally:
        for m, state in states:
            m.show_viewport = state


def outer_boundary(wing):
    """Return the raw BatWing boundary edge farthest along +X."""
    bm = bmesh.new()
    bm.from_mesh(wing.data)
    candidates = [e for e in bm.edges if len(e.link_faces) == 1]
    if not candidates:
        bm.free()
        raise RuntimeError("BatWing has no open boundary edge")
    edge = max(candidates, key=lambda e: sum(v.co.x for v in e.verts) / 2.0)
    pts = [v.co.copy() for v in edge.verts]
    front_i = 0 if pts[0].y <= pts[1].y else 1
    out = (pts[front_i], pts[1 - front_i])
    bm.free()
    return out


def extrude_outer_strip(wing, target_front, target_rear):
    """Append one quad to the current +X boundary and return diagnostics."""
    old_front, old_rear = outer_boundary(wing)
    bm = bmesh.new()
    bm.from_mesh(wing.data)
    bm.verts.ensure_lookup_table()
    # Re-identify in the live BMesh by coordinate to avoid stale handles.
    def closest(pt):
        return min(bm.verts, key=lambda v: (v.co - pt).length)
    vf = closest(old_front)
    vr = closest(old_rear)
    nf = bm.verts.new(Vector(target_front))
    nr = bm.verts.new(Vector(target_rear))
    bm.verts.index_update()
    face = bm.faces.new((vf, vr, nr, nf))
    face.smooth = True
    new_front = tuple(nf.co)
    new_rear = tuple(nr.co)
    bm.to_mesh(wing.data)
    wing.data.update()
    result = {
        "old_front": tuple(old_front),
        "old_rear": tuple(old_rear),
        "new_front": new_front,
        "new_rear": new_rear,
        "verts": len(wing.data.vertices),
        "faces": len(wing.data.polygons),
    }
    bm.free()
    return result
