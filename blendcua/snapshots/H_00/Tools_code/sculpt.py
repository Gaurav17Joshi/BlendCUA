"""Screen-space stroke sculpting — carve damage into a dense mesh.

The paint module draws strokes onto a TEXTURE. This module drives the same
stroke description into GEOMETRY: every vertex whose screen projection falls
near the stroke is pushed inward along its own normal, so a stroke run along a
silhouette edge knocks a chip out of that edge.

Why screen space: the picking loop is identical to painting — set an ortho
view, render an overlay of candidate paths, read the PNG, adjust the anchor
points, apply. Nothing needs to be expressed in world coordinates, which is
what makes the strokes easy to author and re-author.

Stroke dict — the path fields are exactly paint.py's, so the same dict can be
handed to stroke_lines_preview() and to apply_carve_strokes():

    {
      "points":    [(x_norm, y_norm), ...]     # 2+ anchors, y grows DOWN
      "waviness":  "straight"|"subtle"|"wavy"|"bumpy"|"jagged"
      "amplitude": float      # optional, overrides the waviness preset
      "frequency": float      # optional
      "roughness": float      # optional, for waviness="jagged"
      "seed":      int
      "smooth":    bool       # Catmull-Rom (default) vs straight segments

      # --- sculpt-only ---
      "width":     float      # screen-space cull radius (normalized)
      "radius":    float      # WORLD-space falloff radius — the real brush size
      "depth":     float      # max inward displacement, WORLD units
      "noise":     float      # 0..1, how much the depth varies along the stroke
      "noise_scale": float    # world-space frequency of that variation
      "sharp":     float      # >1 narrows the profile to a V (Crease brush)
      "relax_scale": float    # 0..1, how much the smoothing pass rounds this
                              # stroke off — keep low for creases
      "bite":      float      # 0..1, fraction of the stroke left untouched, so
                              # the damage reads as separate chips not a groove
      "depth_band": float     # world depth kept behind the front surface
      "label":     str
    }

Front-facing vertices only: a stroke over the near edge must not also carve the
far side of the object, which is directly behind it on screen.
"""

import bpy
import numpy as np
from mathutils import Vector

from lib.view import get_viewport
from lib.pathgen import build_stroke_path

DEFAULT_WIDTH = 0.010        # screen-space gather radius (culling only)
DEFAULT_RADIUS = 0.030       # WORLD-space falloff radius — this is the brush size
DEFAULT_DEPTH = 0.010
DEFAULT_NOISE = 0.55
DEFAULT_BITE = 0.0          # >0 gates the noise to zero, breaking the stroke up
DEFAULT_NOISE_SCALE = 9.0
FACING_MIN = 0.05           # permissive: only drop clearly back-facing verts
SMOOTH_ITERS = 6            # Laplacian relax passes — this is what rounds edges
SMOOTH_STRENGTH = 0.55


def _resolve_path(stroke):
    """Stroke dict -> dense [(x_norm, y_norm), ...] polyline."""
    return build_stroke_path(
        stroke["points"],
        waviness=stroke.get("waviness", "straight"),
        amplitude=stroke.get("amplitude"),
        frequency=stroke.get("frequency"),
        seed=int(stroke.get("seed", 0)),
        smooth=bool(stroke.get("smooth", True)),
        roughness=float(stroke.get("roughness", 1.0)),
    )


def _world_arrays(obj):
    """(N,3) world coords and (N,3) world normals as float64 numpy arrays."""
    mesh = obj.data
    n = len(mesh.vertices)

    co = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)

    no = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get("normal", no)
    no = no.reshape(n, 3)

    mw = np.array(obj.matrix_world.to_4x4(), dtype=np.float64)
    world = co @ mw[:3, :3].T + mw[:3, 3]

    # Normals transform by the inverse-transpose of the 3x3 block.
    nm = np.linalg.inv(mw[:3, :3]).T
    wn = no @ nm.T
    lens = np.linalg.norm(wn, axis=1)
    lens[lens < 1e-12] = 1.0
    wn /= lens[:, None]
    return world, wn


