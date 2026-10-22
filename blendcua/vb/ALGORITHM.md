# Version B, the algorithm as built

Simple description of what `vb/version_b.py` does when you run it on one task,
for example `python vb/version_b.py --task 18_thors_hammer --rounds 2`.
Written to check the build against the paper, not to replace it.

Before Version B starts, the task has already been built once by the old
loop: **Planner** wrote `plans/<task>/`, **Executor + Reviewer** built it into
`mem/<task>_run_001/` (action files, screenshots, reviews), and the finished
model with its 12 renders sits in `blends/<task>/`. Version B never redoes
that; it starts from it.

Vocabulary: **the store** = the files an agent may improve: `Skills/`,
`Tool_scripts/Tools_code/`, `Tool_scripts/Tools_ref/`, `prompt_files/`, and
`plans/<task>/`. The task text under `tasks/` is never edited.

---

## Algo

**1. Driver** (`vb/version_b.py`, plain code, no model)
Decides what the "subject" is: the model to be judged. First time it is
`blends/<task>/` (the original build). Records everything in
`vb/state/<task>/state.json`; appends events to `vb/harness_log.jsonl`.

**2. Checker, discovery mode** (`Checker/checker_agent.py`, an agent)
Looks at the subject's 12 renders and the reference images. It is NOT given the
plan or the action files, so it can only report what it sees, not what was
intended. It writes a list of defects, each with a stable id
(`part.kind.name`), a severity (major / minor), and evidence.
→ stores `Checker/reports/<subject>/defects.json`
If the list is empty the task is done: go to step 12.
If a report already exists for this subject, it is reused, not recomputed.

**3. Round starts.** Round number n = 1, 2, ... (default 2 rounds).
Before the round's edits, the driver copies the store to
`vb/state/<task>/round_NN/store_before/` so it can be put back.

