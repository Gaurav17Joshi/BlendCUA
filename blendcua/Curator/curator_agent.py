#!/usr/bin/env python3
"""ATTRIBUTION + REMEDY — the curator block of Version B.

    TASK -> PLAN + BUILD -> RESULT -> CHECKER -> [CURATOR] -> REBUILD
         -> CHECKER -> FIXED? -> KEEP -> HARNESS

The checker says what is wrong with the model. The curator says *who is at
fault* and *what to change about the harness*, then stops. It does not rebuild:
that is the next block, and keeping the decision separate from the rebuild is
what lets the decision be inspected before any money is spent on it.

Architecture is checker_agent.py's, which is planner_agent.py's: one long
conversation with a shell and a scratch folder, read the evidence with real
tool calls rather than trusting a digest, problems fed back and retried.

Three things make this agent different from the checker.

**It reads everything.** The checker is denied the plan on purpose. The curator
needs the plan, the action files and the reviews — attribution is exactly the
question of which of those produced the defect, and it cannot be answered from
the renders alone.

**It may not edit the task.** The brief and the reference photograph are the
ground truth for the whole method; changing them to suit the model is not a
remedy, it is moving the goalposts. `audit_task_edit()` fails the run if any
tool call writes into `blends/<task>/task/`. This is the mirror of the
checker's `audit_plan_access()`: each agent has one thing it must not touch,
and in both cases it is verified rather than trusted.

**It groups before it attributes.** Several defects are often one mistake seen
from different angles, and a per-defect loop would buy three remedies for one
root cause. The grouping is the first-class output, not a convenience.

    python Curator/curator_agent.py --task 11_umbrella

Reads Checker/reports/<task>/defects.json. Writes into Curator/reports/<task>/:

    curation.json            the deliverable: groups, attributions, remedies
    <task>_attribution.md    who is at fault, with citations
    <task>_remedy.md         what to change, and how to rebuild to test it
    curator_summary.md       what it said when it finished
    curator_check.json       validation result + task-edit audit
    curator_usage.json       cost of the call
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[1])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

CURATOR_DIR = Path(__file__).resolve().parent
ROOT = CURATOR_DIR.parent
sys.path.insert(0, str(ROOT))

import agent_env                                          # noqa: E402
import blendcua_core as core                              # noqa: E402
from models import MODELS, OPENAI_REASONING_EFFORT        # noqa: E402

BLENDS_DIR = ROOT / "blends"
MEM_DIR = ROOT / "mem"

# Where our own output goes, and where the checker's comes from. These are
# deliberately different trees. Version B §4: the checker "must stay outside
# whatever the remedy step is allowed to edit" — if a remedy can touch the
# checker, the cheapest way to make FIXED? say yes is to weaken the check.
# The curator reads CHECKER_REPORTS and never writes into it.
REPORTS_DIR = CURATOR_DIR / "reports"
CHECKER_REPORTS = ROOT / "Checker" / "reports"

STALE_TIMEOUT_S = "900"

# ── the vocabularies the spec fixes ─────────────────────────────────────────
# Version B §5. `none` is deliberately in the list: without it the curator is
# forced to blame something for every defect and writes harness edits that
# teach nothing.
FAULT_CLASSES = ["plan", "exec", "review", "views", "none"]

# Version B §7. Which rebuild proves the remedy.
REBUILD_PATHS = ["R1", "R2", "R3", "none"]

# Version B §6, the twelve cases. Kept as data so the validator can check the
# curator's self-declared case against the rebuild path it chose.
CASES = {
    1:  ("plan carried a wrong number or count", ["R2"]),
    2:  ("plan named the constraint ambiguously", ["R2"]),
    3:  ("plan never named the constraint at all", ["R3"]),
    4:  ("approach was wrong, a better one exists", ["R2"]),
    5:  ("right operation does not exist, agent faked it", ["R1", "R2"]),
    6:  ("a tool existed, was used, and was wrong here", ["R1"]),
    7:  ("appearance value eyeballed instead of overlaid", ["R1", "R2"]),
    8:  ("reviewer had a check and passed it anyway", ["none"]),
    9:  ("reviewer had no check for this", ["none"]),
    10: ("views wrong, or the telling view never generated", ["R3"]),
    11: ("nothing broke, something worth keeping", ["none"]),
    12: ("the brief itself was ambiguous", ["none"]),
}

REMEDY_KINDS = ["plan_edit", "skill", "tool", "tool_fix", "checklist", "task_note"]


# ── inputs ───────────────────────────────────────────────────────────────────

def find_subject(name: str) -> Path:
    p = BLENDS_DIR / name
    if not p.is_dir():
        raise SystemExit(f"no such task folder: {p}")
    return p


def find_run(task_name: str, run: str | None) -> Path:
    """The mem/ run folder holding the action files and reviews."""
    if run:
        p = MEM_DIR / run
        if not p.is_dir():
            raise SystemExit(f"no such run folder: {p}")
        return p
    cands = sorted(MEM_DIR.glob(f"{task_name}_run_*"))
    if not cands:
        raise SystemExit(f"no mem/{task_name}_run_* folder — pass --run explicitly")
    return cands[-1]                                       # latest run


def build_digest(run_dir: Path) -> str:
    """The build as a citable index: every action file and every review round.

    Not the file contents — those are for the agent to `read` when a defect
    actually points at them. What this has to do is make the citation space
    visible, so an attribution can name `step_002/07_seat_ribs.py` without the
    agent having to go hunting for what exists.
    """
    steps = sorted((run_dir / "steps").glob("step_*"))
    if not steps:
        return "(no steps/ in this run)"
    rel = rel_to(run_dir, ROOT).as_posix()
    out = []
    for s in steps:
        actions = sorted(p.name for p in s.glob("*.py"))
        rounds = sorted(r.name for r in (s / "review").glob("round_*")) \
            if (s / "review").is_dir() else []
        verdicts = []
        for r in rounds:
            rt = s / "review" / r / "review.txt"
            if rt.is_file():
                txt = rt.read_text(encoding="utf-8", errors="replace").strip()
                tail = txt[-400:]
                verdict = ("PASS" if re.search(r"\bPASS\b", tail)
                           else "FAIL" if re.search(r"\bFAIL\b", tail) else "?")
                verdicts.append(f"{r}={verdict}")
        out.append(
            f"- `{rel}/steps/{s.name}/`\n"
            f"    actions: {', '.join(actions) if actions else '(none)'}\n"
            f"    reviews: {', '.join(verdicts) if verdicts else '(none)'}"
        )
    return "\n".join(out)


def skills_index() -> str:
    """What skills already exist, per role. Indexed, not inlined.

    The curator's job includes deciding whether a lesson belongs in an
    existing skill or a new one, and it cannot make that call without knowing
    what is already written. Full text would be tens of thousands of tokens,
    so this is names plus each file's description line, and the agent reads the
    ones it needs.
    """
    parts = []
    for role in ("Planner", "Executor", "Reviewer", "Feedback", "Curator"):
        d = ROOT / "Skills" / role
        if not d.is_dir():
            continue
        rows = []
        for f in sorted(d.rglob("*.md")):
            if f.parent != d and "name:" not in f.read_text(encoding="utf-8", errors="replace")[:400]:
                continue      # evidence notes beside a skill, not a skill
            desc = ""
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
                    break
            rows.append(f"    - `{f.name}` — {desc[:110]}" if desc
                        else f"    - `{f.name}`")
        parts.append(f"  **Skills/{role}/** ({len(rows)})\n" + "\n".join(rows))
    return "\n\n".join(parts) if parts else "(no skills yet)"


def defects_digest(path: Path) -> tuple[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    defects = data.get("defects") or []
    lines = [f"**Checker verdict.** {(data.get('verdict') or '').strip()}", ""]
    for d in defects:
        ev = d.get("evidence") or {}
        lines.append(
            f"- `{d.get('id')}` — **{d.get('severity')}** / {d.get('kind')} / "
            f"{d.get('component')}\n"
            f"    summary:  {d.get('summary')}\n"
            f"    expected: {d.get('expected')}\n"
            f"    observed: {d.get('observed')}\n"
            f"    views:    {', '.join(ev.get('views') or []) or '—'}\n"
            f"    confidence: {d.get('confidence')}"
        )
    return "\n".join(lines), defects


def current_tools() -> str:
    p = ROOT / "prompt_files" / "current_tools.md"
    if not p.is_file():
        return "(prompt_files/current_tools.md not found)"
    txt = p.read_text(encoding="utf-8", errors="replace")
    return txt if len(txt) < 6000 else txt[:6000] + "\n\n…(truncated, `read` it in full)"


# ── prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the curator for a Blender build harness. A checker has judged a "
    "finished model and listed its defects. You decide two things: which part "
    "of the harness is at fault for each defect, and what to change so the "
    "next build does better. You have a shell and read access to the plan, the "
    "action files and the review transcripts — read them, because an "
    "attribution you cannot cite a file for is not an attribution. You never "
    "edit the task brief or the reference photograph: they are the ground "
    "truth, and changing them to suit the model is not a remedy. You do not "
    "rebuild anything; you decide, write it down, and stop."
)


def build_intro(*, task_name: str, run_dir: Path, description: str,
                defects_md: str, build_md: str, skills_md: str,
                tools_md: str, report_dir: Path, plan_rel: str,
                n_defects: int, subject_name: str | None = None,
                defects_rel: str | None = None) -> str:
    rel_report = rel_to(report_dir, ROOT).as_posix()
    subject_name = subject_name or task_name
    defects_rel = defects_rel or f"Checker/reports/{task_name}/defects.json"
    rel_run = rel_to(run_dir, ROOT).as_posix()
    return f"""\
