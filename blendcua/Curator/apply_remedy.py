#!/usr/bin/env python3
"""The REMEDY step of Version B: carry out what the curator decided.

    python Curator/apply_remedy.py --task 11_umbrella \\
        --curation Curator/reports/11_umbrella/round_01/curation.json \\
        --out Curator/reports/11_umbrella/round_01/apply [--run 11_umbrella_run_002]

The curator (curator_agent.py) groups, attributes and chooses; it writes
nothing into the harness. This agent makes the edits: the LOCAL FIX that
makes this build right (a corrected plan, or corrected action files for an
R1 replay) and the DURABLE RECORD that makes the next build better (a skill,
a tool with its skill trigger and index entry). Version B section 6: the two
go together, and the task is never edited.

What it writes is audited, not trusted. After the conversation the store is
diffed against the state it started in and every rule the spec fixes is
checked in code:

  * the task brief and reference photograph are untouched
  * nothing under Checker/ is written (the checker stays outside the remedy)
  * reviewer skills are ADD-ONLY: every line that was there is still there
  * other skills are extended, not gutted (no dropped sections, no shrink)
  * tool edits are additive (no removed public names, no rewrites), new
    tools parse, are registered in the tool index, are named after a motif
    rather than an object, and are mentioned by a skill
  * plan edits stay inside plans/<task>/, keep the ref-image header, still
    parse into steps, and keep every existing review check verbatim
  * action-file edits stay inside mem/<run>/steps/ and only for an R1 remedy

Problems are fed back and the agent gets to fix them; if they remain, the
driver reverts the store from its snapshot.

Output (in --out):
    applied.json        per remedy: files changed, notes, expected objects
    apply_summary.md    the agent's closing message
    apply_check.json    guard results
    apply_usage.json    cost
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[1])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CURATOR_DIR = Path(__file__).resolve().parent
ROOT = CURATOR_DIR.parent
LEDGER = ROOT / "tasks" / "PROGRESS.csv"   # run_v2.py's ledger: not part of the task
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vb"))

import agent_env                                          # noqa: E402
import blendcua_core as core                              # noqa: E402
from models import MODELS, OPENAI_REASONING_EFFORT        # noqa: E402
from curator_agent import VIEW_RULE, view_escapes  # noqa: E402  (the view is the whole world)
import common as C                                        # noqa: E402

STALE_TIMEOUT_S = "900"
MAX_DELETE_RATIO = 0.25

_OBJECT_WORDS: tuple[str, ...] = (
    "umbrella", "chair", "skull", "shark", "hammer", "lantern", "hourglass",
    "chess", "domino", "sneaker", "monstera", "datestone", "can", "gate",
    "tablecloth", "thinker", "dog", "box", "glass", "anglepoise", "thor",
    "canopy", "mjolnir",
)

ALLOWED_PREFIXES = ("Skills/", "Tool_scripts/Tools_code/", "Tool_scripts/Tools_ref/",
                    "prompt_files/")


# ── state before ─────────────────────────────────────────────────────────────

def _h(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return ""


def protected_hashes(task: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for base in (ROOT / "tasks", ROOT / "blends" / task / "task"):
        if base.is_dir():
            for p in base.rglob("*"):
                # the ledger is the driver's own file, rewritten after every stage of every
                # worker: another task moving on must not fail this task's apply check
                if p.is_file() and p != LEDGER:
                    out[str(rel_to(p, ROOT)).replace("\\", "/")] = _h(p)
    for p in (ROOT / "Checker").glob("*.py"):
        out[str(rel_to(p, ROOT)).replace("\\", "/")] = _h(p)
    for name in ("defects.json", "verdict.json"):
        p = ROOT / "Checker" / "reports" / task / name
        if p.is_file():
            out[str(rel_to(p, ROOT)).replace("\\", "/")] = _h(p)
    return out


def skills_text() -> dict[str, str]:
    return {str(rel_to(p, ROOT)).replace("\\", "/"): p.read_text(encoding="utf-8", errors="replace")
            for p in (ROOT / "Skills").rglob("*.md")}


def tools_text() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8", errors="replace")
            for p in (ROOT / "Tool_scripts" / "Tools_code").glob("*.py")}


# ── guards ───────────────────────────────────────────────────────────────────

def check_protected(before: dict[str, str]) -> list[str]:
    out = []
    for rel, old in before.items():
        p = ROOT / rel
        if not p.is_file():
            out.append(f"{rel} was DELETED — protected file")
        elif _h(p) != old:
            what = "the task" if rel.startswith(("tasks/", "blends/")) else "the checker"
            out.append(f"{rel} was edited — {what} must not change")
    return out


def check_reviewer_skills(before: dict[str, str]) -> list[str]:
    """Add-only: every non-blank line that existed still exists, no shrink."""
    out = []
    for rel, old in before.items():
        if not rel.startswith("Skills/Reviewer/"):
            continue
        p = ROOT / rel
        if not p.is_file():
            out.append(f"{rel} was DELETED — reviewer skills are add-only")
            continue
        new = p.read_text(encoding="utf-8", errors="replace")
        if new == old:
            continue
        old_lines = [l.rstrip() for l in old.splitlines() if l.strip()]
        new_lines = [l.rstrip() for l in new.splitlines() if l.strip()]
        missing = [l for l in old_lines if l not in new_lines]
        if missing:
            out.append(f"{rel}: {len(missing)} existing line(s) removed or reworded — "
                       f"a reviewer check may be added but never deleted or "
                       f"shortened. First: {missing[0][:90]!r}")
        if len(new) < len(old):
            out.append(f"{rel} shrank from {len(old)} to {len(new)} chars — reviewer "
                       f"skills only grow")
    return out


def check_other_skills(before: dict[str, str]) -> list[str]:
    out = []
    heads = lambda t: [l.strip() for l in t.splitlines() if l.startswith("## ")]
    for rel, old in before.items():
        if rel.startswith("Skills/Reviewer/"):
            continue
        p = ROOT / rel
        if not p.is_file():
            out.append(f"{rel} was DELETED — a remedy extends skills, it does not remove them")
            continue
        new = p.read_text(encoding="utf-8", errors="replace")
        if new == old:
            continue
        lost = [h for h in heads(old) if h not in heads(new)]
        if lost:
            out.append(f"{rel} drops {len(lost)} section(s): {'; '.join(lost[:3])} — "
                       f"extend a skill, do not rewrite it")
        if len(new) < 0.66 * len(old):
            out.append(f"{rel} shrank from {len(old)} to {len(new)} chars — that is a "
                       f"rewrite, not an extension")
    return out


def _frontmatter_ok(text: str) -> bool:
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    fm = text[3:end]
    return "name:" in fm and "description:" in fm


def check_new_skills(before: dict[str, str]) -> list[str]:
    out = []
    for p in (ROOT / "Skills").rglob("*.md"):
        rel = str(rel_to(p, ROOT)).replace("\\", "/")
        if rel in before or p.name == "README.md":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if not _frontmatter_ok(text):
            out.append(f"{rel}: new skill needs frontmatter with `name:` and "
                       f"`description:` (the trigger line the index shows)")
        if p.parent.name not in ("Planner", "Executor", "Reviewer", "Feedback", "Scripting"):
            out.append(f"{rel}: skills live under Skills/<Role>/ for a named consumer")
        if "evidence" not in text.lower() and "mem/" not in text:
            out.append(f"{rel}: a skill must cite the run and step that taught it "
                       f"(an `evidence:` frontmatter line or a mem/<run>/... path)")
    return out


def _defs(src: str) -> set[str]:
    try:
        return {n.name for n in ast.parse(src).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    except SyntaxError:
        return set()


_PROPER_OBJECT_WORDS = ("umbrella", "chair", "skull", "shark", "hammer", "lantern",
                        "hourglass", "chess", "domino", "sneaker", "monstera",
                        "datestone", "tablecloth", "thinker", "anglepoise", "thor",
                        "mjolnir", "canopy", "stonehead", "pommel", "rook", "pawn")


def _object_words_in_source(src: str) -> set[str]:
    """Object names inside a tool's STRING LITERALS (prompts, filenames,
    defaults). Comments and docstrings may cite the run that motivated the
    tool; code that only works for one object may not."""
    found: set[str] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            # skip docstrings: a module/function docstring is the first
            # statement's value; ast.get_docstring handles the common cases
            for w in _PROPER_OBJECT_WORDS:
                if w in low:
                    found.add(w)
    docs = " ".join(filter(None, [ast.get_docstring(tree) or ""] + [
        ast.get_docstring(n) or "" for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))])).lower()
    # words that appear ONLY in docstrings are citations, not baked behaviour
    literal_only = set()
    for w in found:
        n_doc = docs.count(w)
        n_all = src.lower().count(w)
        if n_all > n_doc:
            literal_only.add(w)
    return literal_only


def check_tools(before: dict[str, str]) -> list[str]:
    out = []
    tools_dir = ROOT / "Tool_scripts" / "Tools_code"
    index = ROOT / "Tool_scripts" / "Tools_ref" / "INDEX.md"
    index_txt = index.read_text(encoding="utf-8", errors="replace") if index.is_file() else ""
    ctools = ROOT / "prompt_files" / "current_tools.md"
    ctools_txt = ctools.read_text(encoding="utf-8", errors="replace") if ctools.is_file() else ""
    skills_all = "\n".join(skills_text().values())
    for p in tools_dir.glob("*.py"):
        stem = p.stem
        new = p.read_text(encoding="utf-8", errors="replace")
        if stem in before:
            old = before[stem]
            if new == old:
                continue
            try:
                ast.parse(new)
            except SyntaxError as e:
                out.append(f"Tools_code/{stem}.py does not parse: {e}")
                continue
            lost = _defs(old) - _defs(new)
            if lost:
                out.append(f"Tools_code/{stem}.py REMOVES public name(s) "
                           f"{sorted(lost)} — tool edits are additive")
            a, b = old.splitlines(), new.splitlines()
            diff = list(difflib.unified_diff(a, b, lineterm="", n=0))
            added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
            if removed > max(4, MAX_DELETE_RATIO * max(added, 1)):
                out.append(f"Tools_code/{stem}.py deletes {removed} lines against {added} "
                           f"added — a rewrite, not an extension; add a function or an "
                           f"optional parameter instead")
        else:
            try:
                ast.parse(new)
            except SyntaxError as e:
                out.append(f"new tool Tools_code/{stem}.py does not parse: {e}")
                continue
            hit = [w for w in _OBJECT_WORDS if w in stem.lower()]
            if hit:
                out.append(f"new tool {stem}.py is named after an object ({hit[0]}) — "
                           f"name the motif, not the thing that occasioned it")
            if stem not in index_txt or stem not in ctools_txt:
                out.append(f"new tool {stem}.py is not registered — run "
                           f"`python Tool_scripts/gen_tool_index.py` so it appears in "
                           f"Tools_ref/INDEX.md and prompt_files/current_tools.md")
            if stem not in skills_all:
                out.append(f"new tool {stem}.py has no trigger — no skill says when to "
                           f"reach for it, so it will not be used")
            if '"""' not in new[:2000]:
                out.append(f"new tool {stem}.py has no module docstring")
            baked = _object_words_in_source(new)
            if baked:
                out.append(f"new tool {stem}.py has the object baked into its code "
                           f"({', '.join(sorted(baked)[:4])} appear in its string "
                           f"literals) — a tool is written at the level of the motif; "
                           f"the object's description must come in as a parameter")
    for stem in before:
        if not (tools_dir / f"{stem}.py").is_file():
            out.append(f"Tools_code/{stem}.py was DELETED — never remove a tool")
    return out


