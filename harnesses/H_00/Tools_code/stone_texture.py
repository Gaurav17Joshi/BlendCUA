# The brush texture — a cracked-stone height map, generated rather than
# downloaded so the run stays reproducible offline and the feature size is a
# number we control instead of whatever a stock JPEG happened to have.
#
# The reference (images/Pillar/Pillar_texture_brush.png) is a grayscale map of
# broken plates: bright irregular slabs separated by dark crack lines, softly
# blurred. That is exactly a Worley/Voronoi F2-F1 field, so that is what this
# builds:
#
#   plates  each cell gets its own brightness, so neighbouring slabs sit at
#           different heights instead of forming one flat sheet
#   cracks  smoothstep on (F2 - F1) — thin dark lines exactly on the cell
#           boundaries, which is where stone actually splits
#   grain   fbm value noise over the whole thing, so the plate faces are
#           rough rather than poster-flat
#
# Everything is computed on a torus (neighbour cells wrap, noise grids wrap),
# so the map tiles. It is stamped, not tiled, at AREA_PLANE mapping — but a
# seamless map means the stamp has no visible border when dabs overlap.
#
# MEAN IS FORCED TO 0.5. The brush reads the texture as a multiplier on
# strength and adds texture_sample_bias to it; with bias -0.5 a mean of 0.5
# means the stroke pushes OUT of the bright plates and IN along the dark
# cracks in equal measure. A map with mean 0.7 would inflate the whole face.

import struct
import zlib

import numpy as np


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, 1e-9), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _value_noise(size, n, rng):
    """One octave of tileable value noise: an n x n random grid, bilinearly
    upsampled to size x size with wraparound."""
    g = rng.random((n, n))
    t = np.arange(size, dtype=np.float64) * n / size
    i0 = np.floor(t).astype(int) % n
    i1 = (i0 + 1) % n
    f = (t - np.floor(t))[:, None]
    f = f * f * (3.0 - 2.0 * f)                      # smooth the ramp
    rows = g[i0] * (1.0 - f) + g[i1] * f             # (size, n)
    cols = rows[:, i0] * (1.0 - f.T) + rows[:, i1] * f.T
    return cols


def _fbm(size, n0, octaves, rng):
    out = np.zeros((size, size))
    amp, tot, n = 1.0, 0.0, n0
    for _ in range(octaves):
        out += amp * _value_noise(size, n, rng)
        tot += amp
        amp *= 0.5
        n *= 2
    return out / tot


def _blur(a, radius):
    """Tileable box blur, applied twice — cheap and close enough to gaussian."""
    for _ in range(2):
        acc = np.zeros_like(a)
        for d in range(-radius, radius + 1):
            acc += np.roll(a, d, axis=0)
        a = acc / (2 * radius + 1)
        acc = np.zeros_like(a)
        for d in range(-radius, radius + 1):
            acc += np.roll(a, d, axis=1)
        a = acc / (2 * radius + 1)
    return a


def build(size=1024, cells=9, seed=5, crack=0.050, plate_range=0.45,
          grain=0.22, blur_px=3, warp=0.075, amplitude=1.0):
    """The height map, float in 0..1 with mean forced to 0.5.

    cells        how many plates across the image. This, together with the
                 brush diameter, IS the feature size on the model: a 320 mm
                 brush footprint at 12 cells gives ~27 mm plates.
    crack        width of the dark boundary line, in F2-F1 units.
    plate_range  how much neighbouring plates differ in height.
    grain        weight of the fine roughness laid on top.
    warp         how far the cell field is dragged around by low-frequency
                 noise before the cells are computed. Without it the plates
                 come out as clean polygons and the map reads as a mosaic;
                 this is what makes the flakes irregular.
    amplitude    squeezes the map towards its 0.5 midpoint. THIS IS THE DEPTH
                 CONTROL, and it is here rather than on the brush because
                 brush strength turns out not to be one: a textured DRAW
                 stroke with overlapping dabs converges on the same maximum
                 displacement whether strength is 0.04 or 0.25 (measured —
                 all three identical to 0.01 mm). Strength only sets how fast
                 it gets there. What the cut depth actually tracks is the
                 texture's own contrast, so that is the knob.
    """
    rng = np.random.default_rng(seed)

    # jittered-grid Worley. Each pixel only needs the 3x3 cells around it;
    # keeping the neighbour index UNWRAPPED while wrapping only the lookup is
    # what makes the field tile without a seam.
    jit = rng.random((cells, cells, 2))
    u = (np.arange(size) + 0.5) / size
    px, py = np.meshgrid(u, u, indexing="xy")

    # Domain warp. Cheap, and the single biggest difference between "looks
    # like cracked stone" and "looks like a tiled floor".
    px = px + warp * (_fbm(size, 3, 4, rng) - 0.5)
    py = py + warp * (_fbm(size, 3, 4, rng) - 0.5)

    cx = np.floor(px * cells).astype(int)
    cy = np.floor(py * cells).astype(int)

    d = np.empty((9, size, size))
    cid = np.empty((9, size, size), dtype=np.int32)
    k = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx, ny = cx + dx, cy + dy
            wx, wy = nx % cells, ny % cells
            qx = (nx + jit[wy, wx, 0]) / cells
            qy = (ny + jit[wy, wx, 1]) / cells
            d[k] = np.hypot(px - qx, py - qy)
            cid[k] = wy * cells + wx
            k += 1

    order = np.argsort(d, axis=0)
    f1 = np.take_along_axis(d, order[:1], axis=0)[0]
    f2 = np.take_along_axis(d, order[1:2], axis=0)[0]
    nearest = np.take_along_axis(cid, order[:1], axis=0)[0]

    plate_h = rng.random(cells * cells)
    height = 1.0 - plate_range + plate_range * plate_h[nearest]

    # dark line on the cell boundary
    height *= 0.25 + 0.75 * _smoothstep(0.0, crack, f2 - f1)

    height = _blur(height, blur_px)
    # Grain goes on AFTER the blur, or the blur is what you see instead of
    # the grain — the plate faces need to be rough at a much finer scale than
    # the cracks are soft.
    height = (1.0 - grain) * height + grain * _fbm(size, 16, 4, rng)

    height -= height.min()
    height /= max(height.max(), 1e-9)
    height += 0.5 - height.mean()                    # see the header note
    height = 0.5 + (height - 0.5) * float(amplitude)
    return np.clip(height, 0.0, 1.0)