# Curator — task `{task_name}`

## Your job

The checker has judged the finished model without ever seeing the plan, and
found {n_defects} defect(s). They are listed below. You do three things in one
pass over the whole list, and then you stop.

1. **Group.** Defects that are the same underlying mistake go in one group.
   Several defects are often one error seen from different angles — a rib splay
   that is wrong makes the stance wrong, the footprint wrong and the silhouette
   wrong — and three separate remedies for one root cause is exactly what the
   grouping is here to prevent. A group of one is fine when a defect really is
   its own mistake.
2. **Attribute.** For each group, name at most two fault classes and **cite the
   artefact that shows it**. An attribution with no citable evidence is not an
   attribution; write `none` instead.
3. **Choose and remedy.** Pick the **1–2 groups that matter most** — majors
   first, and whichever fix helps the most groups — and write the remedy for
   each. Everything you do not choose still gets logged with its attribution.

## The fault classes

| class | what it means | evidence it must cite |
|---|---|---|
| `plan` | the plan was wrong, missing a step, carried a wrong number, or never named the constraint | the plan step, or its absence |
| `exec` | the plan was right and the action files did something else | `steps/step_NNN/NN_*.py` |
| `review` | the defect was there at the end of a step and the reviewer passed it | the `review.txt` that returned PASS |
| `views` | the planner worked from views that could not show the thing that went wrong: the synthesised views were wrong, or the view that would have shown it was never generated | the generated view, or the plan's own "reference decision" section showing it measured only the one photograph |
| `none` | not attributable to the harness: a base capability limit, or within tolerance | — |

On `views`, be concrete about what it covers. The planner receives one
photograph. When that photograph is oblique, a three-quarter render, or shows
one face only, every number the planner can measure is a projection, and the
plan then either carries a wrong or vague 3-D quantity (a depth, a thickness,
the orientation of a part relative to another) or never names it at all. That
is a `views` fault, not merely a `plan` one: the plan step was written without
the straight-on front, side or top view that would have supplied the number,
and the cure is to give the planner that view — synthesised from the reference
with an image model (`Tool_scripts/generate_views_gpt_image.py` is the
prototype; `Skills/Planner/Gpt_images/prompting-reference-plates.md` records what wording
works) and verified before anything is measured off it — rather than to add
one more number by hand. Cite `plans/{task_name}/scripts/` (no synthesised
plate there) or the plan's reference-decision section as the gap. If a
missing view is the root, the case is 10 and the rebuild is R3, because the
question is whether the planner now writes a better plan with the view in
front of it.

Two rules on this, and they are not decoration.

- **`none` is a real option.** If you are forced to blame something for every
  defect you will write harness edits that teach nothing. Use it.
- **`review` can stand alone.** Usually it is a co-class — something else
  produced the defect and the reviewer merely failed to catch it, and then the
  producing class is what gets remedied. But it can be the whole story: the
  plan named the constraint, the build got it wrong, the reviewer had
  everything it needed to see that, and passed anyway.

