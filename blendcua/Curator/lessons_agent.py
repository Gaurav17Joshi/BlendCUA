"""Lessons agent: when a build came out well, write down why, as skills.

    python Curator/lessons_agent.py --task 05_energy_can --run 05_energy_can_run_001 \
        --out Curator/reports/05_energy_can/lessons [--defects Checker/reports/<run>/defects.json]

The mirror image of the blame agent. The blame agent is only called when the checker found
something major; this one is called when it did not (no major defect, or nothing at all). It
reads the plan, the step handovers and reviews, the checker's notes, and writes what made the
build work into the skills of the role that did it: a planner decision that paid off, an
executor construction that read right first time, a review check that caught the one thing.
Add-only, one paragraph per lesson, each citing the run file it comes from.

Writes only under Skills/. Reports Curator/reports/<task>/lessons/lessons.json:
    {"files": [...store files touched...], "lessons": [{"skill", "lesson", "cites"}], "summary"}
The driver publishes exactly those files (harness.publish) so a lesson enters the shared store
through the same door as an accepted remedy.
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[1])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import agent_env  # noqa: E402
import blendcua_core as core  # noqa: E402
from models import MODELS, OPENAI_REASONING_EFFORT  # noqa: E402
from curator_agent import _write_calls, skills_index, view_escapes, VIEW_RULE  # noqa: E402

SYSTEM_PROMPT = """You are the lessons step of a Blender build harness. A planner wrote a plan, an
executor built it step by step, a reviewer judged each step, and a separate checker compared the
finished model with the reference photograph and found nothing major. Your job is to make sure
the harness does this again on the next object: find what was done right, and write it into the
skills that the planner, executor and reviewer read, so it is a rule next time and not luck.

How to work:
1. Read the task brief, the plan, every step's handover.md and review/round_*/review.txt, and the
   checker's notes and defects (minor ones tell you what was nearly wrong).
2. Name at most FIVE lessons. A lesson is a decision or construction that is (a) visible in a file
   of this run, (b) general beyond this object, and (c) not already in a skill (read the index and
   the candidate skill before writing). "Use good proportions" is not a lesson. "Take the shape
   from the straight image2 plate and only the proportions from the photo, because the photo is
   oblique" is.
3. For each lesson, append one short section to the most fitting existing skill under
   Skills/<Role>/ (Planner, Executor, Reviewer, Scripting), or create a new skill file there with
   the same frontmatter shape as its neighbours if none fits. Add-only: never rewrite or delete
   what is there. Cite the run file (mem/<run>/steps/step_N/...) the lesson comes from.
4. Write the report JSON to the path you are given, with the exact list of files you touched.
   Budget: you have about 60 turns. Read at most 15 files, write the skills by turn 40, and
   write the report right after the skills, before anything else.

Never touch Tool_scripts/, prompt_files/, plans/, mem/, tasks/, Checker/ or the reference.
""" + VIEW_RULE + "\n"

SALVAGE_PROMPT = """You are the salvage step of a Blender build harness. A round tried a remedy (a
plan rewrite, skill text, sometimes a tool) and rebuilt the object. The checker then judged the
rebuild: some of the targeted defects are RESOLVED, others are UNCHANGED, and nothing got WORSE.
The rule says a remedy is kept only when it closes everything it targeted, so the edits were
reverted. But part of it worked, and that part must not be lost.

