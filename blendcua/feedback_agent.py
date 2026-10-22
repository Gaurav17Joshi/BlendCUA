"""Feedback agent (the curator) — reads one finished run and improves the harness.

    python feedback_agent.py --run pallet_stack_run_001

It asks one question about the run: *what would have made that easier?* — and
then builds the answer and checks it, rather than just writing it down.

Two halves:

1. **A digest, computed here in code.** Not a summary — an index of the places
   the run struggled: steps that burned more actions than their neighbours,
   `REDO LOGIC` comments, review rounds the reviewer sent back, scripts the
   builder wrote for itself, tools it authored mid-run. The curator reads the
   real files behind those pointers; the digest only says where to look.

2. **The curator conversation**, with a shell and file access, which commits
   two kinds of artifact:
     * **tools** into `Tool_scripts/Tools_code/` — code, tested by rewriting the
       actions that motivated them and replaying, so a tool that does not
       reproduce the run's geometry is discarded rather than argued for;
     * **skills** into `Skills/<Consumer>/` — text, each citing the run and step
       that taught it, indexed in `Skills/README.md`.

Everything it did lands in `mem/<run>/curation/`.

Two rules are enforced here rather than trusted to the prompt: a new tool file
must at least parse, and reviewer-facing skills may only be added, never
deleted or shortened — the curator is implicitly optimised against the review
pass rate, and the cheapest way to make a step pass is to make its check vaguer.
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[0])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import argparse
import ast
import json
import os
import re
import sys
import shutil
import statistics
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
MEM = ROOT / "mem"
SKILLS = ROOT / "Skills"
TOOLS_CODE = ROOT / "Tool_scripts" / "Tools_code"
SNAPSHOTS = ROOT / "snapshots"

REDO_RE = re.compile(r"#\s*REDO LOGIC:\s*(.+)")


# ── digest ───────────────────────────────────────────────────────────────────

def _verdict(text: str) -> str:
    for line in reversed([l.strip(" *_") for l in text.splitlines() if l.strip()]):
        if line.upper().startswith("PASS"):
            return "PASS"
        if line.upper().startswith("TRY") or "TRY_AGAIN" in line.upper():
            return "TRY_AGAIN"
    return "UNKNOWN"


def build_digest(run_dir: Path) -> dict:
    steps = []
    for step_dir in sorted((run_dir / "steps").glob("step_*")):
        actions = sorted(p for p in step_dir.glob("*.py") if not p.name.startswith("review_"))
        redos = []
        for a in actions:
            for m in REDO_RE.finditer(a.read_text(encoding="utf-8", errors="replace")):
                redos.append({"file": a.name, "text": m.group(1).strip()})
        rounds = []
        for rd in sorted((step_dir / "review").glob("round_*")) if (step_dir / "review").is_dir() else []:
            rt = rd / "review.txt"
            text = rt.read_text(encoding="utf-8", errors="replace") if rt.is_file() else ""
            rounds.append({
                "round": rd.name,
                "verdict": _verdict(text) if text.strip() else "EMPTY",
                "first_lines": "\n".join(text.strip().splitlines()[:6]),
            })
        scripts = sorted(p.name for p in (step_dir / "scripts").glob("*")) \
            if (step_dir / "scripts").is_dir() else []
        steps.append({
            "step": int(step_dir.name.split("_")[-1]),
            "dir": str(rel_to(step_dir, ROOT)).replace("\\", "/"),
            "actions": len(actions),
            "action_files": [a.name for a in actions],
            "redo_comments": redos,
            "review_rounds": rounds,
            "scripts_written": scripts,
        })

    counts = [s["actions"] for s in steps] or [0]
    med = statistics.median(counts)
    for s in steps:
        s["action_outlier"] = bool(med and s["actions"] >= 1.5 * med)

    # Tools the builder authored mid-run: present now, absent when the run began.
    #
    # The baseline is the run's own store_baseline.json, written by the builder
    # before its first action. Diffing against the newest snapshot instead — as
    # this did — silently attributes anything a human changed between snapshot
    # and run to the builder. On 04_datestone that produced a digest naming two
    # hand-written files as "the strongest evidence in the whole record", on a
    # run that executed zero steps.
    authored = []
    baseline_src = None
    before = set()
    bfile = run_dir / "store_baseline.json"
    if bfile.is_file():
        try:
            before = set(json.loads(bfile.read_text(encoding="utf-8")).get("tools", []))
            baseline_src = "store_baseline.json (run start)"
        except Exception:
            before = set()
    if not before:
        # Older runs predate the baseline file. Fall back, but say so, so the
        # curator can discount the claim rather than trust it.
        snaps = sorted(SNAPSHOTS.glob("H_*"))
        if snaps and (snaps[-1] / "Tools_code").is_dir():
            before = {q.name for q in (snaps[-1] / "Tools_code").glob("*.py")}
            baseline_src = (f"{snaps[-1].name} snapshot (approximate — may include "
                            f"edits made outside the run)")
    if before:
        authored = sorted({q.name for q in TOOLS_CODE.glob("*.py")} - before)

    sore = []
    for s in steps:
        why = []
        if s["action_outlier"]:
            why.append(f"{s['actions']} actions vs median {med:g}")
        if s["redo_comments"]:
            why.append(f"{len(s['redo_comments'])} redo comment(s)")
        bad = [r for r in s["review_rounds"] if r["verdict"] != "PASS"]
        if bad:
            why.append(f"{len(bad)} review round(s) not passed")
        if s["scripts_written"]:
            why.append(f"wrote {len(s['scripts_written'])} inspection script(s)")
        if why:
            sore.append({"step": s["step"], "dir": s["dir"], "why": why})

    return {
        "run": run_dir.name,
        "median_actions_per_step": med,
        "steps": steps,
        "sore_spots": sore,
        "tools_authored_during_run": authored,
        "baseline_snapshot": baseline_src,
    }


def digest_brief(d: dict) -> str:
    """The part that goes in the prompt — pointers, not contents."""
    lines = [f"Run `{d['run']}` — {len(d['steps'])} steps, "
             f"median {d['median_actions_per_step']:g} actions per step.", ""]
    if d["tools_authored_during_run"]:
        approx = "approximate" in (d.get("baseline_snapshot") or "")
        lines += [("**Tools that appeared during this run** (baseline: "
                   f"{d['baseline_snapshot']}). "
                   + ("Treat with caution — this baseline cannot distinguish the "
                      "builder's work from edits made outside the run."
                      if approx else
                      "The builder wrote these itself — start here, they are the "
                      "strongest evidence in the record.")),
                  *(f"  - `Tool_scripts/Tools_code/{t}`" for t in d["tools_authored_during_run"]), ""]
    if not d["sore_spots"]:
        lines.append("No sore spots found: no action-count outliers, no redo comments, "
                     "no failed review rounds, no inspection scripts. Say so and stop.")
        return "\n".join(lines)
    lines.append("**Sore spots** — the places this run struggled. Open these and read them:")
    for s in d["sore_spots"]:
        lines.append(f"\n- **Step {s['step']}** (`{s['dir']}`) — {'; '.join(s['why'])}")
        st = next(x for x in d["steps"] if x["step"] == s["step"])
        for r in st["redo_comments"]:
            lines.append(f"    - redo in `{r['file']}`: {r['text']}")
        for rv in st["review_rounds"]:
            if rv["verdict"] != "PASS":
                head = rv["first_lines"].replace("\n", " ")[:200]
                lines.append(f"    - {rv['round']} → {rv['verdict']}: {head}")
        if st["scripts_written"]:
            lines.append(f"    - own scripts: {', '.join(st['scripts_written'])}")
    return "\n".join(lines)


# ── prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the curator of a Blender build harness. After each run you decide "
    "what the harness was missing, build it, and prove it would have helped by "
    "replaying the actions that motivated it. You improve the harness; you do "
    "not grade the run."
)


def build_intro(run: str, brief: str) -> str:
    skills = core.load_skills_index("Feedback", "Scripting")
    return f"""\