def _project(world, region, rv3d):
    """World points -> normalized screen (x, y) with y growing DOWN, plus a
    validity mask. Done with the perspective matrix directly: calling
    location_3d_to_region_2d per vertex costs one RNA round trip each, which is
    minutes on a 300k mesh.
    """
    pm = np.array(rv3d.perspective_matrix, dtype=np.float64)
    homog = np.hstack([world, np.ones((world.shape[0], 1))])
    clip = homog @ pm.T
    w = clip[:, 3].copy()
    ok = np.abs(w) > 1e-9
    w[~ok] = 1.0
    ndc = clip[:, :3] / w[:, None]
    xn = ndc[:, 0] * 0.5 + 0.5
    yn = 1.0 - (ndc[:, 1] * 0.5 + 0.5)
    return xn, yn, ok


def _view_dir(rv3d):
    """Unit vector pointing FROM the camera INTO the scene."""
    return np.array(rv3d.view_rotation @ Vector((0.0, 0.0, -1.0)), dtype=np.float64)


def _seg_dist(px, py, ax, ay, bx, by):
    """Vectorized point-to-segment distance for one segment."""
    abx, aby = bx - ax, by - ay
    ab2 = abx * abx + aby * aby
    if ab2 < 1e-14:
        return np.hypot(px - ax, py - ay)
    t = np.clip(((px - ax) * abx + (py - ay) * aby) / ab2, 0.0, 1.0)
    return np.hypot(px - (ax + t * abx), py - (ay + t * aby))


