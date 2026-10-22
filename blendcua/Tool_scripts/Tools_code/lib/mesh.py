"""
bmesh selection + topology helpers.
"""

import bpy
import bmesh
from mathutils import Vector


def enter_edit(obj_name, select_all=True):
    """Reset Blender to a clean EDIT-mode context on the named object.

    Call this at the top of any action that operates on a specific object.
    Safe from any starting state: wrong mode, wrong active object, stale
    selection, or mid-operation crash/rerun.

    Steps performed:
      1. Exit to OBJECT mode (required before switching the active object).
      2. Deselect everything (clears stale selection from the previous action).
      3. Look up the object by name (reliable across reruns).
      4. Select it and make it the active object (both are needed for EDIT mode).
      5. Enter EDIT mode on that object.
      6. Select all geometry (so overlays and ops see the full mesh).

    Args:
        obj_name:   Name of the object in bpy.data.objects.
        select_all: If True (default), selects all verts/edges/faces after
                    entering EDIT mode. Pass False when the action will
                    immediately make its own selection.

    Returns:
        The bpy.types.Object, so you can chain:
            obj = enter_edit("Base")
            bm  = bmesh.from_edit_mesh(obj.data)
    """
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    obj = bpy.data.objects[obj_name]
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    if select_all:
        bpy.ops.mesh.select_all(action='SELECT')
    return obj


def walk_ring(seed_edge):
    """Walk the loop-cut ring containing seed_edge.

    Returns a list of edges in ring order: bwd[::-1] + [seed] + fwd.
    Quad-only; stops at any face that isn't a quad.
    """
    seen = {seed_edge}

    def march(loop):
        out, l = [], loop
        while True:
            if len(l.face.edges) != 4:
                break
            l = l.link_loop_next.link_loop_next
            if l.edge in seen:
                break
            out.append(l.edge)
            seen.add(l.edge)
            nxt = l.link_loop_radial_next
            if nxt is l:
                break
            l = nxt
        return out

    loops = seed_edge.link_loops
    fwd = march(loops[0]) if len(loops) > 0 else []
    bwd = march(loops[1]) if len(loops) > 1 else []
    return list(reversed(bwd)) + [seed_edge] + fwd


def loopcut_at_fractions(obj, bm, ring_edges, fractions, top_z, bottom_z, from_top=True):
    """Cut `len(fractions)` new horizontal rings into `ring_edges`, each
    positioned at an arbitrary fraction of the [bottom_z, top_z] span —
    unlike `bmesh.ops.subdivide_edges(cuts=N)` alone, which only ever gives
    even spacing.

    Two-phase, both safe/proven primitives: (1) subdivide evenly with
    `cuts=len(fractions)` — grid-fill only knows how to split evenly, so this
    is the reliable way to get correct quad topology; (2) slide each new
    ring along Z from its even position to its requested fraction. Sliding a
    still-straight, unscaled ring along Z is just moving a vertex along the
    edge it already sits on — no distortion. Do this BEFORE any XY scaling
    of the band; sliding a vert that's already been bent outward would not
    do what you want.

    Args:
        obj:        the mesh's owning Object (needed for the
                    `bmesh.update_edit_mesh` call at the end).
        bm:         the current edit-mode BMesh.
        ring_edges: an edge ring from `walk_ring(face.loops[DIR_INDEX].edge)`
                    — the same input `bmesh.ops.subdivide_edges` normally
                    takes directly.
        fractions:  list of floats in (0, 1), one new ring per entry, in the
                    SAME order as given (need not be sorted).
        top_z, bottom_z: world-Z of the two ends of the span being cut (e.g.
                    an extruded band's pinned bottom ring and its top face).
        from_top:   if True (default), fraction 0.2 lands 20% of the way
                    DOWN from top_z. If False, 0.2 lands 20% of the way UP
                    from bottom_z.

    Returns:
        list of lists of BMVert — one ring per entry in `fractions`, in the
        same order (`out[i]` is the ring for `fractions[i]`). Caller must
        re-fetch `bm` fresh before any further `bmesh.ops` call — indices
        are not stable through `subdivide_edges` with `use_grid_fill=True`.

    Raises ValueError if the subdivide didn't produce exactly one distinct
    Z level per requested fraction (means `ring_edges` didn't form a single
    straight vertical band, e.g. it already had a kink in it).
    """
    n = len(fractions)
    if n < 1:
        return []

    mw = obj.matrix_world
    mw_inv = mw.inverted()

    span = top_z - bottom_z
    target_zs = [
        (top_z - f * span) if from_top else (bottom_z + f * span)
        for f in fractions
    ]

    hist = GeoHistory()
    hist.snapshot('_loopcut_at_fractions_pre', bm)
    bmesh.ops.subdivide_edges(bm, edges=ring_edges, cuts=n, use_grid_fill=True)
    new_verts = hist.new_verts_since('_loopcut_at_fractions_pre', bm)

    # Right after an even-cuts subdivide, the n new rings sit at n evenly
    # spaced Z levels — group by that before repositioning. `top_z`/
    # `bottom_z` are WORLD-space (per the docstring), but v.co is LOCAL —
    # the object's origin is not necessarily at world Z=0 (e.g. a cylinder
    # built via primitive_cylinder_add(location=(0,0,h/2)) sits with its
    # origin at world Z=h/2), so grouping/target-matching must happen in
    # WORLD space throughout, converting back to local only for the final
    # assignment. Comparing/assigning target_zs against v.co.z directly
    # (local) would silently place verts at the wrong world height by
    # exactly the object's Z offset — this bit us once already.
    even_zs = sorted({round((mw @ v.co).z, 5) for v in new_verts})
    if len(even_zs) != n:
        raise ValueError(
            f"expected {n} distinct even-cut Z levels from the subdivide, "
            f"found {len(even_zs)} ({even_zs}) — ring_edges may not form a "
            f"single straight vertical band."
        )
    rings_by_even_z = {
        z: [v for v in new_verts if round((mw @ v.co).z, 5) == z] for z in even_zs
    }

    # Assign the physically-LOWEST even ring to whichever fraction wants the
    # smallest target Z, next-lowest to the next target Z, and so on up —
    # this guarantees vertical connectivity order never inverts, regardless
    # of what order `fractions` was given in. Store results back under the
    # ORIGINAL fractions index so out[i] always matches fractions[i].
    order_by_target = sorted(range(n), key=lambda i: target_zs[i])
    out_rings = [None] * n
    for even_z, idx in zip(even_zs, order_by_target):
        ring = rings_by_even_z[even_z]
        for v in ring:
            world_pos = mw @ v.co
            world_pos.z = target_zs[idx]
            v.co = mw_inv @ world_pos
        out_rings[idx] = ring

    bmesh.update_edit_mesh(obj.data)
    return out_rings