## Judge like a person, then attribute like a procedure

Read `Skills/Curator/human-judgement.md` before you attribute anything, and
read two of the worked examples under `Skills/Curator/good_context/` (they are
short). They are what a person said about six finished builds: what was wrong,
why, and what to do. The agents that came before you missed most of it, and
the pattern of what they missed is the point:

- **Construction, not only measurement.** "Three lofts instead of one mesh",
  "a cuboid under a cylinder", "a plate made and then not used", "built toward
  the camera to match the picture" are causes a fix can act on. Look at HOW a
  part was made (`steps/step_NNN/NN_*.py`, the screenshots), not only at what
  measures wrong.
- **Model the object, not the picture.** If a part was placed or shaped so the
  render matches the photo from the hero angle (laces off the centreline, a
  tongue on the visible side, jaws hung outside the snout, a flat head with a
  strip twisted to fake a band), that is an approach fault. Say so.
- **Shape from the plate, proportion from the photo.** If a straight plate was
  synthesised and the plan then measured everything on the tilted photo anyway,
  that is a `plan` fault of its own kind: the plate existed and was not used.

Answer these five questions for every defect, in order, and derive the class
and the case from the answers rather than from an impression:

1. Is the quantity or feature named in the plan?  (no -> `plan`)
2. If named, did the build meet the plan's number or wording? (reviewer log)
   (no -> `exec`, and `review` if the reviewer passed it anyway)
3. If met and still wrong, where did the number come from: a straight plate;
   the photo along an axis it can show; the photo along an axis it cannot show
   (-> `views`); or a guess (-> `plan`)?
4. Did the reviewer measure it at all?  (no -> add `review`)
5. Does an operation exist that produces this feature properly?  (no -> the
   case is 5 and the remedy builds it; "extend a skill" is not an answer here)

`views` means exactly a dimension the single photo could not give: depth for a
front photo, width for a side photo. It does NOT mean a surface the camera did
not look at (an underside, a far side); that is `exec` or `review`.

**Path sanity.** Whatever the case table says: if the local fix touches one
action and nothing later depends on it, the path is R1. If it touches only the
plan text of one step, R2 from that step. R3 only when the planner's decision
procedure itself has to change.

**Every remedy carries a check.** Name one measurement the reviewer will run
next time and the number it must hit, and say what else in the plan depends
on the quantity you change. A remedy that is only skill wording ranks below
one with a check.

## What a remedy has to contain

Two parts, and the second is not optional:

- the **local fix**, which makes *this* build right, and
- the **durable record**, which makes the *next* build better.

Fixing the plan for this task without writing down the lesson teaches the
harness nothing. If the plan said eight ribs and the reference has ten, you fix
the plan *and* write into a Planner skill what class of mistake that was and
how to avoid it next time.

**Cheap is not the goal, right is.** A remedy that papers over a missing
capability will pass its own re-check and then fail on the test split. If what
went wrong is that the right operation does not exist, build the tool. What
earns a tool is a *motif that will come back* — cut an opening into a surface
and fit geometry into it, fit a repeated feature along a curved edge, seat one
mesh into a recess in another. What does not earn a tool is one object's quirk.
A tool may not be named after an object; that rule is the mechanical version of
this test.

Every new tool comes with a skill saying when to reach for it, and gets
registered in `prompt_files/current_tools.md`. A tool nobody knows about is not
an addition to the harness. Skills can also stand alone: a good construction
order found while building this object is worth writing down even though
nothing broke.

**The task is never edited.** If the brief really is ambiguous, that is a note
about the task set (`task_note`), filed as such, and it does not count as
learning.

## The twelve cases

Declare which one each chosen remedy is. The number fixes the expected rebuild
path, and the validator checks the pair.

{chr(10).join(f"{n}. {d}  → `{'`/`'.join(p)}`" for n, (d, p) in CASES.items())}

## Rebuild paths

- `R1` — you edit the action file that is wrong and the whole action sequence is
  re-run in one dispatch. No agent involved. Seconds. **Only valid when the
  correction does not ripple**: if fixing action 3 of step 2 changes what the
  later actions should do, replaying them unchanged produces a build that no
  longer makes sense, and that is R2.
- `R2` — executor and reviewer run again from the plan, under the new harness.
  The planner does not run. One build.
- `R3` — planner runs first, then executor and reviewer. One plan + one build.

**A skill cannot be tested by R1 at all.** Replaying the old action files
replays exactly the decisions the skill was written to change. Any remedy whose
point is that the agent now *chooses* differently needs R2 at least.

## The task brief

The build agent was given this and the reference photograph, nothing else.

{description}

## The checker's defects

{defects_md}

**One thing to know about `defects.json` if you open it** — it is at
`{defects_rel}`. Each defect in that
file also carries an `attribution` and a `remedy` field which the checker filled
in itself. **Ignore both.** The checker never saw the plan, the action files or
the reviews, so it has no basis for deciding which part of the harness is at
fault — and it shows: it labelled every defect with the same single class.
Those fields are a placeholder for your output, not an input to it. The list
above is deliberately stripped of them. Attribute from the evidence yourself.

## The plan

`{plan_rel}` — read it. This is the document the `plan` fault class is about.

## The build

Action files are the only record of what was actually done, and they can be
re-run, which is what makes R1 possible. Reviews are per step, per round, and
the verdict is the last line.

{build_md}

Full run folder: `{rel_run}/`

## Skills that already exist

Read the ones you might be extending. A lesson usually belongs in an existing
skill rather than a new one.

{skills_md}

## Tools that already exist

{tools_md}

## Renders

`blends/{subject_name}/views/` — the same twelve the checker saw, if you want to
look at a defect yourself. `blends/{subject_name}/task/reference.png` is the
reference.

## Two places you must not write

{VIEW_RULE}

Read anything. Write into neither of these, and both are audited:

- `blends/{subject_name}/task/` — the brief and the reference photograph are the
  ground truth for the whole method. A curator that can edit them can make any
  defect go away by redefining the target.
- `Checker/` — the checker has to stay outside what the remedy is allowed to
  edit. If a remedy can touch the checker, the cheapest way to make the
  re-check say "fixed" is to weaken the check. Your own output goes in
  `{rel_report}/`, which is a different tree on purpose.

