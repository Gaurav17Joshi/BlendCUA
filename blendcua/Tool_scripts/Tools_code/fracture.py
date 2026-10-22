"""Cracks that read as SPLIT STONE rather than as an engraved line.

Not pillar-specific: this works on any mesh, from any view, in screen
coordinates like the rest of the harness.

--------------------------------------------------------------------------
WHY A SINGLE CARVED GROOVE NEVER LOOKS RIGHT
--------------------------------------------------------------------------
The obvious way to cut a crack is to drag a sharp brush along a line and,
if it looks weak, drag a wider soft brush along the same line. That is what
I did first, and it produces a RIBBON: a channel of constant width, with a
symmetrical lip on both sides, ending abruptly at both tips. It reads as
something a tool cut into a smooth surface, because that is exactly what it
is.

Look at a real fracture (images/Pillar/Pillar_damage3.png). Four things are
true of it, and none of them are true of a groove:

  1. IT IS NOT A CHANNEL, IT IS A BOUNDARY. What the eye actually reads is
     that the stone on one side of the line sits at a different level and
     angle from the stone on the other. The dark line is only the seam
     between two plates. A symmetric groove has no two sides — both banks
     are the same height — so it can never read as a split however deep it
     is cut. This is the big one.

  2. ITS WIDTH VARIES ALONG ITS LENGTH. It is a hairline in places, opens
     out in others, and very nearly closes in between. A constant width is
     the single loudest tell that a machine made it.

  3. IT ENDS IN NOTHING. A fracture dies out; it does not stop. Both tips
     feather away until there is nothing left to see.

  4. IT IS STRAIGHT-ISH WITH KINKS, NOT WAVY. Stone fails along a plane and
     then re-directs, so a crack runs straight for a stretch, kinks, and
     runs straight again. Splining anchors through a Catmull-Rom rounds
     every one of those kinks off and gives you a river. Author the anchors
     with `smooth=False` and let the jagged wobble supply the fine detail.

--------------------------------------------------------------------------
WHAT THIS MODULE DOES ABOUT IT
--------------------------------------------------------------------------
Three passes, of which the second is the one that matters:

  CORE       DRAW_SHARP inverted, driven by a PROFILE so its width and depth
             vary along the length and both ends feather to nothing.
  SHOULDER   a wide, weak, inverted DRAW running PARALLEL TO THE CRACK AND
             OFF TO ONE SIDE, dropping that side by a few millimetres. This
             is the plate offset from (1). It is not a lip, it is not
             symmetric, and it must not be centred on the crack.
  LOBES      optional short scrapes hanging off the crack on the shoulder
             side, where a flake has spalled away along the fracture.

There is deliberately NO crease pass. CREASE pinches both banks in towards
the line, which is precisely the symmetry that has to be broken.

--------------------------------------------------------------------------
USE
--------------------------------------------------------------------------
    import fracture as fr

    plan = fr.plan(points, region, ppm, seed=5, core_r=0.028,
                   shoulder=dict(side=+1, radius=0.11, strength=0.07),
                   lobes=[dict(at=0.42, length=0.09, radius=0.055)])
    fr.preview_strokes(plan, core_r=0.028, ppm=ppm, region=region)  # to draw
    rep = fr.cut("Pillar", points, region, ppm, ...)                # to sculpt

`plan()` is pure geometry and `cut()` calls it, so a preview drawn from the
plan cannot disagree with the cut — the shoulder and the lobes are derived
from the core's own resolved samples, not re-derived from the anchors.
"""

import math

import numpy as np

from lib.pathgen import build_stroke_path, offset_polyline
import sculpt_native as sn

# --------------------------------------------------------------------------
# profiles — how hard the brush presses along the stroke
# --------------------------------------------------------------------------

# (t, pressure) keyframes. Pressure scales BOTH depth and width, so a dip is
# the crack nearly closing rather than merely getting shallower.
#
# Ends are pinned at 0. The first and last dab of a stroke are the ones that
# betray a tool: a crack that starts at full width has a blunt end, and there
# is no such thing on stone.
FRACTURE = ((0.00, 0.00), (0.07, 0.80), (0.20, 0.50), (0.36, 1.00),
            (0.52, 0.42), (0.70, 0.95), (0.86, 0.38), (1.00, 0.00))

# A BRANCH is not a small crack, and giving it the fracture profile is why
# the first two came out invisible. A branch starts ON the trunk, where the
# stone is already open, so it is at its WIDEST at its first dab and feathers
# only at its free end. Taper both ends of a 300 mm branch and there is
# nothing left in the middle to see.
BRANCH = ((0.00, 0.95), (0.18, 1.00), (0.55, 0.80), (1.00, 0.00))

