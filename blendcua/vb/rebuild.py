"""The three rebuild paths of Version B (project_vb_v2 section 7).

    R1  the corrected action files are replayed in one dispatch. No agent.
    R2  executor + reviewer run again from the (corrected) plan under the
        new harness. Optionally from a step: earlier steps are copied from
        the base run and replayed into the scene first.
    R3  planner first, then R2 in full.

    An R2 starts at the first step the remedy touches (the remedy's own from_step, else
    the step its evidence names; a rewritten plan step clamps it): the steps below are
    copied from the base run and replayed, not rebuilt. Every rebuild writes
    mem/<run>/prior_attempt.md, which each step-subagent reads: where the previous
    attempt is, that it may take code from it, and what must be built differently.
    A dead build (process killed mid-step) is continued in place from its last
    end-of-step checkpoint (resume_run / --resume-build; the round loop does it for a
    rebuild through dead_rebuild_run).

    python vb/rebuild.py --path R1 --base 11_umbrella_run_001 --run 11_umbrella_run_002
    python vb/rebuild.py --path R2 --task 11_umbrella [--from-step 3 --base ...]
    python vb/rebuild.py --path R3 --task 11_umbrella
    python vb/rebuild.py --resume-build --task 04_skull --run 04_skull_run_001

Every path ends with a bundle in blends/<run>/ and a rebuild.json beside
the run's steps describing what ran.
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[1])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import bundle as B  # noqa: E402

LOGS = C.VB_STATE / "logs"


def _record(run: str, data: dict) -> None:
    C.write_json(C.MEM / run / "rebuild.json", data)


# ── R1 ───────────────────────────────────────────────────────────────────────

def prepare_r1(base_run: str, new_run: str | None = None) -> str:
    """A relocated copy of the base run, ready for the curator's action edits."""
    task = C.task_of_run(base_run)
    new_run = new_run or C.next_run_name(task)
    copied = C.copy_run(base_run, new_run)
    print(f"[rebuild] R1 prepared mem/{new_run}: {len(copied)} action files copied "
          f"from {base_run}")
    _record(new_run, {"path": "R1", "base_run": base_run, "stage": "prepared",
                      "at": C.now()})
    return new_run


def execute_r1(new_run: str, *, base_run: str | None = None,
               timeout: float = 1800.0, task: str | None = None) -> dict:
    """Replay the edited action sequence, save, render, and hash-compare."""
    t0 = time.time()
    rec = C.read_json(C.MEM / new_run / "rebuild.json", {}) or {}
    base_run = base_run or rec.get("base_run")
    task = task or C.task_of_run(base_run or new_run)
    if not C.blender_ready(fit_viewport=True):
        return {"ok": False, "error": "blender not ready"}
    C.blender_reset()
    dest = B.bundle_run(new_run, mode="replay", task=task, base_run=base_run, force=True)
    out = {"path": "R1", "base_run": base_run, "run": new_run, "ok": dest is not None,
           "seconds": round(time.time() - t0, 1), "at": C.now(), "stage": "done"}
    # The hash rule: geometry outside the corrected region must be identical.
    before = C.read_json(C.BLENDS / base_run / "geom_digest.json") if base_run else None
    if before is None and base_run:
        before = C.read_json(C.MEM / base_run / "geom_digest.json")
    after = C.read_json(C.MEM / new_run / "geom_digest.json")
    out["geometry"] = C.compare_digests(before, after)
    if not out["geometry"].get("measured"):
        out["geometry"]["note"] = ("base run has no geom_digest.json — bundle it once "
                                   "with --mode replay to get a baseline")
    _record(new_run, out)
    return out


# ── R2 ───────────────────────────────────────────────────────────────────────