def selected_verts_world(bm, mw):
    """World-space coords of selected verts."""
    return [mw @ v.co for v in bm.verts if v.select]


def centroid(world_pts):
    """Average of world points. Returns Vector. Pass a non-empty list."""
    return sum(world_pts, Vector()) / len(world_pts)


def representative_spoke(pivot, world_pts, axis_mask):
    """Pick a 'handle' vector for a multi-axis scale.

    Of the candidate world_pts, returns the (pt - pivot) with the longest
    component within the masked subspace, with unmasked components zeroed.

    axis_mask examples:
      (0,1,0) — Y only:    spoke is the Y displacement of the vert with max |dy|
      (1,1,0) — radial XY: spoke is the XY displacement of the vert with max
                           sqrt(dx² + dy²) — i.e. the one farthest from the
                           central Z axis
      (1,1,1) — uniform:   spoke is the full displacement of the farthest vert

    Why this matters: when fed to `transform.resize(value=(f if m else 1, ...))`,
    the chosen handle's scaled position equals `pivot + spoke * factor` for any
    mask, because the unmasked components of spoke are zero. So the on-screen
    tick markers always preview the true scaled position of that vert.
    """
    mx, my, mz = axis_mask

    def masked_delta(w):
        d = w - pivot
        return Vector((d.x * mx, d.y * my, d.z * mz))

    handle = max(world_pts, key=lambda w: masked_delta(w).length)
    return masked_delta(handle)


def deselect_all(bm):
    """Direct deselect via bmesh, then flush outward. No operator."""
    for v in bm.verts:
        v.select = False
    bm.select_flush(False)


def select_verts_where(bm, predicate, mw=None):
    """Select verts where predicate(vert, world_pos) is True. Flushes inward.

    If mw is None, uses local coords; otherwise multiplies by matrix_world.
    Returns the count selected.
    """
    count = 0
    for v in bm.verts:
        wp = (mw @ v.co) if mw else v.co
        if predicate(v, wp):
            v.select = True
            count += 1
    bm.select_flush(True)
    return count


def select_verts_at_z(bm, mw, z_levels, tol=1e-3):
    """Common case: select all verts whose world Z matches any value in z_levels.

    Useful for re-selecting loop-cut bands after a render (which can drop selection).
    """
    return select_verts_where(
        bm,
        lambda v, wp: any(abs(wp.z - z) < tol for z in z_levels),
        mw=mw,
    )


def z_levels(bm, mw, decimals=4):
    """All unique world-Z values among verts (sorted)."""
    return sorted({round((mw @ v.co).z, decimals) for v in bm.verts})


