"""
Pure-math path generation for texture-paint stroke tools. No bpy — usable
both from inside Blender (paint.py) and, if ever needed, from a standalone
subprocess, since it's plain Python/math.

  catmull_rom_polyline(anchors, samples_per_segment=20)
      Dense polyline through `anchors` (list of (x, y)) using a clamped
      Catmull-Rom spline — passes exactly through every anchor, unlike
      Bezier (which needs separate tangent handles the caller would have
      to reason about). 2 anchors degenerates to a straight line. Rounds
      off every anchor — good for an organic seam/crack, wrong for
      anything with real corners (see linear_polyline below).

  linear_polyline(anchors, samples_per_segment=20)
      Dense polyline through `anchors` via plain straight segments — every
      anchor stays a sharp corner. Use this (usually with build_stroke_
      path(..., smooth=False)) for angular shapes like a carved panel
      border, then let add_wobble()'s small amount of wobble supply the
      hand-carved irregularity instead of spline rounding.

  add_wobble(polyline, amplitude, frequency, seed=0)
      Offsets each point perpendicular to the curve's local tangent by a
      SINGLE sine wave, so a hand-picked path reads as organic/hand-drawn
      rather than a mathematically perfect curve. Good for seams/panel
      borders — a smooth, gentle meander. Wrong for cracks (see
      add_jagged_wobble) — a single sine is periodic and reads as a
      "wave", not a fracture. Tapers to zero over the first/last 8% of
      the path so the anchored start/end points don't drift.
      amplitude/frequency are in the SAME units as the polyline's own
      coordinates (normalized 0-1 image space, in this codebase).

  add_jagged_wobble(polyline, amplitude, seed=0, roughness=1.0)
      Like add_wobble, but sums 3 sine waves at incommensurate
      frequencies (each with its own seeded random phase/amplitude
      weight) instead of one — cheap multi-octave noise. Doesn't repeat
      periodically over a single path the way one sine does, and mixes
      broad meander with fine jitter, which is what makes it read as an
      irregular crack/fracture rather than a "wave". `roughness` (default
      1.0) shifts the balance toward the fine/jittery octave (>1) or the
      broad/wandering octave (<1).

  offset_polyline(polyline, distance, aspect=1.0)
      The same path shifted sideways by a constant distance, to the left
      of travel for positive values. Needed whenever one stroke has to
      run alongside another rather than on top of it — a fracture's
      shoulder, a second scrape beside the first. `aspect` is the
      region's width/height: normalized x and y do NOT cover the same
      number of metres, so without it a "constant" offset is a third
      wider on one axis than the other and the two paths converge.

  WAVINESS_PRESETS
      Named (amplitude, frequency) pairs: "straight", "subtle", "wavy",
      "bumpy" — pass a preset name instead of raw numbers for the common
      cases. Doesn't cover "jagged" (crack) — that needs add_jagged_
      wobble's extra roughness knob, so build_stroke_path exposes it as
      its own waviness="jagged" branch instead of a preset tuple.

  build_stroke_path(anchors, waviness="straight", amplitude=None,
                    frequency=None, seed=0, samples_per_segment=20,
                    smooth=True, roughness=1.0)
      Convenience: (catmull_rom_polyline or linear_polyline, per `smooth`)
      + add_wobble()/add_jagged_wobble() in one call. waviness="jagged"
      routes to add_jagged_wobble (amplitude defaults to 0.01 if not
      given); every other waviness routes to add_wobble as before.
      Explicit amplitude/frequency override the waviness preset if given.
"""

import math

WAVINESS_PRESETS = {
    "straight": (0.0,   0.0),
    "subtle":   (0.006, 1.5),
    "wavy":     (0.016, 2.2),
    "bumpy":    (0.006, 8.0),
}


