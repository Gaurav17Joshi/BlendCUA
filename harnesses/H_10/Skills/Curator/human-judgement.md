---
name: human-judgement
description: What a person says is wrong with a finished build, why, and what to fix; eight rules from six judged builds, with the worked examples in good_context/. Read before attributing or proposing.
---

# Judging like a person

Six finished builds (dog, gate, sneaker, shark, two hammers) were judged by a person and by
the checker and blame agents. The person's notes are in `good_context/` (one file each, plus
`general_rules.txt`). The agents found what they could measure and missed what the person saw
first: how the thing was built. The rules below are the person's, in their words.

GENERAL RULES  (what the six judgements have in common)
==========================================

1. Model the object, not the picture.
   Laces built toward the camera (sneaker), a tongue on the visible side of the head (dog), jaws
   hung outside the snout (shark), a flat head with a twisted gold strip to fake a band going
   around (hammer): each came from making the render look like the photo instead of making the
   thing. It buys a small gain in one view and a huge error in every other. Match the picture
   only when the task explicitly asks for it.

2. One main mesh for a low-poly object, with roots reserved for what branches off it.
   The majority of the piece is one mesh structure; supporting things are added on top. Head,
   neck and body as three lofts join badly (dog) even when each loft follows the photo well.
   But one mesh does not mean one row-table loft: a limb leaves the body from a station
   interval reserved for it and is extruded from there in its own direction (a dog's neck and
   legs, a human's arms). Add-ons are for real attachments only (ears, a wing plate, fins,
   eyes), and a foot is the end of the leg, not a box under it. No single method fits every
   subject: judge whether the construction chosen fits this one.

3. Cavities are cuts, not parts.
   A mouth is a recess in the head with teeth inside it (shark, dog), not gum blocks and lip
   tubes. This needs a cut tool: draw the cut in the side view, the mesh is opened there, later
   calls can expand it.

4. When the photo is tilted, make it straight first, then actually use it.
   Make upright front/side/top plates with gpt-image-2 (hammer run_001 never did). Then split
   the measuring: SHAPE from the straight plate, PROPORTION from the photo. Making the plate and
   not using it is the same as not making it (hammer run_003 built a rectangle next to its own
   front plate).

5. Curves come from the image, not from a few points.
   A handful of landmarks gives an approximation of a scroll (gate). Crop the region, extract
   the curve, build it, overlay the built curve on the reference and compare.

6. Effort goes where it shows.
   The basic structure (dog body, shoe body, hammer head) is where the half done work sits;
   the paint, swoosh, wrap and rivets got the effort and look good. The first structural step
   deserves the most points, the most matching, and the strictest review.

7. Judge by how it was built, not only by what measures wrong.
   Depth ratios and pixel counts catch some faults. "This part is a separate block", "this part
   is crude", "this is attached in the wrong place" are what a person sees first (hammer handle
   on the face of the head, dog feet, gate tubes) and the checker mostly misses them.

8. Tools asked for by these six: a cut tool, a curve-mapping and overlay tool, upright plates
   actually used for tracing. Skill wording alone would not have fixed any of the six.

9. Before you name any other cause, check whether the reference was measured at all.
   (Added 2026-09-12 from the skull and tablecloth rounds.) Most wrong shapes in this harness
   have one of two roots, and the remedy is different for each:
   - **Not enough scripting and measuring of the reference.** Open the construction step's
     `scripts/` folder. Empty, or a bounding box and a colour median, means the shape was
     typed from memory: a 12-point ring through nine typed widths (skull), a "convenient scale
     rather than the pixels" (tablecloth rebuild), a station table retyped from the plan
     (sneaker). The remedy is not a better adjective ("broad, flattened, carved-looking") and
     not a tighter number; it is the read itself: mask, row table, landmarks, the outline
     traced into a polygon and drawn back on the photo, the build made from that file, the
     residual as the gate (`Scripting/measure-before-you-build`, `Planner/trace-the-reference`,
     tool `outline_trace`). Say which script is missing and what it must print.
   - **The view cannot give the shape.** The photo is oblique, the part is foreshortened or
     hidden, or its cross-section is not in any view. Then no amount of measuring the one
     picture helps and the remedy is a better view: an upright front/side/top plate made with
     gpt-image-2 and verified against the photo (`Planner/Gpt_images/prompting-reference-plates`),
     then measured with `plate_loft` (`Planner/plan-from-plates`). This is the `views` class,
     and it must come with the instruction to *measure* the plate, or it becomes the hammer's
     plate made and not used.
   Decide which of the two it is from the evidence (was the shape readable in the photo, and
   did anyone read it?) and write the remedy as that procedure. The tablecloth legs were
   readable in the photo and nobody read them; the skull's cross-section was not, and needed
   the plates. A remedy that says neither is a rewrite of the same failure.


11. A three-quarter width is not a depth; one-view relief is not relief; a lit patch is not a tone.
   (Added 2026-09-13 from the hammer rounds.) Three findings the curator should phrase as
   method faults, with the remedy named: (a) a "too bulky in the three-quarter view" reading
   (head-zone width 0.61 vs 0.46 L) depends on depth AND camera together - a thin block seen
   from the front and a deep one seen from its end give the same number - so the remedy is the
   joint scan in `Executor/settle-by-experiment`, not "reduce the depth"; (b) sculpted ridges
   that the checker cannot count on the far side were native screen-space strokes from one
   view - remedy `Executor/relief-along-world-paths`; (c) a material whose "lit" median
   matches the photo but reads pale is flat where the photo has a spread (median 113 with
   quartiles 73 / 186) - judge the luminance distribution (median with quartiles, same mask
   on both pictures), name the lights as much as the material, and do not call the base
   colour wrong.

## How to use the examples

- Read two of the files in `good_context/` before attributing. Match the *kind* of fault, not
  the object: a mouth built as parts is the shark's fault whatever the animal; a straight
  plate made and not used is the hammer's fault whatever the object.
- When judging one of these six subjects, do not read its own file.
- When proposing a remedy, prefer what the person asked for: a tool where the operation is
  missing (a cut tool, a curve-mapping and overlay tool), a plan rule where the approach was
  wrong (model the object, not the picture; shape from the plate, proportion from the photo),
  a reviewer check that would have caught it. Skill wording alone did not fix any of the six.
