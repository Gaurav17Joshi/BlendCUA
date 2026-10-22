---
name: trace-or-type
description: Read this when a plan is about to say "trace the plate" or "build the part as primitives" for any part of a subject. Decide per part by what the outline is made of - trace when the silhouette is the shape (curves, no repeating rule), type measured primitives when the outline is straight runs, chamfers and circles - and either way measure the plate row by row and rasterise the built mesh back into the plate's pixel grid for a residual. The decision changes how the mesh is made, not whether it is checked.
evidence: mem/09_thors_hammer_run_003 steps/step_002 (typed blocks, front audit IoU 0.93 / 8 px on 1024) against mem/09_thors_hammer_run_001 and run_002 step 2 (the plate's head polygon traced and lofted, "bulky slab" twice from the checker); mem/06_tablecloth_drape_run_003 step 1 (traced pedestal legs at 8-11 px) as the case where tracing was right (2026-09-13)
---

# Trace or type: decide per part, by what the outline is made of

Two ways to turn a plate into a mesh, and the wrong one costs a round each time:

- **Trace** - extrude the contour polygon (`build-from-traced-outline`) or loft stations
  (`blueprint-traced-loft`) - when the silhouette *is* the shape: curved, organic, no
  repeating rule, more stations than you could type. A pedestal leg, a vase, a skull, a bird.
- **Type** - boxes, lathes and tubes with measured numbers - when the outline is straight
  runs, chamfers, circles and repeated features. A hammer head, a plinth, a rivet band, a
  collar, a handle with a wrap. The measurement gives every number, and a primitive carries
  no tracing noise: no wobble along a straight edge, no rounded corner where the plate has a
  chamfer, no fake bulge where the plate shows an underside.

## The rule

Look at the part's outline in the plate and ask: *could I write it down as a dozen numbers?*
If yes, type it and let the numbers come from the row/column tables. If the honest answer is
"only as a polygon", trace it. A subject usually needs both, part by part (the hammer: head,
bands, collar, pommel typed; nothing traced, because nothing in it is a free curve).

## Either way, the same checks

- **Measure the plate the same way whichever you choose**: the subject mask from the
  blueprint contour, row and column tables, feature rows (rivets, seams, rings), colour
  patches, all saved as JSON with an overlay. Typing does not excuse an empty `scripts/`.
- **Rasterise the built mesh back into the plate's pixel grid** (world -> plate px through the
  frame you loaded the plate with) and compare left/right edges per row with the plate mask:
  mean and worst error, IoU. This is the gate for a typed part exactly as the outline
  residual is for a traced one. Hammer head: IoU 0.93, mean 8 px, worst rows explained.
- **Say which it was in the handover**, and why: "typed: straight lines and 45-degree
  chamfers" or "traced: the curve has no rule".

## What tracing got wrong here

Runs 001 and 002 traced the hammer head's plate polygon. The plate is a generated
straight-on view, so the head's underside shows as a dark strip with elliptical rivets; the
polygon carried that strip as a bottom flare, the loft gave it depth, and the checker called
the head a bulky slab twice. A typed block from the outer stone columns has no such strip to
mis-read.  When the plate shows something a straight-on drawing could not (an underside, a
foreshortened ring), that is the camera, not shape; typed parts let you leave it out.
