# BlendCuavb_run

**The full loop, ready to run over the task set**: Planner -> Executor + Reviewer -> bundle ->
Checker -> Curator (blame + remedy) -> rebuild -> Checker verdict -> accept -> snapshot.
`python run_v2.py --parallel 2` runs it over every task in `tasks/train`; `--status` shows the ledger
`tasks/PROGRESS.csv`; to continue after a stop, run the same command again (every stage checks the disk
first, nothing is redone). Runs made elsewhere are imported with `vb/import_run.py --as <new_run> --plan`
so plan and build count as done. Split out of `BlendCuav2b_try/` on 2026-09-10 with the code, skills,
tools and prompts and all 20 tasks under `tasks/train/`, but no runs: every task is built fresh here.

What changed against BlendCuav2b_try (see `md_files/agent_improvements.md`): the checker looks before
it measures and runs width/colour/attachment checks on every subject; the curator attributes by a
fixed questionnaire and reads `Skills/Curator/human-judgement.md` plus the human examples in
`Skills/Curator/good_context/`; the planner has `Skills/Planner/Gpt_images/prompting-reference-plates.md`
(make plates, then use them); the reviewer has `Skills/Reviewer/construction-not-only-numbers.md`.

Blender: `python Tool_scripts/win_start_blender.py` starts the GUI Blender with the server and fits the
viewport to 800x600 (`--restart` after a crash, `--status` to check, `--port 6667` for a second one);
`run_v2.py` does this itself when nothing listens on a worker's port. `run_v2.py --parallel 2` builds two
tasks side by side on ports 6666 and 6667 (each with its own `.hermes_home_<port>` and handshake file) and
runs the Version B stage one task at a time, since it edits the shared Skills/Tools/prompts. Algorithm: `vb/ALGORITHM.md`. Version B driver: `vb/version_b.py`.

The rest of this file is the original harness README.

---


# BlendCuaLoop

The self-improvement loop: a planner writes a build plan, the executor and
reviewer build it, and a curator improves the harness before the next task.

One task is one pass:

```
tasks/<Task>/  ──planner──▶  plans/<Task>/  ──build──▶  mem/<run>/  ──curator──▶  Tools_code/ + Skills/
 photo +                      plan +                     actions,                  ▲
 sentence                     landmarks +                screenshots,              │
                              scripts/                   review rounds       snapshots/H_NN/
```

The base model never changes. The harness — the tools and the skills — is the
only thing that does, which is what makes a 20-task curriculum a measurement
rather than twenty separate builds.

---

## Before you run anything

**1. Start the Blender side.** Open Blender → Scripting → run
`Tool_scripts/blender_server.py`. It listens on `localhost:6666`. Check it:

```powershell
python -c "import socket; socket.create_connection(('localhost',6666),timeout=2)"
```

**2. Use the `blendcua` conda env.** Base Python has neither `hermes-agent` nor
`openai`.

```powershell
conda activate blendcua
```

**3. Keys look after themselves.** `blendcua_core.load_api_keys()` reads
`C:\Users\render\blendcua.env.txt` — outside the repo, and it refuses to load a
key file from inside it. Nothing to export. Override the location with
`BLENDCUA_KEY_FILE` if you move it.

---

## Running it

### The whole curriculum

```powershell
```

Plans, builds, curates and snapshots each of the 20 training tasks in order.
Resume in the middle, or do one task:

```powershell
```

### The three stages on their own

```powershell
python planner_agent.py  --task 09_oak_barrel        # writes plans/09_oak_barrel/
python blendcua_agent.py --task 09_oak_barrel        # builds it
python feedback_agent.py --run  09_oak_barrel_run_001  # curates the harness
```

Useful flags: `planner_agent --force` replans over an existing plan;
`feedback_agent --dry-run` prints the digest and changes nothing;

### Evaluation

```powershell
```

Same loop with curation and snapshots switched off. A test task measures the
harness; it does not get to change it.

