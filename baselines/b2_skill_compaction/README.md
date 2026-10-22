# B2: skill-compaction baseline for BlendCUA

**B2 is an LLM agent that drives Blender. After each task it compresses its finished
trajectory into reusable skills, stores them, and retrieves them on later tasks.** This is the
Voyager / SkillWeaver recipe. It is the *learning* baseline for BlendCUA: it improves with
experience too, so when BlendCUA beats it, the difference is in *what* is learned (a harness
repaired against checked defects vs. skills distilled from raw trajectories), not in whether
anything was learned.

B2 was built from `md_files/BASELINE_B2_BRIEF.md`. Nothing under `BlendCuavb_run/` is written
to (see "Isolation" below).

## Run it

Use the real interpreter (`python` on PATH is a broken Store shim):

```
set PY=C:\Users\kunal\AppData\Local\Programs\Python\Python312\python.exe
%PY% run_b2.py --split train              # grow the library over the 20 training tasks
%PY% run_b2.py --split test --freeze      # evaluate with the library frozen (no writes)
%PY% run_b2.py --task 09_thors_hammer     # one task
%PY% run_b2.py --status                   # what has run
%PY% run_b2.py --report                   # rewrite RESULTS.md
```

`run_b2.py` accepts any split folder under `tasks/`. A rerun is resumable. Finished tasks are
skipped, and a half-finished task picks up again at the phase it stopped in (agent → bundle →
compaction). If the agent phase itself was interrupted, the task starts over as the next run
number, and the interrupted run is kept and marked `aborted`.

## What the paper must cite

### 1. Blender channel: TCP fallback, not BlenderMCP

B2 reaches Blender through a TCP socket server running inside a GUI Blender 5.2
(`blender_server_b2.py`, started by `blender_link.py`). The server executes the agent's code on
Blender's main thread and returns what it printed plus any traceback. This is the same
mechanism BlendCUA uses (`BlendCuavb_run/Tool_scripts/win_blender_server.py`). There were two
reasons to use it: the user's instruction for this baseline was that the existing
connection is sufficient, and using it means both systems drive Blender the same way and
differ only in harness. BlenderMCP would add its own tool surface, which would be a confound.
Differences from the main server: results come back on the same socket rather than through a
status file; the namespace persists between calls (REPL-like); and **none** of BlendCUA's
`Tools_code` modules or vendored packages are on `sys.path`.

Two workers run at once. Each has its own Blender on port **6680** or **6681** (never
6666/6667) and two of the machine's four GPUs (`CUDA_VISIBLE_DEVICES`). Every task starts in
a fresh Blender launched with `--factory-startup`.

### 2. Retrieval: an LLM picks from the index, and the whole index stays reachable

Before each task, the library index (each skill's name, one-line description, when-to-use and
function names) goes to the same model as the agent, together with the task brief and its main
reference image. The model picks up to 8 skills. Those skills go into the agent's first
message in full (doc + code). The agent's system prompt also lists **every** skill in the
library, and the agent can pull any other skill into context mid-task with `load_skill(name)`.
Every skill module can be imported inside Blender (`import <name>`) whether or not it was
retrieved. Retrieval therefore decides what starts in context. It never limits what the agent
can reach.

Why an LLM pick rather than embeddings: the library holds tens of skills, and its entries are
written by the same model, so the selector can read every candidate in one prompt. Embedding
similarity on a two-sentence brief would add a second model and a threshold to tune.

## The pieces

| file | role |
|---|---|
| `run_b2.py` | curriculum runner: task order, two worker lanes, phases, resume, `RESULTS.md` |
| `agent.py` | the per-task loop: one conversation until `finish` or the budget runs out; logs everything |
| `retrieval.py` | skill selection (above) |
| `compaction.py` | trajectory → skills after each training task |
| `library.py` | the on-disk library: index, log, snapshots, reference counting |
| `blender_link.py`, `blender_server_b2.py` | the Blender connection (above) |
| `bundle_b2.py` | the main system's bundler, pointed at `Blend_baselinB2/` |
| `llm.py` | Responses API calls, retries, token/cost accounting |
| `b2_config.py` | model, prices, caps, ports, paths |
| `prompts/system.md` | the agent's system prompt |
| `agent_claude.py`, `b2_mcp_server.py` | the same per-task loop when the model is Claude, run inside the Claude Code harness (below) |

### The agent (`agent.py`)

- **Model:** the main system's executor, read from `BlendCuavb_run/models.py`:
  `gpt-5.6-luna` with `reasoning_effort = max`. Keys come from `blendcua_core.load_api_keys()`.
  The model is called through the OpenAI Responses API with `store=False`. Reasoning is carried
  between turns as encrypted content, so the model keeps its own chain of thought across the
  whole task.
