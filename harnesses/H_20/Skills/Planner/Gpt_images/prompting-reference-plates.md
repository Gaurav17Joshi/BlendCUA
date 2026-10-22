---
name: prompting-reference-plates
description: How to prompt gpt-image-2 for front/side/top plates of a reference, what goes wrong, and the rule that a plate you make is a plate you measure from — the failure is almost always something the prompt asserted, not something the model could not do.
---

# Prompting reference plates

Re-projecting a reference photo into front / side / top plates. Evidence is the
66-plate `gpt-image-2` run in `BlendCuaLoop1/Image_test/baseline/`, the 75-plate re-runs on
`gpt-image-2.5-flare` and `-sunburst`, and the 9-plate prompt trial in
`BlendCuaLoop1/Image_test/hammer_trial/`.

> **The model is not failing to understand you. It is doing what you said.**
> Before blaming the model, check every factual claim your prompt makes about
> the object against the reference image. The worst failures are the ones the
> model executed perfectly.

## 1. The false assertion — the expensive one

`18_thors_hammer/00_upright_front` asked for the hammer stood upright, and
included this clause:

> …the head level at the top with its long side facing the camera, **and the two
> gold bands horizontal**.

The bands are not horizontal. They wrap the head near each striking face, so in
a true front view they read as two **vertical** bands. The prompt asserted a
falsehood and the model obeyed it — it turned the head 90° on the handle to
comply. The plate is a faithful rendering of a wrong instruction.

Delete that one clause and say nothing else about the head, and the plate comes
back correct on `gpt-image-2` and `-flare`. That is the whole bug.

This class is expensive because it does not look like a prompt bug. The output
is confident, well-lit and internally consistent; only a measurement or a
careful look at the reference catches it.

**Rule: state only what you have verified in the reference.** If you have not
checked which way a feature runs, do not mention which way it runs.

## 2. Silence is not neutral — the model has a prior

Removing the false clause was not sufficient everywhere. Three prompts were
crossed with three models (9 plates, $0.22):

| prompt | what it says about the head | image-2 | flare | sunburst |
|---|---|:--:|:--:|:--:|
| A | nothing | ✅ | ✅ | ❌ |
| B | names where the striking faces end up | ✅ | ✅ | ✅ |
| C | anchors to the reference's rigid geometry | ✅ | ✅ | ✅ |

Where the prompt said nothing, `-sunburst` still produced horizontal bands —
the popular Mjolnir has a band round the head that way, and with no instruction
the prior wins. An unstated fact is not a fact the model leaves alone; it is a
fact the model fills in from training data.

**Rule: for any feature whose orientation matters, say it positively. One
clause is enough.** B is the shortest thing that worked on all three models.

## 3. A material inventory is not a geometry

Compare two subject constants in `generate_views_gpt_image.py`:

```python
S_STONE  = "...carved with the numerals 1934, with three graduated incised
            vertical grooves at each of the four corners and a stepped
            moulding along the bottom edge."          # spatial relations
S_HAMMER = "...a blocky cracked grey stone head, a dark metal collar, a wooden
            handle with a red leather wrap and a dark metal pommel."
```

`S_HAMMER` is a parts-and-materials list with no spatial relations at all. It
tells the model what the hammer is *made of*, never how the pieces *attach*. A
material list survives a re-projection happily — the colours and textures come
back correct — while the structure is free to drift, which is exactly what
happened. `S_STONE`, which does carry relations (corners, bottom edge), held up
better.

**Rule: the subject line must say how the parts are arranged, not just what
they are.** "The head is a block whose long axis runs perpendicular to the
handle" is the sentence that was missing.

## 4. Chained prep plates propagate the error

The plan builds views off an earlier output:

```python
job("01_side", ..., src="00_upright_front")
job("02_top",  ..., src="00_upright_front")
```

`00_upright_front` was wrong, so both downstream plates were re-projections of
a hammer with its head already on backwards. There is no gate between the
stages: nothing checks the prep plate before two more calls are spent on it.

**Rule: verify a prep plate before anything is derived from it.** Chaining is
worth it — it is what keeps the views mutually consistent — but only with a
check at the join.

## 5. The prohibition wall does not carry weight

`common()` appends the same block to 63 of the 76 prompts: *no text, no labels,
no watermark, no measurement marks, no extra props, no second copy of the
object, no cropping.* Seven prohibitions, most irrelevant to any given plate.
Meanwhile the one constraint that actually mattered for the hammer — where the
bands run — was absent. Generic prohibitions are cheap to write and buy little;
a specific positive statement about *this* object is what moves the output.

The remaining 13 prompts are hand-written and skip `common()` entirely, which
is its own hazard: `00_upright_front` is one of them, and the bespoke prompts
are where the unverified claims live. A prompt written by hand for one plate
gets less scrutiny than a helper reused sixty times.

## On negation

The prompts file for the trial assumed negation should be avoided, since image
models often reproduce what you forbid. The evidence here does not support a
blanket ban:

- REVIEW.md Lesson A found that naming what must **not** be in frame is exactly
  what fixed `04_datestone_1934/02_top`, `06_iron_gate/02_top`,
  `11_umbrella/02_side` and `12_tablecloth_drape/02_side`.
