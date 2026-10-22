# Curator

The **ATTRIBUTE + REMEDY** block, Version B §5–§7 (`md_files/project_vb_v2.tex`).

    python Curator/curator_agent.py --task 11_umbrella

The checker says what is wrong with the model. The curator says *who is at
fault* and *what to change about the harness*, then stops. It does not rebuild
— that is the next block, and keeping the decision separate from the rebuild is
what lets the decision be read before any money is spent acting on it.

## What it sees, and what it must not touch

| reads | may not **write** |
|---|---|
| `Checker/reports/<Task>/defects.json` — the defect list | `blends/<Task>/task/` — the brief and reference |
| `blends/<Task>/plan/` — the plan, in full | `Checker/` — anything at all |
| `mem/<run>/steps/` — action files and review transcripts | |
| `Skills/` indexed, `prompt_files/current_tools.md` | |
| `blends/<Task>/views/` — the same twelve renders | |

It reads out of `Checker/reports/<Task>/` and writes into
`Curator/reports/<Task>/`. Two trees on purpose — see the second guard below.

**The curator reads the plan; the checker does not.** That inversion is the
point of having two agents. Attribution is precisely the question of whether
the plan, the actions, the reviewer or the views produced the defect, and it
cannot be answered from renders alone.

**Two write-guards, both audited rather than trusted.** Read access is
unrestricted — reading evidence is the whole job. Only writes are policed, and
that includes shell redirects, `mv`, `cp`, `rm`, `tee` and `sed -i`.

- `audit_task_edit()` — the task is never edited. The brief and the reference
  photograph are the ground truth for the whole method; a curator that can edit
  them can make any defect go away by redefining the target. This is the mirror
  of the checker's `audit_plan_access()`: each agent has one thing it must not
  touch.
- `audit_checker_write()` — the checker must stay outside what the remedy is
  allowed to edit (§4). If a remedy can touch the checker, the cheapest way to
  make the re-check say "fixed" is to weaken the check — the same concern that
  makes reviewer checklists add-only. `Curator/` being a separate folder from
  `Checker/` is what makes this checkable at all.

Note that writing `blends/<Task>/plan/` **is** allowed: correcting the plan is a
legitimate local fix (cases 1–3).

## Output

    Curator/reports/<Task>/
        curation.json            the deliverable
        <Task>_attribution.md    who is at fault, with citations
        <Task>_remedy.md         what to change, and how to rebuild to test it
        curator_scripts/         its own scratch folder
        curator_summary.md       what it said when it finished
        curator_check.json       validation result + task-edit audit
        curator_usage.json       cost of the call

It groups before it attributes, and the grouping is a first-class output rather
than a convenience: several defects are usually one mistake seen from different
angles, and a per-defect loop would buy three remedies for one root cause.

## What `check_curation()` enforces

The interesting half of this agent is the validator, because most of Version B's
rules are the kind a language model will drift off if nothing checks them:

- every grouped defect id exists in `defects.json`, and no id is in two groups
- 1–2 groups chosen, exactly one remedy each; warns if a minor was chosen while
  a major was left unchosen
- fault class from `plan`/`exec`/`review`/`views`/`none`, at most two per group,
  and `none` cannot be combined with another class
- **every non-`none` attribution cites a path that exists on disk.** An
  attribution with no citable evidence is not an attribution, so this is a hard
  problem rather than a warning
- `case` is 1–12 and the rebuild path matches what that case implies (case 3
  means the plan never named the constraint, which only R3 can test)
- **a skill-only remedy may not be R1.** Replaying the old action files replays
  exactly the decision the skill was written to change
- a `tool` target may not be named after an object — the mechanical version of
  "what earns a tool is a motif that will come back"
- every remedy has a `durable_record`; the local fix alone teaches the harness
  nothing

Malformed output is fed back and re-attempted (`--retries`), same as the
checker.

Two central-config entries, already present:

- `models.py` -> `MODELS["curator"]`
- `agent_env.py` -> `CURATOR_TOOLSETS = ["blendcua_fs"]`

`blendcua_fs` only, and that is a scar rather than a preference: `blendcua`'s
`write_and_run` is gated on an active step context, and an earlier curator trial
reached for the one tool it knew drove Blender, got "no active BlendCUA step
context", and gave up instead of falling back to `Tool_scripts/run.py`. See the
comment in `agent_env.py`.

## Carrying the remedy out: `apply_remedy.py`

    python Curator/apply_remedy.py --task 11_umbrella         --curation Curator/reports/11_umbrella/round_01/curation.json         --out Curator/reports/11_umbrella/round_01/apply [--run <new_run>]

A second agent makes the edits the curator decided: the local fix (the plan in
`plans/<task>/`, or the action files of a relocated run copy for R1) and the
durable record (skills, tools with their index entry and skill trigger). It is
audited afterwards, in code, against every rule Version B fixes — task and
checker untouched, reviewer skills and plan review checks add-only, other
skills extended not gutted, tool edits additive, new tools registered and
motif-named, scope limited to the store — and problems are fed back for two
more attempts. It writes `applied.json`, which says which files belong to
which remedy, so `vb/accept.py` can revert a dropped remedy on its own.

`--out` on `curator_agent.py` puts a round's curation under
`Curator/reports/<task>/round_NN/`; `--note` carries the previous round's
outcome into the next. The driver is `vb/version_b.py`; see `vb/README.md`.
