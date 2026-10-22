---
name: numbers-that-hold-up
description: Putting numbers in a plan — stating targets rather than settings, checking them against the reference, and why a precise plan can stop an agent from looking.
evidence: 11_umbrella_run_001 step_004; 16_hourglass_run_001 step_003
---

# Numbers that hold up

A plan's numbers are the most valuable thing in it and the easiest thing to get
wrong, because a wrong number does not look wrong. It looks like all the others.
Three ways they fail, each observed:

## 1. A setting is not a target

`strength=0.85` tells the agent what to type. It does not tell it what should come
out the other end, so when the result is wrong the agent has nothing to compare
against and moves on.

A pillar plan said, correctly, *"a native brush is not predictable, so every call
returns what it measured — write those to a report and read them."* The agent did
exactly that: it recorded `max_in: -0.003` and continued. Three millimetres, on a
four-metre pillar, where the intended cut was fifteen to twenty-one. Nothing was
skipped. There was simply no number to fail against.

**State both.** The setting so the agent has a starting point, and the measurement
so it knows whether it landed:

> Use the inverted `CREASE` brush at **strength 0.85**. Each crease must report
> **15–21 mm** of cut; if it comes back at a few millimetres the strength is too
> low or the brush is too few pixels, and the fix is to raise one and re-frame for
> the other — not to accept the number and move on.

Adding the target changed the same build from 3 mm to 13–21 mm. Nothing else
changed.

The same rule applies to an API named in a plan: "the operator exists" is a
setting, not a result. State the functional acceptance target—such as evaluated
records, non-empty bounds, or changed instances at sampled frames—and say when
the deterministic fallback takes over. A capability probe that passes while its
cache evaluates empty must not block the fallback.

## 2. Every number must be checked against the reference, not against the plan

This is the subtle one, and it defeats an otherwise good checklist. Sometimes the reference is not reliable tho, so keep that in mind.

A chilli-plant plan gave a pot as `R 0.130, H 0.123, belly at 64% of its height,
rim wall 0.235 R`. The build matched all of it. The review passed all of it. The
pot was visibly wrong — a shallow dish where the reference has a deep bowl —
because `H` had been measured wrongly when the plan was written. It should have
been **0.157**.

Look at why nothing caught it. Every check in that step was **self-referential**:

| the check | what it compares against |
|---|---|
| widest point above mid-height | a fraction of the pot's own height |
| rim wall `0.235 R` | a fraction of its own radius |
| overhangs the plinth, centred | another object in the same scene |
| flared foot with a waist | its own shape |

Not one compared the pot to the photograph. A wrong number propagates through the
build *and* the review without ever touching the thing it was measured from.

**This is the bounding-box failure again, in a new place.** See
`wording-that-cannot-be-misread.md`: *between a visual signal and a textual signal,
the agent follows the textual one.* There, a box drawn on a photo was read as a
specification and produced a skull at twice its width. Here, `H 0.123` was read as
a specification and produced a dish. The reference was in the folder both times,
open and correct, and both times the sentence won.

That rule is the whole reason a reference-anchored check is necessary. You cannot
rely on the agent noticing that the image disagrees with your number — it will not,
because your number is text. The only thing that reliably beats a wrong sentence is
**another sentence telling it to go and measure the image**.

**Every step needs at least one check anchored outside the plan.** Write it first
in the list and say why it is there:

> **Measure the pot against the REFERENCE, not against this plan.** Every other
> check here is self-referential, so a wrong number in the table above passes all
> of them cleanly. Threshold the pot out of the photograph, convert with the named
> scale functions, and state both against the built pot's. **The width-to-height
> ratio is the one that matters: about 1.66 : 1.**

With that check present, the next run measured the reference independently, got
430 × 260 px → 0.260 × 0.157 m, and confirmed the corrected number.

**Prefer ratios to absolutes.** Two dimensions can each look plausible and still
encode the wrong shape. `0.260` and `0.123` are both believable pot numbers;
`2.11 : 1` is obviously a dish. State the ratio and the reader can see the error.

### When the reference itself is not reliable

"Anchor to the reference" is not "trust the reference". Photographs and renders lie
in specific, recognisable ways, and the plan should say which apply here:

- **Clipped at the frame edge.** The chilli reference cuts its topmost leaf off, so
  the plant's true height is unknown and its bounding box is a lower bound. The plan
  says so and names the pot as the anchor instead: *"the reference clips its topmost
  leaf at the frame edge, so its plant box is truncated and its true top unknown.
  Anchor on the pot, which is not."*
- **Cropped by the viewport, not by the file.** A reference plate measured on screen
  gave an aspect of 1.71 against the file's own 1.33 — because at that zoom the frame
  was cutting it. Measure the file, or project the plate's own corners; never measure
  a reference off a screenshot of it.
- **Occluded by the thing in front.** Half the duck's neck is hidden against the
  breast, so the visible outline is not the neck's edge. Tracing what you can see
  puts every ring in the wrong place.
- **A render of somebody else's model**, not a photograph of the subject. Then it
  fixes style and poly budget and says nothing reliable about real-world scale.

So: name the anchor you trust and why, name the parts of the reference that cannot
be measured, and prefer a feature that is fully in frame, fully lit and unoccluded
over the one you actually care about. A check anchored to a clipped edge is worse
than no check, because it fails a correct build.

## 3. Your number can contradict your own criterion

A gravestone plan specified cracks as `width 0.004, strength 0.7, colour 0.16,
multiply`, and its checklist required *"thin grey hairlines"*. The agent used those
values exactly and the reviewer failed it for painting near-black grooves. Both
were reading the plan correctly; the plan disagreed with itself.

The same shape of error put `386 verts / 768 tris` in one line of a pillar plan and
*"the low poly is not a decimation but the cage the sculpt was built from"* —
a 64-vertex cage — in another. Four sentences said one thing, two said the other,
and it cost a review round to discover.

**Before shipping a plan, read every number against the criterion that judges it.**
If the criterion is a word ("hairline", "subtle", "heavy"), ask what value produces
that word and whether yours does. A number that was carried over from somewhere
else, or that nobody ever rendered, is the one to distrust.

## 4. Precision can stop the agent from looking

The uncomfortable one. Giving the agent good numbers makes a step *feel* settled,
and a settled step invites it to stop verifying.

A pillar step 2 that had been given every radius, strength and depth previewed its
first corner and then cut eleven more times blind — where the same step, on a plan
that specified nothing, previewed before every pass. The general advice file even
contained a clause excusing "scripted steps" from previews, harmless until a plan
supplied the constants that made the clause fire.

**The more precisely you specify a step, the more explicitly you must say to check
it.** A number is a starting point in world units; the tool acts in screen pixels,
on this mesh, at this framing. Say so where the numbers are:

> These are brush sizes, not results. Preview every pass, not just the first — the
> numbers are in millimetres and the brush is in screen pixels, and the preview is
> where you find out the two agree.

## The test before you ship

For each number in the plan, answer:

1. **Is there a target beside it?** If it only says what to set, add what it should
   measure.
2. **Did you check it against the reference, or against the rest of the plan?**
3. **Does any criterion in the same document describe a result this number cannot
   produce?**
4. **If it is a dimension, is the ratio stated?**
5. **Does the step say to verify, even though you gave the number?**
6. **Is a final-render target being described as optional camera advice?** If the
   reviewer names a rendered ratio or envelope, make it an output target and
   require a cheap same-aspect preview; a starting lens need not match the photo,
   but the measured render still has to meet the stated composition.

## 5. A projected repeated-row gap is not world spacing

Treat a perspective projected gap as an image target, not as a world spacing. For
an oblique repeated row, require both the projected gap ratio and the derived
world edge clearance: record `r_gap = g_projected / W_projected`, the scale-based
`g_world`, and the centre-spacing equation (for a domino row, `S = T + g_world`).
A guessed `S` is not validated merely because rigid bodies make contact; contact is
a physics result, not evidence that the photograph was converted correctly.

Put the reference-anchored spacing check before the bake. If `S` changes, explicitly
recheck every dependent contact and timing event, the visible chain envelope, and
the camera fit before accepting the rebake. Keep the reference measurement and the
build setting in separate fields so a precise old setting cannot masquerade as a
measured target.

Evidence: `mem/13_domino_cascade_run_001/steps/step_001/review/round_01/review.txt`,
where the old `0.34` target was measured and passed without a tight reference-gap
check.
