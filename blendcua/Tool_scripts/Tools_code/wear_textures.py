# WEAR AND TEAR TEXTURE LIBRARY
#
# Height maps for sculpt_native.displace / stroke_displace. Every generator
# returns a float array in 0..1, tileable, `size` pixels square, and is
# deterministic given its seed.
#
# Two rules decide whether any of these will look right:
#
#   FEATURE SIZE vs MESH. Displacement cannot express detail finer than about
#   EIGHT mesh cells. Feature size in metres is
#       plane_size / tile / cells
#   where `tile` is the texture's repeat_x/repeat_y. Check it against the mesh
#   BEFORE choosing settings — too fine does not come out subtle, it comes out
#   as aliased noise, and no amount of strength tuning fixes it.
#
#   POLARITY. mid_level is the map value that does not move. Maps whose damage
#   is DARK (pits, flakes, scratches) want a HIGH mid_level, so the dark parts
#   cut in and the intact surface stays put. Maps whose damage is BRIGHT
#   (pebbles) want a LOW one, so only the bright parts lift. Get this wrong
#   and the damage inverts: pits become warts.
#
# Each function's docstring gives its own recommended mid_level, a strength
# range in metres, and its minimum feature size. LIBRARY at the bottom carries
# the same values as data, so an action can loop over them.

import numpy as np

from stone_texture import _blur, _fbm, _smoothstep, build, build_pebbles
from stone_texture import write_png                      # re-exported


def _norm(a, amplitude=1.0):
    a = a - a.min()
    a = a / max(a.max(), 1e-9)
    return np.clip(0.5 + (a - 0.5) * float(amplitude), 0.0, 1.0)


def _value_noise_at(size, n, rng, px, py):
    """Value noise sampled at arbitrary wrapped coordinates.

    stone_texture._value_noise only works on the regular grid; the domain
    warp in erosion() needs to sample off it.
    """
    g = rng.random((n, n))
    x = (px % 1.0) * n
    y = (py % 1.0) * n
    i0 = np.floor(x).astype(int) % n
    j0 = np.floor(y).astype(int) % n
    i1, j1 = (i0 + 1) % n, (j0 + 1) % n
    fx = x - np.floor(x)
    fy = y - np.floor(y)
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    a = g[j0, i0] * (1 - fx) + g[j0, i1] * fx
    b = g[j1, i0] * (1 - fx) + g[j1, i1] * fx
    return a * (1 - fy) + b * fy


def _cell_field(size, cells, seed, warp, rng):
    """Shared setup: a warped coordinate grid and its cell indices.

    The domain warp is what stops every one of these reading as a grid. It
    costs almost nothing and it is the difference between "cracked stone" and
    "tiled floor".
    """
    u = (np.arange(size) + 0.5) / size
    px, py = np.meshgrid(u, u, indexing="xy")
    if warp:
        px = px + warp * (_fbm(size, 4, 3, rng) - 0.5)
        py = py + warp * (_fbm(size, 4, 3, rng) - 0.5)
    return px, py, np.floor(px * cells).astype(int), np.floor(py * cells).astype(int)


# --------------------------------------------------------------------------


def cracked_plates(size=1024, cells=9, seed=5, **kw):
    """Broken slabs separated by dark crack lines. The general stone face.

    The damage is the cracks, and neighbouring plates sit at different
    heights, so it reads as masonry that has split and shifted rather than as
    something eroded. This is the one to reach for on a large flat face.

    mid_level 0.5    strength 0.008 - 0.020 m    min feature 20 mm
    """
    return build(size=size, cells=cells, seed=seed, **kw)


def pebbles(size=1024, cells=8, seed=3, **kw):
    """Rounded stones sitting proud of a floor. Cobbles, aggregate, shingle.

    The only map here whose damage is BRIGHT — it ADDS material rather than
    removing it, so it wants a low mid_level sitting on the map's floor.

    mid_level 0.05   strength 0.008 - 0.020 m    min feature 20 mm
    """
    return build_pebbles(size=size, cells=cells, seed=seed, **kw)


