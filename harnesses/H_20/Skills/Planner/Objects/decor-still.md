---
name: decor-still
description: Read this before planning or building a still of several simple props (a seasonal decoration, a table arrangement, a hero object with small things around it) from one photograph. The props are made simply, each by the construction that fits it, and their arrangement is part of the task. Says how to measure a cluttered photo by boxes instead of tracing it, how to fix a world frame, how to build each kind of prop, how to place the props in the hero's frame through a measured reference camera and seat them by contact (camera last), and what to check.
evidence: mem/11_pumpkin_decor_run_003 (hand, 2026-09-13): measured by boxes, built from proportions, props placed through the camera, judged good; mem/11_pumpkin_decor_run_001 as the counter-example (ring-traced perspective photo, star-shaped body, disc caps, flat painted flames, hand-drawn leaf polygons standing on edge, one landmark box over everything); mem/16_chocolate_cup_decor_run_002 (hand, 2026-09-16) for the rewritten section 4 and checks 3-5, with mem/16_chocolate_cup_decor_run_001 as its counter-example (every placement solved through the run's own camera; blends/16_chocolate_cup_decor_run_002/LESSONS.md)
---

# A decor still: simple props, measured by boxes, arranged in the hero's frame

A still is a hero object with small props around it on a ground, photographed in
perspective with the props touching and hiding each other. Two things fail such a task:
reading the photo as if it were a blueprint, and building good props but placing them
by guesswork. The plan decides the construction per prop and owns the arrangement.

## 1. Measure by boxes, coarse to fine, never by tracing

- **First pass, full frame:** one box per important thing (the hero, each prop, each
  flame, each leaf). **Second pass, per crop:** a crop of each thing and boxes for its
  parts (eyes and their catchlights, brows, mouth, caps and kernels, wax, wick, flame).
  Draw both passes on the photo and look at them before anything else is done.
- A box is the tight bbox of a colour mask **inside a hand-chosen search window**; the
  window is the only thing chosen by eye, and it is drawn so it can be checked. Sample the
  photo's colours per role first and set the mask from them.
- Where a mask cannot separate (a stem against a backdrop of the same hue, a glossy cap
  that reads as its highlights), read the box by eye and say so in the file.
- The hero's outline is **not traced** (`trace-the-reference`, "When a trace works").
  Its edges are brightness jumps against the local backdrop, each side found where that
  side is clear; the hidden side is declared hidden, not invented.
- Counts and proportions come from measurement, not looks: the number of ribs from the
  spacing of adjacent grooves, the eye's height-to-width from its box, the face axis from
  the eyes' midpoint. The photo's camera turns the hero; the angles on it are referred to
  that axis.

## 2. One world frame, everything a fraction of the hero

- One convention fixes the scale (the hero's width). Every prop size is a fraction of it
  from the boxes, times a stated depth factor for things nearer the camera than the hero.
- What the photo cannot show (a crown dip, how flat a base is) is a named convention.
- The derived numbers live in one file every action reads; no number is typed into an
  action.

## 3. Build each prop the simple way that fits it

- **Round hero with ribs:** one closed solid of revolution; the ribs are a displacement
  along the surface normal so they scallop into the poles instead of stopping at the
  equator; smooth shading. A faceted fan of planes is the mistake to name.
- **Marks stuck on a curved surface** (eyes, brows, a mouth): seated by raycast, domed
  or sunk into the surface, never a flat disc that floats off the curve.
- **Small solids** (acorns, candles, cups): closed revolves from a profile, with the parts
  that read (a cap's rounded rim, a wax rim, a wick) as their own small solids; rotate,
  then drop to the ground by the lowest vertex.
- **Flames:** `Executor/candle-flame.md`.
- **Thin things on the ground** (leaves, petals, paper): `Objects/flat-objects.md`, with
  two rules this class adds: the image comes from gpt-image-2 with a transparent
  background and its alpha is verified (near-binary, with a painted halo under alpha 0
  that is blanked), and a leaf on the ground stays flat, a shallow cup and a lifted lobe
  tip, never standing on edge.

## 4. Arrange in the hero's frame, camera last

(Rewritten 2026-09-16 from the chocolate cup, task 16. The earlier version solved each
prop's lateral position through the run's own camera. The loop's cup did exactly that for
every face mark, drizzle path, marshmallow and cane point, passed all five of its reviews,
and was wrong from every other angle: its camera was not the reference camera, and a
pixel leaves depth free. See `Executor/measure-the-reference-camera.md`.)

- **Measure the reference camera first, from geometry**: a many-point ellipse on the
  sharpest circular edge of the hero, cross-checked against its other circles, with
  square pixels forced. It goes in the world frame file.
- **Convert each prop and mark into the hero's frame** through that measured camera:
  azimuth, height and radius on the hero for things on it (a face, a drizzle), a position
  on the ground or in the vessel for things beside or in it. A pixel gives two
  coordinates; the third comes from a known surface (the hero's profile, the ground, a
  liquid level), never a depth typed by hand.
- **Seat every prop by contact** (`Executor/seating-by-contact.md`): a vertical drop by ray
  cast for resting props, floating for props in a liquid, two computed contacts for a
  leaning one. No support point is pinned by hand.
- **Set the camera last**, at the measured elevation, only for presentation.
- Report each prop's frame position next to the reference's, its contact gap and its
  percentage inside its support, and check no prop vertex is inside the hero.

## 5. Presentation, kept simple

- One cyclorama (ground curving up into the backdrop), not a ground plus a wall, so there
  is no horizon line; a low matte base with the photo's backdrop colour as weak emission.
- One key, one fill, and the flames' own lights, soft enough that nothing you calibrate
  clips. Calibrate on region means (`Executor/tone-calibration-region-means.md`); single
  patches land on drizzle, highlights or an occluding neighbour.

## 6. Checks, in order

1. Closed counts after every construction step.
2. Each prop from the front, top and a low three-quarter, alone.
3. The arrangement report (frame positions against the reference's, contact gaps,
   percentage inside each support, nothing inside the hero). These gates must test the
   defect they name: "sits on the cream" is not `min z > 0`
   (`Reviewer/writing-review-checklists.md`).
4. The colour comparison, last, on region means with visibility and clipping masks
   (`Executor/tone-calibration-region-means.md`), not on single patches.
5. A full ordered replay of every action from an empty scene, then each checkpoint loaded
   and checked to hold only its own step's objects.

A round hero read from the photo (mug, bowl, pumpkin body) takes its profile by the
forward fit in `Executor/lathe-profile-from-silhouette.md`; a sculpted topping by
`Executor/native-sculpt-spirals.md`.

## The plan's deliverable

The two-pass box overlay and the boxes file with the by-eye ones marked; the world frame
file with its conventions and depth factors named; per prop, the construction chosen and
the ratios it uses; the measured reference camera; the arrangement method (frame
positions, the surface each prop's depth comes from, how each is seated); and the checks
above named for the reviewer.