**4. Curator** (`Curator/curator_agent.py`, an agent)
Reads the defect list from step 2, the plan, the action files, the reviewer
verdicts and the screenshots of the base run. Groups related defects, and for
each group says where the fault came from: **plan** (the plan never asked for
it), **exec** (the plan asked, the executor did it wrong), **review** (the
reviewer let it through), **views** (the plan was measured off a bad photo
angle), or **none**. Every claim must cite a file and line. Then it picks one
or two groups to act on (majors first), and for each names a "case" (1 to 12,
the paper's table) and the smallest rebuild that can test the fix: **R1**
(replay the corrected actions), **R2** (executor + reviewer again from the
plan), **R3** (planner again, then R2), or **none** (reviewer-only change).
In round 2 and later it also gets a note saying what round n-1 tried and how
it ended, so it does not repeat it.
→ stores `Curator/reports/<task>/round_NN/curation.json` (+ attribution.md, remedy.md)

**5. Remedy** (`Curator/apply_remedy.py`, an agent + code guards)
Makes the edits the curator decided, in two parts per group: a **local fix**
(edit the plan text, or the recorded action file for R1) and a **durable
record** (a new or extended skill, a new or extended tool, a reviewer check)
so the next task benefits too. Then code guards check the edits:
task never touched, `Checker/` never touched, reviewer skills and plan checks
add-only, other skills extended not gutted, tools additive, a new tool must
parse, be registered in the tool index, be cited by a skill, have a general
(motif) name and no object names baked into its strings.
→ stores `Curator/reports/<task>/round_NN/apply/applied.json`
**If a guard fails → put the store back from store_before, skip to step 11
(next round).**

**6. Rebuild** (`vb/rebuild.py`, code that launches the old agents)
The widest path any chosen group asked for is used:
- **R1**: replay the corrected action files into Blender in one dispatch. No
  agent. A hash of every object is compared with the base run: geometry outside
  the corrected region must be identical.
- **R2**: **Executor + Reviewer** (`blendcua_agent.py`) build the task again
  from the (now corrected) plan under the new skills and tools. Can start from
  a step, replaying the earlier steps from the base run first.
- **R3**: the old plan is archived to `plans/_archive/` and the folder cleared;
  **Planner** (`planner_agent.py`) writes a new plan from the task alone under
  the new skills; then R2.
Every path ends by saving the model and rendering its 12 views.
→ stores `mem/<task>_run_00k/` (new action files, screenshots, reviews,
`rebuild.json`) and `blends/<task>_run_00k/` (blend, views, geometry digest)
**If the rebuild fails → put the store back, skip to step 11.**

**7. Checker, verdict mode** (same agent as step 2, different prompt)
Gets the rebuilt model's renders AND the old defect list from step 2. For every
old defect id it must answer **RESOLVED / UNCHANGED / WORSE** with evidence, and
separately scan for new **major** defects that were not on the list. It still
does not see the plan. (This is the piece the earlier v2b attempt lacked: it
re-ran discovery, which always found "new" majors, so nothing was ever kept.)
→ stores `Checker/reports/<new_run>/verdict.json`

**8. Accept** (`vb/accept.py`, plain code)
For each group the round acted on, KEEP its edits only if:
- every defect id in the group came back RESOLVED, and
- the verdict found no new major defect (strict by default), and
- for R1, the geometry hash rule held.
If one group closed while another got WORSE, both are dropped: one rebuild
cannot tell which edit caused what. Reviewer-only remedies (path `none`) are
kept without a rebuild.
DROPPED edits are put back file by file from store_before (only the files that
round claimed, so another task's edits are untouched).
→ stores `Curator/reports/<task>/round_NN/acceptance.json` and, for each kept
group, `accepted/<group>.json` with the before/after of every file.

**9. If something was kept:** stop rounds here. The rebuilt model is now the
better one, and a later round would need a fresh discovery on it (step 2 with
the new run as subject), which is a new pass of the loop. Go to step 12.

**10. If nothing was kept:** the store is back to what it was before the round.

**11. Next round:** n = n + 1. If n is within the round budget, go back to
step 4 with the same defect list and a note describing round n-1's failure
("try something bigger, do not repeat"). Otherwise go to step 12.

**12. Snapshot** (`feedback_agent.py --snapshot`, code)
If anything was kept over all rounds, the store is snapshotted to
`snapshots/H_NN/` with a note listing the kept groups. The next task starts
from this H. If nothing was kept, no snapshot; the harness is unchanged.

---

## Starting a new pass from a rebuilt model

If you point the driver at a rebuilt run (`--run <task>_run_003`), step 1 makes
that run the subject, so step 2 runs discovery on the rebuilt renders and the
rounds work from that fresh list. This is what "hammer round 2" did.

## What each agent is allowed to see

| agent | sees | does not see |
|---|---|---|
| Checker (both modes) | renders, reference images, task text, scene geometry via scripts; in verdict mode also the old defect list | the plan, the action files, the curator's decisions |
| Curator | defects, plan, action files, reviews, screenshots | the checker's chain of thought; cannot edit anything |
| Remedy | the curation, the store | the task text (read-only), `Checker/` |
| Planner / Executor / Reviewer | the store as improved | the defect list (they must benefit through skills, tools and the plan only) |

## Where a round's decisions land

```
Checker/reports/<subject>/defects.json          step 2   discovery
Curator/reports/<task>/round_NN/curation.json   step 4   grouping, blame, choice
Curator/reports/<task>/round_NN/apply/          step 5   edits made, guard results
mem/<new_run>/, blends/<new_run>/               step 6   the rebuilt model
Checker/reports/<new_run>/verdict.json          step 7   per-id verdict
Curator/reports/<task>/round_NN/acceptance.json step 8   kept / dropped, reasons
vb/state/<task>/state.json                      all      where the driver is
vb/harness_log.jsonl                            all      one line per event
snapshots/H_NN/                                 step 12  the improved harness
```

## Options that change the flow

- `--rounds N`: round budget (default 2).
- `--rebuild R1|R2|R3`: override the curator's chosen path.
- `--from-step k`: R2 only, replay steps below k from the base run.
- `--stop-after check|curate|apply|rebuild|verdict`: stop early to inspect.
- `--resume`: continue a task whose state.json shows finished rounds.
- `--lenient-new-majors`: keep an edit even if a new major appeared.
- `vb/resume_round.py`: finish a round whose rebuild died mid-build (Blender
  closed), by replaying the finished steps into a new run and continuing from
  step 6.

---

# What actually happened on the two tasks

Same numbering as the algo above. "Kept?" is step 8's answer.

## Umbrella, round 1 (base: `11_umbrella_run_001`)

**Step 2, Checker found 7 defects.** Two majors: rib tips at different heights
(spread 1.41 units, the frame looked twisted) and a puckered, too-peaked canopy.
Five minors: whole frame one brass colour, navy too blue, no shaft ornament, no
finial ornament, a hidden reference Empty left in the scene.

**Step 4, Curator made 6 groups and chose the two majors.**

| group | blame (with citation) | case | rebuild |
|---|---|---|---|
| rib_tip_level | plan: step 2 never said "all tips at one height"; exec: the rib action added `pitch = -0.70*sin(angle)` to every tip | 3 | R3 |
| canopy_surface | exec: wrong cage recipe (0.78 inner lift, triangulated crown, low-res cloth solve) though the plan did ask for a shallow tent | 4 | R2 |

Not chosen: the four minors ("quota is two, majors first").

**Step 5, Remedy made these edits** (all guards passed):
- Plan step 2 rewritten with a named datum `RibTipLevelZ`, a 0.01 tolerance,
  and a numeric review check.
- Planner skill `wording-that-cannot-be-misread.md` extended: for a radial
  frame, state the 3-D level ring, not only the XY radius.
- Reviewer skill `writing-review-checklists.md` extended: measure tip-z spread.
- New executor skill `cloth-tent-profiles.md`: shallow quad radial tent, bounded
  ring slopes, inspect before Solidify.
- No tool. No action file edited (both paths regenerate the actions).

**Step 6, Rebuild R3** (widest of R3 and R2): the old plan was archived,
the planner wrote a new plan, then the executor built it. 176 min, about $2.
Note: the very first attempt let the planner see the remedy-edited plan and it
copied `RibTipLevelZ` verbatim; the plan folder is now cleared before R3.
Result: `mem/11_umbrella_run_002`, `blends/11_umbrella_run_002`.

**Step 7, Checker verdict** on run_002:

| defect | before, after | status |
|---|---|---|
| rib_tip_heights (major) | spread 1.41, now 0.09, one rib still short | UNCHANGED |
| cloth_surface (major) | silhouette IoU 0.81, now 0.70 | WORSE |
| navy_too_blue (minor) | colour spread 58, now 40, reference 33 | RESOLVED |
| the other 4 minors | same | UNCHANGED |
| new majors | none | |

**Step 8, Kept? No.** rib_tip_level not closed (UNCHANGED), canopy_surface
WORSE. All edits put back. Step 12: no snapshot.

**Did the remedy work?** Half. The rib fix did what it said (tips level to
0.09, 15x better) but the checker's rule is "gone", not "better". The canopy
fix backfired: the plan still carried 2-D silhouette targets measured off the
reference photo, which is shot from below; a level frame cannot match them, so
the reviewer failed step 3 twice and the executor ended with a steep cone. That
is a `views`-type fault the curator did not name. Round 2 was not run.

## Hammer, round 1 (base: `18_thors_hammer_run_001`)

**Step 2, Checker found 7 defects.** Majors: a hexagonal hole in the head
that is not in the reference, the head far too deep (depth/face-height 0.75,
reference about 0.30), crack/weathering contrast wrong (too dark, too blue),
periodic stripes on the side walls. Minors: pommel colour, pommel shape, leather
ridges too fine.

**Step 4, Curator ran twice.**
- First pass (kept as `round_01_attempt1_noviews`): 4 groups, blamed plan and
  exec only, chose head geometry (case 3, R3) and stone material (case 7, R2).
  It never considered that the plan's numbers came from one oblique photo.
- I made the `views` class concrete in the curator prompt (generic wording, no
  hint about this task) and re-ran. Second pass, used for the round:

| group | blame | case | rebuild |
|---|---|---|---|
| stonehead_blockout_geometry (hole + depth) | plan: step 3 asks for a "recessed chip", no depth target; **views**: depth was read off the oblique reference | 10 | R3 |
| stonehead_surface_material (contrast + stripes) | exec: dark multiply crack cores, front X/Z projection on side faces; review: passed on "maps are non-flat" | 7 | R2 |

Not chosen: pommel, leather ridge scale (minors).

**Step 5, Remedy made these edits** (guards passed on the second try):
- Synthesised front/side/top plates of the head with gpt-image-2, audited them
  against the source, and rewrote the plan: closed continuous head, no chip,
  depth/face-height about 0.30 with tolerance.
- Planner skill `numbers-that-hold-up.md` extended: an oblique photo is not a
  depth measurement; synthesise plates first.
- Reviewer skills `writing-review-checklists.md` and
  `verify-built-feature-values.md` extended: no-opening check, luminance
  median/p90 versus reference, side-wall band check.
- Executor skill `material-target-audits.md` extended.
- New tool `Tool_scripts/Tools_code/synth_views.py`, registered in the index.
  Its first version had "hammer", "stonehead", "pommel" written into its
  prompts; the object-word guard rejected it and the agent rewrote it generic.

**Step 6, Rebuild R3**: fresh plan from the task alone. The planner called
`synth_views.py` on its own, unprompted, which is the durable record working.
Blender closed during step 2 (cause unknown); the build was resumed from
step 1's recorded actions into `18_thors_hammer_run_003` with
`vb/resume_round.py`.

**Step 7, Checker verdict** on run_003:

| defect | before, after | status |
|---|---|---|
| unreferenced_socket_hole (major) | big hole gone; a small chip still reads as a cavity at a looser threshold | UNCHANGED |
| excessive_depth (major) | depth/face-height 0.75, now 0.52 (target 0.30) | UNCHANGED |
| crack_weathering_contrast (major) | median luminance 74, now 87, reference 107; still no bright veins | UNCHANGED |
| periodic_side_striping (major) | dark bands 11 to 2 on top, 7 to 4 on bottom | RESOLVED |
| leatherwrap ridge_scale (minor) | 35 to 24 peaks, about 10 broad turns | RESOLVED |
| pommel colour, pommel shape (minors) | same | UNCHANGED |
| new majors | none | |

**Step 8, Kept? No.** Each group had at least one id not RESOLVED. All edits
put back, including `synth_views.py`.

**Did the remedy work?** Mostly yes in substance, no by the rule. The hole
disappeared, the depth moved a third of the way to target, the stripes closed,
and even the un-chosen leather minor closed as a side effect. Nothing counted
because every group still had one UNCHANGED id.

## Hammer, round 2 (base: `18_thors_hammer_run_003`, the rebuilt model)

Started as a new pass: the driver was pointed at run_003, so step 2 ran fresh.

**Step 2, Checker found 4 defects** on run_003 (down from 7). Hole and drum
were not listed at all. Majors: crack network sparse and dark (three cracks on
the front face only); leather folds are horizontal rings, the reference has
diagonal folds. Minors: pommel end profile, wood grain too regular.
(Note the disagreement with step 7 above, which called hole and depth UNCHANGED
on the same renders. Verdict mode is anchored to the old ids and looks for any
remnant; discovery mode reports what stands out.)

**Step 4, Curator** chose both majors:

| group | blame | case | rebuild |
|---|---|---|---|
| stonehead_crack_coverage | plan: "a few cracks" is not a coverage target; exec: three ribbon meshes; **no tool exists** for a branched face-aware crack network | 5 | R2 |
| leatherwrap_spiral_direction | plan: says "circumferential", never "diagonal"; exec: constant-Z rows | 4 | R2 |

Proposed remedy: build `surface_crack_network.py` + executor skill + reviewer
coverage check; rewrite step 3 wording for helical paths + planner skill.

**Steps 5 to 8: not run.** Stopped after curation at the user's request.

**Repeat of step 4 in the new folder** (`smoke_copy`, the smoke test after the
move): same defects, same prompt, same two groups chosen, same R2, but the
stone group was attributed case 1 (wrong count in the plan, edit the plan) rather
than case 5 (missing tool, build one). Same diagnosis, different prescription.

## Scorecard

| task / round | chosen groups | rebuild | model better? | kept by rule? | cost |
|---|---|---|---|---|---|
| umbrella r1 | rib level (plan), canopy (exec) | R3 | frame yes, canopy no | no | about $2.5 |
| hammer r1 | head geometry (views), stone material (exec) | R3 | yes on all four majors, two closed | no | about $2.5 |
| hammer r2 | crack network (tool), leather direction (plan) | R2 proposed | not built | not run | about $0.3 so far |

Total kept across both tasks: nothing. Total snapshots: none.

## Things this shows about the checker and curator

1. **Accept is binary, the improvements were not.** Three majors improved a lot
   and one closed as a side effect, and none of it was credited. Options:
   let discovery state a numeric tolerance per defect so verdict can close on
   it; or add PARTIAL and keep an edit when a group is PARTIAL or better with
   no WORSE.
2. **Verdict mode and discovery mode disagree.** Anchored on the old id, the
   checker kept the hole "UNCHANGED" for a small chip; asked fresh, it did not
   list it. One of the two is wrong, and which one decides whether an edit is
   kept.
3. **The curator's case choice is not stable** (case 5 vs case 1 on identical
   input). The case decides whether a tool gets built, so this matters.
4. **The curator only blames what it can cite.** It missed the umbrella's
   `views` fault because nothing in the plan says "measured off a photo from
   below"; the fault is in the numbers, not the words.
5. **A remedy that changes geometry needs the plan's measurements re-derived.**
   The umbrella's new plan kept 2-D silhouette targets from the old photo; the
   fix and the old numbers fought and the old numbers won at review.

## Addendum (2026-09-11): per-worker harness branches and the lessons stage

With `run_v2.py --parallel N` each worker runs in its own view (harness/wK, a git branch of the
store) synced to main at task start; accepted remedies and lessons are merged into main at accept
(see README, "Two workers, two harnesses"). Reviews are one round (review once, one unreviewed
fix, move on). When discovery finds no major defect the lessons agent runs instead of a blame round.

## Addendum (2026-09-11, later): rebuild from the blamed step, prior-attempt note, dead-build resume

- `stage 11` (rebuild) for R2 now takes `from_step` = the remedy's `from_step`, else the
  step named by the chosen groups' attribution evidence / `local_fix.target`, clamped by
  the lowest plan step the remedy rewrote (`rebuild.derive_from_step`). Steps below it are
  copied from the base run and replayed (`common.copy_run(upto_step)` + `batch_replay`),
  the executor runs `--only-steps from_step..`. Recorded in the round state.
- Every R2/R3 writes `mem/<new_run>/prior_attempt.md` (`rebuild.prior_attempt_note`), read
  by `blendcua_core.build_subagent_prompt` for each step of that run: the old run's paths,
  the replayed steps, permission to reuse code that still fits, and what must be new
  (local_fix, faulted file, checker summaries, the remedy's `prior_reuse`).
- If the previous process died inside a round's rebuild, `rebuild.dead_rebuild_run` finds
  the run (newer than the round, no `rebuild.json`, a checkpoint below an unbuilt step) and
  `resume_rebuild` continues it in place from the checkpoint, then bundles and records it.
  `run_v2.py` does the same for a first build (`resume_step` → `rebuild.py --resume-build`).
- Curator schema: `from_step` (int, validated) and `prior_reuse` (text) per remedy; missing
  ones are warnings, not failures.