- **Input:** the brief (`task.md`), every reference image in the task folder, the retrieved
  skills, and the library index.
- **Tools:** `run_python` (Blender, the only Blender channel), `screenshot` (the GUI viewport),
  `view_image`, `host_python` (Python 3.12 with numpy/scipy/Pillow, for image measurement), and
  `generate_image` (gpt-image-2, because several briefs tell the builder to make extra views
  with it; BlendCUA's executor reaches the same model from its shell). There are also
  `load_skill` and `finish`.
- **One review round (a deviation from the brief, requested by the user on 2026-09-18):** the
  first time the builder calls `finish`, a reviewer agent takes over the same live Blender. It
  uses the same model and effort, has `run_python`, `screenshot` and `view_image`, and is told
  not to change the scene. It renders and inspects the scene against the brief and references,
  then submits a prioritised critique of at most about 8 items (`prompts/reviewer.md`, 40
  tool-call budget). The critique goes back to the builder as the result of that `finish` call,
  and the builder gets one more pass. Its second `finish` is final. The review text is stored in
  `review.md` and the scene before review in `pre_review.blend`. Review spend counts toward the
  task's cost and caps. The review is skipped if the hard cap is within reach. BlendCUA's
  reviewer runs per plan step, up to two rounds each; B2's runs once per task, with no plan,
  checklist or checker behind it.
- **What it does not have:** no upfront plan or per-step checklist, no checker, no
  defect attribution, no rebuild loop, none of `BlendCuavb_run/Tool_scripts/Tools_code/`, none
  of `BlendCuavb_run/Skills/`. The system prompt gives environment facts only (how code is
  executed, where files go, what the deliverable is), not Blender procedures.
- **Robustness:** API errors are retried with backoff. A `run_python` call that hangs past its
  timeout, or a Blender crash, restarts Blender from the last checkpoint, which is saved at
  most every 5 minutes after a successful call, and the agent is told what was lost. Once the
  context passes 200K input tokens, older screenshots and long old tool outputs are stubbed
  out. The brief and the reference images are never touched.
- **Deliverable:** after `finish`, or when a cap is hit, the live scene is saved to
  `runs/<run>/final.blend` with every image packed. If Blender is dead at that point, the last
  checkpoint is saved instead.

### Budget (fairness rule 3)

BlendCUA's builds cost a median of **$2.00** and about 515K output tokens. B2 gets the same
scale of budget, with stated caps:

- **Soft:** at $2.50 or 100 minutes, the agent is told once to wrap up and call `finish`.
- **Hard:** the run stops at **$4.00**, **180 minutes** or 600 tool calls, and the scene is
  saved as it stands. The stop reason is recorded in `usage.json` and `RESULTS.md`.

The system prompt tells the agent that a typical task should take about an hour.

Cost is computed at the prices in `models.py`: $0.20/M input and $1.20/M output. Cached input
is taken as $0.02/M, the GPT-5 family's usual 10% ratio. gpt-image-2 calls are counted (calls
and tokens) but not included in the dollar figure. Retrieval spend is included in each task's
`cost_usd`. Compaction spend is recorded separately in `compaction.json`.

### Skills: executable code plus prose

Each skill is `library/skills/<name>.py` (a module of parameterised, documented functions with
no top-level side effects) plus `<name>.md` (what it does, when to use it, a usage example,
and the pitfalls the trajectory hit). This follows Voyager, whose skills are executable code,
and SkillWeaver, whose skills are APIs. Prose alone would be the weakest version of this
baseline.

After each training task, `compaction.py` gives the same model the following:

- the brief;
- the full trajectory: the agent's remarks and reasoning summaries, and every action's code
  with its outcome;
- the agent's finish summary;
- the reference image and renders of the saved scene;
- the library index;
- the full text of every skill the run used.

It returns 0–5 skills. It is told to generalise code that worked, fold the fixes from retries
into that code, and prefer transferable techniques over one-off object builders. It can
*update* an existing skill (`replaces`) instead of adding a near-duplicate. Every skill must
parse, define at least one public function, have no top-level side effects, and import cleanly
in a headless Blender. Failures go back to the model once with the errors. Anything that still
fails is dropped and logged as `rejected`. Compaction never judges the model: there is no
checker. Its only evidence is the agent's own trajectory.

## Swapping the model (the bake-off)

`B2_MODEL=<name>` picks an entrant from `b2_config.PROFILES`; `B2_RUN_TAG=<name>` keeps its
output in `runs_<tag>/`, `blends_<tag>/`, `state_<tag>/` and `RESULTS_<tag>.md`, so a bake-off
never touches the curriculum's folders. Run entrants with `--freeze`: the library they read is
the 54-skill one the training curriculum left, and none of them writes to it.