- `HAMMER_GEOM` contains "the gold bands are NOT horizontal" *alongside* the
  positive fact, and every variant using it passed.
- Prompt B passed on all three models using no negation at all.

So: **negation is safe when it follows the positive statement, and untested on
its own.** Say what is true, then optionally rule out the specific thing you
have seen go wrong. Never rule something out instead of saying what is true.

The isolated negation cell (prompt B plus a bare "the bands must NOT run
horizontally") was never needed — A, B and C did not all fail — so that
question is still open. `hammer_prompt_trial.py --prompts D` runs it.

## Checklist before spending a run

1. Every factual claim in the prompt checked against the reference image.
2. Any feature whose orientation matters stated positively, once.
3. Subject line carries spatial relations, not just materials.
4. Prep plates verified before derived plates are generated.
5. Constraints specific to this object, not a wall of generic prohibitions.

`score_hammer.py` automates item 1 for this failure class: it PCAs the red wrap
for the handle axis and the two gold bands for the band axis, and flags any
plate where the angle between them moves more than 10° from the reference. It
only means anything on a front-on plate — on an oblique view a band shows two
facets at different angles and the number is ambiguous.


## Use the plate you made

A plate is not a decoration for the plan. The only reason to spend a run on a straight front,
side or top view is that shape is easier to measure on it than on a tilted photo. So:

1. **Shape from the plate, proportion from the photo.** Trace outlines, stepped widths,
   chamfers, band positions and the like on the straight plate. Take overall proportions
   (head to handle, body to fin) from the reference photo, which is the only ground truth for
   scale. Say in the plan which source each number came from.
2. **Every important plate is cited by at least one plan number and one review check.** A
   plan that synthesises a front plate and then measures everything on the reference has not
   used it, and the build comes out as if the plate did not exist (this happened: the head was
   a rectangle next to its own front plate).
3. **Verify before you measure.** Check the plate against the reference for identity (same
   part count, same attachments, same orientation of any feature that matters) before any
   number is read from it; a chained plate inherits the first plate's error.
4. **Tell the executor to use it too.** Put the plate's path in the step that builds the part
   it shows, and ask the reviewer to overlay the built silhouette on it.

## 7. Repeated rows need a telling axis plate before spacing

For an oblique repeated row, request a straight top and/or side plate before deriving
any 3-D centre spacing or edge gap. The plate request must describe only structure
verified in the source, state the row direction positively, and expose the repeated
edge gap rather than decorating the plan with another perspective crop.

Verify the plate against the source before measuring it: check count, order,
proportions, attachments, and the orientation/state of the repeated parts. Record
which numbers came from the verified plate and which remain measurements of the
original photograph. A plate that is only saved in the plan folder but never used
for the shape or spacing decision counts as no plate. Put its path and measured
ratio in both the planning decision and the relevant review check.

Evidence: `plans/13_domino_cascade/scripts/planner_summary.md` (13_domino_cascade,
where the planner recorded that perspective prevented recovery of world spacing).

## Files beside this skill

`image_test_README.md` and `image_test_REVIEW.md` are the notes of the three-model plate trial this skill is drawn from; `hammer_prompt_examples.txt` holds the prompts of the hammer trial. The plates themselves (about 180 MB) stay in `BlendCuaLoop_try/Image_test/`. The generator is `Tool_scripts/generate_views_gpt_image.py`.

## 8. The shape-authority gate is more than identity

After identity and part-count checks, compare every synthesized plate against the source with a normalized PCA and a named-part overlay. Normalize translation, scale and in-plane rotation before comparing the global major/minor axes, and overlay the named head, shell, tail and each appendage so a plausible bbox cannot hide a wrong planform.

Reject or regenerate a plate whose global axis ratio is wrong; identity and bbox agreement alone are not shape verification. Do not write station, root, texture, or camera data from a candidate that fails this gate. Keep the rejected candidate as audit evidence, but make the verified plate and its comparison manifest the only shape authority.

Before writing station data, record which proportions come from the verified plate and which remain measurements of the reference photograph. The plan and review should cite the verified plate by path and repeat the normalized PCA target, while the named-part overlay remains available for the executor and reviewer.

Evidence: `blends/15_sea_turtle_run_001/task/reference/top_blueprint.json` and the Step-1 PASS at `mem/15_sea_turtle_run_001/steps/step_001/review/round_02/review.txt`.

## 9. Shallow pitched roofs need a telling depth plate

For a shallow pitched roof seen obliquely, require a verified TOP plus SIDE/RIGHT plate
before choosing rear-slope row count or depth. Measure ridge-to-eave depth, occupied rows,
deck exposure, row offsets, and the lower-edge profile from the plates; never turn a hidden
depth convention or “a few back tiles” into a fixed two-row recipe. Verify the prep plate
against the original before deriving any other plate, and put the verified plate path and
the measured table in both the plan number and the review check. Shape comes from the
straight plate; projected overall width, colour, and the final camera remain anchored to
the original photograph.

Evidence: `plans/20_low_poly_well/scripts/planner_summary.md` records that the roof
backside was inferred from an oblique image, while
`plans/20_low_poly_well/scripts/roof_plates/roof_plate_verification.json` and
`roof_slope_occupancy.json` are the corrected plate-and-measurement bundle.