---

## What each piece does

### `planner_agent.py` — task → plan

Reads `tasks/<split>/<Task>/` (one reference image, one `task.md`) and writes
`plans/<Task>/`, which is the folder shape `blendcua_agent.py --task` already
consumes, so the build stage needs no changes.

It works in two stages inside one conversation. First it **measures**: it writes
short Python into `plans/<Task>/scripts/` and runs it — segment the subject,
trace the outline, measure ratios between parts, crop a region and look at it —
because a plan's value is mostly in its numbers. Then it **writes** the plan
around those numbers.

The rule it is held to is *propose discretely, resolve mechanically*: decide
which feature you want and roughly where, then let a few lines of Python find the
exact edge. A coordinate read off an image by eye is the most common way a plan
is confidently wrong. This is the same idea the executor's overlays are built on,
moved to image space.

Output:

```
plans/<Task>/
    <Task>_plan.md         first line: <!-- ref-image: <file in this folder> -->
    reference.png          copied in, so the folder is self-contained
    scripts/               its measurement scripts, crops, overlays
    marked_<task>.json     landmarks: name, group, u, v, px, note
    marked_<task>.jpg
```

`u`/`v` are fractions of the image, origin top-left, `v` growing down — the same
convention `silhouette_vs_reference` reports in, so the planner, the builder and
the reviewer all share one coordinate system.

Afterwards a few mechanical checks run: does the plan exist, does its
`ref-image` header resolve inside the folder, does it have steps, a toolkit
section and review checks, did it actually measure anything. Results in
`plans/<Task>/scripts/planner_check.json`.

**Exemplars.** The planner imitates the plans listed in `plans/EXEMPLARS.txt` —
passes every step, so plans that worked become examples and plans that failed do
not.

### `blendcua_agent.py` — plan → geometry

Unchanged from H0. Executor walks the plan, a per-step subagent writes and runs
the action files, and a reviewer with its own tool access judges each step
against the plan's checklist. See §"Where things land" below.

### `feedback_agent.py` — run → a better harness

Asks one question about the finished run — *what would have made that easier?* —
and then builds the answer and checks it, rather than just writing it down.

**First, a digest, computed in code.** Not a summary: an index of the places the
run struggled. Steps whose action count is an outlier against the median, `REDO
LOGIC` comments, review rounds that came back `TRY_AGAIN`, inspection scripts the
builder wrote for itself, and tools it authored mid-run. The curator reads the
real files behind those pointers — the digest only says where to look.

**Then the curator**, with a shell and file access, sorting each sore spot into
one of three kinds:

| what happened | what it becomes |
|---|---|
| six fiddly actions where one call should do | a **tool** |
| a tool existed but was wrong here | a **tool fix** |
| the builder simply did not know something | a **skill** |

The test between the last and the first: *if it had known this, would it have
written different code?* Yes → skill. It would have written the same code and
only wished it were one call → tool.

**A tool is not accepted on the strength of the argument for it.** The curator
writes it, rewrites the actions that motivated it so they use it, replays them,
and compares the resulting geometry against what the run actually produced. Same
mesh in fewer actions → keep. Different mesh → the tool is wrong. `replay_batch.py`
does the replay in one dispatch with mesh hashes, so this is seconds per
experiment. Skills have no equivalent test, which is why they instead cite the
run and step that taught them.

Two rules are enforced in code rather than trusted to the prompt:

- a new tool file must parse, and **may not be named after an object** — the
  abstraction is the motif, not the thing that occasioned it;
- **reviewer skills are add-only.** A check may be added; none may be deleted or
  shortened. The curator is implicitly optimised against the review pass rate,
  and the cheapest way to make a step pass is to make its check vaguer.

Everything lands in `mem/<run>/curation/`: `digest.json`, `digest.md`,
`changeset.md` (what it committed and what it replayed), `curator_summary.md`,
`checks.json`.