| entrant | model | reached by |
|---|---|---|
| `luna` (default) | the main system's executor, `gpt-5.6-luna` | OpenAI Responses API |
| `deepseek` | `deepseek/deepseek-v4.1-flash` | OpenRouter (same stateless Responses API) |
| `muse` | `meta/muse-spark-1.3-contributor` | OpenRouter |
| `claude` | `claude-opus-5`, effort `max` | **the Claude Code harness** (below) |
| `fable` | `claude-fable-5-1`, effort `max` | the same Claude Code harness |

### The no-library ablation (`B2_NO_LIBRARY=1`)

B2's premise is that skills distilled from past trajectories help. `B2_NO_LIBRARY=1` tests it
by removing the library completely: nothing is copied into the run, retrieval never runs, the
`load_skill` tool is not offered, the skills folder is not put on Blender's `sys.path`, and
the prompt says nothing about skills at all. Everything else — tools, system prompt wording,
review round, caps, deliverable, bundling — is untouched, so a no-library run is directly
comparable with the same model's normal run.

The two variants share one `prompts/system.md`: `library.prompt_blocks()` returns the
`{load_skill_tool}` and `{library_section}` placeholders filled or empty, so the variants
cannot drift apart in any other wording. Give the ablation its own `B2_RUN_TAG` (e.g.
`claude_nolib`) so it does not share output folders with the normal run.

### The Claude entrant (`agent_claude.py`)

Claude does not run inside `agent.py`'s conversation loop. It runs inside Claude Code, which is
its own harness, driven headless (`claude.exe -p --output-format stream-json`). Two reasons:
it is the harness this model is actually deployed in, and it authenticates with the machine's
Claude subscription, so the run costs plan usage rather than per-token money.

What is held constant against the other entrants: the Blender session and the TCP channel, all
seven tools with the same names, schemas and implementations, `prompts/system.md`, the frozen
library and its retrieval, the one review round, the deliverable, and every artefact written
under the run folder. Claude Code reaches all of it through `b2_mcp_server.py`, a small MCP
server holding no state of its own: it forwards each `tools/call` to `agent_claude.py` over a
local socket, where the same `Agent.dispatch()` the other entrants use executes it against the
live Blender and returns text, or text plus images for `screenshot` and `view_image`.

```
claude.exe -p  ──stdio MCP──▶  b2_mcp_server.py  ──TCP──▶  agent_claude.py  ──▶ Blender / host / library
```

Differences that follow from the harness, all recorded in `usage.json`:

- **Built-in tools are off** (`--tools ""`, `--strict-mcp-config`): no file editing, no shell,
  no web. The `mcp__b2__*` tools are the only ones, so the tool surface matches the others.
  Claude Code's own agent system prompt stays, with `prompts/system.md` appended to it.
- **The review round is a second `claude.exe`** with the reviewer toolset, launched while the
  builder's first `finish` call is still blocked; its review comes back as that call's result,
  and the builder continues in the same session for its final pass. `MCP_TOOL_TIMEOUT` is
  raised to an hour so the blocked call survives the round.
- **Retrieval** is a headless Claude call with no tools and a JSON schema, so the pick is made
  by the same model and account. It is the one place the reference image is not sent: that
  call has no tool with which to open one.
- **Budget:** there are no dollars to cap, so the caps are wall-clock and tool calls only. The
  `$` column in `RESULTS_claude.md` is the list-price equivalent Claude Code reports, for
  comparison with the other entrants — it is not money spent. A subscription usage limit is
  waited out and the session resumed, and the waiting time is not charged to the task's clock.
- **Three ways a session can end badly, and they are not the same thing.** A *usage limit* waits
  for the stated reset. A *transient server error* (`API Error: 529 Overloaded`, 500, 503) backs
  off 1, 2, 4... up to 15 min, `MAX_API_RETRIES` times, on its own budget — it must not spend the
  three "you stopped without finishing" nudges, or an outage lasting ten minutes destroys a
  half-built scene. Only the model actually giving up spends a nudge. In all three cases the
  waiting time is added back to the run's clock.
- **An unfinished run that bundles to nothing is `aborted`, never `done`.** The empty start scene
  saves as a ~0.1 MB `.blend` and bundles with "no renderable geometry"; recording that as `done`
  would both score a non-result and make the next invocation skip the task. Size alone is not the
  test — a genuine low-poly result can be 0.16 MB — so the rule is *did not call `finish`* **and**
  *produced nothing to render*.
- The command line carries neither the prompt nor the system prompt (Windows caps it at 32K and
  the retrieved skills alone can exceed that): the prompt goes in on stdin, the system prompt
  as `--append-system-prompt-file`.
