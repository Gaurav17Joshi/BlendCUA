"""B2 curriculum runner.

    python run_b2.py --split train              # grow the library over the curriculum
    python run_b2.py --split test --freeze      # evaluate, no new skills written
    python run_b2.py --task 09_thors_hammer     # one task
    python run_b2.py --status                   # what has run
    python run_b2.py --report                   # rewrite RESULTS.md

Tasks run in name order (01..20, the main system's order) on two workers at a
time (Blender ports 6680/6681). Per task:

    agent      agent.py in a subprocess: retrieval, conversation, final.blend
    bundle     bundle_b2.py: the main system's bundler into blends/<run>/
    compact    compaction.py (train only): trajectory -> skills, then
               library/snapshots/NN/

Each phase is recorded in runs/<run>/status.json, so a rerun skips finished
tasks and resumes a half-finished one at the phase it stopped in. A task whose
agent phase was interrupted is started again as the next run number, and the
interrupted run is marked `aborted` (kept, not deleted).

With two workers the library a task sees is the one left by every task that
FINISHED before it started, so task N+1 usually starts without task N's skills
(it runs alongside it). Compaction is serialised under one lock.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import b2_config as CFG
import library as L

RUN_RE = re.compile(r"^(.*)_run_(\d{3})$")
_COMPACT_LOCK = threading.Lock()
_PRINT_LOCK = threading.Lock()


def say(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with _PRINT_LOCK:
        print(line, flush=True)
        CFG.STATE.mkdir(parents=True, exist_ok=True)
        with open(CFG.STATE / "runner.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(p: Path, d) -> None:
    Path(p).write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")


def tasks_of(split: str) -> list[Path]:
    d = CFG.TASKS / split
    return sorted(p for p in d.iterdir() if p.is_dir() and (p / "task.md").is_file())


def find_task(name: str) -> Path:
    for p in CFG.TASKS.glob(f"*/{name}"):
        if (p / "task.md").is_file():
            return p
    raise SystemExit(f"no task {name} under tasks/")


def runs_of(task: str) -> list[Path]:
    out = []
    for p in CFG.RUNS.glob(f"{task}_run_*"):
        m = RUN_RE.match(p.name)
        if m and m.group(1) == task and p.is_dir():
            out.append(p)
    return sorted(out)


def latest_run(task: str) -> Path | None:
    live = [r for r in runs_of(task) if (read_json(r / "status.json", {}) or {}).get("phase") != "aborted"]
    return live[-1] if live else None


def new_run(task: str) -> Path:
    n = max([int(RUN_RE.match(p.name).group(2)) for p in runs_of(task)] or [0]) + 1
    d = CFG.RUNS / f"{task}_run_{n:03d}"
    d.mkdir(parents=True)
    return d


def task_number(task: str) -> str:
    m = re.match(r"^(\d+)", task)
    return m.group(1) if m else task


def is_done(task: str, freeze: bool) -> bool:
    r = latest_run(task)
    return bool(r) and (read_json(r / "status.json", {}) or {}).get("phase") == "done"


# ── shared desktop ───────────────────────────────────────────────────────────
# Another session on this machine takes Agents_convo/DESKTOP_LOCK.md while it drives
# the real mouse and keyboard. A new task opens a new GUI Blender window, which can
# take focus, so no task starts while the lock exists; running tasks are unaffected
# (B2 never sends input, and its screenshots read Blender's own framebuffer). The
# wait happens before the agent starts, so it is not charged to the agent's clock.
# A lock untouched for B2_LOCK_STALE_MIN minutes (default 90) is treated as stale.
DESKTOP_LOCK = Path(os.environ.get("B2_DESKTOP_LOCK",
                                   str(CFG.ROOT.parent / "Agents_convo" / "DESKTOP_LOCK.md")))
LOCK_STALE_S = 60 * float(os.environ.get("B2_LOCK_STALE_MIN", "90"))


def wait_for_desktop(task: str) -> None:
    waited = False
    while DESKTOP_LOCK.is_file():
        age = time.time() - DESKTOP_LOCK.stat().st_mtime
        if age > LOCK_STALE_S:
            say(f"{task}: {DESKTOP_LOCK.name} untouched for {age / 60:.0f} min; treating it as stale")
            return
        if not waited:
            say(f"{task}: {DESKTOP_LOCK.name} is held; waiting before opening a Blender window")
            waited = True
        time.sleep(30)
    if waited:
        say(f"{task}: {DESKTOP_LOCK.name} released; starting")


# ── one task ─────────────────────────────────────────────────────────────────

def run_task(task_dir: Path, worker: int, freeze: bool) -> None:
    task = task_dir.name
    run_dir = latest_run(task)
    st = read_json(run_dir / "status.json", {}) if run_dir else {}
    if run_dir and st.get("phase") == "done":
        say(f"{task}: already done ({run_dir.name})")
        return
    if run_dir is None or st.get("phase") in (None, "running"):
        if run_dir is not None:
            pid = st.get("agent_pid")
            if pid:   # an orphaned agent from a killed runner would still hold the port
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            st["phase"] = "aborted"
            st["aborted_at"] = L.now()
            write_json(run_dir / "status.json", st)
            say(f"{task}: {run_dir.name} was interrupted mid-agent; marked aborted")
        wait_for_desktop(task)
        run_dir = new_run(task)
        say(f"{task}: agent starting as {run_dir.name} on worker {worker} "
            f"(port {CFG.WORKERS[worker]['port']})")
        argv = [CFG.PY, str(CFG.ROOT / CFG.AGENT_SCRIPT), "--task-dir", str(task_dir),
                "--run-dir", str(run_dir), "--worker", str(worker)] + (["--freeze"] if freeze else [])
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                   PYTHONUNBUFFERED="1")
        with open(run_dir / "agent_stdout.log", "a", encoding="utf-8") as fh:
            rc = subprocess.call(argv, cwd=str(CFG.ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env)
        st = read_json(run_dir / "status.json", {}) or {}
        if not (run_dir / "usage.json").is_file():
            # the harness itself crashed: not a B2 result, so retry on the next invocation
            st.update(phase="aborted", aborted_at=L.now(),
                      end_reason=f"harness crash: agent process rc={rc}, no usage.json")
            write_json(run_dir / "status.json", st)
            say(f"{task}: HARNESS CRASH in {run_dir.name} (rc={rc}); marked aborted, see agent_stdout.log")
            return
        if st.get("phase") != "agent_done":
            # the agent process itself died without writing its end state
            st.update(phase="agent_done", produced_blend=(run_dir / "final.blend").is_file(),
                      end_reason=f"agent process exited rc={rc} without finishing")
            write_json(run_dir / "status.json", st)
        u = read_json(run_dir / "usage.json", {}) or {}
        if not u.get("finished_by_agent") and not u.get("tool_calls"):
            # The agent never got to work at all (a subscription limit, an auth
            # failure, a dead model). The .blend it saved is the empty start
            # scene, so this is not a B2 result: keep it, mark it aborted, and
            # let the next invocation redo the task rather than record a score.
            st.update(phase="aborted", aborted_at=L.now(),
                      end_reason=f"no work done: {u.get('end_reason')}")
            write_json(run_dir / "status.json", st)
            say(f"{task}: NO WORK DONE in {run_dir.name} ({u.get('end_reason')}); marked aborted")
            return
        say(f"{task}: agent done rc={rc}: {st.get('end_reason')}; blend={st.get('produced_blend')}; "
            f"${u.get('cost_usd', '?')} {u.get('wall_clock_min', '?')} min "
            f"{u.get('tool_calls', '?')} tool calls")

    run = run_dir.name
    if st.get("phase") == "agent_done":
        if (run_dir / "final.blend").is_file():
            say(f"{task}: bundling {run}")
            with open(run_dir / "bundle.log", "a", encoding="utf-8") as fh:
                rc = subprocess.call([CFG.PY, str(CFG.ROOT / "bundle_b2.py"), "--run", run],
                                     cwd=str(CFG.ROOT), stdout=fh, stderr=subprocess.STDOUT,
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                              PYTHONDONTWRITEBYTECODE="1"))
            st["bundled"] = rc == 0
        else:
            st["bundled"] = False
        st["phase"] = "bundled"
        write_json(run_dir / "status.json", st)
        say(f"{task}: bundle {'ok' if st['bundled'] else 'FAILED'}")

        # A run that never reached `finish` AND has nothing bundleable produced
        # no result to score: the saved .blend is the empty start scene. This is
        # what a transient API outage looks like from here (the agent is cut off
        # mid-build), so mark it aborted and let the task be redone rather than
        # recording it as done -- a `done` task is skipped on the next run.
        u2 = read_json(run_dir / "usage.json", {}) or {}
        if not st["bundled"] and not u2.get("finished_by_agent"):
            st.update(phase="aborted", aborted_at=L.now(),
                      end_reason=f"unfinished, nothing to bundle: {st.get('end_reason')}")
            write_json(run_dir / "status.json", st)
            say(f"{task}: UNFINISHED + bundle FAILED in {run} "
                f"({st.get('end_reason')}); marked aborted")
            return

    if st.get("phase") == "bundled":
        if freeze or st.get("freeze"):
            st["compaction"] = "skipped (library frozen)"
        elif not (run_dir / "usage.json").is_file():
            st["compaction"] = "skipped (no usage.json)"
        else:
            import compaction
            with _COMPACT_LOCK:
                say(f"{task}: compacting {run}")
                try:
                    res = compaction.compact(run, log=say)
                    st["compaction"] = {"written": len(res["written"]), "rejected": len(res["rejected"]),
                                        "library_size_after": res["library_size_after"]}
                except Exception as e:  # noqa: BLE001
                    say(f"{task}: compaction FAILED: {type(e).__name__}: {e}")
                    st["compaction"] = f"failed: {type(e).__name__}: {str(e)[:300]}"
                    L.log("compaction_failed", task=task, run=run, error=str(e)[:500])
                snap = L.snapshot(task_number(task))
                st["snapshot"] = str(snap.relative_to(CFG.ROOT))
        st["phase"] = "done"
        st["done_at"] = L.now()
        write_json(run_dir / "status.json", st)
        say(f"{task}: done ({run})")
    write_results()


# ── curriculum ───────────────────────────────────────────────────────────────

def run_split(task_dirs: list[Path], freeze: bool, workers: int) -> None:
    q: queue.Queue = queue.Queue()
    for t in task_dirs:
        if is_done(t.name, freeze):
            say(f"{t.name}: done already, skipping")
        else:
            q.put(t)
    if q.empty():
        say("nothing to run")
        write_results()
        return

    # Lanes listed in B2_GATED_LANES (e.g. "1") take a new task only while
    # STATE/lane<w>.go exists, so an extra Blender can be switched on or off
    # mid-run without restarting the runner. A task already started always finishes.
    gated = {int(x) for x in os.environ.get("B2_GATED_LANES", "").split(",") if x.strip()}

    def lane(w: int) -> None:
        while True:
            if w in gated and not (CFG.STATE / f"lane{w}.go").is_file():
                if q.empty():
                    return
                time.sleep(30)
                continue
            try:
                t = q.get_nowait()
            except queue.Empty:
                return
            try:
                run_task(t, w, freeze)
            except Exception as e:  # noqa: BLE001
                import traceback
                say(f"{t.name}: RUNNER ERROR on worker {w}: {e}\n{traceback.format_exc()}")
            time.sleep(5)

    threads = [threading.Thread(target=lane, args=(w,), daemon=False) for w in range(workers)]
    for i, th in enumerate(threads):
        th.start()
        if i == 0 and len(threads) > 1:
            time.sleep(20)   # stagger Blender launches
    for th in threads:
        th.join()
    say("all queued tasks processed")
    write_results()


# ── reporting ────────────────────────────────────────────────────────────────

def rows() -> list[dict]:
    out = []
    for split_dir in sorted(p for p in CFG.TASKS.iterdir() if p.is_dir()):
        for t in tasks_of(split_dir.name):
            r = latest_run(t.name)
            st = (read_json(r / "status.json", {}) if r else {}) or {}
            u = (read_json(r / "usage.json", {}) if r else {}) or {}
            c = (read_json(r / "compaction.json", {}) if r else {}) or {}
            sk = u.get("skills", {})
            out.append({"split": split_dir.name, "task": t.name, "run": r.name if r else "",
                        "phase": st.get("phase", "not run"), "end": u.get("end_reason") or st.get("end_reason", ""),
                        "blend": st.get("produced_blend"), "bundled": st.get("bundled"),
                        "cost": u.get("cost_usd"), "out_tok": (u.get("agent") or {}).get("output_tokens"),
                        "in_tok": (u.get("agent") or {}).get("input_tokens"),
                        "wall": u.get("wall_clock_min"), "tools": u.get("tool_calls"),
                        "actions": u.get("blender_actions"), "restarts": u.get("blender_restarts"),
                        "lib": sk.get("library_size_at_start"), "retrieved": sk.get("retrieved", []),
                        "loaded": sk.get("loaded_on_demand", []), "referenced": sk.get("referenced_in_code", []),
                        "review_cost": ((u.get("review") or {}).get("usage") or {}).get("cost_usd") if (u.get("review") or {}).get("happened") else None,
                        "written": c.get("written", []), "compaction_cost": (c.get("usage") or {}).get("cost_usd"),
                        "aborted": sum(1 for x in runs_of(t.name)
                                       if (read_json(x / "status.json", {}) or {}).get("phase") == "aborted")})
    return out


def fmt(v, spec=""):
    if v is None or v == "":
        return "–"
    return format(v, spec) if spec else str(v)


def write_results() -> None:
    rs = rows()
    if CFG.HARNESS == "claude_code":
        head = (f"Generated {L.now()} by `run_b2.py`. Model `{CFG.MODEL}`, effort "
                f"`{CFG.REASONING_EFFORT}`, running in the **Claude Code harness** "
                f"(`agent_claude.py`), which reaches B2's tools through `b2_mcp_server.py`. "
                f"Billed to the Claude subscription, not per token: the **$** column is the "
                f"list-price equivalent Claude Code reports, for comparison with the other "
                f"entrants only. Caps are wall-clock and tool calls: soft {CFG.SOFT_WALL_MIN} min "
                f"(agent told to wrap up), hard {CFG.HARD_WALL_MIN} min or {CFG.MAX_TOOL_CALLS} "
                f"tool calls.")
    else:
        head = (f"Generated {L.now()} by `run_b2.py`. Model `{CFG.MODEL}`, reasoning effort "
                f"`{CFG.REASONING_EFFORT}`. Cost at ${CFG.PRICE['input']}/M input, "
                f"${CFG.PRICE['cached_input']}/M cached input, ${CFG.PRICE['output']}/M output "
                f"(gpt-image-2 calls counted separately, not in $). Caps: soft "
                f"${CFG.SOFT_COST_USD:.2f} / {CFG.SOFT_WALL_MIN} min (agent told to wrap up), "
                f"hard ${CFG.HARD_COST_USD:.2f} / {CFG.HARD_WALL_MIN} min.")
    lines = ["# B2 results", "", head, "",
             "Columns: **end** = how the agent loop ended; **blend** = a final .blend was saved; "
             "**bundled** = judge folder complete in blends/<run>/; **$** = builder + reviewer + retrieval spend; "
             "**review $** = the one review round's share; "
             "**lib** = skills in the library when the task started; **ret** = skills retrieved into "
             "context; **load** = loaded on demand; **ref** = library skills whose module name appears "
             "in the code the agent ran; **wrote** = skills written/updated by compaction after it.", ""]
    for split in sorted({r["split"] for r in rs}):
        sub = [r for r in rs if r["split"] == split]
        lines += [f"## {split}", "",
                  "| task | run | phase | end | blend | bundled | $ | review $ | out tok | min | tool calls | Blender actions | lib | ret | load | ref | wrote | compaction $ |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in sub:
            wrote = ", ".join(f"{w['kind'][0]}:{w['name']}" for w in r["written"]) if r["written"] else ("0" if r["phase"] == "done" else "–")
            lines.append("| " + " | ".join([
                r["task"], r["run"] or "–", r["phase"] + (f" (+{r['aborted']} aborted)" if r["aborted"] else ""),
                (r["end"] or "–")[:60], fmt(r["blend"]), fmt(r["bundled"]), fmt(r["cost"], ".2f"),
                fmt(r["review_cost"], ".2f"), fmt(r["out_tok"], ","), fmt(r["wall"]), fmt(r["tools"]), fmt(r["actions"]), fmt(r["lib"]),
                str(len(r["retrieved"])) if r["run"] else "–", str(len(r["loaded"])) if r["run"] else "–",
                (f"{len(r['referenced'])} ({', '.join(r['referenced'])})" if r["referenced"] else ("0" if r["run"] else "–")),
                wrote, fmt(r["compaction_cost"], ".3f")]) + " |")
        done = [r for r in sub if r["phase"] == "done"]
        costs = sorted(r["cost"] for r in done if r["cost"] is not None)
        walls = sorted(r["wall"] for r in done if r["wall"] is not None)
        med = lambda xs: (xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2) if xs else None  # noqa: E731
        n_written = sum(1 for r in done for w in r["written"] if w["kind"] == "write")
        n_updated = sum(1 for r in done for w in r["written"] if w["kind"] == "update")
        reuse_tasks = sum(1 for r in done if r["referenced"])
        lines += ["", f"**{split} totals:** {len(done)}/{len(sub)} tasks done; "
                  f"{sum(1 for r in done if r['blend'])} produced a .blend; "
                  f"{sum(1 for r in done if r['end'] == 'finished')} finished by the agent's own `finish`; "
                  f"agent spend ${sum(costs):.2f} (median {fmt(med(costs), '.2f')}); "
                  f"wall-clock median {fmt(med(walls), '.0f')} min; "
                  f"skills written {n_written}, updated {n_updated}; "
                  f"tasks that used ≥1 library skill in their code: {reuse_tasks}; "
                  f"skill references in code: {sum(len(r['referenced']) for r in done)}; "
                  f"retrievals: {sum(len(r['retrieved']) for r in done)}.", ""]
    lines += [f"Library now holds {len(L.read_index())} skills (library/skills/index.json); "
              "per-task snapshots in library/snapshots/NN/; every event in library/library_log.jsonl.", ""]
    CFG.RESULTS.write_text("\n".join(lines), encoding="utf-8")


def print_status() -> None:
    for r in rows():
        print(f"{r['split']:6} {r['task']:26} {r['run'] or '-':28} {r['phase']:10} "
              f"blend={fmt(r['blend']):5} bundled={fmt(r['bundled']):5} ${fmt(r['cost'], '.2f'):>5} "
              f"{fmt(r['wall']):>6}min tools={fmt(r['tools']):>4} lib={fmt(r['lib'])} "
              f"ref={len(r['referenced'])} wrote={len(r['written'])}  {(r['end'] or '')[:50]}")
    print(f"library: {len(L.read_index())} skills")


# ── entry ────────────────────────────────────────────────────────────────────

def acquire_runner_lock() -> None:
    lock = CFG.STATE / "runner.pid"
    CFG.STATE.mkdir(parents=True, exist_ok=True)
    try:
        pid = int(lock.read_text().strip())
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        if str(pid) in out and pid != os.getpid():
            raise SystemExit(f"another run_b2.py (pid {pid}) is running")
    except (OSError, ValueError):
        pass
    lock.write_text(str(os.getpid()))


def main() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split")
    ap.add_argument("--task")
    ap.add_argument("--freeze", action="store_true", help="retrieval on, no skills written")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    CFG.RUNS.mkdir(exist_ok=True)
    CFG.SKILLS.mkdir(parents=True, exist_ok=True)
    if a.status:
        print_status()
        return
    if a.report:
        write_results()
        print(CFG.RESULTS.read_text(encoding="utf-8"))
        return
    acquire_runner_lock()
    if a.task:
        say(f"single task {a.task} (freeze={a.freeze})")
        run_task(find_task(a.task), 0, a.freeze)
        return
    if not a.split:
        ap.error("give --split, --task, --status or --report")
    tds = tasks_of(a.split)
    say(f"split {a.split}: {len(tds)} tasks, {a.workers} workers, freeze={a.freeze}")
    run_split(tds, a.freeze, max(1, min(a.workers, len(CFG.WORKERS))))


if __name__ == "__main__":
    main()