def pits(size=1024, cells=10, seed=7, occupancy=0.45, radius=0.42,
         radius_var=0.5, depth_var=0.55, profile=1.3, warp=0.06, grain=0.06,
         blur_px=2, amplitude=1.0):
    """Scattered pockmarks eaten INTO the surface. Salt, frost, acid rain.

    The inverse of pebbles, and deliberately sparse: `occupancy` leaves most
    cells empty so the pits read as separate events on an intact surface. At
    occupancy 1.0 every cell pits and the result is a sponge — a material,
    not damage.

    `profile` above 1 makes each pit meet the surface tangentially. At 0.5 it
    is a true hemisphere, which meets the surface VERTICALLY and displaces
    into a punched hole with a cliff around it.

    mid_level 1.0    strength 0.004 - 0.012 m    min feature 20 mm
    """
    rng = np.random.default_rng(seed)
    live = rng.random((cells, cells)) < occupancy
    jit = rng.random((cells, cells, 2))
    rad = radius * (1.0 - radius_var + 2.0 * radius_var * rng.random((cells, cells)))
    dep = 1.0 - depth_var * rng.random((cells, cells))
    ang = rng.random((cells, cells)) * np.pi
    asp = 1.0 + 0.35 * (2.0 * rng.random((cells, cells)) - 1.0)

    px, py, cx, cy = _cell_field(size, cells, seed, warp, rng)

    hole = np.zeros((size, size))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx, ny = cx + dx, cy + dy
            wx, wy = nx % cells, ny % cells
            ex = px - (nx + jit[wy, wx, 0]) / cells
            ey = py - (ny + jit[wy, wx, 1]) / cells
            a = ang[wy, wx]
            ca, sa = np.cos(a), np.sin(a)
            rx = (ex * ca + ey * sa) * asp[wy, wx]
            ry = (-ex * sa + ey * ca) / asp[wy, wx]
            r = rad[wy, wx] / cells
            t = np.clip(1.0 - (rx * rx + ry * ry) / (r * r), 0.0, 1.0)
            hole = np.maximum(hole, live[wy, wx] * dep[wy, wx] * t ** profile)

    height = 1.0 - hole
    height = _blur(height, blur_px)
    height = (1.0 - grain) * height + grain * _fbm(size, 10, 3, rng)
    return _norm(height, amplitude)


def flakes(size=1024, cells=7, seed=13, levels=3, drop=0.34, bevel=0.10,
           warp=0.09, grain=0.07, blur_px=1, amplitude=1.0):
    """Spalled terraces: a surface layer broken away in irregular plates.

    Cell heights are QUANTISED to a few levels with hard boundaries, so the
    surface steps down in flat terraces instead of undulating. That step is
    what makes it read as material that has come OFF rather than material
    that has worn. `bevel` gives the step a finite slope — a truly vertical
    one aliases into a staircase on any real mesh.

    mid_level 1.0    strength 0.004 - 0.014 m    min feature 25 mm
    """
    rng = np.random.default_rng(seed)
    jit = rng.random((cells, cells, 2))
    lvl = rng.integers(0, levels, size=(cells, cells)) / max(levels - 1.0, 1.0)

    px, py, cx, cy = _cell_field(size, cells, seed, warp, rng)

    d = np.empty((9, size, size))
    val = np.empty((9, size, size))
    k = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx, ny = cx + dx, cy + dy
            wx, wy = nx % cells, ny % cells
            qx = (nx + jit[wy, wx, 0]) / cells
            qy = (ny + jit[wy, wx, 1]) / cells
            d[k] = np.hypot(px - qx, py - qy)
            val[k] = lvl[wy, wx]
            k += 1

    order = np.argsort(d, axis=0)
    f1 = np.take_along_axis(d, order[:1], axis=0)[0]
    f2 = np.take_along_axis(d, order[1:2], axis=0)[0]
    v1 = np.take_along_axis(val, order[:1], axis=0)[0]
    v2 = np.take_along_axis(val, order[1:2], axis=0)[0]

    t = _smoothstep(0.0, bevel / cells, f2 - f1)
    height = 1.0 - drop * (v1 * t + 0.5 * (v1 + v2) * (1.0 - t))

    height = _blur(height, blur_px)
    height = (1.0 - grain) * height + grain * _fbm(size, 12, 3, rng)
    return _norm(height, amplitude)