def check_plan(task: str, old_text: str | None, old_steps: list[dict]) -> list[str]:
    out = []
    mds = sorted((ROOT / "plans" / task).glob("*.md"))
    if not mds:
        return [f"plans/{task}/ has no plan .md any more"]
    if len(mds) > 1:
        out.append(f"plans/{task}/ now holds {len(mds)} .md files: {[m.name for m in mds]} — "
                   f"the builder needs exactly one")
    new_text = mds[0].read_text(encoding="utf-8", errors="replace")
    if old_text is not None and new_text == old_text:
        return out
    if not re.search(r"<!--\s*ref-image:\s*(.+?)\s*-->", new_text[:2000]):
        out.append("the plan lost its `<!-- ref-image: ... -->` header line")
    try:
        new_steps = core.parse_plan(new_text)
    except Exception as exc:
        return out + [f"the plan no longer parses: {exc}"]
    if not new_steps:
        return out + ["the plan parses to ZERO steps — headings must be `## Step N — title`"]
    old_by = {s["step_number"]: s for s in old_steps}
    new_by = {s["step_number"]: s for s in new_steps}
    for n, s in old_by.items():
        if n not in new_by:
            out.append(f"step {n} disappeared from the plan")
            continue
        new_checks = [c.strip() for c in new_by[n]["review_checks"]]
        for c in s["review_checks"]:
            if c.strip() not in new_checks:
                out.append(f"step {n}: review check removed or reworded — checks are "
                           f"add-only, keep the old line and add a new one: "
                           f"{c.strip()[:90]!r}")
    return out