## What to write

Your scratch folder is `{rel_report}/curator_scripts/`. Nothing goes into the working folder's root (no tmp_*.py, crops or notes beside the code): files left there are deleted at the next sync. Write **three** files
into `{rel_report}/`.

### 1. `curation.json`

```json
{{
  "task": "{task_name}",
  "run": "{run_dir.name}",
  "summary": "one paragraph: what actually went wrong on this task",
  "groups": [
    {{
      "group_id": "canopy_tenting",
      "defect_ids": ["umbrella.geometry.canopy_flat"],
      "root_cause": "one sentence, the underlying mistake",
      "severity": "major",
      "attribution": [
        {{
          "class": "plan",
          "evidence": "blends/{subject_name}/plan/{task_name}_plan.md#step-3",
          "reasoning": "why this artefact shows this class is at fault"
        }}
      ],
      "chosen": true
    }}
  ],
  "remedies": [
    {{
      "group_id": "canopy_tenting",
      "case": 3,
      "local_fix": {{
        "what": "what you would change to make THIS build right",
        "target": "the exact file the fix lands in"
      }},
      "durable_record": [
        {{
          "kind": "skill",
          "target": "Skills/Planner/cloth-pin-density.md",
          "action": "create",
          "content_sketch": "2-4 lines of what it would say",
          "cites": "mem/{run_dir.name}/steps/step_003/review/round_01/review.txt"
        }}
      ],
      "rebuild": "R3",
      "from_step": 3,
      "prior_reuse": "one or two sentences: what of the previous attempt's later steps the rebuild may take as it is, and what it must build fresh",
      "rebuild_reasoning": "why this path and not a cheaper one",
      "acceptance": "which defect id must come back RESOLVED for this to be kept"
    }}
  ],
  "not_acted_on": [
    {{"group_id": "…", "why": "one line — quota, low severity, or attributed none"}}
  ]
}}
```

Rules the validator enforces, so get them right the first time:

- every `defect_ids` entry is an id that exists in the checker's list, and no
  id appears in two groups
- 1 or 2 groups have `chosen: true`, and there is exactly one remedy per chosen
  group
- `class` is one of `plan` / `exec` / `review` / `views` / `none`, at most two
  per group
- every non-`none` attribution's `evidence` is a path that **exists on disk**
  (a `#fragment` suffix is allowed and ignored for the existence check)