def scratches(size=1024, count=90, seed=17, length=0.22, length_var=0.7,
              width=0.008, width_var=0.6, angle=25.0, spread=28.0,
              depth_var=0.7, grain=0.05, blur_px=1, amplitude=1.0):
    """Directional gouges — dragged, scraped, tooled, quarried.

    The only map here with a DIRECTION. `angle` sets the dominant bearing in
    degrees, `spread` how far individual scratches wander from it. At spread
    90 they are effectively random and the surface reads as generic distress
    rather than as something having been dragged across it.

    Easiest map to make too fine to render: width is a fraction of the TILE,
    so 0.008 on a 0.4 m tile is a 3 mm scratch and needs a 0.4 mm mesh. Widen
    the scratch or coarsen the tiling rather than subdividing the model.

    mid_level 1.0    strength 0.003 - 0.010 m    min feature width*tile >= 8 cells
    """
    rng = np.random.default_rng(seed)
    u = (np.arange(size) + 0.5) / size
    px, py = np.meshgrid(u, u, indexing="xy")
    cut = np.zeros((size, size))

    for _ in range(count):
        x0, y0 = rng.random(), rng.random()
        a = np.radians(angle + spread * (2.0 * rng.random() - 1.0))
        ln = length * (1.0 - length_var + 2.0 * length_var * rng.random())
        wd = width * (1.0 - width_var + 2.0 * width_var * rng.random())
        dep = 1.0 - depth_var * rng.random()

        # wrapped offsets, so a scratch running off one edge returns on the
        # other and the map still tiles
        ex = (px - x0 + 0.5) % 1.0 - 0.5
        ey = (py - y0 + 0.5) % 1.0 - 0.5
        along = ex * np.cos(a) + ey * np.sin(a)
        across = -ex * np.sin(a) + ey * np.cos(a)
        t = np.clip(along / max(ln, 1e-9), 0.0, 1.0)
        inside = (along > -1e-6) & (along < ln) & (np.abs(across) < wd * 3.5)
        # taper the ends, so a scratch starts and stops instead of being cut
        taper = np.clip(np.minimum(t, 1.0 - t) * 6.0, 0.0, 1.0)
        prof = np.exp(-(across / max(wd, 1e-9)) ** 2) * taper * inside
        cut = np.maximum(cut, dep * prof)

    height = 1.0 - cut
    height = _blur(height, blur_px)
    height = (1.0 - grain) * height + grain * _fbm(size, 10, 3, rng)
    return _norm(height, amplitude)


def erosion(size=1024, seed=23, base=5, octaves=5, ridge=0.75, warp=0.12,
            grain=0.05, blur_px=1, amplitude=1.0):
    """Water-worn: rounded channels and smooth divides, no straight edges.

    Ridged fbm — each octave folded as 1 - |2f - 1| — which gives creases
    where plain fbm gives blobs. Domain-warped so the channels wander instead
    of running along the noise grid's own directions.

    Nothing here has a characteristic size, so it is the safest map on a
    coarse mesh: it degrades into gentle undulation rather than into noise.

    mid_level 0.7    strength 0.006 - 0.018 m    no hard minimum
    """
    rng = np.random.default_rng(seed)
    u = (np.arange(size) + 0.5) / size
    px, py = np.meshgrid(u, u, indexing="xy")
    wx = warp * (_fbm(size, 3, 3, rng) - 0.5)
    wy = warp * (_fbm(size, 3, 3, rng) - 0.5)

    out = np.zeros((size, size))
    amp, tot, n = 1.0, 0.0, base
    for _ in range(octaves):
        f = _value_noise_at(size, n, rng, px + wx, py + wy)
        r = 1.0 - np.abs(2.0 * f - 1.0)
        out += amp * (ridge * r + (1.0 - ridge) * f)
        tot += amp
        amp *= 0.55
        n = int(n * 2)
    out /= tot

    out = _blur(out, blur_px)
    out = (1.0 - grain) * out + grain * _fbm(size, 12, 3, rng)
    return _norm(out, amplitude)


def granular(size=1024, seed=29, base=14, octaves=3, contrast=1.8,
             blur_px=1, amplitude=1.0):
    """Even coarse roughness — sandblasted, weathered, tooled.

    No structure at all, only grain. Best used as a FINISHING layer at low
    strength over one of the others; on its own it reads as sandpaper.

    Being entirely high frequency it is the map most likely to alias. Keep
    `base` low rather than raising the mesh density.

    mid_level 0.5    strength 0.001 - 0.004 m    min feature 20 mm
    """
    rng = np.random.default_rng(seed)
    f = _fbm(size, base, octaves, rng)
    f = np.clip(0.5 + (f - f.mean()) * contrast, 0.0, 1.0)
    return _norm(_blur(f, blur_px), amplitude)


# name -> (function, mid_level, strength m, min feature mm, one-liner)
LIBRARY = {
    "cracked_plates": (cracked_plates, 0.5, 0.012, 20,
                       "broken slabs with crack lines between them"),
    "pebbles":        (pebbles, 0.05, 0.015, 20,
                       "rounded stones sitting proud of a floor"),
    "pits":           (pits, 1.0, 0.008, 20,
                       "scattered pockmarks eaten into the surface"),
    "flakes":         (flakes, 1.0, 0.010, 25,
                       "spalled terraces where a layer broke away"),
    "scratches":      (scratches, 1.0, 0.006, 25,
                       "directional gouges, dragged or scraped"),
    "erosion":        (erosion, 0.7, 0.012, 0,
                       "water-worn channels, rounded, no straight edges"),
    "granular":       (granular, 0.5, 0.003, 20,
                       "even coarse roughness; a finishing layer"),
}