### `agent_env.py` — making the plugin visible

The planner and the curator each open their own hermes conversation, outside
`blendcua_agent.py`. That is where the plugin environment was being set up, so on
the first live run both came up with **zero tools** — and an agent with no tools
does not error, it narrates. The planner reported having written a plan, with an
empty folder behind it.

`agent_env.ensure_plugin_env()` sets the three things the plugin loader needs
(`HERMES_ENABLE_PROJECT_PLUGINS`, `HERMES_HOME`, and the plugin named in
`.hermes_home/config.yaml`) and runs from the project directory, since
`.hermes/plugins/` resolves against the cwd. It merges into `config.yaml` rather
than replacing it, so `blendcua_agent.py`'s own `mcp_servers` block survives.

It also picks the toolset, which is a real decision:

| toolset | tools | who gets it |
|---|---|---|
| `blendcua_fs` | read, write, edit, glob, grep, bash | planner, curator |
| `blendcua` | write_and_run — drives live Blender | curator only |

The planner measures a photograph and writes a document; it has no business
creating geometry. The curator needs Blender because testing a candidate tool
means replaying actions against it.

`agent_env.check_tools()` warns if a conversation made no tool calls at all —
silence looked exactly like success the first time.

### Skills — how each agent gets them

Skills are role-scoped documents under `Skills/<Role>/`, each with `name` and
`description` in its frontmatter. There are five roles: `Planner`, `Executor`,
`Reviewer`, `Feedback`, and `Scripting`, which cuts across the others because
every role ends up writing throwaway Python to answer a question a glance cannot.

All of them together are about 37k characters. Putting that in every conversation
would be a real and measurable cost; putting none of it in means an agent cannot
find out they exist. So the prompt carries **names and triggers only**, and the
body is one `bash` call away — the same split of labour `tool_help.py` already
uses for the tool docstrings:

```bash
python Tool_scripts/skill_help.py measure-or-eyeball     # the full skill
python Tool_scripts/skill_help.py --search coordinate    # find one by what it covers
python Tool_scripts/skill_help.py --role Executor        # everything for one role
python Tool_scripts/skill_help.py --list                 # all of them
```

Who gets which index:

| agent | index it receives | full text it receives |
|---|---|---|
| Step-Subagent | Executor + Scripting | — |
| Reviewer | Reviewer + Scripting | — |
| Planner | Scripting | all of `Skills/Planner/` |
| Curator | Feedback + Scripting | — |

The planner is the exception: writing the plan *is* its job, so its own role's
skills go in whole rather than as triggers. Its prompt also names the two
Scripting skills worth reading before it writes its first measurement script.

The index costs about 1.8k characters for nine skills.

`blendcua_core.load_skills_index(*roles)` builds the block, and
`Tool_scripts/skill_help.py` serves the bodies. Because `blendcua_core.py` is
mirrored from H0 and would be overwritten by a sync, the three edits that wire
runs automatically after copying:

```powershell
python wire_skills.py            # report what is or is not wired
python wire_skills.py --apply    # re-apply it
```

### Snapshots

```powershell
python feedback_agent.py --snapshot          # H_01, H_02, … auto-numbered
python feedback_agent.py --snapshot H_00     # or name it
```

Copies the three directories that actually change — `Tool_scripts/Tools_code/`,
every curation. `snapshots/H_07` against `H_08` *is* the answer to "what did the
curator learn from task 7", and the digest uses the newest snapshot to work out
which tools the builder wrote during the run.

`H_00` is the starting harness. It is already there.

---

## Tasks

```
tasks/train/09_oak_barrel/
    reference.png
    task.md            one sentence: what to build
```

Deliberately thin. The plan, the measurements and the scripts are the planner's
job, not something you write here.

Populate or repopulate from the pool:

```powershell
python make_tasks.py --list                  # show all 40 and their default split
python make_tasks.py                         # the default 20 train / 10 test
python make_tasks.py --train 1,3,4,6 --clean # your own picks, by pool number
```

