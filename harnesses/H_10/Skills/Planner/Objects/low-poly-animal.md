---
name: low-poly-animal
description: Read this before planning or building any low-poly animal that stands on legs (dog, deer, horse, cat, cow) from side/front/top plates. The body, neck and head are one ring loft along the spine built from a measured station file; the legs grow out of root faces reserved in that loft; the mouth is a cut; tail, ears, eyes and tongue are the only add-ons. Says which plate answers which question, what to read body-only, how to shape a ring so it is not an ellipse, and what to check from three-quarters.
evidence: mem/10_low_poly_dog_run_002 (hand, 2026-09-13): side residual under 3 px, closed mesh throughout, judged good; mem/10_low_poly_dog_run_001 and Curator/good_context/20_low_poly_dog.txt as the counter-example (three lofts butted together, tube legs with box feet, tongue on the camera side)
---

# Low-poly animal: one loft along the spine, limbs grown from it, features cut into it

A standing animal is a sideways body with a neck that rises, a head with a mouth, four
legs that leave the body at angles, and a tail. No single trace gives that shape
(`low-poly-one-mesh`), and the row-slicing loft of `blueprint-traced-loft` is wrong for
it. This skill is the per-part decision for that class, in build order.

## 1. Decide the parts before any measuring

- **Body, neck and head are one mesh**: one chain of rings from the nose to the rump.
  Three lofts (head, neck, torso) joined afterwards is the mistake the person sees first.
- **Legs are extruded from root faces reserved in that loft**, never tubes butted against
  the flank, and the foot is the last stations of the leg, never a block under it.
- **The mouth is a cut** into the head (`cut-openings-from-traced-lines`), so the head is
  built closed first, jaw included, with material to cut.
- **Add-ons only for real attachments**: tail as its own chain buried in the rump, ears as
  small wedges, eyes as beads, tongue inside the cut. Nothing else is a separate object.

## 2. Which plate answers which question

- **Side plate: lengths and heights.** Stations are vertical columns of the side plate; a
  thick neck on a big head does not need tilted rings, vertical ones follow the crest and
  throat fine. Put stations where the outline turns (stop, occiput, withers, croup) and
  at the front and back edge of each leg root.
- **Top plate: width per station**, read at the same head-to-tail fraction, not the same
  pixel column. Skip the columns where ears or elbows widen the outline and interpolate.
- **Front plate: the width ceiling per height.** It shows the widest thing at every
  height, so a ring vertex may never reach beyond it. This one rule makes the neck
  narrower than the shoulders under it and keeps the chest at the plate's width. A
  chain that only knows width and height per station cannot do this.
- **Generated plates disagree with each other.** Measure the three bboxes first, write the
  disagreement into the plan, and name the authority per dimension. Residual gates that
  ignore this are unreachable.
- **Read body-only.** Under the legs the side contour is the leg: draw the belly line
  across the leg columns. Under the head the plate shows the open mouth: draw the closed
  envelope from nose to chin to jaw. Save both overrides in the station file and use the
  same overrides when the residual is measured.

## 3. Build the body from the station file, in world space

- Place rings directly from the JSON (centre, half-height, half-width): no screen-space
  unprojection, no numbers typed into the action.
- **Shape the section.** A ring is not an ellipse: narrower toward the spine, a little
  narrower toward the belly, boxier on the muzzle, rounder on the trunk. Then normalise
  so the polygon's extreme vertices sit exactly on the measured spans, because an N-gon
  with its vertices off the axes falls short of them, and clamp every vertex to the
  front plate's width at its own height.
- Reserve the leg roots as a two-by-two face patch on the lower flank, two station
  intervals long, and record which faces they are.
- End the rump with a smaller ring before the cap so the rear reads rounded, not sliced.
- Audit closed (boundary and non-manifold counts) before anything is attached.

## 4. Legs

- Horizontal stations per leg: the side plate gives front/back extent, the front plate
  gives the pair's separation and width; the hind pair is hidden in the front plate, so
  say what it borrows from the fore pair.
- Extrude the root patch once per station and set the boundary loop onto a measured
  rounded-rectangle ring; the last station is the sole on the floor, which is the cap.
  Joints are just stations where the plate's outline turns.
- Then check the full silhouette, side and front, and look at the roots from
  three-quarters: no seam, no ring where the leg meets the body.

## 5. Head features

- Mouth lines: when the side plate shows the opening, read the lines from the plate (it is
  the model's own frame, no registration); use the photo as the cross-check. Preview on
  the mesh, cut once, paint by plane, audit closed.
- Tongue on the centreline inside the cut, not on the visible side. Eyes seated by
  raycast, not at a plan coordinate. Ears as small wedges standing off the skull, placed
  from the front plate's rows and the side plate's window, in a shade that reads.

## 6. Checks that matter, in this order

1. Closed mesh counts after every construction step.
2. Outline residual per view against the body-only reference, compared at equal
   length fraction when the plates differ in length; quote mean and worst and where.
3. Three-quarter views front and rear, and a low view of the chest: a silhouette that fits
   from the side while the chest is a slab from the front is a fail.
4. Effort goes where it shows: the body loft and the leg roots are most of the grade;
   colour and lighting come last and stay simple.

## The counter-example

run_001 of the dog followed the side outline well and still failed: an ellipse chain in
screen space (front view badly off), the head open with no jaw, leg columns read as body,
tubes for legs with boxes for feet, the tail a taper of the body, and no residual ever
computed against the plates. run_002 built the same dog from the rules above; its
`steps/step_002..003/scripts/` are the runbook (`measure_body_sections.py`,
`01_build_body.py`, `measure_legs.py`, `01_grow_legs.py`, `outline_residual.py`).

## The plan's deliverable

The part decision (what is one loft, what is grown from a root, what is cut, what is an
add-on); the station file with its body-only overrides and the per-dimension plate
authority; the reserved roots by name; the residual gate per view with the disagreement
stated; and the three-quarter checks named for the reviewer.
