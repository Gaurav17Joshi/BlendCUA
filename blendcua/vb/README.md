# Version B — the loop after the build

The blocks of `md_files/project_vb_v2_mac.tex` that come after the planner,
executor and reviewer have finished:

```
blends/<task>/ (first build)
      │
      ▼
 Checker, discovery ──► Checker/reports/<task>/defects.json      (ids are the join key)
      │
      ▼
 Curator ────────────► Curator/reports/<task>/round_01/curation.json   who is at fault, what to change
      │
      ▼        ┌──────────────────────────────── at most two rounds ───────────────────────────────┐
 Remedy ──────► round_01/apply/applied.json     the local fix + the durable record, guards in code  │
      │                                                                                             │
 rebuild ─────► R1 replay | R2 executor+reviewer | R3 planner then R2   ──► blends/<new_run>/        │
      │                                                                                             │
 Checker, verdict ───► Checker/reports/<new_run>/verdict.json   RESOLVED / UNCHANGED / WORSE per id │
      │                                                                                             │
 accept ──────► round_01/acceptance.json  keep the edits whose defect closed, revert the rest       │
      └─────── nothing closed? round_02 with a note asking for a bigger remedy ─────────────────────┘
      │
      ▼
 vb/harness_log.jsonl   kept / dropped / unacted / survived, with attributions
 snapshots/H_NN/        the harness after the task, with VERSION_B_NOTE.md
```

## Running it

The plan and the first build must already exist: `plans/<task>/`,
`mem/<task>_run_001/`, and the bundle `blends/<task>/` (made by
`vb/bundle.py --mode live`). Blender must be open with
`Tool_scripts/win_blender_server.py` running **from this folder**
(`python blender_health.py --probe` says whether it is).

```powershell
python vb/version_b.py --task 11_umbrella                 # the whole thing, two rounds
python vb/version_b.py --task 11_umbrella --stop-after curate
python vb/version_b.py --task 11_umbrella --rebuild R2    # override the path the curator chose
python vb/version_b.py --task 11_umbrella --from-step 3 --rebuild R2   # R2 from a checkpoint
python vb/version_b.py --task 11_umbrella --resume
```

Each stage is a script of its own and is idempotent: a report that exists is
not redone.

| stage | script | writes |
|---|---|---|
| discovery | `Checker/checker_agent.py --task T` | `Checker/reports/T/defects.json` |
| curate | `Curator/curator_agent.py --task T --out Curator/reports/T/round_NN` | `curation.json`, attribution and remedy write-ups |
| remedy | `Curator/apply_remedy.py --task T --curation ... --out .../apply` | `applied.json` — which files belong to which remedy |
| rebuild | `vb/rebuild.py --path R1\|R2\|R3 ...` | `mem/<new_run>/`, `blends/<new_run>/`, `mem/<new_run>/rebuild.json` |
| bundle | `vb/bundle.py --run <run> --mode live\|replay` | `blends/<run>/` with the twelve views and `geom_digest.json` |
| verdict | `Checker/checker_agent.py --task T --subject <new_run> --verdict-from Checker/reports/T/defects.json` | `Checker/reports/<new_run>/verdict.json` |
| accept | `vb/accept.py --task T --round-dir ... --verdict ... --rebuild ... --snapshot ...` | `acceptance.json`, `accepted/<group>.json`, reverts |

State: `vb/state/<task>/state.json`; per-round store snapshots in
`vb/state/<task>/round_NN/store_before/`; logs in `vb/state/<task>/logs/`.

## What each block decides

**Checker, verdict mode.** Discovery has a quota, so a second discovery pass
on a better model still returns about four defects per object — which is why
the earlier v2b attempt discarded every remedy. Verdict mode is given the
earlier `defects.json` and answers only: for each id, RESOLVED / UNCHANGED /
WORSE, with the same measurement retaken; and separately, is there a NEW major
defect. The plan folder stays off limits and the audit now also covers
`plans/` and any `blends/*/plan/`.

**Remedy.** The curator decides and writes nothing into the harness; the
remedy agent carries the decision out and is audited afterwards: the task is
untouched, nothing under `Checker/` is written, reviewer skills and plan review
checks are add-only (every existing line survives verbatim), other skills are
extended not gutted, tool edits are additive, a new tool parses, is registered
(`gen_tool_index.py`), is named after a motif and is mentioned by a skill,
the plan keeps its `ref-image` header and still parses, and nothing outside
`Skills/`, `Tools_code/`, `Tools_ref/`, `prompt_files/`, `plans/<task>/` (and
`mem/<new_run>/steps/` for R1) changes. Problems are fed back twice; if they
remain the store is restored from the round's snapshot.

**Rebuild path.** The widest of the chosen remedies' paths (R1 < R2 < R3),
unless `--rebuild` overrides it. R1 replays a relocated copy of the run whose
action files the remedy agent corrected; the copy is made before the remedy
step and every action file is rewritten to this folder's root and the new run
name. If the agent reports that its correction ripples into later actions, the
driver escalates to R2. R2 runs `blendcua_agent.py` on a fresh run name; with
`--from-step N` the earlier steps are copied from the base run and replayed
into the scene first, and the dispatch server seeds the handover from the
copied `handover.md`. R3 archives `plans/<task>` to `plans/_archive/`, re-runs
the planner with `--force`, then R2 in full. Note that under R3 a hand edit
to the plan is regenerated away: what R3 tests is the Planner skill.

**Accept.** Per chosen group: every id RESOLVED, no new major anywhere (a new
major whose `component.kind` matches a baseline id is a re-description and
does not count), and for R1 no geometry moved outside the objects the remedy
declared. One group closed while another got WORSE fails the round. Dropped
remedies have their files restored from the snapshot; a file shared with a kept
remedy stays. Kept edits get `accepted/<group>.json` with the before/after
observation, measurement and views. Everything, including the defects nobody
acted on, goes to `vb/harness_log.jsonl` with its attribution.

## Things that were fixed to make a rebuild possible here

- `prompt_files/*.md` hardcoded the Mac folder (`BlendCuaLoop_try`) as the
  project root; new builds would have imported tools from, and written
  screenshots into, the synced Mac copy. Repointed to this folder.
- The live server can be re-sent its own script over the socket with `ROOT`
  pinned, which is how a server started from the wrong folder is repointed
  without restarting Blender (`vb/common.py` does not do this itself; see the
  session notes).
- `Checker/checker_agent.py` no longer accepts `attribution`/`remedy` fields in
  discovery output (the checker has no basis for them); any it writes are
  stripped.