def execute_r2(task: str, *, new_run: str | None = None, from_step: int | None = None,
               base_run: str | None = None, build_timeout: float = 6 * 3600,
               log: Path | None = None, prior_note: str = "") -> dict:
    t0 = time.time()
    new_run = new_run or C.next_run_name(task)
    steps = C.plan_steps(task)
    nums = [s["step_number"] for s in steps]
    if not nums:
        return {"ok": False, "error": "plan parses to zero steps"}
    if from_step and from_step > 1 and not base_run:
        return {"ok": False, "error": "--from-step needs --base"}
    if not C.blender_ready(fit_viewport=True):
        return {"ok": False, "error": "blender not ready"}
    C.blender_reset()

    only = None
    if from_step and from_step > 1:
        junk = C.MEM / new_run
        if junk.is_dir() and not checkpoint_steps(new_run) and not (junk / "rebuild.json").is_file():
            # a previous attempt of this round copied the prefix and then failed before
            # building anything: nothing of value, start the copy again
            shutil.rmtree(junk)
            print(f"[rebuild] removed the empty run folder mem/{new_run} left by a failed attempt")
        C.copy_run(base_run, new_run, upto_step=from_step)
        ok, err, n = C.batch_replay(new_run, upto_step=from_step, label="R2 prefix")
        if not ok:
            return {"ok": False, "error": f"prefix replay failed: {err[-500:]}",
                    "run": new_run}
        print(f"[rebuild] R2 from step {from_step}: {n} earlier action(s) replayed")
        only = ",".join(str(k) for k in nums if k >= from_step)

    # the plan is named explicitly: an executor may leave other .md files (a plate report)
    # in the plan folder, and resolve_task refuses to guess between two
    argv = [C.PY, C.ROOT / "blendcua_agent.py", "--task", task, "--run", new_run,
            "--plan", C.plan_path(task).name]
    if only:
        argv += ["--only-steps", only]
    write_prior_note(new_run, prior_note)
    log = log or (LOGS / f"{new_run}_build.log")
    rc = C.sh(argv, log=log, timeout=build_timeout)
    print(f"[rebuild] blendcua_agent rc={rc} ({(time.time() - t0) / 60:.0f} min)")
    out = {"path": "R2", "task": task, "run": new_run, "from_step": from_step,
           "base_run": base_run, "build_rc": rc, "log": str(rel_to(log, C.ROOT)),
           "prior_note": bool(prior_note), "at": C.now()}
    if rc != 0 and not (C.MEM / new_run / "steps").is_dir():
        out.update(ok=False, error=f"build failed rc={rc}")
        _record(new_run, out)
        return out
    dest = B.bundle_run(new_run, mode="live", base_run=base_run, force=True)
    out.update(ok=dest is not None, seconds=round(time.time() - t0, 1), stage="done")
    _record(new_run, out)
    return out


# ── resume: a build that died mid-step, and the step an R2 starts from ──────

_STEP_IN_PATH = re.compile(r"step[_-](\d{1,3})\b", re.I)
PRIOR_NOTE = "prior_attempt.md"


def checkpoint_steps(run: str) -> list[int]:
    d = C.MEM / run / "checkpoints"
    out = []
    for p in (d.glob("step_*.blend") if d.is_dir() else []):
        try:
            out.append(int(p.stem.split("_")[-1]))
        except ValueError:
            pass
    return sorted(out)


def resume_point(task: str, run: str) -> int | None:
    """The step a dead run can continue from: one past its highest end-of-step checkpoint,
    provided the plan has that step (a run checkpointed at its last step is not dead)."""
    ck = checkpoint_steps(run)
    if not ck:
        return None
    nums = [s["step_number"] for s in C.plan_steps(task)]
    nxt = max(ck) + 1
    return nxt if nxt in nums else None


def load_checkpoint(run: str, step: int) -> bool:
    """Open the end-of-step .blend the executor saved (the same file its own rewinds use)."""
    body = ("import sys\n"
            f"sys.path.insert(0, r'{C.TOOLS_CODE}')\n"
            "from checkpoint import load_step\n"
            f"_r = load_step({run!r}, {step})\n"
            "assert _r.get('ok'), _r.get('error')\n")
    st, dt = C.dispatch(body, 180, f"checkpoint {run} step {step}")
    ok = bool(st and st.get("ok"))
    print(f"[resume] checkpoint step {step} of {run} {'loaded' if ok else 'FAILED'} in {dt:.1f}s"
          + ("" if ok else f" — {str((st or {}).get('error'))[-200:]}"))
    return ok


def _park_partial_steps(run: str, from_step: int) -> list[str]:
    """Move the unfinished step folders (>= from_step) out of steps/ so the executor starts
    them clean. They stay beside the run as evidence of what the dead attempt did."""
    steps = C.MEM / run / "steps"
    dead = C.MEM / run / "steps_dead" / time.strftime("%Y%m%d_%H%M%S")
    moved = []
    for d in sorted(steps.glob("step_*")):
        m = C.STEP_RE.match(d.name)
        if m and int(m.group(1)) >= from_step:
            dead.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(dead / d.name))
            moved.append(d.name)
    return moved