def write_png(path, arr):
    """8-bit grayscale PNG, written by hand.

    Blender's own image save would round-trip this through colour management,
    and a height map that silently picks up an sRGB transform has its midpoint
    moved from 0.50 to 0.21 — which quietly breaks texture_sample_bias.
    """
    a = np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)
    h, w = a.shape
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return path


def build_pebbles(size=1024, cells=8, seed=3, warp=0.05, radius=0.50,
                  radius_var=0.42, height_var=0.40, profile=1.45,
                  aspect=0.35, floor=0.06, grain=0.10, blur_px=1,
                  amplitude=1.0):
    """A field of rounded pebbles, as a 0..1 height map.

    Different construction from build(): that one draws the LINES between
    cells, which gives cracked plates. This one draws a DOME per cell and
    leaves the gaps low, which gives pebbles sitting proud of a floor.

    profile   exponent on the dome, h = (1 - (d/r)^2)^profile. At 0.5 this is
              a true hemisphere — and a hemisphere meets the floor VERTICALLY,
              so displaced it comes out as a stamped disc with a cliff round
              its rim, which is exactly what the first version looked like.
              Any exponent above 1 meets the floor tangentially instead; 1.45
              keeps a full-looking dome while landing softly.
    height_var how much pebbles differ in how proud they sit. Without it every
              pebble tops out at the same height and the band reads as a
              moulded tread plate.
    aspect    how far pebbles depart from circular, each with its own random
              elongation and rotation.
    radius_var spread of pebble sizes.
    floor     height of the ground between them.
    grain     fine roughness over everything, so they are stone not plastic.
    """
    rng = np.random.default_rng(seed)

    jit = rng.random((cells, cells, 2))
    rad = radius * (1.0 - radius_var + 2.0 * radius_var * rng.random((cells, cells)))
    hgt = 1.0 - height_var * rng.random((cells, cells))
    ang = rng.random((cells, cells)) * np.pi
    asp = 1.0 + aspect * (2.0 * rng.random((cells, cells)) - 1.0)

    u = (np.arange(size) + 0.5) / size
    px, py = np.meshgrid(u, u, indexing="xy")
    px = px + warp * (_fbm(size, 4, 3, rng) - 0.5)
    py = py + warp * (_fbm(size, 4, 3, rng) - 0.5)
    cx = np.floor(px * cells).astype(int)
    cy = np.floor(py * cells).astype(int)

    height = np.zeros((size, size))
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
            t = np.clip(1.0 - (rx * rx + ry * ry) / max(1e-12, 1.0) / (r * r),
                        0.0, 1.0)
            # highest dome wins, so overlapping pebbles stack instead of
            # summing into a lump
            height = np.maximum(height, hgt[wy, wx] * t ** profile)

    height = floor + (1.0 - floor) * height
    height = _blur(height, blur_px)
    # Grain at 10 cells x 3 octaves, not 20 x 4. The finer version put detail
    # at roughly the mesh's own cell size, which aliases into visible moiré
    # ripples across the flat ground once displaced — a texture cannot carry
    # detail finer than the geometry it is pushing.
    height = (1.0 - grain) * height + grain * _fbm(size, 10, 3, rng)

    height -= height.min()
    height /= max(height.max(), 1e-9)
    return np.clip(0.5 + (height - 0.5) * float(amplitude), 0.0, 1.0)
