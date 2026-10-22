---
name: plan-from-plates
description: Read this when a task has (or the plan makes) front and side blueprints of a ONE-AXIS low-poly mass (skull, vase, head). The plan measures the plates and hands the executor a station procedure and the plate_loft tool; the steps follow the subject's parts, and the build is done in orthographic views with only the final camera on the photograph's angle. A branched or sideways subject decides its construction per part first (low-poly-one-mesh).
evidence: mem/Skull_tryout (three steps, residual 1.5 / 2.0 px); plans/04_skull/04_skull_plan.md step 2 as the counter-example (a nine-station width table the executor lofted into a box)
---

# Plan from the plates, not around them

The skull plan said "trace the front contour and side profile against the two blueprint
empties, then loft a 12-vertex ring through nine stations" and listed the station widths.
"Trace" is one word with no procedure; "loft nine stations with these widths" is a recipe.
An executor under an action budget follows the recipe. Two rebuilds later the head was
still a box, because the plan had never turned the drawing into a construction.

## Where the plates come from matters

If the plates are generated during the build (step 1 makes them with gpt-image), the
planner never sees them and cannot measure anything. Either the task supplies verified
front/side plates beside the reference, or the plan's step 1 is "make and verify the
plates and write `stations.json` with `plate_loft.measure_plates`", and every later step
reads that file. Never put plate numbers into the plan by hand; put the **measurement**
into the plan.

## The shape of the steps follows the parts, not a template

The skull went masses, then features, then presentation because a skull is one mass with
features cut into it. That is not a template. A figure is one step for the whole body
(the task may say so), a dog is body-with-reserved-roots then limbs from those roots, a
hammer is two measured blocks. Decide the steps from the parts and the per-part decision
in `low-poly-one-mesh` section 2. For a one-axis mass, the skull's order still applies:

1. **Main masses.** `plate_loft.measure_plates` -> `place_plates` -> `loft_rings`, one
   object per bone/part that is a separate thing (a skull: cranium+maxilla, and a jaw as
   a U). Name the station heights (dense where the outline curves, one at every profile
   step), the base rows where the mass really ends, and the `egg` assumption. Review:
   `reference_outline` on both plates and `outline_residual` per plate, mean and worst,
   against a stated gate (15 px on a 1024 px plate is achievable; say it).
2. **Features, from the front and side plates.** Loops, converging strokes and arcs are
   measured (dark strokes inside a window), then cut into or placed on the masses:
   sockets and apertures as exact boolean cuts to a measured depth; tooth rows on the
   masses' own rings, crowns on the band next to the occlusal line and an alveolar strip
   for the rest; joints as unions. Review: the same outline check with every object,
   plus a count and a crop of each cut feature.
3. **Materials and presentation.** Colours sampled from the photograph (median RGB of a
   patch per material role, converted to linear), a neutral backdrop, the camera on the
   photograph's angle, a plain key + fill. Review: rendered crops against the photo.

Build in ortho front/right views throughout; the photograph's perspective is for the
last step only. The reviewer's "measured contour gate" belongs in step 1, and it must be
computed on the plate (`outline_residual`), not on a viewport screenshot.

## What to write and what not to

- Write the station fractions and why (which profile feature each sits on), the base
  rows, the egg factor and that it is an assumption.
- Write the feature windows (which region of which plate holds the loop / strokes) so the
  executor's read is a lookup, not a search.
- Do not write widths, radii or coordinates. Every number the executor needs comes out of
  `measure_plates` / the feature read at build time, with the pixel reads kept beside the
  value for audit.
- Say the tool by name. "Trace the plate" produces a typed table; "`plate_loft.loft_rings`
  through `stations.json`" produces a traced mesh.