def check_scope(changes: dict[str, list[str]], task: str, run: str | None,
                allow_actions: bool, out_rel: str) -> list[str]:
    out = []
    for kind in ("modified", "created", "deleted"):
        for rel in changes[kind]:
            if rel.startswith(out_rel):
                continue
            if rel.startswith(ALLOWED_PREFIXES) or rel.startswith(f"plans/{task}/"):
                continue
            if run and rel.startswith(f"mem/{run}/steps/"):
                if allow_actions:
                    continue
                out.append(f"{rel} {kind} — action files may only be edited for an "
                           f"R1 remedy, and none of the chosen remedies is R1")
                continue
            out.append(f"{rel} {kind} — outside the store a remedy may change "
                       f"(Skills/, Tools_code/, prompt_files/, plans/{task}/"
                       f"{', mem/<run>/steps/' if allow_actions else ''})")
    return out


def _write_calls(result: dict, needles: tuple[str, ...]) -> list[str]:
    write_tools = {"write", "edit", "multi_edit", "notebook_edit"}
    hits: list[str] = []
    for m in result.get("messages") or []:
        for call in (m.get("tool_calls") or []):
            fn = ((call.get("function") or {}).get("name") or call.get("name") or "").lower()
            blob = json.dumps(call, default=str)
            if not any(n in blob for n in needles):
                continue
            if fn in write_tools:
                hits.append(f"{fn}: {blob[:200]}")
            elif fn == "bash":
                # same target-aware test as the curator: only a write whose
                # TARGET is in the path counts, not a grep pattern or 2>/dev/null
                from curator_agent import _bash_command, _bash_writes_into
                cmd = _bash_command(call) or blob
                if _bash_writes_into(cmd, needles):
                    hits.append(f"bash (writes): {cmd[:200]}")
    return hits


# ── prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the remedy step of a Blender build harness. A curator has decided "
    "which defects to act on, who is at fault and what to change. You carry "
    "those decisions out: you edit the plan or the action files so that THIS "
    "build comes out right, and you write the skill or build the tool that "
    "makes the NEXT build better. You have a shell and file access. You never "
    "edit the task brief or the reference photograph, never write into the "
    "checker, never weaken a reviewer check, and never rewrite an existing "
    "tool. When you finish you write applied.json listing exactly which files "
    "belong to which remedy, and stop."
)


def _chosen(curation: dict) -> tuple[list[dict], list[dict]]:
    groups = {g.get("group_id"): g for g in curation.get("groups") or []}
    chosen = [g for g in curation.get("groups") or [] if g.get("chosen")]
    remedies = [r for r in curation.get("remedies") or [] if r.get("group_id") in
                {g.get("group_id") for g in chosen}]
    return chosen, remedies


def build_intro(*, task: str, curation: dict, curation_rel: str, remedy_md: str,
                run: str | None, base_run: str, out_rel: str, plan_rel: str,
                allow_actions: bool, widest: str, prior_note: str) -> str:
    chosen, remedies = _chosen(curation)
    rem_json = json.dumps({"groups": chosen, "remedies": remedies}, indent=2)
    skills_idx = core.load_skills_index("Planner", "Executor", "Reviewer", "Scripting")
    run_block = (
        f"The R1 replay will run the action files under `mem/{run}/steps/` — a "
        f"relocated copy of `mem/{base_run}` made for you. **Edit the copy, never "
        f"the original run.** Keep the file names; an action selects geometry by "
        f"position or landmark, never by hard-coded index, because face ordering "
        f"does not replay. If your correction to action N changes what later "
        f"actions should do, say so in `applied.json` (`ripples: true`) — the "
        f"driver then escalates to R2 instead of replaying stale actions."
        if allow_actions else
        f"No chosen remedy is R1, so **do not edit any action file**. The rebuild "
        f"path is {widest}: the executor (and for R3 the planner) run again from "
        f"the plan under the new harness."
    )
    prior = f"\n## From the previous round\n\n{prior_note}\n" if prior_note else ""
    return f"""\
# Remedy — task `{task}`

## Your job

The curator has chosen {len(chosen)} group(s) of defects to act on and written
a remedy for each. Carry them out, exactly as decided, in two parts each:

1. **The local fix** — the change that makes THIS build come out right.
2. **The durable record** — the change that makes the NEXT build better.

The second is not optional. A corrected plan with no skill behind it teaches
the harness nothing; a skill with no local fix cannot be tested.

Then write `{out_rel}/applied.json` (format below) and stop. You do not
rebuild, you do not run the checker, you do not decide whether it worked.

{VIEW_RULE}
{prior}
## What the curator decided

```json
{rem_json}
```

The curator's own write-up of the same remedies, which says how to execute
them:

---

{remedy_md}

---

The full curation is at `{curation_rel}`; the unchosen groups in it are logged
and are not yours to act on.

## Where things actually live

| what | path | notes |
|---|---|---|
| **the plan the builder reads** | `{plan_rel}` | **this is the file a plan fix lands in.** `blends/{task}/plan/` is a read-only copy for the checker; editing it changes nothing |
| the plan's assets | `plans/{task}/` (landmarks JSON, scripts/) | |
| the action files | `mem/{base_run}/steps/step_NNN/NN_*.py` | the original build; read freely |
| skills | `Skills/<Planner|Executor|Reviewer|Scripting>/*.md` | frontmatter `name:`, `description:` (the trigger), `evidence:` |
| tools | `Tool_scripts/Tools_code/<module>.py` | see `Tool_scripts/Tools_code/TOOL_AUTHORING.md` |
| tool index | `Tool_scripts/Tools_ref/INDEX.md`, `prompt_files/current_tools.md` | regenerated by `python Tool_scripts/gen_tool_index.py` |
| the renders | `blends/{task}/views/` | the twelve the checker judged |
| the reference | `blends/{task}/task/reference.png` | read-only |

{run_block}

## Rules enforced in code after you finish

1. **The task is never edited** — nothing under `tasks/` or `blends/{task}/task/`.
2. **Nothing under `Checker/` is written.** The checker stays outside what a
   remedy can touch, otherwise the cheapest way to pass the re-check is to
   weaken it.
3. **Reviewer skills (`Skills/Reviewer/*.md`) are add-only.** Every line that
   is there stays there, word for word; you append. The same holds for the
   review checklists in the plan: keep every existing check line verbatim and
   add new ones after it. Never reword or delete a check.
4. **Other skills are extended, not rewritten.** Add a section; do not drop
   sections or shrink the file. A new skill goes under the right role folder
   with frontmatter (`name`, `description` as the one-line trigger, `evidence`
   citing `mem/<run>/steps/step_NNN`) and cites the run and step that taught it.
5. **Tool edits are additive.** Add a function or an optional parameter; never
   remove a public name and never rewrite a module — existing action files
   import them. A new tool must parse, carry a module docstring, be named after
   the motif rather than the object (`fit_into_recess.py`, not `hammer_head.py`),
   be registered by running `python Tool_scripts/gen_tool_index.py`, and be
   named in a skill that says when to reach for it. A tool nobody knows about
   is not an addition to the harness.
6. **The plan keeps its shape.** First line stays `<!-- ref-image: ... -->`;
   headings stay `## Step N — title`; it must still parse (`python -c
   "import blendcua_core as c, pathlib; print(len(c.parse_plan(pathlib.Path('{plan_rel}').read_text(encoding='utf-8'))))"`).
7. **Scope.** You may write only under `Skills/`, `Tool_scripts/Tools_code/`,
   `Tool_scripts/Tools_ref/`, `prompt_files/`, `plans/{task}/`,
   {f'`mem/{run}/steps/`, ' if allow_actions else ''}and `{out_rel}/`.

## Notes on particular remedy kinds

- **A view-generation remedy** (the fault class `views`: the planner worked
  from a single oblique photograph and never had the straight-on view that
  would have shown the structure). The capability to synthesise such views
  with `gpt-image-2` already exists as a prototype in
  `Tool_scripts/generate_views_gpt_image.py`, with the prompting lessons in
  `Skills/Planner/Gpt_images/prompting-reference-plates.md` and worked results under
  `BlendCuaLoop1/Image_test/hammer_trial/`. A proper tool for the planner is a script under
  `Tool_scripts/` (say `Tool_scripts/synth_views.py`) that takes a task name,
  the views wanted and a short positive description of the object's
  structure, writes the plates into `plans/<task>/scripts/`, and records the
  prompts in a manifest; plus a Planner skill that says when to run it and how
  to word the prompt (state only what the reference shows; say positively
  which way a feature runs; verify a prep plate before deriving from it). The
  key is read by `blendcua_core.load_api_keys()`; never print or copy it.
- **A plan fix** is an edit to `{plan_rel}` — measured numbers, a named
  constraint, an unambiguous sentence — never a rewrite of the whole document.
- **A tool fix or new tool** can be tried against Blender before you commit it:
  `python Tool_scripts/run.py --file <script>` dispatches a script to the live
  session and waits; `python blender_health.py --probe` tells you whether the
  server is up. Only if it is up — do not sit waiting for it.

## Skills that already exist (extend one of these before creating a new one)

{skills_idx}

## Your output

Write `{out_rel}/applied.json`:

```json
{{
  "task": "{task}",
  "run": {json.dumps(run)},
  "remedies": [
    {{
      "group_id": "the curator's group_id",
      "local_fix": {{"files": ["plans/{task}/{task}_plan.md"], "what": "one sentence"}},
      "durable_record": {{"files": ["Skills/Planner/foo.md"], "what": "one sentence"}},
      "ripples": false,
      "expected_changed_objects": ["Rib_00", "…"],
      "notes": "anything the accept step should know"
    }}
  ],
  "notes": "overall"
}}
```

`files` are repo-relative paths, every file you created or changed, each
listed under exactly one remedy (a shared file such as a reviewer skill both
remedies extend goes under the first and is noted in the second). `ripples`
matters only for R1. `expected_changed_objects` (R1 only) names the Blender
objects whose geometry the correction is expected to change; the hash rule
fails the remedy if anything else moves.

Finish with a short summary of what you changed and why, per remedy.
"""