- Every `claude.exe` runs with an environment scrubbed of `ANTHROPIC_*` and `CLAUDE_CODE_*`.
  The first would make Claude Code bill an API key instead of the plan; the second would leak
  the launching session into the child.

## Data and logs

```
tasks/train/<task>/          brief + reference plates (edited copies: see tasks/EDITS.md)
runs/<task>_run_NNN/
    trajectory.jsonl         every model turn (text, reasoning summary, tool calls, tokens, $)
                             and every tool result, in order
    actions/NNNN_blender.py  every piece of code run in Blender (+ .out.txt with its output)
    actions/NNNN_host.py     host-side scripts
    work/                    the agent's renders, screenshots, generated images
    skills/                  the library as it was when the task started (on Blender's sys.path)
    usage.json               tokens, $, API calls, tool calls, wall-clock, restarts, skills
                             (library size at start, retrieved, loaded, referenced in code)
    compaction.json          skills written/updated/rejected after the task, compaction $
    status.json              phase: running -> agent_done -> bundled -> done (or aborted)
    final.blend              the deliverable
    console.log, agent_stdout.log, bundle.log, blender_console.log
blends/<run>/                judge folder, same layout as BlendCuavb_run/blends/<run>/
library/skills/              the growing library (index.json + <name>.py + <name>.md)
library/snapshots/NN/        the library after task NN
library/library_log.jsonl    task_start, retrieve, load_on_demand, reference, write,
                             update, rejected
RESULTS.md                   per-task table + totals (regenerated after every task)
state/                       runner.log, pid files, scratch
```

**"Referenced in code"** counts the library skills whose module name appears as an identifier
in the code the agent ran in Blender. A skill that was imported and called counts. A retrieved
skill that was ignored does not.

## Task edits

The tasks are copies of `BlendCuavb_run/tasks/train`. They were edited as instructed so that
B2 is not pointed at BlendCUA's harness. Details are in `tasks/EDITS.md`. In short:

- References to BlendCUA's plans, tools, skills and its `blueprint` tool are removed or
  reworded.
- Blueprint images and JSON, which are outputs of the main system's `blueprint` tool, are
  removed, as are archives, generator scripts and manifests.
- The reference photo and the reference plates the briefs describe are kept.

## Bundling (fairness rule 5)

`bundle_b2.py` imports `BlendCuavb_run/vb/bundle.py` and `common.py` and reuses their functions
and templates unchanged: the SAVE, PROOF and FIT templates from `save_final_blend.py`,
`render_views.py` for the twelve views, and `geom_digest.py`. Only the module-level output
paths are redirected into `Blend_baselinB2/`. It follows the `bundle_from_blend.py` path
(headless, from `final.blend`) rather than `--mode live`, because live mode dispatches to the
main experiment's Blender on port 6666. Framing and lighting come from the same code in both
modes. The only addition is a GPU-enable prelude on the proof and fit renders, since a
headless Blender would otherwise render Cycles on the CPU.

## Isolation

`BlendCuavb_run/` is read (models, key loader, bundler, render scripts) and never written.
Because it is not tracked by git, "unchanged" is checked against a size/mtime manifest taken
before B2 was built (`_integrity/main_before.tsv`). Every process B2 starts sets
`PYTHONDONTWRITEBYTECODE`, so importing main-repo modules drops no `.pyc` files there.

## Training run (2026-09-18, with the review round)

The run finished all 20 tasks between 15:38 and 18:59 on two workers, with no harness
crashes and no Blender restarts. Every task ended on the agent's own second `finish`
(no cap was hit), saved a `.blend`, and bundled completely. The per-task table is in `RESULTS.md`.

- **Spend:** builder + reviewer + retrieval **$3.98** in total. That is a median of **$0.17 per task**
  (range $0.08–$0.50), against BlendCUA's median of $2.00. The review rounds account for
  $0.98 of it. Compaction cost $1.30 on top. There were 11 gpt-image-2 calls, counted
  but not priced.
- **Time:** median wall-clock 14 min per task (range 7.6–27 min). Output tokens total
  994,849. B2 stops well under its budget on its own; it is not being cut off.
- **Library:** 54 skills after task 20, with 63 writes, 9 of them updates of an existing skill
  instead of a new one. None was rejected by validation. The per-task states are in
  `library/snapshots/01..20`.
- **Reuse:** retrieval put 83 skills into context across the 20 tasks. Library skills appear
  in the agent's Blender code 14 times, spread over 7 tasks (09, 10, 11, 15, 16, 18, 19); the first
  was at task 09. Most retrieved skills are read and then not imported.

An earlier launch without the review round is kept in `_archive/v1_no_review/`. It completed
tasks 01–02 in about 5 minutes for about $0.05 each before the review round was added.
