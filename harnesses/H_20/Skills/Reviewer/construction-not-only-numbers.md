---
name: construction-not-only-numbers
description: A step can meet every number and still be built wrong; check how parts were made and joined, whether they match the picture instead of the object, and whether a synthesised plate was actually used.
---

# Construction, not only numbers

Six judged builds passed every review and were still wrong in ways a person sees at once:
three lofts joined badly instead of one mesh, a cuboid foot under a cylinder leg, a mouth built
as gum blocks and lip tubes instead of a cut, laces placed to match the photo and floating off
the shoe, a handle entering the face of a hammer head, a front plate synthesised and then never
measured from. Every one of those steps met its numbers.

Add to any review, whatever the checklist says:

- **How was it made?** For each part the step owns: one mesh or separate solids; loft or
  primitive; cut or added. Where the reference shows one continuous form, separate solids
  butted together are a fail even if the outline matches.
- **Where is it attached?** Name the part it joins and the face it enters. A part attached where
  the picture shows it rather than where the object has it (the visible side, the camera side)
  is a fail.
- **Was the plate used?** If the plan holds a synthesised front/side/top plate, the step's shape
  numbers should cite the plate, and its proportions the photo. A plate made and not used is
  the same as no plate.
- **Does it look crude?** A part that is a primitive where the reference has a shaped part
  (flat cut fins, rod legs, tube bars) is a fail of effort, not of measurement. Say so.

## Branched flat-strap construction

For connected scroll or branch networks, add an Important construction check beside
the numeric section check. Inspect a clean FRONT crop and name how the member was
made: one shared network mesh, shared/welded junctions, and flat stable faces. At
every non-terminal branch-to-collar, branch-to-rail, and branch-to-branch transition,
look for zero background gap and one continuous occupied run; a capped object-joined
stroke fails even if its width and bbox pass. Then inspect a TOP or modest oblique crop
and report the front width, edge depth, depth/width ratio, closed sides, and whether
only intentional terminal curls are tapered/capped.

Evidence: `mem/02_iron_gate_run_001/steps/step_003/review/round_01/review.txt`.

## Repeated flat-blade profile gate

For repeated broad leaves, inspect the evaluated Solid forms as well as the alpha render. Require carrier deformation that produces distinct projected silhouette/profile families—not just object rotation, uniform scale, or texture variation—and report representative crop extents or mesh identities before PASS. Reject a repeated single-profile family even when the holes and alpha render look correct.

Evidence: `Curator/reports/03_monstera_pot/round_01/03_monstera_pot_remedy.md#1` and `Curator/reports/03_monstera_pot/round_01/apply/applied.json#remedies[0]`; `Checker/reports/03_monstera_pot_run_002/verdict.json` resolved `leaves.detail.low_shape_variation` with 8 distinct geometry hashes and representative green crops of 362x223, 367x235, 460x290, and 205x277.

## Evaluated Solid resolution gate

When a review calls a curved animal mass smooth, inspect a magnified Solid crop and report the evaluated ring or edge resolution, not only the projected plate residual. Quote the actual circumferential section count and longitudinal station count from the built `TurtleBody` audit. Reject a body that passes projected plate residuals but shows broad planar or stair-stepped shell transitions at the crown, shoulder, rear taper or plastron; smooth shading is not evidence that the construction is dense enough.

Evidence: `mem/15_sea_turtle_run_001/steps/step_002/01_build_turtle_body.py` and the false PASS at `mem/15_sea_turtle_run_001/steps/step_002/review/round_02/review.txt`.

## Important occupied-coverage gate for repeated masonry

Repeated masonry needs an occupied-coverage gate, not only object count, closure, and
course bands. In a clean TOP crop project each evaluated course into angular intervals;
in a FRONT crop inspect the visible course bands. Report the largest adjacent background
slot as a fraction of its local course pitch for every course, together with the course
mean and maximum. PASS only when the maximum slot and mean meet the plan's thresholds and
the wall reads as one continuous chunky ring; 45 separate closed boxes can still fail if
the background slots dominate the intended joints.

Evidence: the false PASS at
`mem/20_low_poly_well_run_001/steps/step_001/review/round_01/review.txt`, which reported
45 stones and five courses but no neighbor-gap measurement.

