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
- `writing-a-build-plan.md` — no method fits all situations; altitude, what belongs in a plan, where plans come from
- `low-poly-one-mesh.md` — read this before planning any low-poly subject: no one method fits all; decide per part whether to trace, in which direction, and whether the trace gives the shape or only helps; one mesh with roots reserved for limbs; the Duck is the worked example
- `trace-or-type.md` — read this when a plan is about to say "trace the plate" or "build it as primitives" for a part: trace when the silhouette is the shape (free curves), type measured primitives when the outline is straight runs, chamfers and circles; either way measure the plate and rasterise the built mesh back into its pixel grid for a residual
- `trace-the-reference.md` — read this before planning a flat PART whose silhouette is readable in the photograph (a leg, a bracket, a handle) and there is no blueprint: the plan reads the outline out of the photo with a script and hands the executor the polygon
- `blueprints-from-plates.md` — read this when a task should be built from straight views and only a photo exists: make the plates (gpt-image-2 on pure white, `make_task_plates.py`), verify identity, turn each plate into a blueprint drawing with the `blueprint` tool (fill, contour, inner and colour-marking strokes, measured landmarks, contour JSON beside it), and hand plate + blueprint to the build
- `plan-from-plates.md` — read this when the task has (or the plan makes) front and side blueprints of a ONE-AXIS mass (skull, vase, head): the plan measures the plates and hands the executor a station procedure and the plate_loft tool; steps follow the parts, not a template
- `structural-ownership-before-presentation.md` — read this when a final presentation step might become a late geometry-repair step
- `numbers-that-hold-up.md` — read this when a camera setting or preview target is described as optional even though the review measures the final render
- `review-checklist-format.md` — the shape a step's Review block must take; prose parses to zero checks
- `wording-that-cannot-be-misread.md` — the ambiguities that have actually failed runs
- `seed-plans.md` — two real seed plans, with what each got right and wrong
- `Gpt_images/prompting-reference-plates.md` — how to prompt gpt-image-2 for front/side/top plates, what goes wrong, and the rule that a plate you make is a plate you measure from; the notes of the plate trials (`image_test_README.md`, `image_test_REVIEW.md`, `hammer_prompt_examples.txt`) sit beside it
- `Objects/` — construction skills scoped to a *class of subject* rather than to plan-writing in general
  - `Objects/flat-objects.md` — read this before planning any thin subject (leaves, petals, feathers, paper, flags): the silhouette goes in an alpha image, a rough deformable cage underneath carries the form
  - `Objects/low-poly-animal.md` — read this before planning or building any standing low-poly animal from side/front/top plates: one ring loft along the spine from a measured station file (side = stations, top = widths, front = the width ceiling per height, body-only reads under legs and mouth), legs grown from reserved root faces, mouth as a cut, tail/ears/eyes/tongue the only add-ons, checked from three-quarters

Skills in a subfolder of a role are loaded like the rest (since 2026-09-11 the planner loader,
`skill_help.py` and the curator index walk subfolders); only files with a frontmatter `name:` count
as skills, so notes and images beside a skill are never injected into a prompt.

**Scripting**
- `measure-before-you-build.md` — what "scripting" means here (a saved `.py` in the step's `scripts/` that reads the reference or the scene and prints numbers / draws an overlay) and why a construction step with an empty `scripts/` folder has built its shape from memory: read first, build from the file, check with the same kind of script
- `where-code-runs.md` — Blender-side vs shell-side, and the four-minute freeze that comes from confusing them
- `reading-an-image.md` — crop, threshold, and what to do when segmentation gives three answers
- `scripts-that-persist.md` — save it, name it after the question, print a verdict
- `blender-state-gotchas.md` — three 5.x server facts that fail silently: `finish` replaces same-named objects, `matrix_world` is stale until `view_layer.update()`, no MATERIAL viewport shading while the engine is Workbench

**Executor**
- `build-from-traced-outline.md` — read this when a step hands you an outline polygon traced from the photograph (or you are about to shape a curved part by feel): extrude the polygon with `outline_trace.extrude_profile`, scale once, bury the root, place by measured angles; check by aligning the render's outline on landmarks over the photo with a per-row residual; move the material onto the photo's medians with the same mask in both pictures
- `cut-openings-from-traced-lines.md` — read this when a step needs an opening the photo shows as edges (a mouth, slot, seam, socket) or you are about to build one as parts stuck on the outside: decide with a script whether the mesh has the mass under the lines (`line_cut.stations` / `silhouette_gap`), preview the traced lines on the body through the photo's frame (`frame_camera`), straighten them, cut once with `slab` + `boolean`, paint the cut faces by plane, audit closed, then plant what goes inside on the mesh's own lips
- `blueprint-traced-loft.md` — read this before building a ONE-AXIS low-poly mass from front and side blueprints (skull, vase, head); not for figures, branched or sideways bodies: the plate_loft tool slices top to bottom, one ring per row
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
- `relief-along-world-paths.md` — read this when relief must read from every side (grooves round a grip, a helix, a ring of dents): a world-space path through `stroke_displace` with a constant texture cuts it all round in metres; native strokes are one-view; record each depth pass and judge on a render