# The shoulder exists over PART of the crack only. In the reference the upper
# third has a whole displaced plate beside it while the lower half is a clean
# hairline, and that unevenness is most of what sells it.
SHOULDER = ((0.00, 0.00), (0.12, 0.10), (0.34, 1.00), (0.58, 0.75),
            (0.80, 0.20), (1.00, 0.00))


def profile(keys):
    """(t, value) keyframes -> the callable apply_stroke(profile=) wants."""
    ts = [float(k[0]) for k in keys]
    vs = [float(k[1]) for k in keys]

    def f(t):
        return float(np.interp(t, ts, vs))
    return f


# --------------------------------------------------------------------------
# geometry — everything the cut will stroke, before anything is sculpted
# --------------------------------------------------------------------------

def _norm_per_metre(region, ppm):
    """One metre, expressed in normalized-Y units at this zoom."""
    return ppm / float(region.height)


def _lobe_path(core, lobe, region, ppm):
    """A short stroke hanging off the crack at `at`, angled `angle` degrees.

    Starts ON the crack, so the flake is attached to the fracture instead of
    floating beside it — a spall that does not touch the crack it came from
    reads as a separate dent.
    """
    aspect = float(region.width) / float(region.height)
    n = len(core)
    i = min(n - 1, max(0, int(round(lobe.get("at", 0.5) * (n - 1)))))
    i0, i1 = max(0, i - 2), min(n - 1, i + 2)

    tx = (core[i1][0] - core[i0][0]) * aspect
    ty = core[i1][1] - core[i0][1]
    tl = math.hypot(tx, ty) or 1.0
    tx, ty = tx / tl, ty / tl
    nx, ny = -ty, tx                       # left of travel

    side = float(lobe.get("side", 1))
    a = math.radians(float(lobe.get("angle", 55.0)))
    dx = tx * math.cos(a) + nx * math.sin(a) * side
    dy = ty * math.cos(a) + ny * math.sin(a) * side

    length = float(lobe.get("length", 0.08)) * _norm_per_metre(region, ppm)
    cx, cy = core[i]
    return [(cx + dx * length * t / aspect, cy + dy * length * t)
            for t in (0.0, 0.5, 1.0)]


def plan(points, region, ppm, seed=0, core_r=0.028, waviness="jagged",
         amplitude=0.004, roughness=1.3, smooth=False, shoulder=None,
         lobes=()):
    """Resolve the core path and everything derived from it.

    smooth=False by default, unlike everywhere else in the harness: a crack
    wants its anchors to stay corners. See point (4) at the top.
    """
    core = build_stroke_path(points, waviness=waviness, amplitude=amplitude,
                             seed=seed, smooth=smooth, roughness=roughness)
    out = {"core": core, "shoulder": None, "lobes": []}

    if shoulder:
        # Clear of the cut, not centred on it. The shoulder's inner edge sits
        # just outside the core's outer edge, so the two passes touch without
        # the wide brush reaching across and levelling the incision it is
        # supposed to be standing beside.
        gap_m = core_r + shoulder["radius"] * float(shoulder.get("gap", 0.55))
        d = (gap_m * _norm_per_metre(region, ppm)
             * float(shoulder.get("side", 1)))
        out["shoulder"] = offset_polyline(
            core, d, float(region.width) / float(region.height))

    for lo in lobes:
        out["lobes"].append(_lobe_path(core, lo, region, ppm))
    return out


# --------------------------------------------------------------------------
# preview
# --------------------------------------------------------------------------