def resume_run(task: str, run: str, *, log: Path | None = None,
               build_timeout: float = 6 * 3600) -> dict:
    """Continue a build that died: restore the scene from its last checkpoint (or, failing
    that, replay the finished steps' actions), park the unfinished step folders, and run the
    executor for the remaining steps IN PLACE, under the same run name."""
    t0 = time.time()
    n = resume_point(task, run)
    if n is None:
        return {"ok": False, "run": run,
                "error": "nothing to resume from (no checkpoint below an unbuilt step)"}
    if not C.blender_ready(fit_viewport=True):
        return {"ok": False, "error": "blender not ready", "run": run}
    C.blender_reset()
    how = f"checkpoint step {n - 1}"
    if not load_checkpoint(run, n - 1):
        ok, err, k = C.batch_replay(run, upto_step=n, label="resume prefix")
        if not ok:
            return {"ok": False, "error": f"prefix replay failed: {err[-500:]}", "run": run}
        how = f"replay of {k} action(s) below step {n}"
    parked = _park_partial_steps(run, n)
    nums = [s["step_number"] for s in C.plan_steps(task)]
    only = ",".join(str(k) for k in nums if k >= n)
    print(f"[resume] {run}: scene from {how}; parked {parked or 'nothing'}; "
          f"executor runs step(s) {only}")
    argv = [C.PY, C.ROOT / "blendcua_agent.py", "--task", task, "--run", run,
            "--plan", C.plan_path(task).name, "--only-steps", only]
    log = log or (LOGS / f"{run}_resume.log")
    rc = C.sh(argv, log=log, timeout=build_timeout)
    print(f"[resume] blendcua_agent rc={rc} ({(time.time() - t0) / 60:.0f} min)")
    return {"ok": rc == 0, "run": run, "from_step": n, "scene": how, "parked": parked,
            "build_rc": rc, "log": str(rel_to(log, C.ROOT)), "at": C.now(),
            "seconds": round(time.time() - t0, 1)}


def resume_rebuild(task: str, run: str, path: str, *, log: Path | None = None) -> dict:
    """A round's rebuild died mid-build: continue it in place, then bundle and record it the
    way execute_r2 would have."""
    t0 = time.time()
    out = resume_run(task, run, log=log)
    out.update(path=path, task=task, resumed=True)
    if not out.get("ok"):
        _record(run, out)
        return out
    dest = B.bundle_run(run, mode="live", force=True)
    out.update(ok=dest is not None, seconds=round(time.time() - t0, 1), stage="done")
    _record(run, out)
    return out


def _folder_time(p: Path) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(p.stat().st_ctime).strftime("%Y-%m-%d %H:%M:%S")


def dead_rebuild_run(task: str, st: dict, n: int, base_run: str) -> str | None:
    """The run a round-n rebuild was writing when its process died, if it can be continued:
    a run of the task that is not the base, not another round's, has no rebuild.json, was
    created after the round started, and has a checkpoint below an unbuilt step."""
    rounds = st.get("rounds") or {}
    rs = rounds.get(str(n)) or {}
    used = {v.get("new_run") for k, v in rounds.items() if k != str(n)}
    started = rs.get("started") or ""
    cands = [rs["new_run"]] if rs.get("new_run") else []
    for p in sorted(C.MEM.glob(f"{task}_run_*")):
        r = p.name
        if r == base_run or r in used or r in cands or not (p / "steps").is_dir():
            continue
        if started and _folder_time(p / "steps") < started:
            continue
        cands.append(r)
    for r in cands:
        if (C.MEM / r / "rebuild.json").is_file():
            continue
        if resume_point(task, r) is not None:
            return r
    return None


