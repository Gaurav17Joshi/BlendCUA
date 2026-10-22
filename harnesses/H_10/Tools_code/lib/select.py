"""
Region-based mesh selection.

select_in_region(tl_norm, br_norm, mode='EDGE') → int

    Deselects everything, then selects elements of the active mesh whose
    screen projection lands completely inside the normalised box [tl_norm,
    br_norm] (each a (x, y) tuple in 0-1 image coords, top-left origin).

    mode='VERT'  — vertex projects inside the box
    mode='EDGE'  — BOTH endpoints project inside the box
    mode='FACE'  — face centroid projects inside the box

    Returns the count of newly selected elements.
    Caller must be in EDIT mode on the target object.
"""

import bpy
import bmesh

from lib.view import get_viewport, proj_fn


def select_in_region(tl_norm, br_norm, mode='EDGE'):
    """Select all verts/edges/faces inside a screen rectangle.

    `tl_norm`/`br_norm` are (x, y) in normalised 0-1 image coords with a
    top-left origin — the same numbers every overlay PNG is labelled in.
    `mode` is 'VERT' | 'EDGE' | 'FACE'.

    This is a SCREEN test, so it takes whatever is behind the rectangle
    as well as what is in front of it. On a closed mesh that means the
    far side too — which is what you want for a symmetric band, and a
    silent extra selection otherwise.
    """
    area, region, rv3d = get_viewport()
    W, H = region.width, region.height
    x1, y1 = tl_norm[0] * W, tl_norm[1] * H
    x2, y2 = br_norm[0] * W, br_norm[1] * H

    def inside(p):
        return p is not None and x1 <= p["x"] <= x2 and y1 <= p["y"] <= y2

    obj  = bpy.context.active_object
    mw   = obj.matrix_world
    proj = proj_fn(region, rv3d)

    bpy.ops.mesh.select_mode(type=mode)
    bpy.ops.mesh.select_all(action='DESELECT')

    bm    = bmesh.from_edit_mesh(obj.data)
    count = 0

    if mode == 'VERT':
        bm.verts.ensure_lookup_table()
        for v in bm.verts:
            if inside(proj(mw @ v.co)):
                v.select = True
                count += 1

    elif mode == 'EDGE':
        bm.edges.ensure_lookup_table()
        for e in bm.edges:
            if inside(proj(mw @ e.verts[0].co)) and inside(proj(mw @ e.verts[1].co)):
                e.select = True
                count += 1

    elif mode == 'FACE':
        bm.faces.ensure_lookup_table()
        for f in bm.faces:
            if inside(proj(mw @ f.calc_center_median())):
                f.select = True
                count += 1

    bmesh.update_edit_mesh(obj.data)
    return count
