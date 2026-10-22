"""Version B, one task: check -> curate -> remedy -> rebuild -> re-check -> keep.

    python vb/version_b.py --task 11_umbrella
    python vb/version_b.py --task 11_umbrella --rounds 2 --rebuild auto
    python vb/version_b.py --task 18_thors_hammer --stop-after curate
    python vb/version_b.py --task 11_umbrella --resume

The plan and the first build already exist (mem/<task>_run_001 and its
bundle blends/<task>/). This driver runs the lines of the algorithm after
them, project_vb_v2 section 2:

    5   Checker (discovery)      Checker/checker_agent.py --task T
    6-9 Curator                  Curator/curator_agent.py  -> round_NN/curation.json
    for at most two rounds:
   10   remedy                   Curator/apply_remedy.py   -> round_NN/apply/applied.json
   11   rebuild path             widest of the chosen remedies (R1 < R2 < R3)
   12   rebuild once             vb/rebuild.py             -> blends/<new_run>/
   13   Checker (verdict)        checker_agent.py --verdict-from -> verdict.json
   14   keep / drop              vb/accept.py              -> round_NN/acceptance.json
   15   nothing closed?          next round, with a note asking for a bigger remedy
   16   log unacted / survived   vb/harness_log.jsonl
   17   snapshot H_i             feedback_agent.py --snapshot, plus a note

State is in vb/state/<task>/state.json; every stage is resumable.
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[1])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C      # noqa: E402
import bundle as B      # noqa: E402
import rebuild as R     # noqa: E402
import accept as A      # noqa: E402

PATH_RANK = {"none": 0, "R1": 1, "R2": 2, "R3": 3}
STAGES = ("check", "curate", "apply", "rebuild", "verdict", "accept")


def _state_path(task: str) -> Path:
    return C.VB_STATE / task / "state.json"


def load_state(task: str) -> dict:
    return C.read_json(_state_path(task), {"task": task, "rounds": {}}) or {"task": task, "rounds": {}}


def save_state(st: dict) -> None:
    st["updated"] = C.now()
    C.write_json(_state_path(st["task"]), st)


def round_dir(task: str, n: int) -> Path:
    return C.CURATOR_REPORTS / task / f"round_{n:02d}"


def latest_original_run(task: str) -> str | None:
    cands = sorted(p.name for p in C.MEM.glob(f"{task}_run_*") if (p / "steps").is_dir())
    return cands[0] if cands else None


# ── stages ───────────────────────────────────────────────────────────────────

def defects_for(subject: str) -> Path:
    return C.CHECKER_REPORTS / subject / "defects.json"


def stage_check(task: str, base_subject: str, log: Path) -> Path:
    out = defects_for(base_subject)
    if out.is_file():
        print(f"[vb] discovery report exists: {rel_to(out, C.ROOT)}")
        return out
    rc = C.sh([C.PY, C.CHECKER_DIR / "checker_agent.py", "--task", task,
               "--subject", base_subject, "--out", C.CHECKER_REPORTS / base_subject,
               "--retries", "1"],
              log=log)
    if rc != 0 or not out.is_file():
        raise SystemExit(f"[vb] checker discovery failed (rc={rc})")
    return out


def stage_curate(task: str, base_run: str, n: int, note: str, log: Path,
                 subject: str | None = None) -> Path:
    subject = subject or task
    rd = round_dir(task, n)
    if (rd / "curation.json").is_file():
        print(f"[vb] curation exists: {rel_to(rd, C.ROOT)}")
        return rd
    legacy = C.CURATOR_REPORTS / task
    if n == 1 and subject == task and (legacy / "curation.json").is_file():
        rd.mkdir(parents=True, exist_ok=True)
        for f in legacy.iterdir():
            if f.is_file():
                shutil.copy2(f, rd / f.name)
        print(f"[vb] reused the existing curation from {rel_to(legacy, C.ROOT)}")
        return rd
    rd.mkdir(parents=True, exist_ok=True)
    argv = [C.PY, C.CURATOR_DIR / "curator_agent.py", "--task", task, "--run", base_run,
            "--out", rd, "--retries", "1", "--subject", subject,
            "--defects", defects_for(subject)]
    if note:
        argv += ["--note", note]
    rc = C.sh(argv, log=log)
    if rc != 0 or not (rd / "curation.json").is_file():
        raise SystemExit(f"[vb] curator failed (rc={rc})")
    return rd


def chosen_paths(curation: dict) -> tuple[str, list[dict]]:
    chosen = {g.get("group_id") for g in curation.get("groups") or [] if g.get("chosen")}
    rems = [r for r in curation.get("remedies") or [] if r.get("group_id") in chosen]
    widest = "none"
    for r in rems:
        p = r.get("rebuild") or "none"
        if PATH_RANK.get(p, 0) > PATH_RANK[widest]:
            widest = p
    return widest, rems


def stage_apply(task: str, rd: Path, run_for_r1: str | None, base_run: str,
                prior_note: str, log: Path) -> dict:
    out = rd / "apply"
    applied = C.read_json(out / "applied.json")
    if applied and not applied.get("problems"):
        print(f"[vb] remedies already applied: {rel_to(out, C.ROOT)}")
        return applied
    argv = [C.PY, C.CURATOR_DIR / "apply_remedy.py", "--task", task,
            "--curation", rd / "curation.json", "--out", out, "--base-run", base_run]
    if run_for_r1:
        argv += ["--run", run_for_r1]
    if prior_note:
        argv += ["--prior-note", prior_note]
    rc = C.sh(argv, log=log)
    applied = C.read_json(out / "applied.json", {}) or {}
    if rc != 0 or applied.get("problems"):
        applied["failed"] = True
    return applied


def stage_verdict(task: str, new_run: str, log: Path, subject: str | None = None) -> Path:
    out_dir = C.CHECKER_REPORTS / new_run
    out = out_dir / "verdict.json"
    if out.is_file():
        print(f"[vb] verdict exists: {rel_to(out, C.ROOT)}")
        return out
    rc = C.sh([C.PY, C.CHECKER_DIR / "checker_agent.py", "--task", task,
               "--subject", new_run, "--out", out_dir,
               "--verdict-from", defects_for(subject or task),
               "--retries", "1"], log=log)
    if rc != 0 or not out.is_file():
        raise SystemExit(f"[vb] checker verdict failed (rc={rc})")
    return out


def stage_lessons(task: str, base_run: str, defects: Path, log: Path) -> dict:
    out = C.CURATOR_REPORTS / task / "lessons"
    if (out / "lessons.json").is_file():
        print(f"[vb] lessons exist: {rel_to(out, C.ROOT)}")
        return C.read_json(out / "lessons.json", {}) or {}
    argv = [C.PY, C.CURATOR_DIR / "lessons_agent.py", "--task", task, "--run", base_run,
            "--out", out, "--defects", defects]
    rc = C.sh(argv, log=log)
    data = C.read_json(out / "lessons.json", {}) or {}
    data["rc"] = rc
    print(f"[vb] lessons: {len(data.get('lessons') or [])} lesson(s) -> {data.get('files')}"
          + ("" if rc == 0 else f" (rc={rc}, not published)"))
    if rc != 0:
        data["files"] = []
    return data


def stage_salvage(task: str, n: int, rd: Path, verdict: Path, summary: dict, log: Path) -> dict:
    """A dropped remedy that closed something: extract the working part into skills."""
    out = rd / "salvage"
    if (out / "salvage.json").is_file():
        print(f"[vb] salvage exists: {rel_to(out, C.ROOT)}")
        return C.read_json(out / "salvage.json", {}) or {}
    store_after = C.VB_STATE / task / f"round_{n:02d}" / "store_after"
    argv = [C.PY, C.CURATOR_DIR / "lessons_agent.py", "--task", task, "--run", summary.get("base_run") or "",
            "--out", out, "--mode", "salvage", "--round-dir", rd, "--verdict", verdict,
            "--store-after", store_after, "--groups", ",".join(summary.get("salvage") or [])]
    rc = C.sh(argv, log=log)
    data = C.read_json(out / "salvage.json", {}) or {}
    data["rc"] = rc
    if rc != 0:
        data["files"] = []
    print(f"[vb] salvage: {len(data.get('lessons') or [])} lesson(s) -> {data.get('files')}"
          + ("" if rc == 0 else f" (rc={rc}, not published)"))
    return data


def snapshot_harness(task: str, note: str) -> Path | None:
    before = {p.name for p in C.SNAPSHOTS.glob("H_*")}
    C.sh([C.PY, C.ROOT / "feedback_agent.py", "--snapshot"])
    new = sorted({p.name for p in C.SNAPSHOTS.glob("H_*")} - before)
    if not new:
        return None
    dst = C.SNAPSHOTS / new[-1]
    (dst / "VERSION_B_NOTE.md").write_text(note, encoding="utf-8")
    return dst


def prior_round_note(task: str, st: dict, n: int) -> str:
    """What the previous round tried and how it ended, for round n's curator."""
    prev = st["rounds"].get(str(n - 1)) or {}
    acc = C.read_json(round_dir(task, n - 1) / "acceptance.json", {}) or {}
    if not acc:
        return ""
    lines = [f"This is round {n}. Round {n - 1} acted on "
             f"{', '.join(r['group_id'] + f' (case {r.get('case')}, {acc.get('rebuild_path')})' for r in acc.get('results', []))} "
             f"and rebuilt as {prev.get('new_run') or acc.get('rebuild_path')}. Outcome:"]
    for r in acc.get("results", []):
        lines.append(f"- {r['group_id']}: {'KEPT' if r['keep'] else 'DROPPED'} — "
                     f"statuses {r['statuses']}; {'; '.join(r['reasons']) or 'closed'}")
    if acc.get("new_majors"):
        lines.append(f"- new major defects in the rebuilt model: "
                     f"{[m.get('id') for m in acc['new_majors']]}")
    lines.append("The harness was reverted to its state before that round, so the "
                 "dropped edits are gone. Go round again with a DIFFERENT remedy, "
                 "usually a bigger one: a tool where a skill was not enough, a plan "
                 "constraint where wording was not enough, R3 where R2 did not "
                 "change the planner's behaviour. Do not propose the same edit again. "
                 "Groups whose defect closed and was kept need no further action; "
                 "pick from the rest, majors first.")
    prev_dir = rel_to(round_dir(task, n - 1), C.ROOT).as_posix()
    lines.append(f"Round {n - 1}'s files: `{prev_dir}/curation.json`, "
                 f"`{prev_dir}/apply/applied.json`, `{prev_dir}/acceptance.json`, and the "
                 f"rebuilt model's verdict at `Checker/reports/{prev.get('new_run')}/verdict.json` "
                 f"(read it: it says how each defect looked after the rebuild).")
    return "\n".join(lines)