def changed_plan_steps(task: str, snap: Path) -> list[int]:
    """Plan steps whose parsed content differs between the round's store_before copy of the
    plan and the live plan (what the remedy step rewrote)."""
    import json
    import blendcua_core as core
    live = C.plan_path(task)
    old = snap / f"plans__{task}" / live.name
    if not old.is_file() or not live.is_file():
        return []

    def by_step(text):
        return {s["step_number"]: json.dumps(s, sort_keys=True, default=str)
                for s in core.parse_plan(text)}
    a = by_step(old.read_text(encoding="utf-8"))
    b = by_step(live.read_text(encoding="utf-8"))
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def derive_from_step(task: str, rems: list[dict], curation: dict, snap: Path) -> int | None:
    """R2: the first step to rebuild. The steps below it are copied from the base run and
    replayed, so a correct earlier part is not re-rolled to fix a later one.

    The remedy's own `from_step` decides when it gives one ("steps 1-2 are the same, copy
    them"); otherwise the step named by the chosen groups' attribution evidence and local_fix
    target. Either way the plan diff clamps it: a step the remedy rewrote cannot be replayed
    from actions written to the old plan. None = the whole build."""
    explicit: set[int] = set()
    evidence: set[int] = set()
    groups = {g.get("group_id"): g for g in curation.get("groups") or []}
    for r in rems:
        fs = r.get("from_step")
        if isinstance(fs, int) and not isinstance(fs, bool) and fs >= 1:
            explicit.add(fs)
        g = groups.get(r.get("group_id")) or {}
        for att in g.get("attribution") or []:
            for m in _STEP_IN_PATH.finditer(str(att.get("evidence") or "")):
                evidence.add(int(m.group(1)))
        lf = r.get("local_fix") or {}
        for m in _STEP_IN_PATH.finditer(str(lf.get("target") or "")):
            evidence.add(int(m.group(1)))
    steps = set(explicit) if explicit else set(evidence)
    steps.update(changed_plan_steps(task, snap))
    if not steps:
        return None
    n = min(steps)
    nums = [s["step_number"] for s in C.plan_steps(task)]
    return n if n > 1 and n in nums else None


def prior_attempt_note(task: str, base_run: str, subject: str, curation: dict,
                       rems: list[dict], from_step: int | None, *,
                       plan_rewritten: str | None = None) -> str:
    """The paragraph every step-subagent of a rebuild reads: where the previous attempt is,
    what of it was already replayed, that it may take code from it, and — in the remedy's
    own words — what must be built differently this time."""
    import json as _json
    defects = C.read_json(C.CHECKER_REPORTS / subject / "defects.json", {}) or {}
    by_id = {d.get("id"): d for d in defects.get("defects") or []}
    groups = {g.get("group_id"): g for g in curation.get("groups") or []}
    lines = [
        "## A previous attempt of this task exists — use it",
        "",
        f"This run is a rebuild. The previous attempt is `mem/{base_run}/`: its action files "
        f"are `steps/step_N/NN_*.py`, each step folder has a `handover.md` and "
        f"`review/round_*/review.txt`, and its renders are `blends/{subject}/views/`. The "
        f"checker's judgement of it is `Checker/reports/{subject}/defects.json` "
        f"(`notes.md` beside it).",
        "",
    ]
    if from_step and from_step > 1:
        span = ("Step 1 of that attempt was" if from_step == 2
                else f"Steps 1-{from_step - 1} of that attempt were")
        lines += [f"{span} copied into this run and replayed into the live scene: built "
                  f"already, handover(s) in this run's step folders, and you start at step "
                  f"{from_step}.", ""]
    else:
        lines += ["Nothing of it was copied: every step is built here.", ""]
    if plan_rewritten:
        lines += [f"The plan was rewritten since that attempt (the old plan is archived at "
                  f"`{plan_rewritten}`). Reuse only what still fits the plan you were given.", ""]
    lines += [
        "You may read that attempt and take code from it wherever it still fits the plan: "
        "setup, measurements, cameras, audit scripts, and every construction the checker "
        "did not fault. Replace every `mem/" + base_run + "` path with this run's, and run "
        "what you copy — the scene has to be built here, not assumed from the old files.",
        "",
        "**What must be built differently** — this rebuild exists to test exactly this, so "
        "copying the faulted construction and adjusting a number defeats it:",
    ]
    for r in rems:
        gid = r.get("group_id")
        g = groups.get(gid) or {}
        ids = g.get("defect_ids") or []
        lf = r.get("local_fix") or {}
        lines.append(f"- **{gid}** ({', '.join(ids)}): {lf.get('what') or '(see curation.json)'}")
        if lf.get("target"):
            lines.append(f"  The faulted construction: `{lf['target']}`.")
        if r.get("prior_reuse"):
            lines.append(f"  On reuse: {r['prior_reuse']}")
        for i in ids:
            d = by_id.get(i)
            if d:
                lines.append(f"  Checker on `{i}`: {d.get('summary', '')} Expected: "
                             f"{d.get('expected', '')}")
    lines += ["", f"(Round record: `Curator/reports/{task}/`, curation.json.)"]
    return "\n".join(lines) + "\n"


