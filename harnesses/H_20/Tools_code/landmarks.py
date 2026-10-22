"""
Landmarks — name verts so they survive across topology-changing ops.

A landmark is stored as a Blender vertex group (Blender propagates group
membership through extrude, subdivide, bevel, etc.), plus an entry in
`mem/<run>/landmarks.json` describing what it is.

Typical usage in a step file:

    # ... select the verts you want to remember ...
    from landmarks import tag
    tag("top_face", "original top face of the cup")

Later:

    from landmarks import select
    select("top_face")    # deselects all + selects the landmark's verts in EDIT mode

See BLENDCUA_AGENT.md §7 for why vertex groups (not indices).
"""

import bpy
import bmesh
import json
import os

from runtime import run_dir

_PREFIX = "bc_"


def tag(name, description=""):
    """Tag currently selected verts as a landmark.

    Must be called in EDIT mode with the desired verts selected. Creates (or
    updates) a vertex group named `bc_<name>` and writes an entry to
    `mem/<run>/landmarks.json`.
    """
    obj = bpy.context.active_object
    bm = bmesh.from_edit_mesh(obj.data)
    vert_ids = [v.index for v in bm.verts if v.select]

    bpy.ops.object.mode_set(mode='OBJECT')
    vg_name = _PREFIX + name
    # vg.add(..., 'REPLACE') only overwrites weights of the verts passed in —
    # it never REMOVES verts already in the group, so re-tagging a landmark
    # kept stale members (bit run_007 step 3: a corrupted 284-vert tag
    # survived a "corrective" re-tag). Recreate the group from scratch.
    old = obj.vertex_groups.get(vg_name)
    if old is not None:
        obj.vertex_groups.remove(old)
    vg = obj.vertex_groups.new(name=vg_name)
    vg.add(vert_ids, 1.0, 'REPLACE')
    bpy.ops.object.mode_set(mode='EDIT')

    LM = f"{run_dir()}/landmarks.json"
    landmarks = {}
    if os.path.exists(LM):
        with open(LM) as f:
            landmarks = json.load(f)
    landmarks[name] = {
        "vertex_group": vg_name,
        "n_verts":      len(vert_ids),
        "description":  description,
    }
    with open(LM, "w") as f:
        json.dump(landmarks, f, indent=2)


def resolve(name):
    """Return the vert INDICES (not BMVerts) belonging to landmark `name`.

    We return ints, not BMVerts, because BMVert refs don't survive across a
    function return — the local bmesh wrapper goes out of scope and the
    BMVerts that came from it become dangling. Look the verts back up with
    `bm.verts[i]` from a fresh bmesh in the caller.
    """
    obj = bpy.context.active_object
    vg_index = obj.vertex_groups[_PREFIX + name].index
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    dl = bm.verts.layers.deform.verify()
    return [v.index for v in bm.verts if vg_index in v[dl]]


def select(name):
    """Deselect all and select the landmark's verts in EDIT mode.

    Holds its own bmesh in this function's scope so the BMVert handles
    stay valid for the whole loop. Calling resolve() and looping over its
    return value would error here — see resolve()'s docstring.
    """
    obj = bpy.context.active_object
    bpy.ops.mesh.select_all(action='DESELECT')

    vg_index = obj.vertex_groups[_PREFIX + name].index
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    dl = bm.verts.layers.deform.verify()
    for v in bm.verts:
        if vg_index in v[dl]:
            v.select_set(True)
    bmesh.update_edit_mesh(obj.data)


def select_edges_among(names, bm, exclusive=True):
    """Select edges whose BOTH endpoints lie within a SINGLE landmark.

    Mirrors lib.mesh.GeoHistory.select_edges_among, but reads membership
    from Blender vertex groups (which persist across actions and through
    topology-changing ops like bevel/extrude). Caller must be in EDGE mode.

    Returns the count of newly-selected edges.

    The "within a single landmark" rule is intentional: union-then-filter
    would also pick up "bridge" edges connecting two different rings —
    e.g. the vertical edges between loop1 and loop2 — which would then be
    fed into `mesh.bevel` and corrupt the result.
    """
    if exclusive:
        for e in bm.edges:
            e.select = False
        bm.select_flush(False)

    obj = bpy.context.active_object
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    dl = bm.verts.layers.deform.verify()

    sel = 0
    for name in names:
        vg_index = obj.vertex_groups[_PREFIX + name].index
        in_lm = {v.index for v in bm.verts if vg_index in v[dl]}
        for e in bm.edges:
            if (e.verts[0].index in in_lm and
                e.verts[1].index in in_lm and
                not e.select):
                e.select = True
                sel += 1
    bm.select_flush(True)
    return sel
