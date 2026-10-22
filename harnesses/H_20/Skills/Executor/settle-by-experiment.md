---
name: settle-by-experiment
description: Read this when a look depends on a mechanism the reference cannot show you (refraction, translucency, glow, a procedural texture, a simulation setting) or a recipe gives you node topology whose numbers you cannot trust in your units, and two guesses in a row have missed. Build a small experiment harness before the third guess; name one hypothesis per variant; let the reference's own measurements pick; model the mechanism once renders show its structure; stop on numbers, not on looks.
evidence: mem/13_black_hole_run_003 steps/step_003 (30 variants in scripts/core_experiments.json, lens_model.py) and step_005 (six star revisions, each with its reason, in world_params_stars.json); mem/11_pumpkin_decor_run_003 step_003 (the flame's facing ramp, three variants); counter-examples mem/13_black_hole_run_002 steps/step_004 and step_005 (twelve and eight REDO passes, one number per full render, no table) (2026-09-13)
---

# Settle it by experiment, not by the next guess

Some things the reference cannot tell you: how a refraction bends what is behind it, how a
translucent wax lights up, how a bloom spreads, what a 4D noise looks like when its coordinates
are warped, which stiffness makes a sheet fold like the photo. A transcript or another run may
hand you the node topology, but its numbers live in units you do not have yet (object
coordinates depend on the object's scale, a Voronoi distance is in cell units, a bloom size is
relative to the frame, a "blend" is really an exponent). One informed guess is fine. Two misses
in a row means the thing is not going to be reasoned into place, and the third guess costs the
same as building the instrument that would settle it.

## The rule

**After two misses, stop tweaking and build a harness.** Then let measurements choose.

## What the harness is

Three small files in the step's `scripts/`, written once and reused every round:

1. **A parameter file** (`*_params.json`) holding every number under test, with a `revision`
   note per change saying what the last render showed and what is changed because of it.
2. **One Blender-side script** that rebuilds only the thing under test from that file (the
   material, the camera, the world) and renders at half size to a named PNG. Seconds per
   variant, not minutes. A shell driver that loops over variants makes the matrix one command.
3. **The reference's own measurement, run on the render.** Whatever step 1 read off the
   reference (a circle fitted to an edge, extents at a luma threshold, a band's angle and
   thickness per column, colour medians in role boxes, a star count) is the same script pointed
   at the render, reporting the same numbers next to the targets. One row per variant in a table
   (`*_experiments.json`); keep every image.

## How to run it

- **One hypothesis per variant, three at a time, named for the hypothesis.** "bare trick,
  blend 0.5 / 0.9 / 0.3" or "ramp on the IOR vs on the colour" tells the next reader what
  question each render answered. Twelve sequential passes on one gain with no table is the
  counter-example (run_002's REDO chains): nothing learned survives the next pass.
- **Numbers pick, images explain.** The table says which variant lands nearest the targets; the
  renders say why the others did not (a lens-shaped blob where a circle was wanted, a notch
  where a ramp went black, a haze over the whole frame). Read both every round. When the
  numbers disagree with what you see, fix the measurement first (a seed line drawn for the
  reference will not fit a render whose band sags less; a search window that finds the black
  space beside the object instead of its centre).
- **Once renders show the structure, model it.** If the mechanism is geometry or physics, write
  the smallest script that predicts the measured quantity (a ray through one refraction to a
  plane; a projected ellipse; a lit-cell fraction), validate it against two renders, then scan
  it. Renders find the structure; the model finds the numbers, in milliseconds instead of
  minutes, and its scan goes in the step as evidence.
- **Trust the recipe's topology; recompute its numbers.** Keep the node graph the transcript
  describes. Derive each number from your own frame and measurements, find the unit it lives in,
  and confirm it with one measured render. A cutoff of 0.0001 in the wrong unit renders nothing;
  a sub-pixel star needs a high value to survive the pixel average; a glow size that suited a
  candle hazes a frame-filling disc.
- **Stop on numbers, not on looks.** The step is done when the reference's targets are inside
  the tolerances you wrote down, with the residuals recorded; "looks fine" is where the loop's
  runs stopped, and their checker said otherwise.

## What goes in the run

The chosen variant becomes the step's action, and its header cites the table and the model
that chose it. The harness scripts, the parameter file with its revisions, the table and the
half-size renders stay in the step's `scripts/` as the record; a reviewer or curator reads the
table before the render. A step whose history is a chain of one-number REDOs and no table has
not settled anything, whatever its last render looks like.