def write_prior_note(run: str, text: str) -> Path | None:
    if not text:
        return None
    p = C.MEM / run / PRIOR_NOTE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ── R3 ───────────────────────────────────────────────────────────────────────

def archive_plan(task: str) -> Path | None:
    src = C.PLANS / task
    if not src.is_dir():
        return None
    arch = C.PLANS / "_archive"
    arch.mkdir(exist_ok=True)
    dst = arch / f"{task}_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    # R3 asks whether the planner writes a better plan ON ITS OWN, so it must
    # start from the task alone. Leaving the previous plan (hand-corrected by
    # the remedy step) in the folder lets the planner read and copy it, which
    # turns R3 into R2 with extra steps: the first umbrella round showed the
    # planner reproducing the remedy's own datum name verbatim.
    for item in list(src.iterdir()):
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    print(f"[rebuild] previous plan archived -> plans/_archive/{dst.name}; "
          f"plans/{task}/ cleared for a clean replan")
    return dst


def execute_r3(task: str, *, new_run: str | None = None, planner_note: str = "",
               build_timeout: float = 6 * 3600, log: Path | None = None,
               prior_note: str = "") -> dict:
    t0 = time.time()
    new_run = new_run or C.next_run_name(task)
    archived = archive_plan(task)
    log = log or (LOGS / f"{new_run}_plan.log")
    argv = [C.PY, C.ROOT / "planner_agent.py", "--task", task, "--force"]
    if planner_note:
        argv += ["--note", planner_note]
    rc = C.sh(argv, log=log, timeout=3600)
    if rc != 0:
        out = {"ok": False, "path": "R3", "error": f"planner rc={rc}", "run": new_run,
               "plan_archived": str(archived) if archived else None,
               "log": str(rel_to(log, C.ROOT))}
        return out
    print(f"[rebuild] R3 replanned {task} in {(time.time() - t0) / 60:.0f} min")
    if prior_note and archived:
        prior_note = prior_note.replace("{plan_archived}", str(rel_to(archived, C.ROOT)))
    out = execute_r2(task, new_run=new_run, build_timeout=build_timeout, prior_note=prior_note)
    out.update(path="R3", plan_archived=str(rel_to(archived, C.ROOT)) if archived else None,
               plan_log=str(rel_to(log, C.ROOT)), seconds=round(time.time() - t0, 1))
    _record(new_run, out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild a task along R1, R2 or R3.")
    ap.add_argument("--path", choices=["R1", "R2", "R3"], default=None)
    ap.add_argument("--resume-build", action="store_true",
                    help="continue a dead build (--task --run) in place from its last checkpoint")
    ap.add_argument("--task", default=None)
    ap.add_argument("--base", default=None, help="base run (R1, or R2 --from-step)")
    ap.add_argument("--run", default=None, help="new run name (default: next free)")
    ap.add_argument("--from-step", type=int, default=None)
    ap.add_argument("--prepare-only", action="store_true", help="R1: copy the run and stop")
    ap.add_argument("--planner-note", default="")
    a = ap.parse_args()
    if a.resume_build:
        if not (a.task and a.run):
            ap.error("--resume-build needs --task and --run")
        out = resume_run(a.task, a.run)
        import json
        print(json.dumps(out, indent=2))
        raise SystemExit(0 if out.get("ok") else 1)
    if not a.path:
        ap.error("--path or --resume-build is required")
    if a.path == "R1":
        if not a.base:
            ap.error("R1 needs --base")
        run = a.run
        if not run or not (C.MEM / run).is_dir():
            run = prepare_r1(a.base, run)
        if a.prepare_only:
            print(run)
            return
        out = execute_r1(run, base_run=a.base)
    elif a.path == "R2":
        if not a.task:
            ap.error("R2 needs --task")
        out = execute_r2(a.task, new_run=a.run, from_step=a.from_step, base_run=a.base)
    else:
        if not a.task:
            ap.error("R3 needs --task")
        out = execute_r3(a.task, new_run=a.run, planner_note=a.planner_note)
    import json
    print(json.dumps(out, indent=2))
    raise SystemExit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