The default split is the one recommended in `../Tasks/Pool40/SELECTION.md`. Test
tasks are matched counterparts to training tasks — the SLR camera pairs with the
Anglepoise, the nautilus with the spiral ramp, the egret with the walk cycle — so
report each test result next to its pair rather than as a pooled average. A
failed pair names the skill that did not generalise; a pooled score hides it.

---

## Still improving H0?

```powershell
```

It mirrors the harness *and* the runner — `Skills/`, `Tool_scripts/`,
`prompt_files/`, `plans/`, `.hermes/`, and the top-level `.py` files — deleting
anything here that H0 no longer has, so the two stay genuinely in step rather
than accumulating leftovers. Differences that are only the project name in the
action-file boilerplate are ignored, and rewritten on the way in.

`snapshots/`, `mem/`, `plans/EXEMPLARS.txt`, and `Tool_scripts/skill_help.py`.
`models.py` is copied across and then has the loop's `planner` and `curator`
roles put back on top, and `wire_skills.py --apply` runs automatically at the end
to restore the skills wiring that copying `blendcua_core.py` removes.

**Stop using it once the loop has started.** The whole point is that the harness
changes only through the curator; copying a fresh one over the top silently
discards everything the curator wrote. Re-snapshot `H_00` after any sync.

---

## Where things land

```
mem/<run_name>/
  landmarks.json              named vertex-group refs, durable across the run
  steps/step_NNN/
    NN_<action>.py            every action file the builder wrote, in order
    screenshots/              per-action shot() output and overlay renders
    overlay_json/             sidecar JSON for the overlay tools
    scripts/                  the builder's own inspection scripts
    review/round_KK/
      review.txt              the reviewer's verdict for that round
      review_NN_<name>.py     its own inspection actions
      action_9N.png           what they produced
  Rollout/
    terminal.log              the Executor's turns
    usage.json                turns, cost, peak context
    rollout.jsonl             structured events
  curation/                   the curator's digest, changeset and checks
```

Two things worth knowing:

**`Rollout/terminal.log` only holds the Executor's turns.** The step subagent
runs in a separate process and logs to `.hermes_home/logs/mcp-stderr.log`, shared
across every run. To get a readable per-run log:

```powershell
```

**A `write_and_run` timeout does not mean the action failed.** The client gives
Blender 30 s to acknowledge; if Blender was merely slow, the subagent reports
zero actions even though the script ran and the geometry exists. If a step's
review shows nothing, check the next step's actions before concluding the
geometry is missing.

**If every `review.txt` says `(no response)`**, the reviewer failed auth on every
call and the run is unverified geometry, not a passed run:

```bash
grep -rL . mem/<run>/steps/step_*/review/round_*/review.txt
```

---

## Configuration

`models.py` holds all four roles — `executor`, `reviewer`, `planner`, `curator` —
with `OPENAI_REASONING_EFFORT` applied to the OpenAI ones. There are no model
flags on the command line; change it in one place.

`--action-budget` (default 20) and `--retry-budget` (default 3) cap the
subagent's actions per step and the review-fix rounds per step.

### Pausing before any harness change

Create an empty file `STOP_BEFORE_REMEDY` in this folder. Builds, bundles, the checker and the
blame stage still run, but every round stops right before its remedy is applied, so the store is
untouched and the reports can be read first. Delete the file and rerun the same command to
continue; the round resumes from its saved curation. To hold a task back entirely, put `skip` in
its round cells in `tasks/PROGRESS.csv`.

Snapshot numbering: `snapshots/H_00` is the harness at the start of the run (before any accepted change), `H_NN` the store after the NN-th publish; hand edits to the base harness are folded into every existing snapshot, not numbered.

### Two workers, two harnesses (the default with --parallel 2)