# ── the loop ─────────────────────────────────────────────────────────────────

def run_task(task: str, *, base_run: str | None, rounds: int, rebuild_override: str | None,
             from_step: int | None, stop_after: str | None, resume: bool,
             skip_snapshot: bool, lenient_new_majors: bool, dry_run: bool,
             lessons_ok: bool = True) -> dict:
    st = load_state(task)
    base_run = base_run or st.get("base_run") or latest_original_run(task)
    if not base_run:
        raise SystemExit(f"[vb] no run folder for {task} under mem/")
    st["base_run"] = base_run
    # The judged model: the task's own bundle for the original build, or the
    # run's bundle when a later round starts from a rebuilt model.
    if base_run != latest_original_run(task) and (C.BLENDS / base_run / "views").is_dir():
        base_subject = base_run
    else:
        base_subject = task if (C.BLENDS / task / "views").is_dir() else base_run
    st["base_subject"] = base_subject
    logs = C.VB_STATE / task / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    save_state(st)
    print(f"[vb] task={task} base_run={base_run} subject={base_subject} rounds={rounds}")

    if dry_run:
        print(json.dumps(st, indent=2))
        return st

    # 5. discovery
    defects = stage_check(task, base_subject, logs / "check.log")
    dlist = (C.read_json(defects, {}) or {}).get("defects") or []
    n_defects = len(dlist)
    n_major = sum(1 for d in dlist if str(d.get("severity", "")).lower() == "major")
    print(f"[vb] {n_defects} defect(s) on the original build, {n_major} major")
    if stop_after == "check":
        return st
    if n_major == 0 and not lessons_ok:
        print("[vb] no major defect, but the build did not pass every review: no lessons, no round")
        st["lessons"] = {"files": [], "skipped": "reviews not all PASS"}
        st["finished"] = C.now(); save_state(st)
        return st
    if n_major == 0:
        # 5b. nothing major: the build is a good one; record why as skills (lessons agent),
        # through the same accept door as a remedy (the driver publishes st["lessons"]["files"])
        if not st.get("lessons") or not (st.get("lessons") or {}).get("files"):
            st["lessons"] = stage_lessons(task, base_run, defects, logs / "lessons.log")
            save_state(st)
            if not skip_snapshot and (st["lessons"] or {}).get("files"):
                note = (f"# Version B — {task}\n\nLessons (no major defect): "
                        f"{', '.join(st['lessons']['files'])}\n")
                snap = snapshot_harness(task, note)
                st["snapshot"] = str(rel_to(snap, C.ROOT)) if snap else None
        st["finished"] = C.now()
        save_state(st)
        return st

    kept_total: list[str] = []
    salvage_files: list[str] = []
    start_round = 1
    if resume:
        done = [int(k) for k, v in st["rounds"].items() if v.get("stage") == "accept"]
        start_round = (max(done) + 1) if done else 1
        kept_total = st.get("kept", [])

    for n in range(start_round, rounds + 1):
        rs = st["rounds"].setdefault(str(n), {"started": C.now()})
        # a resumed round whose rebuild already finished (bundle in place) must not be
        # marked back to "curate"/"apply" by the stages below re-finding their files,
        # or the loop rebuilds it again — for an R3 that means replanning from scratch
        done_rebuild = rs.get("stage") in ("rebuild", "verdict", "accept") and bool(rs.get("bundle_ok"))
        rd = round_dir(task, n)
        note = prior_round_note(task, st, n) if n > 1 else ""

        # 6-9. curate
        stage_curate(task, base_run, n, note, logs / f"round{n}_curate.log",
                     subject=base_subject)
        curation = C.read_json(rd / "curation.json", {})
        widest, rems = chosen_paths(curation)
        path = rebuild_override or widest
        rs.update(stage=("rebuild" if done_rebuild else "curate"), widest=widest, path=path,
                  groups=[r.get("group_id") for r in rems])
        save_state(st)
        print(f"[vb] round {n}: {len(rems)} remedy(ies), widest path {widest}, using {path}")
        if stop_after == "curate":
            return st
        if (C.ROOT / "STOP_BEFORE_REMEDY").is_file():
            # a hand-placed stop: judge and blame, but change nothing in the store
            print(f"[vb] round {n}: STOP_BEFORE_REMEDY is present — stopping before the remedy "
                  f"is applied (delete the file and rerun to continue)")
            return st

        # snapshot the store so a dropped remedy can be undone
        snap = C.VB_STATE / task / f"round_{n:02d}" / "store_before"
        if not (snap / "_manifest.json").is_file():
            C.snapshot_store(snap, task)
        rs["snapshot"] = str(rel_to(snap, C.ROOT))

        # 10. remedy
        new_run = rs.get("new_run")
        if path == "R1" and not new_run:
            new_run = R.prepare_r1(base_run)
            rs["new_run"] = new_run
            save_state(st)
        applied = stage_apply(task, rd, new_run if path == "R1" else None, base_run,
                              note, logs / f"round{n}_apply.log")
        if applied.get("failed"):
            print("[vb] remedy step did not pass the guards — reverting the store")
            A.restore_whole_store(snap, task, rd)
            rs.update(stage="apply_failed")
            save_state(st)
            C.log_event({"event": "round_apply_failed", "task": task, "round": n,
                         "problems": applied.get("problems")})
            continue
        rs["stage"] = "rebuild" if done_rebuild else "apply"
        save_state(st)
        if any(r.get("ripples") for r in applied.get("remedies") or []) and path == "R1":
            print("[vb] an R1 correction ripples into later actions — escalating to R2")
            path = "R2"
            rs["path"] = path
        if path == "none":
            # reviewer-only remedies: no rebuild, kept on citation (cases 8, 9, 11)
            rs.update(stage="accept", kept=[r.get("group_id") for r in rems], no_rebuild=True)
            kept_total += rs["kept"]
            C.log_event({"event": "round_no_rebuild", "task": task, "round": n,
                         "kept_on_citation": rs["kept"]})
            save_state(st)
            break
        if stop_after == "apply":
            return st

        # 11-12. rebuild once
        if rs.get("stage") not in ("rebuild", "verdict", "accept") or not rs.get("bundle_ok"):
            dead = R.dead_rebuild_run(task, st, n, base_run) if path in ("R2", "R3") else None
            if dead:
                # the previous process died inside this round's rebuild: continue that run
                # from its last end-of-step checkpoint instead of building it again
                print(f"[vb] round {n}: rebuild {dead} died mid-build — continuing it from "
                      f"its last checkpoint")
                out = R.resume_rebuild(task, dead, path, log=logs / f"round{n}_build_resumed.log")
            elif path == "R1":
                out = R.execute_r1(new_run, base_run=base_run)
            elif path == "R2":
                # start at the first step the remedy touches; the steps below it are copied
                # from the base run and replayed, so a correct part is not re-rolled to fix
                # a later one. The rebuild's subagents read prior_attempt.md: the old run,
                # what they may take from it, what must be new.
                fs = from_step or R.derive_from_step(task, rems, curation, snap)
                rs["from_step"] = fs
                if fs:
                    print(f"[vb] round {n}: R2 from step {fs} — steps below it replayed from {base_run}")
                note_txt = R.prior_attempt_note(task, base_run, base_subject, curation, rems, fs)
                out = R.execute_r2(task, new_run=new_run, from_step=fs,
                                   base_run=base_run if fs else None,
                                   log=logs / f"round{n}_build.log", prior_note=note_txt)
            else:
                note_txt = R.prior_attempt_note(task, base_run, base_subject, curation, rems, None,
                                                plan_rewritten="{plan_archived}")
                out = R.execute_r3(task, new_run=new_run, log=logs / f"round{n}_plan.log",
                                   prior_note=note_txt)
            new_run = out.get("run") or new_run
            rs.update(new_run=new_run, rebuild=out, bundle_ok=bool(out.get("ok")),
                      stage="rebuild")
            save_state(st)
            if not out.get("ok"):
                print(f"[vb] rebuild failed: {out.get('error')} — reverting the store")
                A.restore_whole_store(snap, task, rd)
                rs["stage"] = "rebuild_failed"
                save_state(st)
                C.log_event({"event": "round_rebuild_failed", "task": task, "round": n,
                             "error": out.get("error"), "run": new_run})
                continue
        if stop_after == "rebuild":
            return st

        # 13. verdict
        verdict = stage_verdict(task, new_run, logs / f"round{n}_verdict.log",
                                subject=base_subject)
        rs["stage"] = "verdict"
        save_state(st)
        if stop_after == "verdict":
            return st

        # 14. keep / drop
        summary = A.decide(task, rd, verdict, C.MEM / new_run / "rebuild.json", snap,
                           strict_new_majors=not lenient_new_majors)
        rs.update(stage="accept", kept=summary["kept"], dropped=summary["dropped"],
                  survived=summary["survived"])
        kept_total += summary["kept"]
        st["kept"] = kept_total
        save_state(st)
        print(f"[vb] round {n}: kept {summary['kept'] or 'nothing'}, "
              f"dropped {summary['dropped'] or 'nothing'}, "
              f"{len(summary['survived'])} defect(s) survive")
        if summary.get("salvage"):
            # 14b. dropped but partly right: keep the lesson, not the edit
            summary["base_run"] = base_run
            rs["salvage"] = stage_salvage(task, n, rd, verdict, summary, logs / f"round{n}_salvage.log")
            salvage_files += rs["salvage"].get("files") or []
            save_state(st)
        if summary["kept"]:
            base_for_next = new_run
            # a kept edit means the rebuilt model is the better one; later rounds
            # would need a fresh discovery on it, which is out of this task's budget
            break

    # 17. snapshot
    if not skip_snapshot and (kept_total or salvage_files):
        note = (f"# Version B — {task}\n\nKept: {', '.join(kept_total)}\n\n"
                f"See Curator/reports/{task}/round_*/accepted/*.json for the before/after "
                f"of every kept edit and vb/harness_log.jsonl for the rest.\n")
        snap = snapshot_harness(task, note)
        st["snapshot"] = str(rel_to(snap, C.ROOT)) if snap else None
    st["finished"] = C.now()
    save_state(st)
    C.log_event({"event": "task_done", "task": task, "kept": kept_total,
                 "rounds": {k: {kk: v.get(kk) for kk in ("stage", "path", "new_run", "kept", "dropped")}
                            for k, v in st["rounds"].items()}})
    return st


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Version B on one task.")
    ap.add_argument("--task", required=True)
    ap.add_argument("--run", default=None, help="the original run (default: <task>_run_001)")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--rebuild", choices=["auto", "R1", "R2", "R3"], default="auto",
                    help="override the rebuild path (default: widest the curator chose)")
    ap.add_argument("--from-step", type=int, default=None,
                    help="R2 only: replay steps below this from the base run, rebuild the rest "
                         "(default: the remedy's from_step, else the step its evidence names; "
                         "see rebuild.derive_from_step)")
    ap.add_argument("--stop-after", choices=list(STAGES), default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--skip-snapshot", action="store_true")
    ap.add_argument("--no-lessons", action="store_true", help="the build did not pass every review: never write lessons from it")
    ap.add_argument("--lenient-new-majors", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    st = run_task(a.task, base_run=a.run, rounds=a.rounds,
                  rebuild_override=None if a.rebuild == "auto" else a.rebuild,
                  from_step=a.from_step, stop_after=a.stop_after, resume=a.resume,
                  skip_snapshot=a.skip_snapshot, lenient_new_majors=a.lenient_new_majors,
                  lessons_ok=not a.no_lessons,
                  dry_run=a.dry_run)
    print(json.dumps({k: st.get(k) for k in ("task", "base_run", "kept", "snapshot")}, indent=2))


if __name__ == "__main__":
    main()