def _circle(centre, radius_px, region, n=48):
    cx, cy = centre
    rx = radius_px / float(region.width)
    ry = radius_px / float(region.height)
    return [(cx + rx * math.cos(2 * math.pi * i / n),
             cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def preview_strokes(pl, region, ppm, core_r, shoulder=None, at=0.36):
    """Stroke dicts for paint.stroke_lines_preview, drawn from the PLAN.

    Every path is marked `resolved`, so the preview draws the samples the
    brush will actually visit rather than re-splining the anchors.
    """
    out = [{"points": pl["core"], "resolved": True, "show_anchors": False,
            "color_hint": (255, 90, 90), "label": "crack"}]
    if pl["shoulder"]:
        out.append({"points": pl["shoulder"], "resolved": True,
                    "show_anchors": False, "color_hint": (255, 190, 60),
                    "label": "shoulder (drops this side)"})
    for i, lp in enumerate(pl["lobes"]):
        out.append({"points": lp, "resolved": True, "show_anchors": False,
                    "color_hint": (170, 255, 120), "label": "flake%d" % i})

    # Size circles where the crack is at FULL pressure — a circle drawn at a
    # point where the profile has the brush at 40% would overstate the cut by
    # more than twice.
    core = pl["core"]
    anchor = core[min(len(core) - 1, int(at * (len(core) - 1)))]
    out.append({"points": _circle(anchor, core_r * ppm, region),
                "resolved": True, "show_anchors": False,
                "color_hint": (60, 200, 255),
                "label": "cut %.0f mm" % (core_r * 2000)})
    if shoulder:
        sh = pl["shoulder"] or core
        sa = sh[min(len(sh) - 1, int(0.34 * (len(sh) - 1)))]
        out.append({"points": _circle(sa, shoulder["radius"] * ppm, region),
                    "resolved": True, "show_anchors": False,
                    "color_hint": (255, 190, 60),
                    "label": "shoulder %.0f mm" % (shoulder["radius"] * 2000)})
    return out


# --------------------------------------------------------------------------
# the cut
# --------------------------------------------------------------------------

def cut(obj_name, points, region, ppm, seed=0, core_r=0.028,
        core_strength=0.85, core_profile=FRACTURE, waviness="jagged",
        amplitude=0.004, roughness=1.3, smooth=False, shoulder=None,
        lobes=(), label="crack"):
    """Cut one fracture. Returns {"rows": [...], "plan": {...}}.

    shoulder : dict(side=+1|-1, radius=metres, strength=0..1,
                    gap=0.55, profile=SHOULDER)
               side is which side of the line drops, in screen terms: +1 is
               the left of travel.
    lobes    : [dict(at=0..1, length=metres, radius=metres, strength=0..1,
                     angle=degrees, side=+1|-1)]
    """
    pl = plan(points, region, ppm, seed=seed, core_r=core_r,
              waviness=waviness, amplitude=amplitude, roughness=roughness,
              smooth=smooth, shoulder=shoulder, lobes=lobes)
    rows = []

    # 1. the incision — profiled in BOTH width and depth
    rep = sn.apply_stroke(
        obj_name, 'DRAW_SHARP',
        {"points": pl["core"], "resolved": True},
        invert=True, size=max(2, int(round(core_r * ppm))),
        strength=core_strength, profile=profile(core_profile),
        profile_size=True, label="%s_core" % label)
    rows.append("  core      r=%3.0f mm  in %+.4f m (%d verts)"
                % (core_r * 1000, rep["max_in"], rep["verts_moved"]))

    # 2. the plate offset — the pass that makes it a split and not a groove
    if shoulder:
        sp = shoulder.get("profile", SHOULDER)
        rep_s = sn.apply_stroke(
            obj_name, 'DRAW',
            {"points": pl["shoulder"], "resolved": True},
            invert=True, size=max(3, int(round(shoulder["radius"] * ppm))),
            strength=shoulder.get("strength", 0.07),
            profile=profile(sp),
            # width constant, depth fading: a shoulder that narrows as it
            # weakens turns back into a second line beside the first
            profile_size=False, label="%s_shoulder" % label)
        rows.append("  shoulder  r=%3.0f mm  side %+d  in %+.4f m (%d verts)"
                    % (shoulder["radius"] * 1000,
                       int(shoulder.get("side", 1)), rep_s["max_in"],
                       rep_s["verts_moved"]))

    # 3. spalled flakes along the fracture
    for i, (lo, lp) in enumerate(zip(lobes, pl["lobes"])):
        rep_l = sn.apply_stroke(
            obj_name, 'PLANE',
            {"points": lp, "resolved": True},
            invert=False, size=max(3, int(round(lo.get("radius", 0.055)
                                                * ppm))),
            strength=lo.get("strength", 0.55),
            plane_offset=lo.get("offset", -0.25),
            plane_height=1.0, plane_depth=0.0,   # scrape: only takes off
            use_plane_trim=True, plane_trim=lo.get("trim", 0.35),
            profile=profile(((0.0, 1.0), (0.55, 0.85), (1.0, 0.0))),
            profile_size=True, label="%s_flake%d" % (label, i))
        rows.append("  flake%d    r=%3.0f mm  in %+.4f m (%d verts)"
                    % (i, lo.get("radius", 0.055) * 1000, rep_l["max_in"],
                       rep_l["verts_moved"]))

    return {"rows": rows, "plan": pl}
