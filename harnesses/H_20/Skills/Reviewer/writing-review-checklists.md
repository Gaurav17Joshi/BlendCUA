---
name: writing-review-checklists
description: How to turn "does it look right" into criteria a VLM can answer the same way twice.
---

# Writing review checklists

Every step of a plan carries a checklist, and a separate reviewer agent runs
against it. **The checklist matters as much as the step description**, and it
fails in one characteristic way: vagueness.

## The rule

"Ensure the object placement is correct" is not a criterion. Correct how? The
reviewer supplies its own definition and it will not be yours.

"Ensure the cup sits on the table near the edge, without overhanging it" is a
criterion: one thing to look at, one answer to give.

This matters because **reviews are fickle**. Asked whether something looks like a
bat, a model will answer, but not stably — the same geometry passes on one run and
fails on the next for no discernible reason. Asked something concrete, it becomes
repeatable.

## Find a concrete proxy for the vague thing you care about

The question you actually care about is "does this look like the animal". The
checkable form used on the bat was: **the model's outline must not cross out into
the background sky.** That is a much narrower question, and it still caught nearly
every real failure, because on that task almost everything that goes wrong shows
up as geometry poking into sky or falling short of the animal.

Good proxies from the five plans in `plans/`:

| the vague thing | the proxy |
|---|---|
| "does the plant look full" | from TOP ortho, branches reach into all four quadrants with no bald sector, and no two are within 15° of each other |
| "is the damage convincing" | every pass reports the millimetres it moved and the vertices it touched; a pass that reports nothing has failed |
| "is the light like the reference" | the hard boundary crosses the plinth at 0.41 and the pot at 0.46 of frame — measured in both pictures by half-way crossing |
| "did the bake work" | the normal map's spread is above zero (a bake that did nothing is uniform blue, mean 0.667, spread 0) |
| "is the wing separate from the body" | the body's outline runs unbroken above the wing |

## Both failure directions

Get this wrong and the reviewer does not give a weaker review — **it reviews a
different object**:

- it **misses errors a human would spot instantly**, because nothing told it to
  look there;
- it **fixates on things that do not matter**, spending the whole review on a
  topology detail while the head sits two inches away at twice its correct width.

The second one is not only a wording problem — it is also a **weighting** problem,
and a flat list of checks has no weighting in it. Group them: the handful that
decide the step under `**Important**`, the bookkeeping under `**Other**`, and the
reviewer is told to crop and measure for the first and confirm-and-move-on for the
second. See `Planner/review-checklist-format.md`, which also covers the parser
requirement — **a Review written as prose is extracted as zero checks**, and the
reviewer then grades on a general impression while appearing to work normally.

## Check the construction, in a view the build did not use

A step can meet every residual and still be the wrong construction: a T-posed figure
lofted from horizontal rows met its front outline at 12 px and was a poncho with cone
arms from three-quarters. The reference's own view is the one view every executor
optimises for, so at least one Important check per construction step is a relation
measured in another view (a three-quarter crop, the side): a neck narrower than head and
chest, a limb that is a separate volume from the body at its root, a depth-to-width
ratio. Relations like these are stable for a reviewer the way "looks like a human" is
not.

## A gate tests the defect it names

The loop's chocolate cup (task 16, run_001) passed 5/5 of its own reviews while its
marshmallows were 34-73% inside the cream and its candy cane rested on nothing. Two
reasons, both in the checklist, not the build:

- **The audits compared the model with the run's own renders**, through the run's own
  camera, never with the reference. A check that reads the build back through the
  projection that built it is circular. At least one Important check per placement step
  compares against the reference, or measures a relation on the model in its own frame.
- **The gates checked a weaker property than their names.** "Committed to the cream" was
  `min z > 0`, i.e. above the floor, which anything in a mug passes; "seated" compared
  projected boxes. "Sits on X" means contact with X and bounded overlap with X: underside
  gap ≤ a tolerance and % of vertices inside X (point-in-solid) ≤ a cap. Leaning objects
  need both contacts measured. See `Executor/seating-by-contact.md` for the table.

When a gate fails, **first check that it measures what it names**. Two cup gates failed
on correct geometry: "eye deepest point ≥ −0.04" measured the hidden back half of the
eye dome inside a 0.15 wall, and "gap under the lowest vertices" ignored that a body on a
slope touches at its uphill side. Fix such a gate on the record: write the old
definition, its failing number and the reason into the action header, then the new one.
Never quietly loosen a threshold.

Evidence: `mem/16_chocolate_cup_decor_run_001` step_004 and `mem/16_chocolate_cup_decor_run_002/steps/step_004/03_audit_props.py`;
`blends/16_chocolate_cup_decor_run_002/LESSONS.md` A5, B5.

## Practical rules

- **One thing per line.** A line containing "and" that could fail two ways will be
  answered for whichever half the reviewer looked at.
- **Ask for the number back.** "Say what the widths and heights actually came out
  as" turns a yes/no into evidence, and makes a wrong pass visible afterwards.
- **Name the view.** "Every vertical edge is chamfered — check zoomed from TOP
  ortho, where one missing chamfer is easy to miss at full frame."
- **Include the negative checks.** "No fruit buried inside the pot", "no stroke
  bled onto a face pointing away from the view it was picked in", "nothing loaded
  into the scene as a reference Empty." Absences are invisible unless asked for.
- **Split important from cosmetic.** Two headings — the things that fail the step,
  and the things worth noting. Otherwise a vertex-count nit reads as equal in
  weight to a wrong silhouette.

## Where reviews go

After every substantial sequence of steps, as often as you can afford. The cost of
a review is one agent's time; the cost of skipping one is every step built on top
of the unreviewed result. **A seed cylinder 20% too wide in step 1 makes the whole
animal 20% too wide**, and no amount of later tapering recovers it — so the check
belongs right after that step, not at the end of the build.

## Important check for traced linework

When a feature is branched or open, make one Important check per feature ROI rather
than accepting its outer envelope. Report the reference/model dark-mask IoU and XOR
fraction with the image size, crop, and threshold stated. Add a few discriminating
row and column runs at internal junctions; fail a missing or merged branch even when
the bbox, endpoints, and motif count agree. Keep upper, lower-left, and lower-right
ROIs separate so a large easy region cannot hide a wrong small branch.

Evidence: `mem/02_iron_gate_run_001/steps/step_002/review/round_01/review.txt`.
