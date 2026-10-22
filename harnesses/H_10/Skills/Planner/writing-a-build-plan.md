---
name: writing-a-build-plan
description: How to write a build plan for this harness — where plans come from, how detailed they should be, and what belongs in one.
---

# Writing a build plan

**No method is fully good for all situations.** Tracing, station lofts, plates,
blockouts, extrusion chains, measured blocks: each fits some subjects and fails others,
silently. The best a plan can do is think about *this* subject part by part, measure and
script what that decision needs, use the tools, and work. A plan that applies the last
run's recipe to a new subject has not planned. `low-poly-one-mesh.md` section 2 lists the
decisions for a traced subject; a hammer head or a slab needs none of them, just its
blocks measured.

A frontier model has no trajectories for this environment. It does not know what
the task looks like from the inside: what order the parts get built in, where the
traps are, what "finished" means for a piece. It will not work that out mid-task —
it improvises, at length and with confidence, often in the wrong direction. **The
trajectory has to come from us, handed over before execution starts.**

## Where a plan comes from

Not from asking a model to plan its own work with no grounding — that produces
something that reads plausibly and is useless. It comes from a loop:

1. An expert writes a **short** seed plan (see `seed-plans.md`).
2. The agent runs it and produces a full trajectory.
3. A human corrects the trajectory wherever it went wrong.
4. Repeat 2–3 until the trajectory comes out clean.
5. **Compress the corrected trajectory back into the plan.**

Step 5 is the one that gets skipped, and it is where the value is. Every number
the run converged on, every wrong turn it recovered from, and every "this looked
like X and was actually Y" belongs in the plan so the next run starts past it.

To write a plan for a *new* subject, give the model 10–20 worked plans in the same
environment plus the tool documentation. The worked plans are what fix the shape
and altitude a plan is supposed to have.

## Altitude — the thing most plans get wrong

- **Over-specified disables the agent.** If every action is scripted in advance
  the agent stops reasoning about the task and starts trying to satisfy the
  specification. The moment reality diverges even slightly it has nothing to fall
  back on, because the plan has trained it out of thinking during that step. It
  follows you into the error.
- **Under-specified leaves you where you started.** "Build a bat" is not a plan.

What works: **state what should be done and why it matters, and leave how open.**
Each step names its objective, indicates which tools suit it, and stops short of
parameters. A step that reads "sweep the branches with `tube`, few sides, taper
front-loaded — a stem loses most of its thickness in its lower third" is the right
altitude. The same step with `sides=6, radii=[0.0042, 0.0031, ...]` is not.

## Scripting — every construction step says what it reads by script

"Scripting" in this harness is a small Python program the executor writes into its step's
`scripts/` folder and runs, that reads the reference picture or the scene and prints
numbers or draws an overlay (a mask and its row table, an outline traced into a polygon,
a thickness, colour medians, the built outline back on the reference with a residual).
It is the only way a shape gets read out of the reference instead of remembered.

The plan carries this in three places, or the executor skips it — the skull, sneaker and
tablecloth-rebuild runs all have empty `scripts/` folders in their construction steps and
a shape that is not the reference's:

- **A `## Scripting` section in the preamble** (every step's subagent sees the preamble):
  what scripting is, that it happens before the first build action, that the build reads
  the saved file, and that an empty `scripts/` fails review.
  `Tool_scripts/add_scripting_section.py` inserts the standard text.
- **In each construction step**: what to measure by script *before* building, with the
  tool functions named (`outline_trace.boundary_polygon` on the wood mask cut at the neck,
  saved as `scripts/legs.json`, drawn back on the photo), and what the end-of-step check
  script reports (outline residual per row, mean and worst). "Trace the contour" is not an
  instruction.
- **In the plan folder's `scripts/`**: the planner's own reads (masks, polygons, station
  JSON) so the executor's first script is a lookup. A plan whose measurements stop at a
  bounding box has not read the reference either.

See `Scripting/measure-before-you-build.md` (the rule), `trace-the-reference.md` (a shape
from one photograph) and `plan-from-plates.md` (from blueprints).

## What belongs in a plan

- **What each construction step reads by script before it builds**, see above.
- **The objective of each step**, and the reason it matters. The reason is what
  the agent falls back on when your instruction stops fitting.
- **Facts that follow from measurement but that the agent should not have to
  derive.** Not just "here are the landmarks" but "the torso is 3.77× longer than
  it is wide" and "the humerus is 14% of the span from arm root to wingtip".
  These are cheap for you and expensive for the agent.
- **Which tool suits the step**, without its parameters.
- **A review checklist per step** — see `Reviewer/writing-review-checklists.md`
  for what to check, and **`review-checklist-format.md` for the shape it must take**.
  The format is not cosmetic: prose is parsed as zero checks.
- **Visual context**, and this matters more than expected: an annotated reference
  with every landmark drawn and named, plus the same thing as JSON so it can be
  read rather than re-measured off pixels.
- **The traps, written forwards.** The highest-value-per-line part of a plan is the
  section listing what goes wrong on this build — but write it as a property of the
  task, not as a report on a previous run. **"A base flare that is too gradual merges
  footing, step and flare into one taper"**, not *"this run's flare was too gradual"*.
  A plan is read by someone building the thing for the first time; a retrospective
  voice tells them about a history they were not part of, and invites them to copy
  the retrospective framing into plans of their own. Never write "lessons from the
  first attempt", "the previous build", or "we found that".
- **The numbers, with what they should measure** — see `numbers-that-hold-up.md`.
  A setting without a target is not checkable.

## What a plan should decide up front

One decision shapes everything downstream and belongs in the first section: **what
the reference actually is.** The five plans in `plans/` each answer it differently
and the method follows from the answer:

| the reference is | so the method is |
|---|---|
| a flat photograph, shot down one axis | trace it — pin a view, work in normalised screen coordinates |
| a perspective render | measure it in fractions of its own size, convert once, build in world space |
| a picture of somebody else's finished object | invent it, judge by eye, no correspondence to recover |
| a painting of the finished thing | model the blockout, paint everything else into one texture |

Getting this wrong is not a detail — it selects the tools, the verification method
and the shape of every step.

## The limit of planning up front

All of this bets that the shape of the task is knowable before it starts. For a
bat it is: body → limbs → membrane → texture, and no photograph reorders that. For
tasks with extreme variability, where you cannot tell how things will look five
steps in, **a plan up front is worse than none** — the agent keeps following it
well past the point where it stopped describing the situation, and a confidently
executed wrong plan is much harder to recover from than ordinary confusion. Those
need something adaptive (replanning between steps, plans that branch); do not
pretend a linear plan covers them.