# Curator — run `{run}`

The build has finished. Your job is to answer one question about it:
**what would have made that easier?** — and then build the answer and check it.

Everything you commit goes to two places, and `mem/{run}/curation/` records what
you did.

## The run

{brief}

## How to work

**1. Read the sore spots properly.** The list above is an index, not a summary.
Open the action files, look at the screenshots with `read`, read the reviewer's
text. You are looking for what the builder was *fighting*.

**2. Sort each one into a kind.**

- *There was no tool for this* — it took six fiddly actions to do something one
  call should do. → a **tool**.
- *There was a tool, but it was wrong or awkward here.* → a **tool fix**.
- *The builder did not know something.* No code was missing; it just needed
  telling. → a **skill**.

The test that separates the third from the first: if the builder had known this,
would it have written different code? If yes it is a skill. If it would have
written the same code and only wished it were one call, it is a tool.

**3. For a tool, build it and test it.** This is the part that matters.

```
a. write the tool into Tool_scripts/Tools_code/
b. rewrite the actions that motivated it so they use it
c. replay them and compare the geometry against what the run actually produced
d. same result in fewer actions -> keep.  different result -> your tool is wrong
```

**You drive Blender from the shell, with `bash`. Not with `write_and_run`** — that
tool only works inside a build step, and you run between steps, so it will refuse
you. The command is:

```
python Tool_scripts/run.py --file <script.py> --timeout 300
```

It needs no step context. Exit 0 means the script ran, 1 means it raised (the
traceback is printed), 2 means Blender is hung. `replay_batch.py` assembles a
step's action files into one script you can hand to `run.py`; read it first to see
how to call it.

**Blender's stdout is invisible to you.** A dispatched script's `print()` goes
nowhere you can read, so a replay must *write its answer to a file*. Use
`geom_digest`, which is built for exactly this:

```python
# preamble EVERY dispatched script needs — Tools_code is not on sys.path by
# default and Blender's cwd is its own install folder, so both must be absolute
import sys, os
ROOT = os.path.abspath(".")          # <- substitute the real harness path
TC = os.path.join(ROOT, "Tool_scripts", "Tools_code")
if TC not in sys.path:
    sys.path.insert(0, TC)

# at the end of both the original replay and the refactored one
import geom_digest
geom_digest.write_digest("mem/_curate/before.json")   # then .../after.json
```

Without that preamble the import fails with `ModuleNotFoundError` even though the
file is plainly there. `replay_batch.py` already builds this preamble into the
scripts it generates, so replays through it need no extra work.

then compare from the shell — no Blender needed, `compare` only reads JSON:

```
python -c "import sys; sys.path.insert(0,'Tool_scripts/Tools_code'); import geom_digest as g, json; print(json.dumps(g.compare('mem/_curate/before.json','mem/_curate/after.json'), indent=2))"
```

`identical: true` is your evidence. `changed` names the objects that moved, so a
false verdict tells you *where* your tool is wrong, not just that it is. The
digest quantises to 1e-5 m, so float noise passes and a 1 mm error fails.

One trap that will bite you otherwise: **Blender's working directory is its own
install folder**, not the harness root, so a relative path opened inside a
dispatched script resolves under `C:/Program Files/...` and fails as
`PermissionError`. `geom_digest` resolves paths against the harness root for you;
anything else you write must use an absolute path.

Before you rely on this, check Blender is actually up:

```
python blender_health.py --probe
```

If it is down, say so in your changeset and mark every tool you could not replay
as **untested** — do not commit it. An untested tool is worse than no tool,
because the next run will trust it. A tool you cannot test this way is a tool you
should not commit.

**4. Generalise before committing.** Ask what the general version is. A chain of
extrude-and-rotate segments following measured points is not a wing tool; it is a
"follow a list of measured points" tool. **A tool named after the object it came
from is rejected** — no `make_bat_wing`, no `pillar_cracks`. Every numeric
constant is either a parameter or carries a comment saying why it is universal.

**5. Write skills where the gap was knowledge.** One claim per file, into the
folder of whoever needed it:

```
Skills/Planner/    what the plan should have said
Skills/Executor/   what the builder should have known while building
Skills/Reviewer/   what the reviewer should have looked at
```

