---
name: how-to-review
description: How to run a review in this harness — the reviewer is an agent with tools, not a grading call on two fixed renders.
---

# How to review

**The reviewer is an agent, not a single grading call.** It gets the plan, the
step's checklist and real tool access, and it writes its own inspection scripts,
rotates and zooms the viewport, crops in on parts and takes fresh screenshots
before giving a verdict.

Grading two fixed renders it had no hand in framing is a much weaker review,
because a large part of reviewing is **deciding what to look at**. The executor
chose those framings, and it chose them while believing its own work was fine.

## What to do before answering anything

1. **Read the checklist first, then look.** Looking first and reading after
   produces a review of whatever happened to catch your eye.
2. **Reframe.** Every render you were handed is a compromise framing. For each
   checklist line, put the thing it names in the middle of the frame at a size you
   can actually judge. `sn.frame_ortho(region, rv3d, direction, centre, half)` and
   a crop-and-upscale in PIL are both one line.
3. **Look from the angle the build could not.** The reference's own view is the
   one view every executor optimises for, so it is the least informative. A plant
   traced from the front is a pressed flower from above; a wing lying flat on a
   flank is invisible dead side-on; four faces weathered differently look
   identical from any single 3/4.
4. **Compute anything computable.** See `Executor/verifying-your-own-work.md` —
   the same catalogue applies to reviewing, and a reviewer that measures beats one
   that squints. "The plant is 364 mm wide against the reference's 376" is a
   review; "the plant looks about right" is not.
5. **Check what the executor asserted.** Action files and `shot()` notes state
   numbers. Verify one or two of them independently rather than accepting the
   report — a stale object with a `.001` suffix can make every reported number
   describe geometry nobody is looking at.
6. **Open the executor's `scripts/` folder before the render.** A construction step
   with an empty `scripts/` built its shape from memory: no mask, no outline, no
   stations read from the reference, so the render can only be plausible, never
   right. That is "Try again" on its own — ask for the read saved as JSON, the trace
   drawn back on the reference, and the built outline's residual. If there are
   scripts, re-run one; the numbers it prints must be the numbers the build used.
   The skull, sneaker and tablecloth-rebuild construction steps all passed review
   with empty folders (see `Scripting/measure-before-you-build.md`).

## The verdict

Answer **every** checklist line explicitly, each with the evidence you gathered —
the number, the crop, the view you took it from. A line you did not check is a
line you report as unchecked, not one you quietly pass.

Then separate what you found:

- **fails** — the step does not meet its criterion, with what you measured;
- **notes** — true but not disqualifying.

Do not add work. If the geometry meets the checklist and you can see something
else you would have done differently, that is a note, not a fail. A reviewer that
extends scope turns every step into two.

## Being wrong in the useful direction

Two common reviewer failures, both worth guarding against by habit:

- **Passing on a plausible render.** "It looks fine" about a thing the checklist
  asked you to measure is the failure mode this whole system exists to prevent. If
  the criterion has a number, produce the number.
- **Failing on a theory you have not checked.** A confident wrong diagnosis costs
  the executor a rebuild. Before reporting a cause, check it — a state dump or a
  bmesh read usually settles it in one script.

## After the verdict

The executor is sent back to fix **only what you named**. That makes the precision
of your wording part of the fix: "the collar is white on the jaw as well as the
neck, at 6 faces above y=0.42" produces a targeted fix; "the head colours are off"
produces another guess.
