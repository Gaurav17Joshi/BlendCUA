# Skills

Role-scoped guidance distilled from real runs in this harness. Each file is a
skill: a short document one agent loads when it is doing that job. They are not
tool documentation — `Tool_scripts/Tooling.md` is the tool reference and
`Tool_scripts/Tools_code/TOOL_AUTHORING.md` is how to add one. These are about
*how to work*, and every one of them exists because something went wrong once.

| folder | who reads it |
|---|---|
| `Planner/` | writes the build plan before execution starts |
| `Executor/` | builds the thing, action by action, and checks its own work |
| `Reviewer/` | inspects a finished step against its checklist |
| `Feedback/` | the correction loop — acting on it, and folding it back into the plan |
| `Scripting/` | anyone writing throwaway Python to look, measure or compare — all three roles do |
| `Curator/` | the blame + remedy agent after the build: how a person judges a finished model, with worked examples in `good_context/` |

## The loop these fit into

1. An expert writes a **short** seed plan — the skeleton, not the document.
2. The agent runs it and produces a full trajectory.
3. A human (or the reviewer) corrects the trajectory wherever it went wrong.
4. Repeat 2–3 until the trajectory comes out clean.
5. **Compress the corrected trajectory back into the plan.**

`Planner/` covers 1 and 5, `Executor/` covers 2, `Reviewer/` covers 3, and
`Feedback/` is the hinge between 3 and 5.

`Scripting/` cuts across all of them: every role ends up writing small Python to
answer a question a glance cannot, and the same mistakes recur wherever it is written.

## Index

**Planner**
- `writing-a-build-plan.md` — altitude, what belongs in a plan, where plans come from
- `low-poly-one-mesh.md` — read this before planning any low-poly subject: the main mass is one extruded mesh traced over a blueprint (not a silhouette), limbs branch out of it when they flow out of it, and features are cut in rather than stuck on
- `structural-ownership-before-presentation.md` — read this when a final presentation step might become a late geometry-repair step
- `numbers-that-hold-up.md` — read this when a camera setting or preview target is described as optional even though the review measures the final render
- `review-checklist-format.md` — the shape a step's Review block must take; prose parses to zero checks
- `wording-that-cannot-be-misread.md` — the ambiguities that have actually failed runs
- `seed-plans.md` — two real seed plans, with what each got right and wrong
- `Gpt_images/prompting-reference-plates.md` — how to prompt gpt-image-2 for front/side/top plates, what goes wrong, and the rule that a plate you make is a plate you measure from; the notes of the plate trials (`image_test_README.md`, `image_test_REVIEW.md`, `hammer_prompt_examples.txt`) sit beside it

Skills in a subfolder of a role are loaded like the rest (since 2026-09-11 the planner loader,
`skill_help.py` and the curator index walk subfolders); only files with a frontmatter `name:` count
as skills, so notes and images beside a skill are never injected into a prompt.

**Scripting**
- `where-code-runs.md` — Blender-side vs shell-side, and the four-minute freeze that comes from confusing them
- `reading-an-image.md` — crop, threshold, and what to do when segmentation gives three answers
- `scripts-that-persist.md` — save it, name it after the question, print a verdict

**Executor**
- `verifying-your-own-work.md` — the eight ways to answer a question with a computation instead of a glance
- `measure-or-eyeball.md` — when to measure, when to look, and the order to do them in
- `coordinate-frames-and-units.md` — the conversions that silently produce plausible wrong answers
- `converted-mesh-frames.md` — read this when converted text/curves or physical-front axes cross coordinate frames
- `layered-relief-budgets.md` — read this before stacking measured grooves/chips with surface weathering
- `reference-envelope-fitting.md` — read this when a source or viewport fit must survive the actual final camera render, or when endpoint landmarks and the full silhouette span disagree
- `repeated-feature-envelopes.md` — read this before building repeated arrays or when radial pins/raw bounds disagree with the reference envelope
- `rendered-relief-proof.md` — read this after fine relief when numerical displacement must also be visible in the final render
- `projected-overlap-is-not-clearance.md` — read this when camera overlap is required without physical intersection
- `material-target-audits.md` — read this before tuning rendered material roles against reference colours
- `checking-invisible-data.md` — how to see UVs, weights and anything else a render does not show
- `verify-live-scene.md` — read this when a saved render exists but Blender's current scene may have been replaced
- `clear-glass-presentation.md` — read this before tuning transparent material against a neutral product reference
- `world-background-nodes.md` — read this before trusting a world-colour helper on a custom node tree
- `reference-mask-audits.md` — read this when traced branches match a bbox but their occupied shape may still differ
- `cloth-collision-direction.md` — read this before a sheet simulation falls onto a closed collision support
- `sequential-cache-evaluation.md` — read this before judging a cached simulation at a late frame or deciding whether a native particle API is functional
- `fenestrated-blade-construction.md` — read this when a procedural leaf is reading as repeated strips, fans, or angular lobes
- `isolate-then-attach.md` — build a part away from the model, attach it last
- `label-tools-and-stale-labels.md` — using `edge_map`-style label tools without getting burned
- `ik-landmark-calibration.md` — read this before searching a rigid IK chain against measured joint landmarks

**Reviewer**
- `writing-review-checklists.md` — turning "does it look right" into something answerable
- `how-to-review.md` — the reviewer is an agent with tools, not a grading call

**Feedback**
- `acting-on-corrections.md` — How to read a correction for its real scope before rebuilding
- `writing-a-retrospective.md` — How to turn a bad round into a plan edit — the step that closes the loop between a correction and the next run