Use the frontmatter the existing skills use, and add an `evidence:` line naming
the run and step that taught it. Then add one line to `Skills/README.md` under
the right heading — write it as a **trigger** ("read this when a measurement
disagrees with the render"), not a summary, because a summary invites skipping.

One sore spot often produces both a tool and a skill, and they often belong to
different agents. That is normal.

**6. Keep the store small.** Before adding a skill, check whether an existing one
in that folder already covers it and should be edited instead. Merging two
overlapping skills is worth more than adding a third.

**Reviewer skills are add-only.** You may add a check. You may not delete one,
soften one, or make one vaguer. You are the wrong party to be relaxing the
standard you are measured against.

## What already exists

Before you write a tool, find out whether one is already there — a duplicate
under a new name passes a replay test perfectly well and still makes the store
worse.

```bash
python Tool_scripts/tool_help.py --search <what it would do>
python Tool_scripts/tool_help.py --module <module>
cat Tool_scripts/Tools_ref/INDEX.md
```

`Tool_scripts/gen_tool_index.py` regenerates that index from the source — run it
after you add or rename anything, or the reference starts drifting from the code
again. `python Tool_scripts/skill_help.py --list` does the same for skills;
check it before adding one, in case an existing skill should be edited instead.

{skills}

## Finish

Write `mem/{run}/curation/changeset.md` listing, for each thing you committed:
what it is, which sore spot it came from, and — for tools — what you replayed and
what the comparison showed. Include what you considered and rejected, and why;
that is as useful as what you kept.

Then reply with a short summary. Do not paste the changeset back.
"""


# ── checks ───────────────────────────────────────────────────────────────────

def check_changes(before: dict[str, str], after_tools: list[Path]) -> list[str]:
    problems = []
    for p in after_tools:
        try:
            ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            problems.append(f"{p.name} does not parse: {e}")
        name = p.stem.lower()
        for noun in ("bat", "duck", "pillar", "gravestone", "chilli", "stool", "pallet",
                     "barrel", "mannequin", "robot", "thonet"):
            if noun in name:
                problems.append(f"{p.name} is named after an object ({noun}) — tools are motif level")
    for rel, old in before.items():
        new_path = ROOT / rel
        if not new_path.is_file():
            problems.append(f"reviewer skill {rel} was DELETED — reviewer skills are add-only")
        elif len(new_path.read_text(encoding="utf-8", errors="replace")) < 0.9 * len(old):
            problems.append(f"reviewer skill {rel} shrank by >10% — reviewer skills are add-only")
    return problems


# ── main ─────────────────────────────────────────────────────────────────────

def curate(run: str, *, dry_run: bool = False) -> dict:
    run_dir = MEM / run
    if not run_dir.is_dir():
        raise SystemExit(f"[curator] no run at {run_dir}")

    out_dir = run_dir / "curation"
    out_dir.mkdir(parents=True, exist_ok=True)

    digest = build_digest(run_dir)
    (out_dir / "digest.json").write_text(json.dumps(digest, indent=2), encoding="utf-8")
    brief = digest_brief(digest)
    (out_dir / "digest.md").write_text(brief, encoding="utf-8")
    print(brief)

    if dry_run:
        print("\n[curator] --dry-run: digest only, no changes made")
        return digest
    if not digest["sore_spots"] and not digest["tools_authored_during_run"]:
        print("\n[curator] nothing to curate — clean run")
        return digest

    reviewer_before = {
        str(rel_to(p, ROOT)).replace("\\", "/"): p.read_text(encoding="utf-8", errors="replace")
        for p in (SKILLS / "Reviewer").glob("*.md")
    }
    tools_before = {p.name for p in TOOLS_CODE.glob("*.py")}

    core.load_api_keys()
    agent_env.ensure_plugin_env()
    # same reason as the planner: one long first turn over a lot of context
    os.environ.setdefault("HERMES_API_CALL_STALE_TIMEOUT", "900")
    from run_agent import AIAgent

    kwargs = dict(
        provider=MODELS["curator"]["provider"],
        model=MODELS["curator"]["model"],
        api_key=core.api_key_for(MODELS["curator"]["provider"]),
        base_url=core.base_url_for(MODELS["curator"]["provider"]),
        quiet_mode=False,
        max_iterations=80,
        ephemeral_system_prompt=SYSTEM_PROMPT,
        enabled_toolsets=agent_env.CURATOR_TOOLSETS,
    )
    if MODELS["curator"]["provider"] == "openai":
        kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}

    print(f"\n[curator] run={run}  sore spots={len(digest['sore_spots'])}")
    t0 = time.time()
    result = AIAgent(**kwargs).run_conversation(build_intro(run, brief))
    wall = time.time() - t0
    print(f"[curator] finished in {wall:.0f}s")
    agent_env.check_tools(result, "curator")
    agent_env.record_usage(result, wall, out_dir / "usage.json",
                 tag="Curator", extra={"run": run,
                                       "sore_spots": len(digest["sore_spots"])})

    (out_dir / "curator_summary.md").write_text(
        (result.get("final_response") or "(no response)").strip(), encoding="utf-8")

    new_tools = [p for p in TOOLS_CODE.glob("*.py") if p.name not in tools_before]
    problems = check_changes(reviewer_before, new_tools)
    print(f"[curator] new tool files: {[p.name for p in new_tools] or 'none'}")
    if problems:
        print("[curator] PROBLEMS:")
        for p in problems:
            print("   -", p)
    (out_dir / "checks.json").write_text(
        json.dumps({"new_tools": [p.name for p in new_tools], "problems": problems}, indent=2),
        encoding="utf-8")
    return digest


# Tasks completed at which a snapshot is also kept as an EVALUATION milestone.
# The per-task snapshots (H_00, H_01, ...) are for diffing "what did task N
# teach"; these are the four points the harness is actually measured at, by
# replaying a held-out probe set under each. 5/10/15/20 over a 20-task
# curriculum gives four points on the growth curve, which is the minimum that
# can show a shape rather than just a start and an end. If the curriculum grows
# to 25, add 25 here — the mechanism does not care.
EVAL_MILESTONES = (5, 10, 15, 20)


def milestone_for(tasks_done: int) -> str | None:
    return f"M_{tasks_done:02d}" if tasks_done in EVAL_MILESTONES else None


def snapshot(label: str | None = None) -> Path:
    """Freeze the harness — the three directories that actually change."""
    SNAPSHOTS.mkdir(exist_ok=True)
    if label is None:
        n = len(list(SNAPSHOTS.glob("H_*")))
        label = f"H_{n:02d}"
    dst = SNAPSHOTS / label
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for rel in ("Tool_scripts/Tools_code", "Skills", "prompt_files"):
        src = ROOT / rel
        if src.is_dir():
            shutil.copytree(src, dst / Path(rel).name,
                            ignore=shutil.ignore_patterns("__pycache__", "_vendor"))
    print(f"[curator] snapshot -> snapshots/{label}")
    return dst


def main() -> None:
    ap = argparse.ArgumentParser(description="Curate the harness from one finished run.")
    ap.add_argument("--run", help="run name under mem/")
    ap.add_argument("--dry-run", action="store_true", help="build the digest and stop")
    ap.add_argument("--snapshot", metavar="LABEL", nargs="?", const="",
                    help="freeze the harness into snapshots/ and exit")
    ap.add_argument("--milestone", type=int, metavar="N",
                    help="also keep an evaluation milestone if N completed tasks "
                         f"is one of {EVAL_MILESTONES}")
    args = ap.parse_args()

    if args.snapshot is not None:
        snapshot(args.snapshot or None)
        if args.milestone:
            m = milestone_for(args.milestone)
            if m:
                snapshot(m)
                print(f"[curator] evaluation milestone {m} kept "
                      f"({args.milestone} tasks completed)")
        return
    if not args.run:
        ap.error("--run is required unless --snapshot is given")

    # A run that executed no steps has nothing to curate, and curating it is
    # not merely wasteful — it produced a digest whose only content was a false
    # claim about who wrote two tools. Exit non-zero so the loop records the
    # task as not curated and the milestone counter does not advance on it.
    d = build_digest(MEM / args.run)
    if not d["steps"]:
        print(f"[curator] {args.run} executed 0 steps — nothing to curate.")
        print("[curator] this usually means the build failed to start; "
              "fix the build, do not curate the wreckage.")
        raise SystemExit(3)

    curate(args.run, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
