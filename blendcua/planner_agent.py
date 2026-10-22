"""Planner — turns a task (a photo and a sentence) into a build plan.

    python planner_agent.py --task 01_pallet_stack

Reads  tasks/<split>/<Task>/   reference image + task.md
Writes plans/<Task>/           <Task>_plan.md, the reference image, scripts/

The plan folder is the same shape blendcua_agent.py already consumes, so the
build step needs no changes:

    plans/<Task>/
        <Task>_plan.md      first line: <!-- ref-image: <file in this folder> -->
        <reference image>   copied in, so the folder is self-contained
        scripts/            the planner's own measurement scripts and any
                            intermediate images they produce
        marked_<task>.json  landmarks, if the planner measured any
        marked_<task>.jpg

Two stages in one conversation. The planner first *measures* — it writes short
Python into scripts/ and runs it with bash to get real numbers off the
photograph — and then *writes* the plan around those numbers. The measuring is
the half with no existing support, which is why the prompt spends most of its
words there.

The exemplar plans it imitates are listed in plans/EXEMPLARS.txt. run_v2.py
appends a task to that file after its run passes, so plans that worked become
examples for later ones and plans that failed do not.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

# The digest and the plans are full of arrows and em-dashes, and this runs on a
# Windows console defaulting to cp1252 — an unguarded print() of that text raises
# UnicodeEncodeError and kills the process. It killed the first real curator run
# after the digest was built but before the agent started. Same guard tool_help.py
# and win_blender_server.py already use.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import agent_env
import blendcua_core as core
from models import MODELS, OPENAI_REASONING_EFFORT

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
PLANS_DIR = ROOT / "plans"
SKILLS_DIR = ROOT / "Skills"
EXEMPLAR_LIST = PLANS_DIR / "EXEMPLARS.txt"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_EXEMPLARS = ["Bat", "Chilli_plant", "Duck", "Gravestone", "Pillar"]
MAX_EXEMPLARS = 5          # they are one line each now, so list them all

# hermes aborts a non-streaming call that produces no first byte within this
# many seconds (its own default is 90, raised to 240 for reasoning models).
# The planner's first turn is a long one — a big image plus a reasoning budget
# at max — and it timed out three times at 240s before this was set.
STALE_TIMEOUT_S = "900"


# ── locating the task ────────────────────────────────────────────────────────

def find_task(name: str) -> Path:
    """tasks/train/<name> or tasks/test/<name>, whichever exists."""
    hits = [p for p in TASKS_DIR.glob(f"*/{name}") if p.is_dir()]
    if not hits:
        raise SystemExit(
            f"[planner] no task folder called {name!r} under {TASKS_DIR}.\n"
            f"           expected tasks/train/{name}/ or tasks/test/{name}/"
        )
    if len(hits) > 1:
        raise SystemExit(f"[planner] {name!r} exists in more than one split: {hits}")
    return hits[0]


def task_assets(task_dir: Path) -> tuple[Path, str]:
    """(reference image, task description). Both are required."""
    images = sorted(p for p in task_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        raise SystemExit(f"[planner] {task_dir} has no reference image")
    if len(images) > 1:
        raise SystemExit(
            f"[planner] {task_dir} has {len(images)} images; a task folder carries "
            f"exactly one reference: {[p.name for p in images]}"
        )
    desc_file = task_dir / "task.md"
    if not desc_file.is_file():
        raise SystemExit(f"[planner] {task_dir} has no task.md")
    return images[0], desc_file.read_text(encoding="utf-8").strip()


# ── context the planner gets ─────────────────────────────────────────────────

def exemplar_names() -> list[str]:
    if EXEMPLAR_LIST.is_file():
        names = [l.strip() for l in EXEMPLAR_LIST.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
    else:
        names = list(DEFAULT_EXEMPLARS)
    return [n for n in names if (PLANS_DIR / n).is_dir()][-MAX_EXEMPLARS:]


def planner_skills() -> str:
    """Every Skills/Planner/*.md, in full.

    These go in whole rather than as an index: writing the plan *is* this
    agent's job, so its own role's skills are always-on. The Scripting skills
    are indexed instead (see scripting_index) — they matter for stage 1, and
    the prompt names the two worth reading before it starts.
    """
    parts = []
    root = SKILLS_DIR / "Planner"
    for f in sorted(root.rglob("*.md")):
        text = f.read_text(encoding="utf-8").strip()
        # a skill may sit in a subfolder (Objects/, Gpt_images/); the evidence notes beside
        # it have no frontmatter name and are not skills
        if f.parent != root and not (text.startswith("---") and "\nname:" in text[:400]):
            continue
        parts.append(f"### Skills/Planner/{f.relative_to(root).as_posix()}\n\n{text}")
    return "\n\n---\n\n".join(parts) if parts else "(no planner skills yet)"


def scripting_index() -> str:
    """Names and triggers for the Scripting skills; bodies read on demand."""
    return core.load_skills_index("Scripting")


def exemplar_block(names: list[str]) -> str:
    """Paths and headline, not the plans themselves.

    An earlier version inlined the full text of three exemplars. They are
    ~25k characters each, which made the first message ~56k characters, and
    with reasoning effort at max the first call never returned inside the
    provider's 240s time-to-first-byte window — three timeouts, no plan. The
    planner has `read`; naming the files is enough, and it can open the one
    whose subject is closest to its own.
    """
    rows = []
    for n in names:
        folder = PLANS_DIR / n
        md = sorted(folder.glob("*.md"))
        if not md:
            continue
        head = md[0].read_text(encoding="utf-8", errors="replace")
        # the "What we are doing" paragraph, or the first prose line
        summary = ""
        for line in head.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "<!--", "|", "-", "*", "`")):
                summary = line
                break
        rows.append(f"- `plans/{n}/{md[0].name}` — {summary[:150]}")
    return "\n".join(rows) if rows else "(no exemplar plans available)"


# ── prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the planner for a Blender build harness. You are given a "
    "reference photograph and a one-line task, and you produce the build plan "
    "another agent will follow. You have a shell and a scratch folder: measure "
    "the photograph with real scripts before you write anything about it."
)


def build_intro(*, task_name: str, description: str, plan_dir: Path,
                image_name: str, exemplars: list[str]) -> str:
    return f"""\
# Planner — task `{task_name}`

## What you are making

{description}

The reference photograph is attached below and is also on disk at
`plans/{task_name}/{image_name}` — read it again with `read` whenever you want
to look at it properly.

## Where your output goes

Everything you produce goes in `plans/{task_name}/`:

| path | what |
|---|---|
| `plans/{task_name}/{task_name}_plan.md` | **the plan** — the deliverable |
| `plans/{task_name}/{image_name}` | the reference, already copied in for you |
| `plans/{task_name}/scripts/` | your measurement scripts and any crops or overlays they produce |
| `plans/{task_name}/marked_{task_name.lower()}.json` | landmarks, if you measure any |
| `plans/{task_name}/marked_{task_name.lower()}.jpg` | the photo with those landmarks drawn on it |

The first line of the plan must be exactly:

```
<!-- ref-image: {image_name} -->
```

The build harness reads that header and resolves the filename **inside the plan
folder**, so it must name the image that is already sitting there.

## Stage 1 — measure, before you write a word of the plan

A plan's value is mostly in its numbers. Write short Python into
`plans/{task_name}/scripts/` and run it with `bash`. Nothing goes into the working folder's root (no tmp_*.py, crops or notes beside the code): files left there are deleted at the next sync. Do not pipe scripts in with
`python -c` — write the file, then run it by name, so you can re-run it after
you look at the output.

**Before you write your first script, read these two** — they are short, and
between them they cover where a script should run and how to get a number out
of an image without fooling yourself:

```bash
python Tool_scripts/skill_help.py where-code-runs
python Tool_scripts/skill_help.py reading-an-image
```

Useful things to compute, depending on the subject:

- segment the subject from the background and take its tight bounding box;
- trace the outline and record its width at a series of heights;
- measure the ratio between two parts (this is what the builder actually needs:
  "the shoulder is 0.28 of the total height", not "the shoulder is 412 px");
- count repeated elements — slats, teeth, staves, spokes;
- crop a part out to look at it closely with `read`.

**Propose discretely, resolve mechanically.** Do not read a coordinate off the
image by eye and write it down. Decide *which* feature you want and roughly
where it is, then let a few lines of Python find the exact edge, corner or
extremum near that guess. A number you guessed from looking is the single most
common way a plan is confidently wrong.

If you record landmarks, write `marked_{task_name.lower()}.json` as a list of
entries shaped like this, and draw the same points onto a copy of the photo:

```json
{{"name": "shoulder", "group": "torso", "u": 0.431, "v": 0.220,
  "px": [897, 572], "note": "top of the shoulder ball, found by scanning up the
  silhouette from the arm root; needed by step 2"}}
```

`u` and `v` are fractions of the image with the origin at the top left and `v`
growing **down**. That is the same convention `silhouette_vs_reference` reports
in, so the builder and the reviewer can compare against your numbers without
converting anything.

### Budget — this is the part that goes wrong

You have about 90 turns. **You can spend around half of them measuring, but not more than 75%; then write.**

The deliverable is the plan. Measurements are only worth what the plan spends
them on, and a plan carrying five solid numbers beats no plan carrying twenty.
An earlier planner ran out of turns with seventeen measurement scripts on disk
and nothing written; everything it learned was thrown away.

So: **write a complete first draft of the plan by turn 30** — every step, every
checklist, with `TODO` where a number is still missing. Then go back and measure
what the draft actually turned out to need. Drafting first tells you which
measurements matter, which is not obvious before you have written the steps.

Measure a thing once. If a script already produced the number, read its output
again rather than re-deriving it.

## Stage 2 — write the plan

Follow the planner skills below on altitude and wording. In short: say what each
step should achieve and why it matters, and leave *how* open. Name the tools that
suit a step without pinning their parameters.

Two things the harness needs from every plan:

1. **A toolkit section.** The builder's own manual does not cover everything in
   `Tool_scripts/Tools_code/` — there are ~195 callables and only some are in
   its prompt. If your plan tells the builder to call something that is not in
   its manual, your plan must say how to call it. Every existing plan in
   `plans/` does this; copy the pattern.

   Here is where to look, so you do not have to go hunting:

   ```bash
   cat Tool_scripts/Tools_ref/INDEX.md                  # every callable that exists
   python Tool_scripts/tool_help.py --search unwrap     # find one by what it does
   python Tool_scripts/tool_help.py apply_chain         # its full docstring
   python Tool_scripts/tool_help.py --module handle     # a whole module
   ```

   `prompt_files/current_tools.md` is what the builder actually receives, so a
   tool documented there needs no repeating in your plan. Anything else does.
   `Tools_ref/operations.md`, `sculpting.md` and `wear_and_texture.md` carry the
   worked examples and traps for the parts kept out of the builder's prompt.
2. **A review checklist per step**, in concrete terms. Not "the proportions look
   right" but a thing to measure and a value to compare it against. The reviewer
   is a separate agent that sees your checklist and nothing else about your
   intent.

## Finish

When the plan is written, reply with a short summary: the steps you chose, the
measurements you took, and anything you were unsure about. Do not paste the plan
back — it is already on disk.

---

{scripting_index()}

---

## Planner skills

{planner_skills()}

---

## Exemplar plans

These worked in this harness. **Read at least one in full before you start
writing** — pick the one whose subject is closest to yours — and copy its shape,
its altitude and its toolkit section. Do not copy its content; your subject is
different.

{exemplar_block(exemplars)}

```bash
python Tool_scripts/skill_help.py writing-a-build-plan   # if you want the rules again
```
"""


# ── validation ───────────────────────────────────────────────────────────────

def check_plan(plan_dir: Path, task_name: str, image_name: str
               ) -> tuple[list[str], list[str]]:
    """Mechanical checks. Returns (problems, warnings).

    Problems are structural — the build cannot run, or runs on nothing.
    Warnings are things that cost time rather than break: chiefly perceptual
    review checks, which the exemplar plans also contain.
    """
    problems: list[str] = []
    warnings: list[str] = []
    mds = [p for p in plan_dir.glob("*.md")]
    if not mds:
        return [f"no .md written into {plan_dir}"], []
    if len(mds) > 1:
        problems.append(f"{len(mds)} .md files in the plan folder: {[p.name for p in mds]}")
    plan = mds[0]
    text = plan.read_text(encoding="utf-8", errors="replace")

    m = re.search(r"<!--\s*ref-image:\s*(.+?)\s*-->", text)
    if not m:
        problems.append("no <!-- ref-image: ... --> header on the plan")
    elif not (plan_dir / Path(m.group(1)).name).is_file():
        problems.append(f"ref-image header names {m.group(1)!r}, which is not in the plan folder")

    # Ask the builder's own parser rather than keeping a second regex in step
    # with it. _STEP_HDR_RE wants exactly "## Step N — title": two hashes, then
    # an em-dash or hyphen before a title. "### Step 1" and "## Step 1: title"
    # both read fine to a human and pass a looser check, but give the builder
    # zero steps — a build that silently does nothing.
    try:
        parsed = core.parse_plan(text)
    except Exception as exc:
        parsed = []
        problems.append(f"the builder's plan parser raised on this plan: {exc}")
    if not parsed:
        problems.append("the builder parses ZERO steps from this plan — headings must be "
                        "exactly '## Step N — title' (two hashes, em-dash or hyphen)")
    else:
        nums = [s["step_number"] for s in parsed]
        if nums != sorted(nums) or nums[0] != 1:
            problems.append(f"step numbers parse as {nums}; expected 1..N in order")
        no_checks = [s["step_number"] for s in parsed if not s["review_checks"]]
        if no_checks:
            problems.append(f"steps {no_checks} have no parseable Review checklist — the "
                            f"reviewer would be handed nothing to judge against")

    if not re.search(r"toolkit", text, re.I):
        problems.append("no toolkit section (see the exemplar plans)")

    # Perceptual review checks are the single most expensive defect a plan can
    # carry. In the 2026-08-27 trial two of three tasks ended with an EXHAUSTED
    # step, and both burned every round on a check the reviewer had already
    # MEASURED as correct — chess step 5 ("the crown notches must read clearly",
    # 87 min) and wine-glass step 3 ("the bowl must not look milky", 123 min).
    # A check phrased as an impression can never be conclusively satisfied, so
    # it consumes the whole retry budget and disqualifies the task from becoming
    # an exemplar. Skills/Planner/review-checklist-format.md says this; saying
    # it was not enough, so it is enforced here.
    # Calibrated against the two checks that actually caused it:
    #   chess 5  "The two silhouettes and the crown READ AT the same visual scale"
    #   wine 3   "The object READS AS clear crystal ... the rim opening reads"
    # Both cite numbers elsewhere in the same check, so "does it mention a
    # number" is not a usable escape hatch — the unfalsifiable clause sits
    # beside the measurable one and the reviewer fails the step on the clause it
    # cannot settle. So the phrase is flagged wherever it appears.
    PERCEPTUAL = (
        r"\bread(s|ing)?\s+(as|at|clearly|convincing)"     # reads as / read at
        r"|\breads\b\s*[.,;]"                              # "...the rim opening reads."
        r"|clearly\s+(visible|readable|legible|shows?)"
        r"|\blooks?\s+(right|good|correct|convincing|natural)"
        r"|visually\s+(convincing|correct|clear|obvious)"
        r"|\b(convincing|legible|unmistakabl[ey]|pleasing)\b"
        r"|\bno\s+obvious\b"
        r"|\bat\s+the\s+same\s+visual\s+scale\b"
    )
    # Reported separately from `problems`: these are warnings, not rejections.
    # The five hand-written exemplar plans carry 2-8 of them each ("the base
    # reads heavier than the capital", "the membrane reads as one continuous
    # surface", "looks right"), so the agent planner is imitating the defect
    # rather than inventing it, and a hard failure would reject every plan in
    # the project. The exemplars simply never paid for it — their builds went
    # well enough not to exhaust the budget.
    for st in parsed:
        for chk in st["review_checks"]:
            m = re.search(PERCEPTUAL, chk, re.I)
            if m:
                warnings.append(
                    f"step {st['step_number']}: perceptual clause {m.group(0)!r} — the "
                    f"reviewer cannot settle this by measurement and may spend the retry "
                    f"budget on it. Prefer a quantity. Check: {chk[:100]!r}")
    if not (plan_dir / "scripts").is_dir():
        problems.append("scripts/ folder missing")
    elif not any((plan_dir / "scripts").iterdir()):
        problems.append("scripts/ is empty — the planner measured nothing")
    return problems, warnings


# ── main ─────────────────────────────────────────────────────────────────────



def plan_task(task_name: str, *, force: bool = False,
              note: str = "") -> Path:
    task_dir = find_task(task_name)
    image_src, description = task_assets(task_dir)

    plan_dir = PLANS_DIR / task_name
    if plan_dir.exists() and any(plan_dir.glob("*.md")) and not force:
        print(f"[planner] {plan_dir} already has a plan — skipping (use --force to redo)")
        return plan_dir

    (plan_dir / "scripts").mkdir(parents=True, exist_ok=True)
    image_dst = plan_dir / image_src.name
    if not image_dst.exists():
        shutil.copy2(image_src, image_dst)

    core.load_api_keys()
    agent_env.ensure_plugin_env()
    os.environ.setdefault("HERMES_API_CALL_STALE_TIMEOUT", STALE_TIMEOUT_S)
    exemplars = exemplar_names()
    intro = build_intro(task_name=task_name, description=description, plan_dir=plan_dir,
                        image_name=image_src.name, exemplars=exemplars)
    if note:
        # Goes at the TOP: a correction the human typed outranks the
        # standing instructions it contradicts.
        intro = (
            "# Instruction for this run\n\n"
            f"{note}\n\n"
            "This overrides anything below it that it contradicts.\n\n"
            "---\n\n" + intro
        )
        print(f"[planner] note: {note}")

    from run_agent import AIAgent
    from agent.image_routing import build_native_content_parts

    first_message, _ = build_native_content_parts(intro, image_paths=[str(image_dst)])

    kwargs = dict(
        provider=MODELS["planner"]["provider"],
        model=MODELS["planner"]["model"],
        api_key=core.api_key_for(MODELS["planner"]["provider"]),
        base_url=core.base_url_for(MODELS["planner"]["provider"]),
        quiet_mode=False,
        max_iterations=90,
        ephemeral_system_prompt=SYSTEM_PROMPT,
        enabled_toolsets=agent_env.PLANNER_TOOLSETS,
    )
    if MODELS["planner"]["provider"] == "openai":
        kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}

    print(f"[planner] task={task_name}  exemplars={exemplars}")
    print(f"[planner] writing into {plan_dir}")
    t0 = time.time()
    result = AIAgent(**kwargs).run_conversation(first_message)
    wall = time.time() - t0
    print(f"[planner] finished in {wall:.0f}s")
    agent_env.check_tools(result, "planner")
    agent_env.record_usage(result, wall, plan_dir / "scripts" / "usage.json",
                 tag="Planner", extra={"task": task_name, "exemplars": exemplars})

    summary = (result.get("final_response") or "").strip()
    (plan_dir / "scripts" / "planner_summary.md").write_text(
        summary or "(no response)", encoding="utf-8")

    problems, warnings = check_plan(plan_dir, task_name, image_src.name)
    if warnings:
        print(f"[planner] {len(warnings)} perceptual review check(s) — these cost "
              f"retry rounds but do not block:")
        for w in warnings[:6]:
            print("   ~", w)
    if problems:
        print("[planner] PROBLEMS with the plan it wrote:")
        for p in problems:
            print("   -", p)
    else:
        print("[planner] plan looks well formed")
    (plan_dir / "scripts" / "planner_check.json").write_text(
        json.dumps({"problems": problems, "warnings": warnings}, indent=2),
        encoding="utf-8")
    return plan_dir, problems


def main() -> None:
    ap = argparse.ArgumentParser(description="Write a build plan for one task.")
    ap.add_argument("--task", required=True, help="task folder name, e.g. 01_pallet_stack")
    ap.add_argument("--force", action="store_true", help="replan even if a plan exists")
    ap.add_argument("--note", default="", help="extra instruction for this planning run")
    ap.add_argument("--retries", type=int, default=1,
                    help="replan attempts if check_plan finds blocking problems")
    args = ap.parse_args()

    # check_plan used to print its findings and exit 0 anyway, so the loop —
    # which does stop on a non-zero rc — sailed past a plan the builder could
    # not parse, ran a build that failed instantly, and then curated the empty
    # run. A check nobody acts on is not a check.
    _, problems = plan_task(args.task, force=args.force, note=args.note)
    for attempt in range(args.retries):
        if not problems:
            break
        print(f"\n[planner] replanning ({attempt + 1}/{args.retries}) — "
              f"feeding the problems back")
        note = (args.note + "\n\n" if args.note else "") + (
            "Your previous plan was rejected by the format check:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\n\nFix exactly these and keep everything else. The step heading "
              "must be `## Step N — title` at the start of its own line."
        )
        _, problems = plan_task(args.task, force=True, note=note)

    if problems:
        print(f"[planner] giving up after {args.retries} retry(ies) — "
              f"{len(problems)} problem(s) remain")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
