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
