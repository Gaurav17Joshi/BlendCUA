"""Project v2 over the task set, resumable, with a ledger.

    python run_v2.py                     # do whatever is not done yet, for every task in tasks/train, then stop
    python run_v2.py --parallel 2        # two Blenders: builds side by side, harness edits one at a time
    python run_v2.py --status            # print the ledger (tasks/PROGRESS.csv) and stop
    python run_v2.py --tasks 01_datestone_1934,04_skull
    python run_v2.py --dry-run
    python run_v2.py --split test --skip-vb --retry-budget 0 --parallel 2   # a test pass: build only, one review round

Continuing after a stop: run the same command again. Every stage checks what is already on
disk before it runs, so a stopped run picks up at the first thing not done. Nothing is redone.

The ledger, tasks/PROGRESS.csv, is written after every stage and rebuilt from disk at start:
one row per task folder in tasks/train (add a folder, it gets a row), one column per stage
(plan, build, bundle, round1..N). A cell you set to "skip" by hand is honoured.

Stages per task, and what "done" means on disk:
    plan      plans/<task>/*_plan.md exists                          planner_agent.py
    build     mem/<task>_run_001/steps/ has every plan step, each      blendcua_agent.py (executor + reviewer)
              with at least one review round
    bundle    blends/<run>/views/final_render.png exists               vb/bundle.py (live scene, or replay for an imported run)
    roundN    vb/state/<task>/state.json round N reached "accept"      vb/version_b.py (checker, blame, remedy, rebuild, verdict, accept)
    snapshot  taken inside version_b if anything was kept

Runs made elsewhere can be imported so plan and build count as done:
    python vb/import_run.py --from ../BlendCuaLoop_try --run 04_datestone_1934_run_001 --as 01_datestone_1934_run_001 --plan

Two workers and the harness. Builds only READ the store (Skills, Tools, prompts); the remedy,
rebuild, verdict and accept part of a round WRITES it. The rule enforced here: no build runs
while a writer runs or waits, and one writer at a time. The checker (renders only) runs beside
anything; the blame agent reads the store, so it counts as a reader like a build. So the day goes: build two, fix one after the other, build the
next two. Every build sees one fixed harness.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vb"))

TASKS = ROOT / "tasks"
PLANS = ROOT / "plans"
MEM = ROOT / "mem"
BLENDS = ROOT / "blends"
CURATOR_REPORTS = ROOT / "Curator" / "reports"
VB_STATE = ROOT / "vb" / "state"
EXEMPLARS = PLANS / "EXEMPLARS.txt"
# the tasks queued in this driver session: each worker view leaves the others' task-keyed
# folders out (harness.sync hide=), so two tasks running side by side cannot see each other
SESSION_TASKS: list[str] = []
LEDGER = TASKS / "PROGRESS.csv"
# which task folder the session runs: tasks/train (the loop) or tasks/test (--split test); a test
# session keeps its own ledger, tasks/PROGRESS_test.csv, and never adds to plans/EXEMPLARS.txt
SPLIT = "train"
LOG = ROOT / "run_v2.log"
PY = sys.executable
BASE_PORT = 6666

# ── the store gate: builds are readers, harness edits are the writer ─────────
_gate = threading.Condition()
_builds_running = 0
_writer_active = False
_writers_waiting = 0
_io_lock = threading.Lock()


def build_begin() -> None:
    global _builds_running
    with _gate:
        while _writer_active or _writers_waiting:
            _gate.wait()
        _builds_running += 1


def build_end() -> None:
    global _builds_running
    with _gate:
        _builds_running -= 1
        _gate.notify_all()


def writer_begin() -> None:
    global _writer_active, _writers_waiting
    with _gate:
        _writers_waiting += 1
        while _writer_active or _builds_running:
            _gate.wait()
        _writers_waiting -= 1
        _writer_active = True


def writer_end() -> None:
    global _writer_active
    with _gate:
        _writer_active = False
        _gate.notify_all()


# ── what is on disk ──────────────────────────────────────────────────────────

def task_list() -> list[str]:
    d = TASKS / SPLIT
    return sorted(p.name for p in d.iterdir() if p.is_dir() and (p / "task.md").is_file())


def plan_file(task: str) -> Path | None:
    hits = sorted((PLANS / task).glob("*_plan.md"))
    return hits[0] if hits else None


def plan_done(task: str) -> bool:
    return plan_file(task) is not None


def plan_step_count(task: str) -> int:
    pf = plan_file(task)
    if not pf:
        return 0
    try:
        import blendcua_core as core
        return len(core.parse_plan(pf.read_text(encoding="utf-8")))
    except Exception:
        return 0


def task_runs(task: str) -> list[str]:
    return sorted(p.name for p in MEM.glob(f"{task}_run_*") if (p / "steps").is_dir())


def review_verdict(step_dir: Path) -> str | None:
    # the newest round that has a review.txt: a reviewer can mkdir a round_NN folder of its own for
    # scratch files (t04_chess_knight step 1, 2026-09-19, made round_02 during its only review), and
    # taking that empty folder as the last round marked a finished build unfinished
    rounds = sorted((step_dir / "review").glob("round_*")) if (step_dir / "review").is_dir() else []
    rounds = [r for r in rounds if (r / "review.txt").is_file()]
    if not rounds:
        return None
    txt = rounds[-1] / "review.txt"
    lines = [l.strip(" *_#") for l in txt.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    for l in reversed(lines[-5:]):
        u = l.upper()
        for v in ("PASS", "FAIL", "EXHAUSTED", "TRY AGAIN", "TRY_AGAIN"):
            if u.startswith(v):
                return v.replace(" ", "_")
    return "UNKNOWN"


def run_state(run: str, want: int) -> tuple[bool, bool]:
    """(done, passed) for one run. Only step_NN *folders* count: an executor can drop a note beside
    them (t05_demon_cauldron_run_001 wrote steps/step_004_measure_skill.txt, 2026-09-20), and reading
    that file as a step with no review marked a finished build unfinished."""
    steps = sorted(s for s in (MEM / run / "steps").glob("step_*") if s.is_dir())
    verdicts = [review_verdict(s) for s in steps]
    done = bool(steps) and (want == 0 or len(steps) >= want) and all(v is not None for v in verdicts)
    return done, done and all(v == "PASS" for v in verdicts)


def build_done(task: str) -> tuple[bool, str | None, bool]:
    """(done, run, passed). done = some run has every plan step, each reviewed at least once.

    The oldest finished run wins -- the one the driver would have settled on had it never miscounted.
    A run that died early stays on disk beside the run that replaced it (t08_low_poly_rabbit_run_001,
    2026-09-20: one step, no review), and judging the task by that corpse reported a finished build as
    unfinished; t05_demon_cauldron was rebuilt from scratch over four hours because of it. Skipping
    the corpses rather than jumping to the newest run also keeps a bundle made from an earlier
    finished run valid, so the repair costs no extra rendering.
    When nothing is finished, the newest run is the one to resume.
    """
    runs = task_runs(task)
    if not runs:
        return False, None, False
    want = plan_step_count(task)
    for run in runs:
        done, passed = run_state(run, want)
        if done:
            return True, run, passed
    return False, runs[-1], False


def resume_step(task: str, run: str | None) -> int | None:
    """A run that died mid-build can go on from one past its highest end-of-step checkpoint."""
    if not run:
        return None
    ck = []
    for p in (MEM / run / "checkpoints").glob("step_*.blend"):
        try:
            ck.append(int(p.stem.split("_")[-1]))
        except ValueError:
            pass
    if not ck:
        return None
    n = max(ck) + 1
    return n if n <= plan_step_count(task) else None


def bundle_done(run: str | None) -> bool:
    return bool(run) and (BLENDS / run / "views" / "final_render.png").is_file()


def vb_state(task: str) -> dict:
    st = VB_STATE / task / "state.json"
    try:
        return json.loads(st.read_text(encoding="utf-8")) if st.is_file() else {}
    except Exception:
        return {}


def rounds_done(task: str) -> list[int]:
    return sorted(int(k) for k, v in (vb_state(task).get("rounds") or {}).items() if v.get("stage") == "accept")


def kept(task: str) -> list[str]:
    return vb_state(task).get("kept") or []


# ── the ledger ───────────────────────────────────────────────────────────────

def ledger_columns(rounds: int) -> list[str]:
    return ["task", "plan", "build", "run", "passed", "bundle"] + [f"round{n}" for n in range(1, rounds + 1)] + ["kept", "note"]


def read_ledger() -> dict[str, dict]:
    if not LEDGER.is_file():
        return {}
    with LEDGER.open(encoding="utf-8", newline="") as f:
        return {r["task"]: r for r in csv.DictReader(f)}


def refresh_ledger(rounds: int, notes: dict[str, str] | None = None) -> dict[str, dict]:
    """Rebuild every row from disk; keep hand-written 'skip' cells and notes."""
    with _io_lock:
        old = read_ledger()
        rows = {}
        for task in task_list():
            o = old.get(task, {})
            done, run, passed = build_done(task)
            r = {"task": task,
                 "plan": "done" if plan_done(task) else "",
                 "build": "done" if done else ("started" if run else ""),
                 "run": run or "",
                 "passed": "yes" if passed else ("no" if done else ""),
                 "bundle": "done" if bundle_done(run) else ""}
            rd = rounds_done(task)
            for n in range(1, rounds + 1):
                r[f"round{n}"] = "done" if n in rd else ""
            r["kept"] = ";".join(kept(task))
            note = (notes or {}).get(task)
            r["note"] = note if note is not None else o.get("note", "")
            for col in ("plan", "build", "bundle") + tuple(f"round{n}" for n in range(1, rounds + 1)):
                if o.get(col) == "skip":
                    r[col] = "skip"
            rows[task] = r
        cols = ledger_columns(rounds)
        with LEDGER.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for task in task_list():
                w.writerow({c: rows[task].get(c, "") for c in cols})
        return rows


def print_ledger(rows: dict[str, dict], rounds: int) -> None:
    cols = ledger_columns(rounds)
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows.values())) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows.values():
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


# ── running things ───────────────────────────────────────────────────────────

def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with _io_lock:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _rebase(a, here: Path):
    """A script path under ROOT becomes the same path inside the worker's view."""
    if isinstance(a, Path) and here != ROOT:
        try:
            return here / a.relative_to(ROOT)
        except ValueError:
            return a
    return a


