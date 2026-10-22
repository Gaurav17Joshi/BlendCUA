---
name: measure-before-you-build
description: What "scripting" means in this harness and why every construction step must do it — a small Python program, saved in the step's scripts/ folder, that reads the reference image or the Blender scene and prints numbers or draws an overlay, BEFORE the shape is built and again after. A construction step with an empty scripts/ folder built its shape from imagination.
evidence: mem/04_skull_run_001 and run_002 step 1-4 scripts/ empty (head a rounded box); mem/07_sneaker_run_001 step 1 empty (typed station table); mem/06_tablecloth_drape_run_002 step 1 empty ("the scale is deliberately convenient rather than copied from pixels"); against mem/06_tablecloth_drape_run_003 where ~200 lines of image reading put the legs within 8-11 px of the photo, and the earlier BlendCuaLoop_try runs of the same tasks (same machine, same executor model, earlier harness) with 10-70 scripts per step
---

# Measure before you build

## What scripting is

A script here is a `.py` file you write and save in **this step's `scripts/` folder**
(`mem/<run>/steps/step_NNN/scripts/`, it already exists), then run, that answers a
question with a number or a picture. Two kinds:

- **Shell-side** (run with `bash python scripts/<name>.py`; PIL, numpy, no Blender): read
  the reference photograph or a render. Mask a material by colour, print the row table of
  runs, find the axis, the floor row, the neck, trace a part's outline into a polygon,
  measure a thickness, medians of a patch, an overlay of your outline on the photo.
  `Tool_scripts/Tools_code/outline_trace.py` has all of these as functions.
- **Blender-side** (an action file, or `write_and_run`): read the scene. Vertex bounds per
  height band, radius per row of a lathe, a silhouette against the reference
  (`perceive.reference_outline`, `silhouette_vs_reference`), a count, a gap.

It is **not** the action that builds the thing, and it is not a paragraph of reasoning
about what the picture probably shows. It prints `L = 271 px`, `pitch 13.5 deg`, `neck at
y 683 half-width 25`, and saves `trace_overlay.png` so the number can be checked by eye.
Every number that goes into a construction should be traceable to a line one of these
scripts printed.

## Why it is not optional

The runs that failed all have the same folder: `steps/step_001/scripts/` empty.
- Skull run_001 and run_002: no script in steps 1-4; the head mass was a 12-point ring
  swept through nine typed widths, 33-50 px off the plate.
- Sneaker run_001 step 1: the plan asked for "a reference-derived station table from the
  measured near-side contour"; the executor typed the table from the plan's fractions.
- Tablecloth rebuild run_002 step 1: "the scale is deliberately convenient rather than copied from
  pixels" in the action header; legs invented, judged worse than before.
- Tablecloth by hand: mask, row table, landmarks, outline polygon — 200 lines — legs within
  8-11 px of the photo.

The earlier BlendCuaLoop_try builds of the same tasks, same executor model, wrote 10-70
scripts per step: the difference is what the plans and prompts asked for, not the model.
A step that builds a shape with no script has not looked at the reference; it has
remembered what such a thing usually looks like.

## A read is a choice, not a row table

Before the first script, the plan (or the step) has said which parts are read, in which
direction, and whether the read gives the shape or only landmarks
(`Planner/low-poly-one-mesh` section 2). A row table of the whole mask is the right read
for a glass and the wrong one for a T-posed figure or a sideways dog; a centreline with
radii read by eye at each station, previewed, then measured against the photograph
afterwards (the Duck) is a valid read and often the better one. A measured block
(width, height, depth) is a valid read of a hammer head. What is not valid is no read:
a shape typed from memory.

## The order inside a construction step

1. **Read first.** Before the first build action: the mask and row table of the part you
   are about to build, its landmarks (axis, floor, joints, extents), its outline or
   station reads, saved as JSON in `scripts/` and drawn back on the reference as a PNG.
   Look at that PNG. If the red line is not on the part, fix the read, not the model.
2. **Build from the file.** The action reads `scripts/<part>.json`; it does not retype the
   numbers. Its header cites the script that produced them.
3. **Check with the same kind of script.** Render, mask, align on landmarks, residual per
   row; or a Blender-side outline on the reference. Quote mean and worst.
4. **Handover lists the scripts** and what each printed, so the reviewer and the next step
   can re-run them instead of trusting a sentence.

## For planners

Every step that builds a shape says **what to measure by script before building**, names
the tool functions, and puts the polygon / station file in the plan folder's `scripts/`
(`plans/<task>/scripts/`) when the planner can measure it itself. "Trace the contour" is
not an instruction; "`outline_trace.boundary_polygon` on the wood mask cut at the neck,
saved as `scripts/legs.json`, drawn back on the photo" is. See
`Planner/trace-the-reference` for the shape-from-photo case and `Planner/plan-from-plates`
for blueprints.

## For reviewers

A construction step whose `scripts/` folder is empty is "Try again" regardless of what
the render looks like: the shape may be plausible and it is still not the reference's.
Ask for the read, the overlay and the residual. The opposite failure is also a fail: a
step on its fourth residual redo of one part is using the wrong read for that part, and
the review should say so instead of asking for a fifth.