- `case` is 1–12 and `rebuild` is consistent with it per the table above
- a `skill`-only remedy may not be `R1`
- `from_step` is the first plan step the rebuild has to redo — the blamed step, or
  the first step your remedy rewrites, whichever is lower. Every step below it is
  copied from the original run and replayed as it was ("steps 1-2 are the same,
  keep them"), so say 1 only when step 1 itself is at fault. `prior_reuse` is your
  note to the rebuild's subagents, who are told where the previous attempt is and
  may take code from it: name what still holds (setup, measurements, cameras, the
  constructions you did not fault) and what must not be copied because it is the
  very thing being replaced.
- a `tool` target may not be named after an object
- every remedy has at least one `durable_record` entry

### 2. `{task_name}_attribution.md`

The same thing to read: the groups, what each is, who is at fault, and the
citation. Include the ones you did not choose — an attribution histogram over
plan/exec/review/views is an ablation for free, and it only works if the
unchosen groups are labelled too.

### 3. `{task_name}_remedy.md`

For each chosen group: the local fix, the durable record with its draft
content, the rebuild path with the reasoning for why not something cheaper, and
the acceptance test. Someone should be able to execute this without asking you
what you meant.

## How to work

Read before you conclude. The plan is a real document and the action files are
real code; a defect about rib seating is decided by opening
`step_002/*.py` and seeing what it actually did, not by guessing from the
render. Use `bash` and your scratch folder freely. Say when the evidence does
not support an attribution — `none` is a finding, not a failure.

Finish by writing the three files, then give a short summary as your final
message.
"""


# ── validation ───────────────────────────────────────────────────────────────

_GROUP_RE = re.compile(r"^[a-z0-9_]+$")
_OBJECT_WORDS: tuple[str, ...] = (
    "umbrella", "chair", "skull", "shark", "hammer", "lantern", "hourglass",
    "chess", "domino", "sneaker", "monstera", "datestone", "can", "gate",
    "tablecloth", "thinker", "dog", "box", "glass", "anglepoise",
)


def _exists(rel: str) -> bool:
    """Does this citation point at something on disk?

    A citation may carry a `#fragment` (a plan heading, a line anchor); that is
    for a human, not the filesystem, so it is stripped before checking.
    """
    clean = (rel or "").split("#", 1)[0].strip().lstrip("/")
    if not clean:
        return False
    return (ROOT / clean).exists()


def check_curation(report_dir: Path, task_name: str,
                   defects: list[dict]) -> tuple[list[str], list[str]]:
    """Mechanical checks on curation.json. Returns (problems, warnings).

    Problems mean the rebuild block cannot consume this. Warnings mean it can,
    but something about the decision is thin.
    """
    problems: list[str] = []
    warnings: list[str] = []

    path = report_dir / "curation.json"
    if not path.is_file():
        return [f"no curation.json written into {report_dir}"], warnings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"curation.json is not valid JSON: {exc}"], warnings
    if not isinstance(data, dict):
        return ["curation.json must be a JSON object"], warnings

    if data.get("task") != task_name:
        warnings.append(f"task field is {data.get('task')!r}, expected {task_name!r}")
    if not (data.get("summary") or "").strip():
        problems.append("no summary")

    known_ids = {d.get("id") for d in defects}
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        return problems + ["groups is missing or empty"], warnings

    seen_ids: dict[str, str] = {}
    gids: set[str] = set()
    chosen: list[str] = []

    for i, g in enumerate(groups):
        tag = f"group[{i}]"
        if not isinstance(g, dict):
            problems.append(f"{tag} is not an object")
            continue
        gid = g.get("group_id") or ""
        tag = f"group {gid or i}"
        if not _GROUP_RE.match(gid):
            problems.append(f"{tag}: group_id must be lower_snake_case")
        if gid in gids:
            problems.append(f"{tag}: duplicate group_id")
        gids.add(gid)

        ids = g.get("defect_ids")
        if not isinstance(ids, list) or not ids:
            problems.append(f"{tag}: defect_ids is missing or empty")
        else:
            for did in ids:
                if did not in known_ids:
                    problems.append(f"{tag}: defect id {did!r} is not in the "
                                    f"checker's list")
                if did in seen_ids:
                    problems.append(f"{tag}: defect id {did!r} already grouped "
                                    f"under {seen_ids[did]!r}")
                seen_ids[did] = gid

        if not (g.get("root_cause") or "").strip():
            problems.append(f"{tag}: no root_cause")

        att = g.get("attribution")
        if not isinstance(att, list) or not att:
            problems.append(f"{tag}: no attribution")
        else:
            if len(att) > 2:
                problems.append(f"{tag}: {len(att)} fault classes, at most 2 allowed")
            classes = []
            for a in att:
                if not isinstance(a, dict):
                    problems.append(f"{tag}: attribution entry is not an object")
                    continue
                cls = a.get("class")
                classes.append(cls)
                if cls not in FAULT_CLASSES:
                    problems.append(f"{tag}: class {cls!r} not in {FAULT_CLASSES}")
                if cls and cls != "none":
                    ev = (a.get("evidence") or "").strip()
                    if not ev:
                        problems.append(f"{tag}: class {cls!r} cites no evidence — "
                                        f"an attribution with no citable evidence "
                                        f"is not an attribution")
                    elif not _exists(ev):
                        problems.append(f"{tag}: class {cls!r} cites {ev!r}, "
                                        f"which does not exist")
                    if not (a.get("reasoning") or "").strip():
                        warnings.append(f"{tag}: class {cls!r} gives no reasoning")
            if "none" in classes and len(classes) > 1:
                problems.append(f"{tag}: 'none' cannot be combined with another class")

        if g.get("chosen") is True:
            chosen.append(gid)

    if not chosen:
        problems.append("no group chosen — the curator must act on 1 or 2")
    elif len(chosen) > 2:
        problems.append(f"{len(chosen)} groups chosen, at most 2 per round")

    # majors first: warn if a minor was chosen while an unchosen major sits there
    sev = {g.get("group_id"): (g.get("severity") or "").lower() for g in groups
           if isinstance(g, dict)}
    unchosen_major = [k for k, v in sev.items() if v == "major" and k not in chosen]
    chosen_minor = [k for k in chosen if sev.get(k) == "minor"]
    if chosen_minor and unchosen_major:
        warnings.append(f"chose minor group(s) {chosen_minor} while major "
                        f"group(s) {unchosen_major} were left unchosen — "
                        f"majors first")

    remedies = data.get("remedies")
    if not isinstance(remedies, list):
        problems.append("remedies is not a list")
        remedies = []
    by_group: dict[str, dict] = {}
    for i, r in enumerate(remedies):
        if not isinstance(r, dict):
            problems.append(f"remedy[{i}] is not an object")
            continue
        gid = r.get("group_id") or ""
        if gid in by_group:
            problems.append(f"remedy for {gid!r} appears twice")
        by_group[gid] = r
        tag = f"remedy {gid or i}"
        if gid not in gids:
            problems.append(f"{tag}: no such group_id")

        case = r.get("case")
        rebuild = r.get("rebuild")
        if case not in CASES:
            problems.append(f"{tag}: case {case!r} is not 1–12")
        if rebuild not in REBUILD_PATHS:
            problems.append(f"{tag}: rebuild {rebuild!r} not in {REBUILD_PATHS}")
        if case in CASES and rebuild in REBUILD_PATHS:
            allowed = CASES[case][1]
            if rebuild not in allowed:
                problems.append(f"{tag}: case {case} ({CASES[case][0]}) expects "
                                f"rebuild {'/'.join(allowed)}, got {rebuild}")

        lf = r.get("local_fix")
        if not isinstance(lf, dict) or not (lf.get("what") or "").strip():
            problems.append(f"{tag}: no local_fix.what")

        fs = r.get("from_step")
        if fs is not None and not (isinstance(fs, int) and not isinstance(fs, bool) and fs >= 1):
            problems.append(f"{tag}: from_step {fs!r} is not a step number (1, 2, ...)")
        elif fs is None and rebuild in ("R2", "R3"):
            warnings.append(f"{tag}: no from_step — the rebuild start is taken from the "
                            f"attribution evidence and the plan diff instead")
        if rebuild in ("R2", "R3") and not (r.get("prior_reuse") or "").strip():
            warnings.append(f"{tag}: no prior_reuse note for the rebuild's subagents")

        dr = r.get("durable_record")
        if not isinstance(dr, list) or not dr:
            problems.append(f"{tag}: no durable_record — the local fix alone "
                            f"teaches the harness nothing")
            dr = []
        kinds = []
        for d in dr:
            if not isinstance(d, dict):
                problems.append(f"{tag}: durable_record entry is not an object")
                continue
            kind = d.get("kind")
            kinds.append(kind)
            if kind not in REMEDY_KINDS:
                problems.append(f"{tag}: kind {kind!r} not in {REMEDY_KINDS}")
            target = (d.get("target") or "").strip()
            if not target:
                problems.append(f"{tag}: durable_record {kind!r} has no target")
            if kind in ("tool", "tool_fix") and target:
                stem = Path(target).stem.lower()
                hit = [w for w in _OBJECT_WORDS if w in stem]
                if hit:
                    problems.append(f"{tag}: tool target {target!r} is named after "
                                    f"an object ({hit[0]}) — a tool may not be")
            if not (d.get("cites") or "").strip():
                warnings.append(f"{tag}: durable_record {kind!r} cites no run/step")
            elif not _exists(d.get("cites")):
                warnings.append(f"{tag}: durable_record {kind!r} cites "
                                f"{d.get('cites')!r}, which does not exist")

        # a skill changes what the agent CHOOSES; replaying the old action files
        # replays exactly the decision the skill was written to change
        if kinds and set(kinds) <= {"skill", "checklist"} and rebuild == "R1":
            problems.append(f"{tag}: remedy is skill-only but rebuild is R1 — a "
                            f"skill cannot be tested by R1, it needs R2 at least")

        if not (r.get("acceptance") or "").strip():
            problems.append(f"{tag}: no acceptance — nothing to judge the edit on")

    for gid in chosen:
        if gid not in by_group:
            problems.append(f"group {gid!r} is chosen but has no remedy")

    for gid in by_group:
        if gid in gids and gid not in chosen:
            warnings.append(f"remedy written for {gid!r}, which is not chosen")

    ungrouped = known_ids - set(seen_ids)
    if ungrouped:
        warnings.append(f"{len(ungrouped)} defect(s) never grouped: "
                        f"{sorted(x for x in ungrouped if x)[:6]}")

    for f in (f"{task_name}_attribution.md", f"{task_name}_remedy.md"):
        if not (report_dir / f).is_file():
            problems.append(f"{f} was not written")
        elif (report_dir / f).stat().st_size < 400:
            warnings.append(f"{f} is very short ({(report_dir / f).stat().st_size} B)")

    return problems, warnings


def _bash_command(call: dict) -> str:
    """The shell command string of a bash tool call (arguments are a JSON string)."""
    args = (call.get("function") or {}).get("arguments") or call.get("arguments") or call.get("input") or ""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            return args
    if isinstance(args, dict):
        return str(args.get("command") or "")
    return ""


def _bash_writes_into(cmd: str, needles: tuple[str, ...]) -> bool:
    """Does this shell command WRITE to a path containing one of `needles`?

    Only the TARGET of a write is judged: `grep -E '>.*Checker' log`,
    `2>/dev/null` and a heredoc with `x > 0` in it are reads and must not
    count (they did once, and cost a round). What counts: a redirection into
    the path, tee/sed -i/rm on it, cp/mv whose last argument is in it, and a
    Python write idiom in the same command as a literal of the path.
    """
    esc = "(?:" + "|".join(re.escape(n) for n in needles) + ")"
    tok = r"""["']?[^\s"'|;&<>]*""" + esc + r"""[^\s"'|;&<>]*["']?"""
    pats = [
        r"(?<![0-9<])>{1,2}\s*" + tok,                                   # > path, >> path (not 2>, not <<)
        r"\btee\b(?:\s+-\S+)*\s+" + tok,                                 # tee [-a] path
        r"\bsed\s+-i\S*(?:\s+(?:-e\s+)?'[^']*'|\s+\"[^\"]*\"|\s+-\S+)*\s+" + tok,   # sed -i ... path
        r"\brm\b(?:\s+-\S+)*(?:\s+\S+)*?\s+" + tok,                      # rm [...] path
        r"\b(?:cp|mv)\b(?:\s+-\S+)*(?:\s+\S+)+\s+" + tok + r"\s*(?:[;&|\n]|$)",   # cp/mv ... path (destination)
    ]
    if any(re.search(pt, cmd) for pt in pats):
        return True
    py_write = re.search(r"write_text\(|write_bytes\(|open\([^)]*,\s*['\"][wax]|shutil\.(?:copy\w*|move)\(|"
                         r"os\.(?:remove|unlink|rename|replace|makedirs|mkdir)\(|\.unlink\(|\.rename\(|\.mkdir\(", cmd)
    if not py_write:
        return False
    # only the literals handed to open()/Path()/shutil/os calls count as targets; a path that is
    # merely mentioned in written CONTENT (a lesson citing mem/<run>/...) is not a write into it
    targets = re.findall(r"(?:open|Path|copy\w*|move|remove|unlink|rename|replace|makedirs|mkdir)\(\s*r?['\"]([^'\"]*)['\"]", cmd)
    return any(re.search(esc, tgt) for tgt in targets)


# ── the worker view is the whole world ──────────────────────────────────────

VIEW_RULE = (
    "Your working folder is the whole repository as far as you are concerned. It may be a "
    "worker view (a folder named harness/wK inside the run folder): the folders above it "
    "are the shared main copy and the other worker's view, and writing there is forbidden "
    "and audited — it fails this step and your edits are discarded. Never `cd ..`, never "
    "use an absolute path to a folder above your working folder, never undo your own edits "
    "with git. Paths relative to the working folder are the only ones that count."
)


def view_escapes(result: dict) -> list[str]:
    """Tool calls that reach ABOVE the working folder when it is a worker view: an absolute
    path to the main run folder (in a write/edit, in a bash command, or inside a script the
    agent writes and runs), or a shell `cd ..` / `..\\..` climb, or a git checkout/stash/reset
    A main-folder path into a shared data junction (mem/, plans/, blends/, tasks/, Checker/reports/,
    Curator/reports/, vb/state/) is the same physical folder as the view's and does not count.
    that undoes edits in the view. Empty when the working folder is the main folder."""
    import viewpaths
    main = viewpaths.main_dir(ROOT)
    if Path(main) == Path(ROOT):
        return []
    spell = re.sub(r"[\\/]+", "/", str(main)).lower()
    climb = re.compile(r"(?:^|[;&|]\s*)cd\s+(?:/d\s+)?[\"']?\.\.(?:[\\/]|\s|$)|(?:^|[\s\"'=])\.\.[\\/]\.\.|git\s+(?:checkout|stash|reset|restore|clean)\b", re.I)
    hits: list[str] = []
    # A call the tool itself refused ("... is outside the project directory") touched nothing:
    # the sandbox already stopped it. Counting the attempt failed whole curations for one
    # probing `bash(cwd=<main folder>)` (shark round 1, sneaker round 2, 2026-09-12).
    refused = {str(m.get("tool_call_id")) for m in (result.get("messages") or [])
               if m.get("role") == "tool" and "is outside the project directory" in str(m.get("content") or "")}
    for m in result.get("messages") or []:
        for call in (m.get("tool_calls") or []):
            fn = ((call.get("function") or {}).get("name") or call.get("name") or "").lower()
            if fn not in ("write", "edit", "multi_edit", "notebook_edit", "bash"):
                continue
            if str(call.get("id") or call.get("call_id")) in refused or str(call.get("call_id")) in refused:
                continue
            blob = re.sub(r"[\\/]+", "/", json.dumps(call, default=str)).lower()
            if any(not re.match(r"/(?:harness/w\d|mem|plans|blends|tasks|snapshots|images|synth_views|checker/reports|curator/reports|vb/state)(?:/|\"|$)", blob[m.end():m.end() + 20])
                   for m in re.finditer(re.escape(spell), blob)):
                hits.append(f"{fn}: names the main folder — {(_bash_command(call) if fn == 'bash' else blob)[:300]}")
                continue
            if fn == "bash":
                cmd = _bash_command(call) or ""
                if climb.search(cmd):
                    hits.append(f"bash: climbs out of the view / undoes edits — {cmd[:160]}")
    return hits


def _write_calls(result: dict, needles: tuple[str, ...]) -> list[str]:
    """Tool calls that WRITE to any path matching one of `needles`.

    Read access is fine everywhere and expected — the curator's whole job is
    reading evidence. Only writes are policed: the write/edit tools with such
    a path, and shell commands whose write target is such a path
    (see _bash_writes_into).
    """
    write_tools = {"write", "edit", "multi_edit", "notebook_edit"}
    hits: list[str] = []
    for m in result.get("messages") or []:
        for call in (m.get("tool_calls") or []):
            fn = ((call.get("function") or {}).get("name")
                  or call.get("name") or "").lower()
            blob = json.dumps(call, default=str)
            if not any(n in blob for n in needles):
                continue
            if fn in write_tools:
                # judge the PATH the tool writes, not the content: a skill that cites
                # mem/<run>/... in its text is not a write into mem/
                args = (call.get("function") or {}).get("arguments") or call.get("arguments") or call.get("input") or ""
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                path = str((args or {}).get("path") or (args or {}).get("file_path") or (args or {}).get("filename") or "")
                if path and not any(n in path for n in needles):
                    continue
                hits.append(f"{fn}: {path or blob[:200]}")
            elif fn == "bash":
                cmd = _bash_command(call) or blob
                if _bash_writes_into(cmd, needles):
                    hits.append(f"bash (writes): {cmd[:200]}")
    return hits


# Folders keyed by task name and by run name: another task's entries there are off limits.
_TASK_KEYED = ("plans", "Curator/reports", "vb/state")
_RUN_KEYED = ("mem", "blends", "Checker/reports")


def other_task_writes(result: dict, task: str) -> list[str]:
    """Tool calls that WRITE into another task's folder: plans/<other>, Curator/reports/<other>,
    vb/state/<other>, or one of its runs under mem/, blends/, Checker/reports/.

    Two workers run side by side. On 2026-09-13 the robot's round-2 apply agent rewrote the
    turtle's applied.json through the shared Curator/reports. harness.sync now links only the
    view's own task into the task-keyed folders; the run-keyed ones stay shared, and this is
    their guard. Needles come in every spelling a path takes in a call: forward slashes, one
    backslash (a raw shell command), two and four (JSON-escaped once and twice)."""
    base = ROOT / "tasks" / "train"
    others = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name != task) if base.is_dir() else []
    needles: list[str] = []
    for t in others:
        rels = [f"{pre}/{t}" for pre in _TASK_KEYED] + [f"{pre}/{t}_run_" for pre in _RUN_KEYED]
        for rel in rels:
            needles += [rel, rel.replace("/", "\\"), rel.replace("/", "\\\\"),
                        rel.replace("/", "\\\\\\\\")]
    return _write_calls(result, tuple(needles)) if needles else []


def audit_checker_write(result: dict) -> list[str]:
    """Did the conversation write into Checker/ ?

    Version B §4: the checker "must stay outside whatever the remedy step is
    allowed to edit". If a remedy can touch the checker, the cheapest way to
    make FIXED? say yes is to weaken the check — the same concern that makes
    reviewer checklists add-only. Splitting Curator/ from Checker/ is what
    makes this checkable at all, so it is checked rather than assumed.
    """
    return (_write_calls(result, ("Checker/", "Checker\\"))
            + [f"(outside the worker view) {h}" for h in view_escapes(result)])


def audit_task_edit(result: dict, task_name: str, subject_name: str | None = None) -> list[str]:
    """Did the conversation write into blends/<task>/task/ ?

    The mirror of the checker's audit_plan_access(). The brief and the
    reference photograph are the ground truth for the whole method; a curator
    that can edit them can make any defect go away by redefining the target.
    Read access is fine and expected — this looks for writes only.
    """
    names = {task_name, subject_name or task_name}
    return _write_calls(result, tuple(n for s in names for n in
                                      (f"blends/{s}/task", "blends" + chr(92) + s + chr(92) + "task")))


# ── main ─────────────────────────────────────────────────────────────────────

def curate_task(task_name: str, *, run: str | None = None, force: bool = False,
                note: str = "", max_iterations: int = 90,
                retries: int = 1, out_dir: Path | None = None,
                defects: Path | None = None,
                subject_name: str | None = None) -> tuple[Path, list[str]]:
    subject_name = subject_name or task_name
    subject = find_subject(subject_name)
    run_dir = find_run(task_name, run)
    report_dir = out_dir or (REPORTS_DIR / task_name)

    defects_path = Path(defects) if defects else CHECKER_REPORTS / task_name / "defects.json"
    if not defects_path.is_file():
        raise SystemExit(
            f"no {defects_path} — run the checker first:\n"
            f"    python Checker/checker_agent.py --task {task_name}")

    if (report_dir / "curation.json").is_file() and not force:
        print(f"[curator] {report_dir}/curation.json exists — skipping "
              f"(use --force to redo)")
        return report_dir, []

    (report_dir / "curator_scripts").mkdir(parents=True, exist_ok=True)

    defects_md, defects = defects_digest(defects_path)
    task_md = subject / "task" / "task.md"
    description = task_md.read_text(encoding="utf-8", errors="replace").strip() \
        if task_md.is_file() else "(no task.md)"
    plan_files = sorted((subject / "plan").glob("*_plan.md"))
    plan_rel = (rel_to(plan_files[0], ROOT).as_posix() if plan_files
                else f"blends/{subject_name}/plan/ (no *_plan.md found)")

    core.load_api_keys()
    agent_env.ensure_plugin_env()              # also chdir()s to ROOT
    os.environ.setdefault("HERMES_API_CALL_STALE_TIMEOUT", STALE_TIMEOUT_S)

    intro = build_intro(
        task_name=task_name, run_dir=run_dir, description=description,
        defects_md=defects_md, build_md=build_digest(run_dir),
        skills_md=skills_index(), tools_md=current_tools(),
        report_dir=report_dir, plan_rel=plan_rel, n_defects=len(defects),
        subject_name=subject_name,
        defects_rel=rel_to(defects_path.resolve(), ROOT).as_posix(),
    )
    if note:
        intro = ("# Instruction for this run\n\n"
                 f"{note}\n\n"
                 "This overrides anything below it that it contradicts.\n\n"
                 "---\n\n" + intro)
        print(f"[curator] note: {note}")

    from run_agent import AIAgent
    from agent.image_routing import build_native_content_parts

    # The reference and the headline render, same as the checker. Everything
    # else — plan, action files, reviews, the other eleven views — the agent
    # opens on demand, because a first message stuffed with images never
    # returns inside the provider's time-to-first-byte window.
    attach = []
    ref = subject / "task" / "reference.png"
    if ref.is_file():
        attach.append(str(ref))
    final = subject / "views" / "final_render.png"
    if final.is_file():
        attach.append(str(final))
    first_message, _ = build_native_content_parts(intro, image_paths=attach)

    cfg = MODELS.get("curator") or MODELS["planner"]
    kwargs = dict(
        provider=cfg["provider"],
        model=cfg["model"],
        api_key=core.api_key_for(cfg["provider"]),
        base_url=core.base_url_for(cfg["provider"]),
        quiet_mode=False,
        max_iterations=max_iterations,
        ephemeral_system_prompt=SYSTEM_PROMPT,
        enabled_toolsets=agent_env.CURATOR_TOOLSETS,
    )
    if cfg["provider"] == "openai":
        kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}

    print(f"[curator] task={task_name}  run={run_dir.name}  "
          f"model={cfg['model']}  defects={len(defects)}")
    print(f"[curator] writing into {report_dir}")

    attempt = 0
    problems: list[str] = []
    warnings: list[str] = []
    message = first_message
    while True:
        t0 = time.time()
        result = AIAgent(**kwargs).run_conversation(message)
        wall = time.time() - t0
        print(f"[curator] finished in {wall:.0f}s")

        agent_env.check_tools(result, "curator")
        agent_env.record_usage(result, wall, report_dir / "curator_usage.json",
                               tag="Curator", extra={"task": task_name,
                                                     "run": run_dir.name})

        summary = (result.get("final_response") or "").strip()
        (report_dir / "curator_summary.md").write_text(summary or "(no response)",
                                                       encoding="utf-8")

        problems, warnings = check_curation(report_dir, task_name, defects)
        edits = audit_task_edit(result, task_name, subject_name)
        if edits:
            problems.append(f"the curator wrote into the task folder in "
                            f"{len(edits)} tool call(s) — the task is never "
                            f"edited and this run should be redone")
        ck_edits = audit_checker_write(result)
        if ck_edits:
            problems.append(f"the curator wrote into Checker/ in "
                            f"{len(ck_edits)} tool call(s) — the checker must "
                            f"stay outside what the remedy can edit")
        cross = other_task_writes(result, task_name)
        if cross:
            problems.append(f"the curator wrote into another task's folder in "
                            f"{len(cross)} tool call(s): {cross[0][:120]}")

        if warnings:
            print(f"[curator] {len(warnings)} warning(s):")
            for w in warnings[:8]:
                print("   ~", w)
        if not problems:
            print("[curator] curation.json is well formed")
            break

        print("[curator] PROBLEMS with curation.json:")
        for p in problems[:12]:
            print("   -", p)
        if edits:
            print("[curator] TASK EDIT VIOLATION:")
            for h in edits[:4]:
                print("   !", h)
        if ck_edits:
            print("[curator] CHECKER WRITE VIOLATION:")
            for h in ck_edits[:4]:
                print("   !", h)

        attempt += 1
        if attempt > retries:
            break
        print(f"[curator] retry {attempt}/{retries} — feeding the problems back")
        message = (
            "The curation you wrote does not validate. Fix these and rewrite "
            "the three files:\n\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nChange only what these problems name; everything else you "
              "concluded stands."
        )

    (report_dir / "curator_check.json").write_text(json.dumps(
        {"problems": problems, "warnings": warnings,
         "task_edit": audit_task_edit(result, task_name, subject_name),
         "checker_write": audit_checker_write(result)},
        indent=2), encoding="utf-8")

    try:
        data = json.loads((report_dir / "curation.json").read_text(encoding="utf-8"))
        gs = data.get("groups") or []
        ch = [g for g in gs if g.get("chosen")]
        hist: dict[str, int] = {}
        for g in gs:
            for a in (g.get("attribution") or []):
                hist[a.get("class")] = hist.get(a.get("class"), 0) + 1
        print(f"[curator] {len(gs)} group(s) over {len(defects)} defect(s), "
              f"{len(ch)} chosen")
        print(f"[curator] attribution histogram: "
              f"{', '.join(f'{k}={v}' for k, v in sorted(hist.items()))}")
        for r in (data.get("remedies") or []):
            print(f"[curator]   {r.get('group_id')}: case {r.get('case')}, "
                  f"rebuild {r.get('rebuild')}")
    except Exception:
        pass

    return report_dir, problems


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Attribute one task's defects to the harness and pick the remedies.")
    ap.add_argument("--task", required=True,
                    help="task folder under blends/, e.g. 11_umbrella")
    ap.add_argument("--run", default=None,
                    help="mem/ run folder (default: latest <task>_run_*)")
    ap.add_argument("--force", action="store_true",
                    help="re-curate even if curation.json exists")
    ap.add_argument("--note", default="", help="extra instruction for this run")
    ap.add_argument("--retries", type=int, default=1,
                    help="re-attempts if curation.json comes back malformed")
    ap.add_argument("--max-iterations", type=int, default=90)
    ap.add_argument("--out", default=None,
                    help="report folder (default: Curator/reports/<task>); Version B "
                         "uses Curator/reports/<task>/round_NN")
    ap.add_argument("--subject", default=None,
                    help="folder under blends/ holding the judged model (default: the task; "
                         "a run name when curating a rebuilt model)")
    ap.add_argument("--defects", default=None,
                    help="defects.json to curate from (default: Checker/reports/<task>/)")
    args = ap.parse_args()

    report_dir, problems = curate_task(
        args.task, run=args.run, force=args.force, note=args.note,
        max_iterations=args.max_iterations, retries=args.retries,
        out_dir=Path(args.out).resolve() if args.out else None,
        defects=Path(args.defects).resolve() if args.defects else None,
        subject_name=args.subject)
    print(f"\n[curator] report: {report_dir}")
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