def _seg_dist3(p, a, b):
    """Vectorized 3D point-to-segment distance. p: (N,3), a/b: (3,)."""
    ab = b - a
    ab2 = float(ab @ ab)
    if ab2 < 1e-16:
        return np.linalg.norm(p - a, axis=1)
    t = np.clip(((p - a) @ ab) / ab2, 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def _path_to_surface(path2d, xn, yn, depth_v, world, gather=0.005):
    """Lift a screen-space path onto the model: for each 2D point take the
    FRONTMOST vertex near it and use that vertex's world position.

    This is what lets the falloff be measured in 3D. Measuring it in screen
    space is what put a hard line down the corner: the two faces meeting at an
    edge project completely differently — one spreads across the screen, the
    other is edge-on and collapses to a line, so it receives near-uniform
    displacement until a depth cutoff ends it abruptly. In 3D both faces are
    simply "so many mm from the edge", and the corner rounds evenly.
    """
    out = []
    for ax, ay in path2d:
        m = (np.abs(xn - ax) < gather) & (np.abs(yn - ay) < gather)
        idx = np.nonzero(m)[0]
        if idx.size == 0:
            continue
        # Frontmost FIRST, then nearest on screen. argmin(depth) alone is not
        # enough: a whole face can share one depth — in FRONT view every vertex
        # on the -Y face has the same y — so argmin returns an arbitrary one,
        # which can sit centimetres to the side of the edge you aimed at. The
        # lifted path then runs parallel to the corner instead of along it, and
        # the falloff peaks beside the edge: the band either side gets carved
        # and the edge itself survives untouched.
        dv = depth_v[idx]
        front = idx[dv <= dv.min() + 0.02]
        near = front[np.argmin((xn[front] - ax) ** 2 + (yn[front] - ay) ** 2)]
        out.append(world[near])
    if len(out) < 2:
        return None
    pts = np.asarray(out, dtype=np.float64)
    keep = [0]
    for i in range(1, len(pts)):
        if np.linalg.norm(pts[i] - pts[keep[-1]]) > 1e-5:
            keep.append(i)
    if len(keep) < 2:
        return None
    pts = pts[keep]

    # Smooth the lifted curve. Each path point snapped to the nearest VERTEX,
    # so the raw polyline is a staircase that jumps between vertex columns —
    # and the distance field to a staircase beads, putting a chain of regular
    # lumps down the carve. A few moving-average passes give back a clean
    # curve; the stroke's own waviness is unaffected because it is far
    # lower-frequency than the vertex spacing.
    for _ in range(6):
        pts[1:-1] = 0.25 * pts[:-2] + 0.5 * pts[1:-1] + 0.25 * pts[2:]
    return pts


def _coherent_noise(pts, scale, seed):
    """Smooth 0..1 field over world space — spatially coherent, so the carve
    depth wanders instead of turning into per-vertex static.
    """
    rng = np.random.default_rng(seed)
    ph = rng.uniform(0.0, 6.283, 3)
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    a = np.sin(scale * (1.7 * x + 0.9 * y + 2.3 * z) + ph[0])
    b = np.sin(scale * (2.9 * x - 1.3 * y + 0.7 * z) + ph[1])
    c = np.sin(scale * (-1.1 * x + 2.7 * y + 1.9 * z) + ph[2])
    return 0.5 + 0.5 * (a + b + c) / 3.0


def apply_carve_strokes(obj_name, strokes, label="carve", report=True):
    """Carve every stroke into `obj_name`, in place. Returns a report dict.

    Must be called in OBJECT mode, with the viewport in the SAME view the
    stroke anchors were picked against — the strokes are screen space, so a
    different camera carves a different place.
    """
    obj = bpy.data.objects[obj_name]
    if obj.type != 'MESH':
        raise TypeError(f"{obj_name} is not a mesh")
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    _, region, rv3d = get_viewport()
    if region is None:
        raise RuntimeError("no 3D viewport")
    rv3d.update()

    world, normals = _world_arrays(obj)
    xn, yn, valid = _project(world, region, rv3d)

    # Two filters, and they do different jobs.
    #
    # FACING only throws away geometry pointing away from the camera. It must
    # stay permissive: a strict threshold rejects the face seen edge-on, but
    # that face is one of the TWO meeting at a corner — reject it and the carve
    # dents one side while the corner itself survives as a crisp line, which
    # reads as a scratch rather than a chip.
    #
    # DEPTH does the work the strict facing test was standing in for. An
    # edge-on face collapses to a line on screen, so all of it falls inside the
    # stroke radius — but only its near end is at the front surface; the rest
    # recedes. Keeping just what lies within `depth_band` of the frontmost
    # surface carves the corner from both sides and leaves the receding face
    # alone, so no washboard.
    vdir = _view_dir(rv3d)
    facing_min = float(strokes[0].get("facing_min", FACING_MIN)) if strokes else FACING_MIN
    facing = normals @ vdir < facing_min

    vm = np.array(rv3d.view_matrix, dtype=np.float64)
    depth_v = -(world @ vm[:3, :3].T + vm[:3, 3])[:, 2]   # distance along view

    total = np.zeros(world.shape[0], dtype=np.float64)
    relax = np.zeros(world.shape[0], dtype=np.float64)
    per_stroke = []

    for s in strokes:
        path = np.asarray(_resolve_path(s), dtype=np.float64)
        width = float(s.get("width", DEFAULT_WIDTH))
        depth = float(s.get("depth", DEFAULT_DEPTH))

        # Screen-space bbox cull first — without it this is N_verts x N_segments
        # distance computations, which on 300k verts is minutes, not seconds.
        lo_x, lo_y = path[:, 0].min() - width, path[:, 1].min() - width
        hi_x, hi_y = path[:, 0].max() + width, path[:, 1].max() + width
        near = valid & facing & (xn >= lo_x) & (xn <= hi_x) & (yn >= lo_y) & (yn <= hi_y)
        idx = np.nonzero(near)[0]
        if idx.size == 0:
            per_stroke.append({"label": s.get("label", ""), "verts": 0})
            continue

        # Lift the stroke onto the surface, then measure distance in 3D.
        path3 = _path_to_surface(path, xn, yn, depth_v, world)
        if path3 is None:
            per_stroke.append({"label": s.get("label", ""), "verts": 0})
            continue

        radius = float(s.get("radius", DEFAULT_RADIUS))
        # Re-cull in 3D: the screen bbox is generous, this is the real one.
        lo3, hi3 = path3.min(axis=0) - radius, path3.max(axis=0) + radius
        keep = np.all((world[idx] >= lo3) & (world[idx] <= hi3), axis=1)
        idx = idx[keep]
        if idx.size == 0:
            per_stroke.append({"label": s.get("label", ""), "verts": 0})
            continue

        pts = world[idx]
        dist = np.full(idx.size, np.inf)
        closest = np.zeros_like(pts)
        for i in range(len(path3) - 1):
            a, b = path3[i], path3[i + 1]
            ab = b - a
            ab2 = float(ab @ ab)
            if ab2 < 1e-16:
                continue
            t = np.clip(((pts - a) @ ab) / ab2, 0.0, 1.0)
            proj = a + t[:, None] * ab
            d = np.linalg.norm(pts - proj, axis=1)
            m = d < dist
            dist[m] = d[m]
            closest[m] = proj[m]

        t = np.clip(1.0 - dist / radius, 0.0, 1.0)
        fall = t * t * (3.0 - 2.0 * t)              # smoothstep
        # `sharp` > 1 narrows the profile to a V — a Crease-brush pinch rather
        # than a Scrape-brush scoop. The smoothstep alone is dome-shaped, which
        # is right for wear but rounds a crease away as fast as you cut it.
        sharp = float(s.get("sharp", 1.0))
        if sharp != 1.0:
            fall = fall ** sharp

        noise = float(s.get("noise", DEFAULT_NOISE))
        bite = float(s.get("bite", DEFAULT_BITE))
        if noise > 0.0:
            nv = _coherent_noise(world[idx], float(s.get("noise_scale",
                                                        DEFAULT_NOISE_SCALE)),
                                 int(s.get("seed", 0)) + 1013)
            # `bite` gates the noise to zero below a threshold, so stretches of
            # the stroke get NOTHING and the damage breaks into separate bites.
            # Without it the multiplier bottoms out at (1 - noise) — 0.3 for
            # noise=0.7 — so every vertex under the stroke moves at least a
            # little and the result is one unbroken ribbon down the edge, which
            # reads as a machined groove rather than chipping.
            if bite > 0.0:
                nv = np.clip((nv - bite) / max(1e-6, 1.0 - bite), 0.0, 1.0)
            fall *= (1.0 - noise) + noise * nv

        amount = fall * depth

        # max, not sum: crossing strokes must not double-gouge.
        # NB `total[idx] = ...`, not `np.maximum(..., out=total[idx])` —
        # fancy indexing returns a COPY, so an out= write lands in a temporary
        # and is silently discarded.
        total[idx] = np.maximum(total[idx], amount)
        # Per-stroke relax scale. A crease stroke sets this low so the
        # smoothing pass does not immediately round off the sharp cut it
        # just made; a wear stroke leaves it at 1.0 and gets fully relaxed.
        relax[idx] = np.maximum(relax[idx], fall * float(s.get('relax_scale', 1.0)))
        per_stroke.append({
            "label": s.get("label", ""),
            "verts": int((amount > 1e-9).sum()),
            "max_depth": float(amount.max()),
        })

    moved = total > 1e-9
    if moved.any():
        # 1. Take the material off, along the normal.
        world[moved] -= normals[moved] * total[moved, None]

        # 2. Round what is left by RELAXING it — Laplacian smoothing, weighted
        #    by the same falloff. This is the step that actually removes the
        #    crease. Displacing along normals only translates the corner line
        #    inward, so a crisp edge survives down the middle of the worn band;
        #    pulling vertices toward the stroke axis instead collapses the
        #    surface onto the line and tears it into spikes. Smoothing is what
        #    a Smooth/Scrape brush does, and rounding an edge IS smoothing it.
        smooth_iters = int(strokes[0].get("smooth_iters", SMOOTH_ITERS))
        smooth_str = float(strokes[0].get("smooth_strength", SMOOTH_STRENGTH))
        if smooth_iters > 0 and smooth_str > 0.0:
            me = obj.data
            ecount = len(me.edges)
            ev = np.empty(ecount * 2, dtype=np.int32)
            me.edges.foreach_get("vertices", ev)
            ev = ev.reshape(ecount, 2)
            a_i, b_i = ev[:, 0], ev[:, 1]
            deg = np.zeros(world.shape[0])
            np.add.at(deg, a_i, 1.0)
            np.add.at(deg, b_i, 1.0)
            deg[deg == 0] = 1.0
            w = (relax * smooth_str)[:, None]
            for _ in range(smooth_iters):
                acc = np.zeros_like(world)
                np.add.at(acc, a_i, world[b_i])
                np.add.at(acc, b_i, world[a_i])
                world += w * (acc / deg[:, None] - world)
        mw_inv = np.array(obj.matrix_world.inverted().to_4x4(), dtype=np.float64)
        local = world @ mw_inv[:3, :3].T + mw_inv[:3, 3]
        obj.data.vertices.foreach_set("co", local.ravel())
        obj.data.update()

    out = {
        "object": obj_name,
        "verts_total": int(world.shape[0]),
        "verts_moved": int(moved.sum()),
        "max_displacement": float(total.max()) if total.size else 0.0,
        "strokes": per_stroke,
    }
    if report:
        print(f"[sculpt:{label}] {out['verts_moved']}/{out['verts_total']} verts "
              f"moved, max {out['max_displacement']:.4f} m")
    return out


def carve_strokes_preview(strokes, label="carve"):
    """READ-ONLY path preview. Delegates to paint.stroke_lines_preview so the
    overlay looks identical to the painting workflow — the sculpt-only fields
    (width/depth/noise) are simply ignored there.
    """
    from paint import stroke_lines_preview
    return stroke_lines_preview(strokes, label=label)


def _relax(obj, world, weight, iters):
    """Laplacian smoothing weighted per-vertex by `weight` (0..1)."""
    if iters <= 0 or not (weight > 0).any():
        return
    me = obj.data
    ecount = len(me.edges)
    ev = np.empty(ecount * 2, dtype=np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(ecount, 2)
    a_i, b_i = ev[:, 0], ev[:, 1]
    deg = np.zeros(world.shape[0])
    np.add.at(deg, a_i, 1.0)
    np.add.at(deg, b_i, 1.0)
    deg[deg == 0] = 1.0
    w = weight[:, None]
    for _ in range(iters):
        acc = np.zeros_like(world)
        np.add.at(acc, a_i, world[b_i])
        np.add.at(acc, b_i, world[a_i])
        world += w * (acc / deg[:, None] - world)


def trim_region(world, center, normal, axis=(0.0, 0.0, 1.0),
                half_len=0.13, lateral=0.075, irregular=0.30, seed=11,
                core=0.45):
    """Footprint of a trim smudge. Shared by apply_trim and its preview so the
    two can never disagree about where the damage lands.

    Returns (idx, fall, s, n, tangent, ax):
      idx     indices into `world` of every vertex the smudge touches
      fall    0..1 weight for those vertices, smooth to zero at the boundary
      s       their signed distance out along the plane normal
    """
    center = np.asarray(center, dtype=np.float64)
    n = np.asarray(normal, dtype=np.float64)
    n = n / np.linalg.norm(n)
    ax = np.asarray(axis, dtype=np.float64)
    ax = ax / np.linalg.norm(ax)
    tangent = np.cross(n, ax)
    tl = np.linalg.norm(tangent)
    tangent = tangent / tl if tl > 1e-9 else np.array([0.0, 0.0, 1.0])

    rel = world - center
    u = rel @ ax                      # along the edge
    v = rel @ tangent                 # across the corner
    s = rel @ n                       # out along the cut normal

    # Cull the far side of the object, and anything obviously out of range,
    # before the expensive trig.
    reach = max(half_len, lateral) * 1.6
    near = np.nonzero((s > -2.0 * lateral) & (np.abs(u) < reach) &
                      (np.abs(v) < reach))[0]
    if near.size == 0:
        return near, np.zeros(0), np.zeros(0), n, tangent, ax

    eu = u[near] / half_len
    ev = v[near] / lateral
    r = np.sqrt(eu * eu + ev * ev)
    theta = np.arctan2(eu, ev)

    # Irregular OUTLINE — the boundary radius wobbles with a few low harmonics.
    # Note this modulates where the smudge STOPS, never how deep it cuts:
    # varying depth per-vertex makes the cut surface non-planar and it terraces
    # into visible stacked plates on a dense mesh.
    rng = np.random.default_rng(seed)
    rmax = np.ones(near.size)
    for k in (1, 2, 3, 5):
        rmax += (irregular / k) * np.sin(k * theta + rng.uniform(0, 6.283))
    rmax = np.clip(rmax, 0.45, 1.6)

    # PLATEAU then rim, not a bare smoothstep. A smoothstep from the centre
    # only reaches 1.0 at the exact middle, so almost nothing gets moved all
    # the way onto the plane and the result is a faint blur instead of a
    # flattened corner. Inside `core` the weight is a hard 1.0 — that band is
    # what actually goes flat — and only outside it does the weight ramp off.
    rc = rmax * core
    m = np.clip((rmax - r) / np.maximum(rmax - rc, 1e-6), 0.0, 1.0)
    fall = m * m * (3.0 - 2.0 * m)

    keep = fall > 1e-3
    return near[keep], fall[keep], s[near][keep], n, tangent, ax


def apply_trim(obj_name, normal, depth, center_world, axis=(0.0, 0.0, 1.0),
               half_len=0.13, lateral=0.075, irregular=0.30, seed=11,
               core=0.45, relax_iters=3, relax_strength=0.20,
               rim_iters=6, rim_strength=0.30, label="trim", report=True):
    """Trim brush — flatten a corner and the ground around it into a SMUDGE.

    What Pillar_damage.png actually shows, and what an earlier version of this
    function got badly wrong: the corner is NOT sliced. There is no facet, no
    crisp boundary, no straight edge anywhere. The corner ridge is squashed
    inward over a tall, soft region and fades back into the untouched surface
    on every side. It reads as a smudge — as if a thumb had been dragged down
    the corner of wet clay.

    The wrong version cut a hard plane over a hard-bounded slab. Both halves of
    that are wrong, and each produced its own artefact:

      * A hard plane with no rim falloff gives a mirror-flat facet whose
        boundary is a crisp line. Real weathering has no such line.
      * A hard region boundary makes that line quantise on the mesh grid, so
        it comes out visibly stair-stepped.

    So: the plane is still ONE plane (that part was right — it is what keeps
    the flattened area flat instead of terraced), but every vertex is moved
    toward it by `fall`, not all the way, and `fall` decays smoothly to zero at
    an irregular boundary. Vertices deep in the middle land on the plane and
    give a genuinely flat patch; vertices near the rim barely move and blend
    out. A relax pass then removes what is left of the mesh grid.

    normal        : world-space direction the smudge faces — out of the corner.
    depth         : how far inside the corner apex the flatten plane sits.
                    Keep this SMALL relative to half_len/lateral. A smudge is
                    broad and shallow; deep-and-narrow reads as a bite.
    center_world  : the point on the corner the smudge is centred on.
    axis          : direction of the edge (Z for a vertical corner).
    half_len      : half-extent along the edge — the smudge's height.
    lateral       : half-extent across the corner — how far onto each face it
                    reaches. Smaller than half_len gives the vertical drag
                    shape the reference has.
    irregular     : how much the outline wobbles. 0 = clean ellipse.
    core          : fraction of the footprint that gets flattened FULLY. The
                    rest is the soft rim. Without a plateau the weight only
                    reaches 1.0 at the exact centre and the corner comes out
                    faintly blurred rather than flattened.
                    Pair it with depth: the plateau can only flatten out to
                    core*lateral if depth is at least core*lateral/sqrt(2).
    relax_iters   : Laplacian passes run BEFORE the flatten, to wipe out the
                    fine chip noise a smudge would erase. Keep these gentle:
                    at 8 passes x 0.40 the smoothing rounded the ridge 30 mm on
                    its own, swamping the flatten so `depth` stopped meaning
                    anything and the plateau was no longer planar.
    rim_iters     : Laplacian passes run AFTER, in the transition band only.
    """
    obj = bpy.data.objects[obj_name]
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    world, _ = _world_arrays(obj)
    center = np.asarray(center_world, dtype=np.float64)

    idx, fall, s, n, tangent, ax = trim_region(
        world, center, normal, axis, half_len, lateral, irregular, seed, core)
    if idx.size == 0:
        raise RuntimeError("trim footprint covered no vertices")

    # RELAX FIRST, then flatten. Order matters, and getting it wrong is
    # visible: relaxing afterwards drags the finished plateau back off its own
    # plane (measured 3.4 mm of wander on a 30 mm cut) while leaving the
    # pre-existing chip noise inside the smudge only half smoothed, so the
    # transition zone comes out mottled and grid-stepped. Smoothing first wipes
    # that fine detail out — which is what a smudge physically does to a
    # weathered surface — and then the flatten lands every plateau vertex
    # exactly on the plane, so the plateau is planar by construction.
    w = np.zeros(world.shape[0])
    w[idx] = fall * relax_strength
    _relax(obj, world, w, relax_iters)

    # s has to be re-read from the relaxed positions, not reused.
    s = (world[idx] - center) @ n

    # Anchor the plane on the CORE of the footprint, not on its rim: the rim
    # runs down onto the flat faces where s is much lower, so taking the max
    # over everything would be fine, but taking it over the core is what makes
    # `depth` mean "into the apex" regardless of how wide the smudge is.
    inner = fall > 0.99
    s_ref = s[inner].max() if inner.any() else s.max()
    plane = s_ref - depth

    move = fall * np.clip(s - plane, 0.0, None)
    world[idx] -= n * move[:, None]

    # Second pass, at the RIM only, weighted by fall*(1-fall) so it peaks in
    # the transition band and falls to zero both on the finished plateau and
    # out on the untouched surface — it can smooth the join without denting
    # either side. This one wants real iterations: the transition is where the
    # falloff gradient is steepest, adjacent cells end up with slightly
    # different normals, and flat shading on a 6 mm grid draws every one of
    # them, so two passes left a visibly stair-stepped band.
    w2 = np.zeros(world.shape[0])
    w2[idx] = 4.0 * fall * (1.0 - fall) * rim_strength
    _relax(obj, world, w2, rim_iters)

    mw_inv = np.array(obj.matrix_world.inverted().to_4x4(), dtype=np.float64)
    local = world @ mw_inv[:3, :3].T + mw_inv[:3, 3]
    obj.data.vertices.foreach_set("co", local.ravel())
    obj.data.update()

    out = {
        "center": tuple(round(float(c), 4) for c in center),
        "verts_in_footprint": int(idx.size),
        "verts_moved": int((move > 1e-6).sum()),
        "max_cut": float(move.max()),
    }
    if report:
        print(f"[sculpt:{label}] smudged {out['verts_moved']}/"
              f"{out['verts_in_footprint']} verts at {out['center']}, "
              f"max {out['max_cut']:.4f} m")
    return out