You get: the round folder (curation.json = what was blamed and proposed; apply/applied.json = the
files the remedy changed), the verdict (which defect ids RESOLVED, with the checker's evidence),
and store_after/ = the reverted files exactly as the remedy left them, at their repo-relative
paths. Read the remedy's edits there and the verdict, and decide which instruction, number,
check or construction is the one the evidence says caused each RESOLVED id. Write only THAT into
the skills (Skills/<Role>/, add-only, one short section per salvaged point, citing the round's
files and the verdict measurement). Do not carry over anything whose defect stayed UNCHANGED.
Do not restore the plan or the tools: skills only.

Write the report JSON to the path you are given:
    {"files": [...], "lessons": [{"skill", "lesson", "cites", "resolved_id"}], "summary": "..."}
Budget: about 60 turns; read at most 15 files; write the report right after the skills.
Never touch Tool_scripts/, prompt_files/, plans/, mem/, tasks/, Checker/ or the reference.
""" + VIEW_RULE + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--defects", default=None)
    ap.add_argument("--max-iterations", type=int, default=60)
    ap.add_argument("--mode", choices=("lessons", "salvage"), default="lessons")
    ap.add_argument("--round-dir", default=None, help="salvage: Curator/reports/<task>/round_NN")
    ap.add_argument("--verdict", default=None, help="salvage: Checker/reports/<new_run>/verdict.json")
    ap.add_argument("--store-after", default=None, help="salvage: vb/state/<task>/round_NN/store_after")
    ap.add_argument("--groups", default="", help="salvage: comma list of the dropped-but-partly-right group ids")
    a = ap.parse_args()
    core.load_api_keys()
    agent_env.ensure_plugin_env()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    run_dir = ROOT / "mem" / a.run
    plan = next((ROOT / "plans" / a.task).glob("*_plan.md"), None)
    checker_dir = ROOT / "Checker" / "reports" / a.run
    report = out / ("salvage.json" if a.mode == "salvage" else "lessons.json")
    if a.mode == "salvage":
        rd = Path(a.round_dir)
        if a.store_after and Path(a.store_after).is_dir():
            reverted = (f"The reverted edits, as the remedy left them: {a.store_after}/ "
                        f"(same relative paths as the repo)\n")
        else:
            reverted = ("The reverted files themselves were not kept for this round: work from "
                        "apply/applied.json (what was changed, in words), curation.json (the content "
                        "sketches) and the verdict.\n")
        intro = (
            f"# Salvage for {a.task}, {rd.name}\n\n"
            f"Groups dropped but partly right: {a.groups or '(see acceptance.json)'}\n"
            f"Round folder: {rel_to(rd, ROOT)}/ (curation.json, apply/applied.json, acceptance.json)\n"
            f"Verdict: {a.verdict}\n"
            f"{reverted}"
            f"Task brief: tasks/train/{a.task}/task.md; original run mem/{a.run}/\n\n"
            f"Skills index (read a body with `python Tool_scripts/skill_help.py <name>`):\n\n{skills_index()}\n\n"
            f"Write the report to {rel_to(report, ROOT)}.\n"
        )
    else:
        intro = (
            f"# Lessons for {a.task}\n\n"
            f"Task brief: tasks/train/{a.task}/task.md\nPlan: {rel_to(plan, ROOT) if plan else '(none)'}\n"
            f"Run: mem/{a.run}/ (steps/step_N/handover.md, steps/step_N/review/round_*/review.txt, the action files)\n"
            f"Checker: {rel_to(checker_dir, ROOT)}/notes.md and defects.json"
            f"{' (' + a.defects + ')' if a.defects else ''}\n"
            f"Rendered result: blends/{a.run}/views/final_render.png beside blends/{a.run}/task/reference.png\n\n"
            f"Skills index (read the body of any skill with `python Tool_scripts/skill_help.py <name>`):\n\n"
            f"{skills_index()}\n\n"
            f"Write the report to {rel_to(report, ROOT)} as JSON: "
            f'{{"files": [...], "lessons": [{{"skill": ..., "lesson": ..., "cites": ...}}], "summary": "..."}}\n'
        )
    cfg = MODELS.get("curator") or MODELS["planner"]
    kwargs = dict(provider=cfg["provider"], model=cfg["model"], api_key=core.api_key_for(cfg["provider"]),
                  base_url=core.base_url_for(cfg["provider"]), quiet_mode=False, max_iterations=a.max_iterations,
                  ephemeral_system_prompt=(SALVAGE_PROMPT if a.mode == "salvage" else SYSTEM_PROMPT),
                  enabled_toolsets=agent_env.CURATOR_TOOLSETS)
    if cfg["provider"] == "openai":
        kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}
    from run_agent import AIAgent
    import hashlib
    def _skills_hash():
        return {str(p.relative_to(ROOT)).replace(chr(92), '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT / 'Skills').rglob('*.md')}
    before = _skills_hash()
    print(f"[{a.mode}] task={a.task} run={a.run} model={cfg['model']} -> {out}")
    t0 = time.time()
    result = AIAgent(**kwargs).run_conversation(intro)
    wall = time.time() - t0
    agent_env.check_tools(result, "lessons")
    agent_env.record_usage(result, wall, out / f"{a.mode}_usage.json", tag=("Salvage" if a.mode == "salvage" else "Lessons"), extra={"task": a.task, "run": a.run})
    (out / f"{a.mode}_summary.md").write_text((result.get("final_response") or "").strip() or "(no response)", encoding="utf-8")
    bad = _write_calls(result, ("Tool_scripts/", "Tool_scripts\\", "prompt_files/", "prompt_files\\", "plans/", "plans\\",
                                "mem/", "mem\\", "tasks/", "tasks\\", "Checker/", "Checker\\"))
    problems = []
    if bad:
        problems.append(f"wrote outside Skills/ in {len(bad)} call(s)")
    from curator_agent import other_task_writes
    cross = other_task_writes(result, a.task)
    if cross:
        problems.append(f"wrote into another task's folder in {len(cross)} call(s): {cross[0][:120]}")
    esc = view_escapes(result)
    if esc:
        problems.append(f"reached outside the worker view in {len(esc)} call(s): {esc[0][:120]}")
    after = _skills_hash()
    changed = sorted(f for f in set(before) | set(after) if before.get(f) != after.get(f))
    if not report.is_file():
        # the agent ran out of turns before the report: the files it changed are the report
        report.write_text(json.dumps({"files": changed, "lessons": [],
                                      "summary": (result.get("final_response") or "")[:600],
                                      "note": "report synthesised from the changed skill files"}, indent=2),
                          encoding="utf-8")
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        files = [str(f).replace("\\", "/") for f in data.get("files") or []]
        files = sorted(set(files) | set(changed))      # what actually changed on disk counts
        if not files:
            problems.append("lessons.json names no files")
        if any(not f.startswith("Skills/") for f in files):
            problems.append("lessons.json names files outside Skills/")
        data["files"] = files
    except Exception as e:  # noqa: BLE001
        problems.append(f"no valid lessons.json: {e}")
        data = {"files": [], "lessons": [], "summary": ""}
    data["problems"] = problems
    data["wall_s"] = round(wall)
    report.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"[{a.mode}] {len(data.get('lessons') or [])} lesson(s) in {len(data['files'])} file(s), {wall:.0f}s"
          + (f"; PROBLEMS: {problems}" if problems else ""))
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