# ── main ─────────────────────────────────────────────────────────────────────

def apply(task: str, curation_path: Path, out_dir: Path, *, run: str | None,
          base_run: str | None, retries: int = 2, max_iterations: int = 80,
          prior_note: str = "") -> tuple[dict, list[str]]:
    curation = json.loads(curation_path.read_text(encoding="utf-8"))
    chosen, remedies = _chosen(curation)
    if not remedies:
        raise SystemExit("[remedy] curation.json has no remedy for a chosen group")
    base_run = base_run or curation.get("run") or ""
    paths = {"none": 0, "R1": 1, "R2": 2, "R3": 3}
    widest = max((r.get("rebuild") or "none" for r in remedies), key=lambda p: paths.get(p, 0))
    allow_actions = any(r.get("rebuild") == "R1" for r in remedies) and bool(run)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_rel = rel_to(out_dir, ROOT).as_posix()
    plan_p = C.plan_path(task)
    plan_rel = rel_to(plan_p, ROOT).as_posix()
    remedy_md_p = curation_path.parent / f"{task}_remedy.md"
    remedy_md = remedy_md_p.read_text(encoding="utf-8", errors="replace") \
        if remedy_md_p.is_file() else "(no remedy write-up on disk)"

    extra = [f"mem/{run}/steps"] if run else []
    manifest_before = C.store_manifest(task, extra_dirs=extra)
    protected = protected_hashes(task)
    skills_before = skills_text()
    tools_before = tools_text()
    plan_before = plan_p.read_text(encoding="utf-8", errors="replace")
    steps_before = core.parse_plan(plan_before)

    core.load_api_keys()
    agent_env.ensure_plugin_env()
    os.environ.setdefault("HERMES_API_CALL_STALE_TIMEOUT", STALE_TIMEOUT_S)
    from run_agent import AIAgent

    intro = build_intro(task=task, curation=curation,
                        curation_rel=rel_to(curation_path, ROOT).as_posix(),
                        remedy_md=remedy_md, run=run, base_run=base_run, out_rel=out_rel,
                        plan_rel=plan_rel, allow_actions=allow_actions, widest=widest,
                        prior_note=prior_note)
    (out_dir / "prompt.md").write_text(intro, encoding="utf-8")

    cfg = MODELS.get("curator") or MODELS["planner"]
    kwargs = dict(provider=cfg["provider"], model=cfg["model"],
                  api_key=core.api_key_for(cfg["provider"]),
                  base_url=core.base_url_for(cfg["provider"]),
                  quiet_mode=False, max_iterations=max_iterations,
                  ephemeral_system_prompt=SYSTEM_PROMPT,
                  enabled_toolsets=agent_env.CURATOR_TOOLSETS)
    if cfg["provider"] == "openai":
        kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}

    print(f"[remedy] task={task} remedies={[r.get('group_id') for r in remedies]} "
          f"widest={widest} run={run} model={cfg['model']}")
    message = intro
    attempt = 0
    problems: list[str] = []
    while True:
        t0 = time.time()
        result = AIAgent(**kwargs).run_conversation(message)
        wall = time.time() - t0
        print(f"[remedy] finished in {wall:.0f}s")
        agent_env.check_tools(result, "remedy")
        agent_env.record_usage(result, wall, out_dir / "apply_usage.json",
                               tag="Remedy", extra={"task": task, "attempt": attempt})
        (out_dir / "apply_summary.md").write_text(
            (result.get("final_response") or "").strip() or "(no response)", encoding="utf-8")

        changes = C.changed_since(manifest_before, task, extra_dirs=extra)
        problems = []
        problems += check_protected(protected)
        problems += [f"tool call wrote into the task folder: {h}"
                     for h in _write_calls(result, ("tasks/", "tasks\\", f"blends/{task}/task",
                                                    f"blends\\{task}\\task"))]
        problems += [f"tool call wrote into Checker/: {h}"
                     for h in _write_calls(result, ("Checker/", "Checker\\"))]
        from curator_agent import other_task_writes
        problems += [f"tool call wrote into another task's folder: {h}"
                     for h in other_task_writes(result, task)]
        from curator_agent import view_escapes
        problems += [f"tool call reached outside the worker view: {h}" for h in view_escapes(result)]
        problems += check_reviewer_skills(skills_before)
        problems += check_other_skills(skills_before)
        problems += check_new_skills(skills_before)
        problems += check_tools(tools_before)
        problems += check_plan(task, plan_before, steps_before)
        problems += check_scope(changes, task, run, allow_actions, out_rel)

        applied_p = out_dir / "applied.json"
        applied = C.read_json(applied_p)
        if not isinstance(applied, dict) or not isinstance(applied.get("remedies"), list):
            problems.append(f"{out_rel}/applied.json missing or malformed")
            applied = {"remedies": []}
        else:
            claimed: set[str] = set()
            gids = {r.get("group_id") for r in remedies}
            for r in applied["remedies"]:
                if r.get("group_id") not in gids:
                    problems.append(f"applied.json names group {r.get('group_id')!r}, "
                                    f"which is not a chosen group")
                for part in ("local_fix", "durable_record"):
                    for f in ((r.get(part) or {}).get("files") or []):
                        claimed.add(str(f).replace("\\", "/"))
                if not ((r.get("durable_record") or {}).get("files")):
                    problems.append(f"applied.json: remedy {r.get('group_id')} has no "
                                    f"durable_record files — the local fix alone teaches "
                                    f"the harness nothing")
            touched = set(changes["modified"]) | set(changes["created"])
            touched = {t for t in touched if not t.startswith(out_rel)}
            unclaimed = sorted(touched - claimed)
            if unclaimed:
                problems.append(f"files changed but not listed under any remedy in "
                                f"applied.json: {unclaimed[:8]}")
            missing = sorted(f for f in claimed if not (ROOT / f).exists())
            if missing:
                problems.append(f"applied.json lists files that do not exist: {missing[:8]}")

        C.write_json(out_dir / "apply_check.json", {
            "attempt": attempt, "problems": problems, "changes": changes,
            "widest": widest, "allow_actions": allow_actions})
        if not problems:
            print("[remedy] guards passed")
            break
        print(f"[remedy] {len(problems)} problem(s):")
        for p in problems[:15]:
            print("   -", p)
        attempt += 1
        if attempt > retries:
            print(f"[remedy] giving up after {retries} retry(ies)")
            break
        message = ("The edits you made do not pass the harness rules. Fix exactly these "
                   "and rewrite applied.json; everything else stands:\n\n"
                   + "\n".join(f"- {p}" for p in problems)
                   + "\n\nRemember: reviewer checks and plan review checks are add-only "
                     "(restore any line you changed, then add yours after it); tool "
                     "edits are additive; every changed file must be listed under a "
                     "remedy in applied.json.")
    applied["changes"] = changes
    applied["widest"] = widest
    applied["problems"] = problems
    C.write_json(out_dir / "applied.json", applied)
    return applied, problems


def main() -> None:
    ap = argparse.ArgumentParser(description="Carry out the curator's chosen remedies.")
    ap.add_argument("--task", required=True)
    ap.add_argument("--curation", required=True, help="path to curation.json")
    ap.add_argument("--out", required=True, help="folder for applied.json etc.")
    ap.add_argument("--run", default=None,
                    help="the NEW run folder whose action files an R1 remedy may edit")
    ap.add_argument("--base-run", default=None)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--max-iterations", type=int, default=80)
    ap.add_argument("--prior-note", default="")
    a = ap.parse_args()
    _, problems = apply(a.task, Path(a.curation).resolve(), Path(a.out).resolve(),
                        run=a.run, base_run=a.base_run, retries=a.retries,
                        max_iterations=a.max_iterations, prior_note=a.prior_note)
    raise SystemExit(2 if problems else 0)


if __name__ == "__main__":
    main()