The store (Skills/, Tool_scripts/Tools_code/, Tool_scripts/Tools_ref/, prompt_files/) is a git
repository (harness/store.git) whose main worktree is this folder. Worker k works in harness/wk:
a worktree on branch wk with the store, plus a copy of the code and junctions to the shared data
folders (mem, plans, blends, tasks, snapshots, reports, vb/state). Every process of a worker runs
with cwd = its view, so agents, tools and its Blender see the usual relative paths, and only the
store differs between workers.

  * at each task start the worker's view is made equal to main (`harness.py sync k`); the whole
    task then runs on that fixed store, so the round's verdict is attributable;
  * when a round keeps a remedy, or the lessons agent writes skills for a build with no major
    defect, exactly those files are committed on the branch and merged into main
    (`harness.py publish`), main's indexes are regenerated, and snapshots/H_NN is taken;
  * merges: non-overlapping edits merge on their own; skills are add-only (git union merge);
    generated indexes are regenerated, never merged; a real conflict in code goes to an agent,
    and failing that main's version stays and the other side is saved as <name>.from_wk.py;
  * anything a worker leaves in its store that no accepted remedy claimed (an executor writing a
    helper into Tools_code) is discarded at its next sync and reported.

`python harness.py status` shows main's log, the views and whether a view is dirty;
`harness.py reset-main <rev>` puts main back; `harness.py remove k` deletes a view safely
(junctions are unlinked, never descended into). `--shared` runs the old single-store gate instead.

### Lessons when a build is good, salvage when a remedy half works

Two ways a round writes into the skills without a kept remedy:

* **Lessons** (`Curator/lessons_agent.py`, mode lessons): the build passed every step review and
  the checker found no major defect. No blame round runs; the agent reads the plan, handovers,
  reviews and checker notes and appends what made the build work to the skills of the role that
  did it (at most five lessons, add-only, each citing the run file). Gated on every review
  passing on purpose: a build the checker accepted but the reviewer had given up on (EXHAUSTED)
  teaches the wrong thing.
* **Salvage** (mode salvage): a remedy was dropped because it did not close everything it
  targeted, but some of its defects are RESOLVED and nothing got WORSE (`acceptance.json` marks
  the group `salvage`). The edits are reverted as usual, kept under
  `vb/state/<task>/round_NN/store_after/`, and the agent reads them beside the verdict and writes
  only the part the evidence says worked into the skills. The plan and tools are not restored.

Both report `{"files": [...]}`; the driver publishes exactly those files (harness.publish), so
they enter the shared store through the same door as an accepted remedy and get a snapshot.



### Rebuilding from the blamed step, reusing the previous attempt, resuming a dead build

Added 2026-09-11 after the datestone rounds: both R2 rebuilds redid the whole build from
step 1 to fix a step-2 defect, took as long as the original build, and twice re-rolled the
numerals of step 1 (which the original had right) into a new major defect.

- **R2 starts at the first step the remedy touches.** The blame agent's remedy carries
  `from_step` ("steps 1-2 are the same, keep them") and `prior_reuse` (a note on what of
  the old attempt may be taken as it is and what must be new). Without `from_step` the
  loop takes the step named by the attribution evidence and the `local_fix` target
  (`vb/rebuild.py: derive_from_step`). A plan step the remedy rewrote always clamps it:
  actions written to the old plan cannot stand in for the new one. Steps below
  `from_step` are copied from the base run and replayed into Blender in one dispatch
  (about a minute); the executor builds from there (`--only-steps`). The round state
  records `from_step`, `mem/<run>/rebuild.json` too.