def _catmull_rom_point(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
               (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
               (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
    y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
               (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
               (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
    return (x, y)


def catmull_rom_polyline(anchors, samples_per_segment=20):
    """Dense polyline through `anchors` via a clamped Catmull-Rom spline.

    Passes exactly through every anchor (unlike Bezier, which would need
    tangent handles you would have to reason about). Two anchors
    degenerates to a straight line. It rounds off every anchor — right
    for an organic seam or crack, wrong for anything with real corners;
    use `linear_polyline` for those.
    """
    pts = [tuple(p) for p in anchors]
    n = len(pts)
    if n < 2:
        return pts
    if n == 2:
        a, b = pts
        return [
            (a[0] + (b[0] - a[0]) * (i / samples_per_segment),
             a[1] + (b[1] - a[1]) * (i / samples_per_segment))
            for i in range(samples_per_segment + 1)
        ]

    # Clamped ends: duplicate the first/last anchor as the phantom point
    # so the curve doesn't overshoot past the endpoints.
    ext = [pts[0]] + pts + [pts[-1]]
    seg_count = n - 1

    out = []
    for i in range(seg_count):
        p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        last = seg_count - 1
        steps = samples_per_segment if i < last else samples_per_segment + 1
        for s in range(steps):
            t = s / samples_per_segment
            out.append(_catmull_rom_point(p0, p1, p2, p3, t))
    return out


def linear_polyline(anchors, samples_per_segment=20):
    """Dense polyline through `anchors` via straight segments.

    Every anchor stays a sharp corner. Use this (usually with
    `build_stroke_path(..., smooth=False)`) for angular shapes like a
    carved panel border, and let `add_wobble`'s small irregularity supply
    the hand-carved quality instead of spline rounding.
    """
    pts = [tuple(p) for p in anchors]
    n = len(pts)
    if n < 2:
        return pts
    out = []
    for i in range(n - 1):
        a, b = pts[i], pts[i + 1]
        steps = samples_per_segment if i < n - 2 else samples_per_segment + 1
        for s in range(steps):
            t = s / samples_per_segment
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def add_wobble(polyline, amplitude, frequency, seed=0):
    """Offset each point perpendicular to the path by a SINGLE sine wave.

    Makes a hand-picked path read as drawn rather than computed. Good for
    seams and panel borders — a gentle meander. Wrong for cracks: one
    sine is periodic and reads as a wave, not a fracture (use
    `add_jagged_wobble`). Tapers to zero over the first and last 8% so
    the anchored endpoints do not drift.

    `amplitude`/`frequency` are in the polyline's own units — normalised
    0-1 image space throughout this codebase.
    """
    if amplitude <= 0 or len(polyline) < 3:
        return list(polyline)

    n = len(polyline)
    cum = [0.0]
    for a, b in zip(polyline, polyline[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = cum[-1] or 1.0
    phase = (seed * 12.9898) % (2 * math.pi)

    out = []
    for i, (x, y) in enumerate(polyline):
        i0 = max(0, i - 1)
        i1 = min(n - 1, i + 1)
        tx = polyline[i1][0] - polyline[i0][0]
        ty = polyline[i1][1] - polyline[i0][1]
        tl = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tl, tx / tl   # perpendicular (normal) direction

        s = cum[i] / total
        offset = amplitude * math.sin(2 * math.pi * frequency * s + phase)
        taper = max(0.0, min(1.0, s / 0.08, (1.0 - s) / 0.08))
        offset *= taper

        out.append((x + nx * offset, y + ny * offset))
    return out


def offset_polyline(polyline, distance, aspect=1.0):
    """Shift a path sideways by `distance`, positive = left of travel.

    `distance` is in normalized-Y units and `aspect` is region width/height,
    so the shift is the same number of PIXELS everywhere regardless of which
    way the path happens to be heading.
    """
    if abs(distance) < 1e-9 or len(polyline) < 2:
        return list(polyline)

    n = len(polyline)
    out = []
    for i, (x, y) in enumerate(polyline):
        i0 = max(0, i - 1)
        i1 = min(n - 1, i + 1)
        # tangent measured in pixel-ish space, so the normal is a true
        # perpendicular on screen and not merely perpendicular in the
        # stretched normalized coordinates
        tx = (polyline[i1][0] - polyline[i0][0]) * aspect
        ty = polyline[i1][1] - polyline[i0][1]
        tl = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tl, tx / tl
        out.append((x + nx * distance / aspect, y + ny * distance))
    return out


def add_jagged_wobble(polyline, amplitude, seed=0, roughness=1.0):
    """Like `add_wobble`, but sums 3 sines at incommensurate frequencies.

    Cheap multi-octave noise: it does not repeat over a single path the
    way one sine does, and it mixes broad meander with fine jitter, which
    is what makes it read as an irregular fracture rather than a wave.
    `roughness` > 1 shifts weight to the fine octave, < 1 to the broad
    wandering one.
    """
    if amplitude <= 0 or len(polyline) < 3:
        return list(polyline)

    n = len(polyline)
    cum = [0.0]
    for a, b in zip(polyline, polyline[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = cum[-1] or 1.0

    # 3 incommensurate-frequency octaves, each with its own seeded phase —
    # doesn't repeat periodically over one path length (unlike a single
    # sine) and mixes a broad wander with fine jitter.
    rnd = lambda k: ((seed + k) * 12.9898) % (2 * math.pi)
    octaves = [
        (0.55, 1.7,  rnd(0)),                    # broad wander
        (0.30, 4.3,  rnd(1)),                    # mid detail
        (0.15 * roughness, 11.0 * roughness, rnd(2)),  # fine jitter
    ]

    out = []
    for i, (x, y) in enumerate(polyline):
        i0 = max(0, i - 1)
        i1 = min(n - 1, i + 1)
        tx = polyline[i1][0] - polyline[i0][0]
        ty = polyline[i1][1] - polyline[i0][1]
        tl = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tl, tx / tl

        s = cum[i] / total
        offset = sum(w * math.sin(2 * math.pi * f * s + p) for w, f, p in octaves) * amplitude
        taper = max(0.0, min(1.0, s / 0.05, (1.0 - s) / 0.05))
        offset *= taper

        out.append((x + nx * offset, y + ny * offset))
    return out


def build_stroke_path(anchors, waviness="straight", amplitude=None,
                      frequency=None, seed=0, samples_per_segment=20,
                      smooth=True, roughness=1.0, resolved=False):
    """Anchors to a finished stroke path in one call.

    Runs `catmull_rom_polyline` or `linear_polyline` (per `smooth`), then a
    wobble. `waviness="jagged"` routes to `add_jagged_wobble` with amplitude
    defaulting to 0.01; every other value routes to `add_wobble` using the
    named preset from `WAVINESS_PRESETS` ("straight", "subtle", "wavy",
    "bumpy"). Explicit `amplitude`/`frequency` override the preset.

    **`resolved=True` DISABLES ALL IRREGULARITY.** It returns `anchors`
    byte-for-byte: no spline, no wobble, whatever `waviness` says. It is only
    correct for a path that ALREADY carries its irregularity. Hand it a path
    computed from geometry — a projected edge, an arris, a ring — and you get
    that geometry's exact shape, which for any straight edge is a dead-straight
    line. Sculpting along it produces a machined groove rather than a broken
    one. If your points came out of a projection helper, you want
    `resolved=False` and a `waviness`.
    """
    # `resolved` says the caller is handing over a finished dense polyline —
    # a path that has already been wobbled, or one derived from another
    # path's samples. Splining it again rounds off the very irregularity it
    # was built to carry, and re-wobbling it wobbles the wobble.
    if resolved:
        # Asking for waviness AND resolved is a contradiction, and a silent one:
        # the caller gets a perfectly straight path while believing it asked for
        # an irregular one. pillar_run_001 step 2 did exactly this — passed the
        # projected corner arris through as resolved, and every crease came out
        # as a machined line down a mathematically perfect edge. Say so rather
        # than quietly honouring the flag.
        if waviness not in (None, "straight") or amplitude:
            print(f"[pathgen] WARNING: build_stroke_path(resolved=True) ignores "
                  f"waviness={waviness!r}/amplitude={amplitude!r} - returning the "
                  f"anchors unchanged. If these points came from geometry rather "
                  f"than from an earlier wobbled path, pass resolved=False.")
        return [tuple(p) for p in anchors]
    builder = catmull_rom_polyline if smooth else linear_polyline
    base = builder(anchors, samples_per_segment=samples_per_segment)

    if waviness == "jagged":
        amp = 0.01 if amplitude is None else amplitude
        return add_jagged_wobble(base, amp, seed=seed, roughness=roughness)

    if amplitude is None or frequency is None:
        pa, pf = WAVINESS_PRESETS.get(waviness, WAVINESS_PRESETS["straight"])
        amplitude = pa if amplitude is None else amplitude
        frequency = pf if frequency is None else frequency
    return add_wobble(base, amplitude, frequency, seed=seed)