def sh(argv: list, port: int, view: Path | None = None) -> int:
    here = view or ROOT
    argv = [_rebase(a, here) for a in argv]
    tag = f"[port {port}{' ' + here.name if view else ''}] "
    log(f"$ {tag}" + " ".join(str(a) for a in argv[1:]))
    env = dict(os.environ, BLENDCUA_PORT=str(port), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.call([str(a) for a in argv], cwd=here, env=env)


def ready(port: int, task: str, view: Path | None = None) -> bool:
    rc = subprocess.call([PY, "-c", "import blender_health as h, sys; sys.exit(0 if h.ensure_ready(task=%r) else 1)" % task],
                         cwd=view or ROOT, env=dict(os.environ, BLENDCUA_PORT=str(port)))
    return rc == 0


_PUBLISH_LOCK = threading.Lock()


def publish_kept(task: str, k: int, a) -> None:
    """After a round: merge what the worker's branch kept (remedy files or lessons) into main."""
    import harness
    st = vb_state(task)
    files: list[str] = []
    what: list[str] = []
    for n, r in sorted((st.get("rounds") or {}).items()):
        if r.get("stage") == "accept" and r.get("kept") and not r.get("published"):
            applied = json.loads((CURATOR_REPORTS / task / f"round_{int(n):02d}" / "apply" / "applied.json").read_text(encoding="utf-8")) \
                if (CURATOR_REPORTS / task / f"round_{int(n):02d}" / "apply" / "applied.json").is_file() else {}
            files += harness.files_from_applied(applied)
            what.append(f"round {n} kept {', '.join(r['kept'])}")
            r["published"] = True
    for n, r in sorted((st.get("rounds") or {}).items()):
        sv = r.get("salvage") or {}
        if sv.get("files") and not sv.get("published"):
            files += [f for f in sv["files"] if f.startswith("Skills/")]
            what.append(f"round {n} salvaged lessons from a dropped remedy")
            sv["published"] = True
    les = st.get("lessons") or {}
    if les.get("files") and not les.get("published"):
        files += [f for f in les["files"] if f.startswith("Skills/")]
        what.append(f"lessons: {les.get('summary', '')[:80]}")
        les["published"] = True
    if not files:
        return
    note = f"# Version B — {task} (worker {k})\n\n" + "\n".join(what) + "\n"
    with _PUBLISH_LOCK:
        rep = harness.publish(k, task, sorted(set(files)), f"{task}: " + "; ".join(what), snapshot_note=note)
    if rep.get("merged"):
        (VB_STATE / task / "state.json").write_text(json.dumps(st, indent=2), encoding="utf-8")
        log(f"{task}: published {len(rep['files'])} file(s) from worker {k} into main ({rep.get('main')}), snapshot {rep.get('snapshot')}")
    else:
        log(f"{task}: publish from worker {k} did not merge: {rep.get('error') or 'nothing to publish'}")


def add_exemplar(task: str) -> None:
    names = [l.strip() for l in EXEMPLARS.read_text(encoding="utf-8").splitlines()] if EXEMPLARS.is_file() else []
    if task not in names:
        with EXEMPLARS.open("a", encoding="utf-8") as f:
            f.write(task + "\n")
        log(f"{task} passed every review: added to plans/EXEMPLARS.txt")


class Stop(Exception):
    pass


class Failed(Exception):
    pass


def fail(a, msg: str):
    log(msg)
    raise Stop if a.stop_on_fail else Failed


def run_task(task: str, a, port: int, rows: dict, k: int = 0) -> None:
    # re-read the ledger now, not the copy taken when the queue was built: a
    # 'skip' cell set by hand while the run is going must be honoured
    row = refresh_ledger(a.rounds).get(task, {})
    built_here = False
    view = None
    if a.isolated:
        # the worker's own harness view, made equal to main now and fixed for the whole task
        import harness
        # a round whose remedy is applied but not yet judged has its store edits in the
        # view, uncommitted: keep them across a restart instead of resetting to main
        mid = any(v.get("stage") in ("apply", "rebuild", "verdict")
                  for v in (vb_state(task).get("rounds") or {}).values())
        others = [t for t in SESSION_TASKS if t != task]
        view = harness.sync(k, keep_store=mid, task=task, hide=others)
        if others:
            log(f"{task}: not linked into its view (queued beside it): {', '.join(others)}")
        log(f"{task}: worker {k} runs in {view.relative_to(ROOT)} (store branch w{k}"
            + (" kept: a round is mid-flight)" if mid else " = main)"))
        # the person's judgement of this very subject (good_context) is the answer key
        hidden = harness.hide_answer_keys(view, task)
        if hidden:
            log(f"{task}: hidden from the view, its own answer key: {', '.join(hidden)}")

    # plan
    if row.get("plan") == "skip":
        log(f"{task}: plan skipped by ledger")
    elif not plan_done(task) or a.replan:
        build_begin()
        try:
            argv = [PY, ROOT / "planner_agent.py", "--task", task] + (["--force"] if a.replan else []) + (["--note", a.note] if a.note else [])
            rc = sh(argv, port, view)
        finally:
            build_end()
        refresh_ledger(a.rounds, {task: "" if rc == 0 else f"planner rc={rc}"})
        if rc != 0:
            fail(a, f"{task}: planner failed")
    else:
        log(f"{task}: plan exists")

    # build
    done, run, passed = build_done(task)
    if row.get("build") == "skip":
        log(f"{task}: build skipped by ledger")
    elif not done:
        n_resume = resume_step(task, run)
        if n_resume:
            log(f"{task}: run {run} died at step {n_resume}; continuing it from its checkpoint")
            argv = [PY, ROOT / "vb" / "rebuild.py", "--resume-build", "--task", task, "--run", run]
        else:
            if run:
                log(f"{task}: run {run} is incomplete and has no checkpoint; the executor starts a new run")
            argv = [PY, ROOT / "blendcua_agent.py", "--task", task]
            pf = plan_file(task)
            if pf:
                argv += ["--plan", pf.name]     # the plan folder may hold other .md files
        build_begin()
        try:
            if not ready(port, task, view):
                raise Stop
            rc = sh(argv, port, view)
        finally:
            build_end()
        done, run, passed = build_done(task)
        built_here = True
        if passed and SPLIT == "train":
            add_exemplar(task)
        refresh_ledger(a.rounds, {task: "" if done else f"build rc={rc}"})
        if not done:
            fail(a, f"{task}: build did not finish")
    else:
        log(f"{task}: build exists ({run})")

    # bundle
    if row.get("bundle") == "skip":
        log(f"{task}: bundle skipped by ledger")
    elif not bundle_done(run):
        mode = "live" if built_here else "replay"
        build_begin()
        try:
            if not ready(port, task, view):
                raise Stop
            rc = sh([PY, ROOT / "vb" / "bundle.py", "--run", run, "--mode", mode, "--task", task, "--force"], port, view)
        finally:
            build_end()
        refresh_ledger(a.rounds, {task: "" if rc == 0 else f"bundle rc={rc}"})
        if rc != 0:
            fail(a, f"{task}: bundle failed")
    else:
        log(f"{task}: bundle exists")

    # Version B rounds
    if a.skip_vb:
        return
    for n in range(1, a.rounds + 1):
        row = refresh_ledger(a.rounds).get(task, {})
        if row.get(f"round{n}") == "skip" or n in rounds_done(task):
            continue
        if n > 1 and kept(task):
            log(f"{task}: round {n - 1} kept an edit; later rounds need a fresh discovery, rounds end here")
            refresh_ledger(a.rounds, {task: f"round {n - 1} kept {';'.join(kept(task))}; further rounds need a new pass"})
            break
        base = [PY, ROOT / "vb" / "version_b.py", "--task", task, "--run", run, "--rounds", str(n), "--resume"]
        if view is not None:
            base.append("--skip-snapshot")     # main is snapshotted after the merge, not the worker's branch
        if not build_done(task)[2]:
            base.append("--no-lessons")       # lessons only from a build that passed every review
        # checker: reads renders only, never the store: beside anything
        rc = sh(base + ["--stop-after", "check"], port, view)
        if rc != 0:
            refresh_ledger(a.rounds, {task: f"round {n} checker rc={rc}"})
            fail(a, f"{task}: round {n} checker failed")
        # blame (or, for a build with no major defect, the lessons agent): reads the store
        build_begin()
        try:
            rc = sh(base + ["--stop-after", "curate"], port, view)
        finally:
            build_end()
        if rc != 0:
            refresh_ledger(a.rounds, {task: f"round {n} blame rc={rc}"})
            fail(a, f"{task}: round {n} blame failed")
        if (vb_state(task).get("lessons") or {}).get("files") is not None and not (vb_state(task).get("rounds") or {}).get(str(n)):
            # no major defect: the lessons agent ran instead of a round; publish and stop
            log(f"{task}: no major defect; lessons recorded instead of a round")
            if view is not None:
                publish_kept(task, k, a)
            refresh_ledger(a.rounds, {task: "no major defect; lessons written"})
            break
        # writing part: remedy, rebuild, verdict, accept: alone in the store when it is shared;
        # in a view it is the worker's own branch, and the merge into main comes after
        if view is None:
            log(f"{task}: round {n} waiting for the store (builds pause until it is done)")
            writer_begin()
        try:
            if not ready(port, task, view):
                raise Stop
            rc = sh(base, port, view)
        finally:
            if view is None:
                writer_end()
        refresh_ledger(a.rounds, {task: "" if rc == 0 else f"round {n} rc={rc}"})
        if rc != 0:
            fail(a, f"{task}: round {n} failed")
        if view is not None:
            publish_kept(task, k, a)


def todo(task: str, rows: dict, a) -> list[str]:
    r = rows[task]
    out = []
    if r["plan"] not in ("done", "skip") or a.replan:
        out.append("plan")
    if r["build"] not in ("done", "skip"):
        out.append("build")
    if r["bundle"] not in ("done", "skip"):
        out.append("bundle")
    if not a.skip_vb:
        out += [f"round{n}" for n in range(1, a.rounds + 1) if r[f"round{n}"] not in ("done", "skip")]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Run project v2 over tasks/train; resumable; ledger in tasks/PROGRESS.csv.")
    ap.add_argument("--tasks", default=None, help="comma list; default: every task in tasks/train")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--port", type=int, default=BASE_PORT)
    ap.add_argument("--first-worker", type=int, default=0,
                    help="index of the first worker (view harness/wK, port --port + K): runs a second "
                         "driver beside a running one, e.g. --first-worker 1 --parallel 1")
    ap.add_argument("--replan", action="store_true")
    ap.add_argument("--note", default="")
    ap.add_argument("--skip-vb", action="store_true")
    ap.add_argument("--split", default="train", choices=["train", "test"],
                    help="task folder to run: tasks/train (default) or tasks/test; test has its own "
                         "ledger (tasks/PROGRESS_test.csv) and never adds exemplars")
    ap.add_argument("--retry-budget", type=int, default=None,
                    help="review rounds per step minus one, for every build and resumed build of this "
                         "session (default: blendcua_core.DEFAULT_RETRY_BUDGET); 0 = one review round")
    ap.add_argument("--stop-on-fail", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--isolated", dest="isolated", action="store_true", default=None,
                    help="each worker on its own harness view (git branch of the store), merged into main on accept; default when --parallel > 1")
    ap.add_argument("--shared", dest="isolated", action="store_false", help="one shared store with the reader/writer gate (the old way)")
    a = ap.parse_args()
    global SPLIT, LEDGER
    SPLIT = a.split
    if SPLIT != "train":
        LEDGER = TASKS / f"PROGRESS_{SPLIT}.csv"
    if a.retry_budget is not None:
        # read by blendcua_core at import, so it reaches blendcua_agent both directly and through
        # vb/rebuild.py --resume-build (sh() passes os.environ down)
        os.environ["BLENDCUA_DEFAULT_RETRY_BUDGET"] = str(a.retry_budget)
    if a.isolated is None:
        a.isolated = a.parallel > 1
    if a.isolated:
        import harness
        harness.init_store()

    rows = refresh_ledger(a.rounds)
    tasks = task_list()
    if a.tasks:
        want = [s.strip() for s in a.tasks.split(",") if s.strip()]
        missing = [w for w in want if w not in tasks]
        if missing:
            raise SystemExit(f"[v2] not in tasks/{SPLIT}: {missing}")
        tasks = want

    if a.status or a.dry_run:
        print_ledger(rows, a.rounds)
        print()
        for t in tasks:
            td = todo(t, rows, a)
            print(f"   {t:26s} {'to do: ' + ', '.join(td) if td else 'nothing to do'}")
        return

    pending = [t for t in tasks if todo(t, rows, a)]
    # every task with work left, not only this driver's queue: a second driver
    # (--first-worker) may be running the others beside this one
    SESSION_TASKS[:] = sorted(set(pending) | {t for t in rows if todo(t, rows, a)})
    log(f"start: {len(pending)} task(s) with work: {', '.join(pending) or '-'}   rounds={a.rounds} parallel={a.parallel}")
    if not pending:
        return

    import queue
    q: "queue.Queue[str]" = queue.Queue()
    for t in pending:
        q.put(t)
    stop = threading.Event()
    retried: set[str] = set()      # a failed task goes to the back of the queue once

    def worker(k: int) -> None:
        port = a.port + k
        while not stop.is_set():
            try:
                task = q.get_nowait()
            except queue.Empty:
                return
            log(f"worker {k} (port {port}) -> {task}: {', '.join(todo(task, rows, a))}")
            try:
                run_task(task, a, port, rows, k)
                log(f"worker {k}: {task} finished")
            except Stop:
                log(f"worker {k}: stopping the run")
                stop.set()
            except Failed:
                if task in retried:
                    log(f"worker {k}: {task} failed again; leaving it for the next run")
                else:
                    retried.add(task)
                    q.put(task)
                    log(f"worker {k}: {task} failed; will retry it once after the other tasks")
            except Exception as e:  # noqa: BLE001
                log(f"worker {k}: {task} error {e!r}; moving on")

    threads = [threading.Thread(target=worker, args=(k,), name=f"w{k}", daemon=True) for k in range(a.first_worker, a.first_worker + max(1, a.parallel))]
    for th in threads:
        th.start()
        time.sleep(15)
    for th in threads:
        th.join()
    rows = refresh_ledger(a.rounds)
    print()
    print_ledger(rows, a.rounds)
    left = [t for t in tasks if todo(t, rows, a)]
    log("all done" if not left else f"stopped with work left on: {', '.join(left)} (run the same command to continue)")


if __name__ == "__main__":
    main()