- **Every rebuild's subagents know about the previous attempt.** `vb/rebuild.py` writes
  `mem/<new_run>/prior_attempt.md` (from `prior_attempt_note`): where the old run is
  (actions, handovers, reviews, renders, the checker's defects), which steps were already
  replayed, that code may be taken from it wherever it still fits the plan, and, in the
  remedy's own words, what must be built differently and why (the `local_fix`, the
  faulted action file, the checker's summary of each defect, the `prior_reuse` note).
  `blendcua_core.build_subagent_prompt` appends it to the handover block of every step
  prompt of that run. R3 adds that the plan was rewritten and where the old one is
  archived. A plain run has no such file and reads nothing.
- **A build that dies mid-step is continued, not restarted.** The executor saves an
  end-of-step `.blend` under `mem/<run>/checkpoints/`. `run_v2.py` now checks an
  incomplete first run for one (`resume_step`) and calls
  `vb/rebuild.py --resume-build --task T --run R`: the checkpoint is loaded (fallback:
  the finished steps' actions replayed), the unfinished step folders are parked under
  `mem/<run>/steps_dead/<stamp>/`, and the executor runs the remaining steps into the same
  run folder. The round loop does the same for a rebuild that died
  (`version_b.py` → `rebuild.dead_rebuild_run` → `resume_rebuild`, which also bundles and
  writes `rebuild.json`). A continued run keeps its original `store_baseline.json`.
  On 2026-09-11 every worker process was killed at once (exit 3221225786,
  STATUS_CONTROL_C_EXIT: the console they shared was closed); skull and monstera had both
  reached their last step, and without this the driver would have rebuilt both from step 1.

### The view is the whole world (added 2026-09-11 after the skull apply step)

The first remedy applied under two workers found out it was in `harness/w1`, noticed the
run folder two levels up had the same layout, wrote its three skill edits there with a
script that spelled the main folder's absolute path, and then ran `git checkout` in the view
to undo its own edits, "to leave the view clean". The plugin's path guard had refused its
first attempt (a `glob` on the main folder); a Python script run through bash was not
covered. The edits were moved into the view by hand and main was cleaned.

Two changes:

- Every Curator-side prompt (blame, apply, lessons, salvage) and `prompt_files/terminal.md`
  now carry `curator_agent.VIEW_RULE`: the working folder is the repository, the folders
  above it are off limits, never `cd ..`, never an absolute path above the working folder,
  never undo your own edits with git.
- `curator_agent.view_escapes(result)` audits every write/edit/bash call of an agent run in
  a view: an absolute path to the main run folder anywhere in the call (a script it writes
  counts), a `cd ..` / `..\..` climb, or a `git checkout|stash|reset|restore|clean`. Any hit
  fails the step the way a write into `Checker/` does: the blame agent (`audit_checker_write`),
  the apply step (`apply_check.json` problems → the round's store is reverted), the lessons
  and salvage agents (exit 1, nothing published). In the main folder the audit is empty.

Also from the same restart: a task whose round is mid-flight (remedy applied, not yet
judged) keeps its worker view's store across a driver restart (`harness.sync(k,
keep_store=True)`), and a resumed round whose rebuild already finished no longer gets its
stage reset to "apply" by the curate/apply stages re-finding their files (that reset made
the 09:33 restart replan monstera from scratch; the unused replan is parked under
`plans/_archive/`). The driver itself is started with its own console (WMI `Win32_Process.Create`,
hidden window): started with a redirected `Start-Process` it shared the tool shell's console,
and one close event on that console ended every worker at 08:03 (exit 3221225786).

### Checker quota: 2 major + 2 minor per subject (added 2026-09-11)

The monstera discovery returned 12 defects, 10 major, one for every part of the plant. The
prompt had no count rule; the "quota" existed only as a comment in the verdict code. Now the
discovery prompt defines a **subject** (a separately standing object of the brief: a potted
plant is one, a table with a chair is two), asks for a top-level `subjects` list in
`defects.json`, and caps the list at 2 major + 2 minor per subject, chosen by how much they
change what a person sees against the photograph. Everything else goes into the verdict text
and an "Also noticed" section of the markdown report. `check_defects` rejects an over-quota
list, so the checker's own retry pass has to rank. Verdict mode is unchanged: it judges the
listed ids and only scans for new majors.
