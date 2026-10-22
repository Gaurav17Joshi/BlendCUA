---
name: trace-the-reference
description: Read this before planning any part whose shape is readable in the reference photograph (a leg, a bracket, a handle, a chair back, a profile of any kind) and there is no blueprint. The plan does not describe the shape in words and numbers; it reads the shape out of the photo with a script (mask, row table, landmarks, outline polygon) and hands the executor that polygon as the build input, with the overlay residual as the gate.
evidence: mem/06_tablecloth_drape_run_003 (2026-09-12) — pedestal legs traced from tasks/train/06_tablecloth_drape/reference.png, side legs within 8-11 px of the photo on 1024 px; 06_tablecloth_drape_run_001 and run_002 (the loop's rebuild) step 1 as the counter-example (bbox numbers in the plan, "carved-looking" in the text, empty scripts folder, legs invented)
---

# The photo is the drawing. Read it, do not describe it.

Scope: a **part with a readable silhouette in one view** (a leg, a bracket, a handle, a
scroll), built as that outline extruded. Not a body, a figure or any part whose
cross-section changes along a turning axis: those are decided part by part in
`low-poly-one-mesh` section 2 and built as a chain or a loft in the part's own direction.

Two tablecloth runs built the pedestal legs from words. The planner's `measure_silhouette.py`
made a clean mask of the pedestal and then reduced it to a bounding box (470x336 px, width
0.50 of the cloth, feet at v 0.916). The plan said "three radial cabriole legs" once and
"a broad, flattened, carved-looking three-branch support over three broad occupied paths"
the next time, and gave the executor one span number to hit. The executor wrote, in its own
action header, "the scale is deliberately convenient rather than copied from pixels", typed a
path from imagination, and its step's `scripts/` folder stayed empty. The reviewer passed a
branch count and a depth ratio. The checker called the legs wrong both times.

The mask was one row-walk away from the legs. `Tool_scripts/Tools_code/outline_trace.py`
is that row-walk, packaged. Blueprints are not required: a photograph with a readable
silhouette of the part is enough, and `blueprint-traced-loft` / `plan-from-plates` remain
the route when front and side plates exist.

## What the planner does (in `plans/<task>/scripts/`, results in the plan)

1. **Mask the material**, keep the largest piece, and **print the row table**
   (`print_row_table`, every 10 px). Look at it. One run splitting into three is a neck with
   two knees beside it; runs merging is where roots form a collar; a run that stays narrow
   on the axis is the near member seen end-on. Write those rows into the plan as landmarks
   ("neck at y 683, half-width 25 px; roots merge 693..790; ring at 673").
2. **Fix the frame from geometry the photo guarantees.** Symmetric turned parts give the axis
   (`axis_x`). Members that stand on one floor give the scale and the camera: three feet at
   the same radius, the two side ones drawn at 30 deg behind the image plane, so
   L = span / (2 cos 30); the near foot sits lower by (1.5 L sin pitch)
   (`pitch_from_floor_points`). State the assumption (120-degree spacing, one floor).
3. **Cut the part out and trace it.** `cut_region` at the neck (the straight cut is the root
   that gets buried) and below the ring; `boundary_polygon` -> `resample_smooth` (~5 px
   spacing, 130 points for a leg) for the mesh and `simplify_closed` (45 points) for the
   record. `draw_polygon` back on the photo: if the red line is not on the part, stop.
4. **Map it into the part's own plane** with `image_to_plane` (foreshortening of the plane
   angle and the pitch undone), divided by L so the executor scales it once. Read the
   thickness from a member seen end-on (the front leg's column width below the side toes:
   33.5 px, t/L 0.124). Save `legs.json` (or whatever the part is) beside the plan.
5. **Write the plan step as a lookup, not a search.** "Build `Foot_*` with
   `outline_trace.extrude_profile` from `scripts/legs.json`, L = the old feet's reach, t = 0.124 L,
   root buried to r 0.04, at -90 / 30 / 150 deg" — every number cites the pixel read that
   produced it. The review gate is the built outline back on the photo:
   `align_by_landmarks` on the axis / floor row / toe span (never on bounding boxes) and
   `mask_residuals` per row, with a stated number (10 px mean edge residual on 1024 px is
   achievable for a traced leg).
6. **Tone targets the same way.** `tone_stats` on the photo and on the current render with
   the same mask rule: median RGB, value, highlight fraction, p95 luminance. Put the photo's
   numbers in the presentation step so the executor scales the base colour by
   `base_colour_scale` instead of eyeballing "dark warm brown".

## What not to write

- Not adjectives ("broad, flattened, carved-looking") and not a typed width table: neither
  reads the drawing. If the plan cannot point at a polygon file, the executor will invent one.
- Not a bounding box as the gate. A box, a count and a depth ratio were all satisfied by
  three bent flat hooks. The gate is the outline on the photo with a residual.
- Not "no plate needed, the shape is visible in the photograph" unless the next sentence
  says who reads it out of the photograph and with what.