class GeoHistory:
    """Tag and snapshot bmesh geometry across a multi-step build.

    Stores vert INDICES (ints), not BMVert references. Why: bmesh wraps the
    underlying C verts in fresh Python BMVert objects on every iteration of
    `bm.verts`, so `set(bm.verts)` and `v in some_set` use Python identity
    and behave unpredictably across ops. Index comparison is reliable.

    Indices are NOT guaranteed stable even through ADD operations —
    `subdivide_edges` with `use_grid_fill=True` reassigns pre-existing
    indices (run_007) — which is why `new_verts_since` diffs by coordinate.
    Tags (index lists) are NOT stable through DELETE operations
    (`mesh.bevel`, `mesh.dissolve_verts`, etc.) or grid-fill subdivides —
    re-derive and re-tag after any such op if you need to follow the
    geometry.

    Snapshot / diff pattern:

        hist = GeoHistory()
        hist.snapshot('pre_cut', bm)
        bmesh.ops.subdivide_edges(bm, edges=ring, cuts=1, use_grid_fill=True)
        new = hist.new_verts_since('pre_cut', bm)
        hist.tag('loop_verts', new)
        ...
        hist.select_verts('loop_verts', bm)             # VERT mode
        bpy.ops.transform.translate(value=(0, 0, dz))

    Edge-from-vert pattern (for bevel and similar edge ops):

        hist.select_edges_among(['loop1', 'loop2'], bm) # EDGE mode
        bpy.ops.mesh.bevel(offset=0.1, ...)
    """

    def __init__(self):
        self._snapshots = {}    # name -> set of vert indices
        self._snap_coords = {}  # name -> set of rounded (x, y, z) tuples
        self._tags      = {}    # name -> list of vert indices

    @staticmethod
    def _ckey(co):
        return (round(co.x, 6), round(co.y, 6), round(co.z, 6))

    def snapshot(self, name, bm):
        """Capture the current vert index set AND coordinate set."""
        bm.verts.ensure_lookup_table()
        self._snapshots[name] = {v.index for v in bm.verts}
        self._snap_coords[name] = {self._ckey(v.co) for v in bm.verts}

    def new_verts_since(self, name, bm):
        """Verts that did not exist at the named snapshot.

        Diffs by COORDINATE, not index: some add ops reassign indices of
        pre-existing verts too (`subdivide_edges` with `use_grid_fill=True`
        did this in run_007, making an index diff report 284 "new" verts
        instead of 32). Add ops never MOVE existing verts, so a vert whose
        rounded coordinate wasn't in the snapshot is genuinely new.

        Call AFTER an add op (subdivide_edges, extrude_region, ...) and
        BEFORE anything that moves or deletes verts.
        """
        bm.verts.ensure_lookup_table()
        before = self._snap_coords[name]
        return [v for v in bm.verts if self._ckey(v.co) not in before]

    def tag(self, name, verts, bm=None):
        """Save vert indices under `name` for later select/lookup.

        If `bm` is provided we call `bm.verts.ensure_lookup_table()` here so
        the `v.index` reads see the current dense indexing. Without it the
        index field is whatever was last computed by ensure_lookup_table —
        which can be stale by many slots after an extrude or other add op,
        producing tags that silently point at the wrong verts later. Pass
        `bm` unless the verts came from `new_verts_since` (which has already
        ensured the table for you).
        """
        if bm is not None:
            bm.verts.ensure_lookup_table()
        self._tags[name] = [v.index for v in verts]

    def vert_indices(self, name):
        """Raw stored indices for a tag — useful for serialization/debug."""
        return list(self._tags.get(name, []))

    def verts(self, name, bm):
        """Resolve tagged indices to current BMVerts in `bm`.

        Drops indices that are out of range (defensive against a tag whose
        underlying verts were deleted).
        """
        bm.verts.ensure_lookup_table()
        n = len(bm.verts)
        return [bm.verts[i] for i in self._tags.get(name, []) if 0 <= i < n]

    def edges_among(self, names, bm):
        """Edges whose both endpoints sit within a SINGLE named tag (any of them).

        Returns the union across tags, but each edge must lie entirely
        inside ONE tag's vert set. Excludes "bridge" edges connecting two
        different tags — e.g. on a cup with two horizontal loop rings, this
        returns each ring's own edges but NOT the verticals between them
        (which would otherwise be selected by a naive union-then-filter and
        then included in operations like `mesh.bevel`).
        """
        bm.verts.ensure_lookup_table()
        out = []
        seen = set()
        for n in names:
            idx_set = set(self._tags.get(n, []))
            for e in bm.edges:
                if id(e) in seen:
                    continue
                if e.verts[0].index in idx_set and e.verts[1].index in idx_set:
                    out.append(e)
                    seen.add(id(e))
        return out

    def select_verts(self, name, bm, exclusive=True):
        """Select tagged verts. Caller should already be in VERT select mode."""
        if exclusive:
            for v in bm.verts:
                v.select = False
            bm.select_flush(False)
        verts = self.verts(name, bm)
        for v in verts:
            v.select = True
        bm.select_flush(True)
        return len(verts)

    def select_edges_among(self, names, bm, exclusive=True):
        """Select edges between tagged verts. Caller should be in EDGE mode."""
        if exclusive:
            for e in bm.edges:
                e.select = False
            bm.select_flush(False)
        edges = self.edges_among(names, bm)
        for e in edges:
            e.select = True
        bm.select_flush(True)
        return len(edges)


def find_side_face_by_z(bm, mw, z_low, z_high, tol=1e-3):
    """First quad face that touches both z_low and z_high (cylinder side wall)."""
    for f in bm.faces:
        if len(f.verts) != 4:
            continue
        vzs = [(mw @ v.co).z for v in f.verts]
        if any(abs(z - z_low) < tol for z in vzs) and any(abs(z - z_high) < tol for z in vzs):
            return f
    return None
