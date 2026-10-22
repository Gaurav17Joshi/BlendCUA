---
name: writing-a-retrospective
description: How to turn a bad round into a plan edit — the step that closes the loop between a correction and the next run.
---

# Writing a retrospective

A correction fixes one run. A retrospective fixes every run after it. This is
step 5 of the loop — **compress the corrected trajectory back into the plan** —
and it is the step that gets skipped.

## When to write one

After any correction that took more than one round, or that was structural rather
than numeric. Not after "make it 20% wider".

## What it has to contain

1. **What happened** — the state that was wrong, concretely. "The first leg
   attached at the body's middle and pointed sideways, mostly along the wing
   direction."
2. **Why** — the actual mechanism, not "I made a mistake". The useful version
   names the reasoning step that failed: *a definition the plan had already given
   was re-derived from the photo instead of carried forward.*
3. **Whose it was.** Be honest and specific, because the fix differs:
   - **agent error** → the lesson goes in a skill or the plan's lessons section;
   - **ambiguous instruction** → the plan's *wording* changes (see
     `Planner/wording-that-cannot-be-misread.md`);
   - **tooling gap** → a tool gets built or fixed, and the note says which.
   The bat legs produced one of each across three rounds.
4. **What would have caught it earlier** — stated as something checkable. "State
   the expected proportion before tracing" is usable; "be more careful" is not.

## Write the mechanism, not the apology

The two retrospectives this project kept are useful because they are diagnostic:

> "The error wasn't perception, it was scope: I never asked 'how far should this
> chain go' against the text, only 'does this line match a visible vein'."

That sentence became a plan line ("the humerus is a small fraction of the span")
and a skill line ("suspect the most prominent feature"). Compare with "I should
have read the plan more carefully", which becomes nothing.

## Then actually move it

A retrospective that stays a document has done half the job. Each finding lands
in exactly one of:

- **the plan's Lessons section** — if it is specific to this subject ("a fruit
  hanging below the rim must clear the pot *sideways*; the constraint is radius,
  not height");
- **a skill in `Skills/`** — if it generalises ("brush size is in screen pixels
  and does not scale with the object");
- **the plan's step wording** — if the plan caused it;
- **a tool change** — if the tool caused it, with the fix written down even when
  it is not applied yet (see `Executor/label-tools-and-stale-labels.md`, which is
  exactly that: a known gap, its symptom, and the fix, recorded before anyone had
  time to make it).

Then delete the retrospective, or keep it as history — but it is no longer where
the knowledge lives.

## Keep the wrong turns in the plan

Plans in this project carry a "Lessons from the first attempt" section, and it is
the highest-value-per-line part of the document — ten bullets that each save a
round. Two rules for it:

- **State the symptom, then the cause.** "Vertical bands on a lathe are a *shading*
  problem — more sides only makes them narrower" is worth more than "use
  smooth_by_angle", because the next person meets the symptom first.
- **Keep it short enough to be read.** When it grows past about a third of the
  plan, compress: merge bullets that share a cause, and cut anything the step
  wording now prevents on its own.
