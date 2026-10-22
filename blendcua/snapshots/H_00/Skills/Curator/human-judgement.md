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

2. One main mesh for a low-poly object.
   The majority of the piece is one mesh structure; supporting things are added on top. Head,
   neck and body as three lofts join badly (dog) even when each loft follows the photo well.
   Add-ons are for real attachments only (legs, ears, tail, fins), and a foot is the end of the
   leg, not a box under it.

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


## How to use the examples

- Read two of the files in `good_context/` before attributing. Match the *kind* of fault, not
  the object: a mouth built as parts is the shark's fault whatever the animal; a straight
  plate made and not used is the hammer's fault whatever the object.
- When judging one of these six subjects, do not read its own file.
- When proposing a remedy, prefer what the person asked for: a tool where the operation is
  missing (a cut tool, a curve-mapping and overlay tool), a plan rule where the approach was
  wrong (model the object, not the picture; shape from the plate, proportion from the photo),
  a reviewer check that would have caught it. Skill wording alone did not fix any of the six.
