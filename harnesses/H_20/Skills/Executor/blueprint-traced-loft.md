---
name: blueprint-traced-loft
description: Read this before building a ONE-AXIS low-poly mass that has a front and a side blueprint (a skull, a head, a vase, a pot). Not for figures, branched or sideways bodies, or slanted parts: there the plan's per-part decision (low-poly-one-mesh) comes first and this tool covers at most one part. For that class the plate is the geometry, not a check — measure both plates into a station table and loft rings through it with the plate_loft tool; then draw the built outline on the plate and report the residual per row.
evidence: mem/Skull_tryout (2026-09-11) — cranium and jaw from plans/04_skull/front_blueprint.png + side_blueprint.png, residual 1.5 px front / 2.0 px side on 1024 px plates; 04_skull_run_001 and run_002 step 2 as the counter-example (33-50 px, typed station table)
---

# The plate is the geometry (for a one-axis mass)

`plate_loft` slices a plate top to bottom and puts one ring per station. That is right
when every horizontal row crosses the subject once: a skull, a vase, a head, a pot. It is
wrong, and wrong silently, when a row crosses two parts (a T-posed figure's arms and
torso), when the subject lies sideways (a dog, a duck, a shark: its cross-sections are
vertical), or when a part's axis turns (a neck, a bent leg). For those, the plan says per
part what is traced, in which direction, and what is built another way
(`Planner/low-poly-one-mesh` sections 2-3), and a limb leaves the body from a reserved
station interval, not from a row table. Use this tool for the one-axis part it fits and
nothing else.

Two runs of the skull built the head mass the same way: a 12-point ring template
swept through nine stations whose widths were **typed into the action** from a
measured table, then the blueprint was overlaid afterwards as a check. Multiply an
ellipse by a width list and you get a rounded box; the reviewer measured 33 px and
50 px residuals against a 15 px gate, five redos nudged the numbers, the method never
changed. Nothing in the build ever *read* the drawing.

The fix is to make the drawing the input. `Tool_scripts/Tools_code/plate_loft.py`:

```python
import plate_loft as PL
data = PL.measure_plates(front_png, side_png, t_stations, base_rows=(0.74, 0.77))
PL.place_plates(front_png, side_png, data["frame"])            # FrontRef / SideRef empties
hm = PL.loft_rings("HM", data["stations"], crown=data["frame"]["crown_point"],
                   base_rows=data["frame"]["base_rows"], egg=0.25, egg_from_t=0.40)
```

`measure_plates` thresholds each plate's fill from its background, registers both on the
subject's top-to-bottom span into one frame (top z=+1, bottom z=-1, face toward -Y), and
at every station height reads the half-width and lateral centre from the front plate and
the front-most and back-most point from the side plate. `loft_rings` puts one n-vertex
superellipse ring through exactly those four extents per station. The fit at the stations
is exact by construction; the only choices left are **where the stations are** and the
**ring shape between the extents**. No number is typed.

## Choosing stations

- Dense where the outline curves (the dome: t = 0.006, 0.02, 0.06, 0.12), sparse on
  straight runs, one at every step in the profile (brow, nasal bridge, cheek notch).
  A bulge between two stations cannot be followed; the answer is another station, not a
  bigger ring.
- The mass ends where the drawing says the bone ends, not on a flat plane. A skull's
  tooth line is level under the face but the base drops behind to the mastoid: give
  `base_rows` the fractions of those rows and the last ring slants (its 150-degree
  vertices on the first row, the 180-degree vertex on the last). Look at the plate for
  where the mass really stops before you decide the cut.
- `egg` narrows the front half of a ring: a face is narrower than the temples, a chin than
  the jaw angles. It is an assumption — two views cannot fix a cross-section. Say so in the
  handover; a top plate would settle it.

## Merged rows and drawn features

The fill answers "where is the outline"; it cannot separate two masses that share a row
(the jaw's ramus in front of the skull base) or find a feature drawn *inside* the fill
(a socket, an aperture, a tooth row, the ramus edge). Those are **strokes**: dark pixels
inside a window of the plate. Read them with a dark-pixel mask restricted to the window
(`mem/Skull_tryout/scripts/measure_features.py` does loops, converging strokes, arcs on a
column, edge strokes per row), and:

- cut sockets and apertures **into** the mass with an exact boolean (cylinder or prism
  from the measured loop / strokes, reaching a measured depth behind the face surface);
  the mass keeps its walls, no liner objects; give the new inner faces a dark material;
- put tooth rows on the measured rings themselves (the mass's tooth-line ring is the
  arch path), crowns on the part of the drawn band next to the occlusal line, the rest a
  continuous alveolar strip — not one picket per tooth over the whole band;
- read a ramus edge from its stroke where the fill has merged, from the fill where it
  stands alone, and build the jaw as a U (body ring loft + two ramus prisms, unioned).

## The check that closes the loop

`perceive.reference_outline([...], ref_name="FrontRef")` draws the exact built
silhouette on the plate at the plate's resolution; `plate_loft.outline_residual` turns
that into a per-row number against the plate fill. Report **mean and worst residual
in plate pixels per plate**, and where the worst is. The skull's 15 px gate is easy for a
traced loft (1.5 / 2.0 px mean) and impossible for a typed one.

Blender's own Python has no Pillow; every overlay used to fail silently inside Blender.
Pillow now lives in the user site-packages and `lib/util.run_overlay` adds that path,
so the overlay PNG is written by Blender itself. If an overlay call returns without
its PNG, that is the first thing to check — do not fall back to "dependency-free"
audits that measure nothing.

## When not to use it

A figure, a branched or sideways body, a slanted part whose axis turns (see the top of this
skill). A subject with no meaningful front/side outline (a cloth drape, a plant), or one whose
form is a chain of parts (a chair) — there `low-poly-one-mesh` and `isolate-then-attach`
apply. A part whose silhouette is readable in the single photograph (a pedestal leg, a
bracket, a handle) needs no plate at all: `build-from-traced-outline` with the
`outline_trace` tool reads the outline straight off the photo. If the plates were generated by gpt-image and not verified (identity check
against the photo, straight views), verify them first: a loft is only as right as the
drawing it traces.

## The tool is a starting point, not a cage

`plate_loft` fixes the method — plates measured, rings through the measurements, outline
back on the plate — not the details. Its ring shape, station choices, base handling and
`egg` were tuned on one skull; another subject will want a different cross-section, a
merged-row rule of its own, a stroke read the tool does not have. When it does not fit,
do what the tryout did: write a few small functions of your own in this step's
`scripts/` folder (a `row_extent` variant, a stroke reader for a window, a different ring
parametrisation), keep the same shape of evidence (every number traceable to plate
pixels, the outline drawn back on the plate, a residual per row), and say in the
handover what you changed and why. Copying the tool's call with the wrong assumptions
is worse than a twenty-line function that reads the drawing you actually have. If the
variant proves general, it belongs in the tool; propose it in the handover.
