"""Shared helpers for the Version B blocks under vb/.

Paths, the Blender socket dispatch with a per-script sentinel, run-folder
copying with the two rewrites a relocated action file needs, store snapshots
for reverting a dropped remedy, and the geometry digest used by the R1 hash
rule. Nothing here talks to a model.
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[1])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEM = ROOT / "mem"
BLENDS = ROOT / "blends"
PLANS = ROOT / "plans"
TASKS = ROOT / "tasks"
SKILLS = ROOT / "Skills"
TOOLS_CODE = ROOT / "Tool_scripts" / "Tools_code"
TOOL_SCRIPTS = ROOT / "Tool_scripts"
PROMPT_FILES = ROOT / "prompt_files"
CHECKER_DIR = ROOT / "Checker"
CHECKER_REPORTS = CHECKER_DIR / "reports"
CURATOR_DIR = ROOT / "Curator"
CURATOR_REPORTS = CURATOR_DIR / "reports"
VB_DIR = ROOT / "vb"
VB_STATE = VB_DIR / "state"
SNAPSHOTS = ROOT / "snapshots"
HARNESS_LOG = VB_DIR / "harness_log.jsonl"

PY = sys.executable
PORT = int(os.environ.get("BLENDCUA_PORT", "6666"))
STATUS_FILE = MEM / ("exec_status.json" if PORT == 6666 else f"exec_status_{PORT}.json")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# The folders a remedy is allowed to change. plans/<task> is added per task.
STORE_DIRS = ("Skills", "Tool_scripts/Tools_code", "prompt_files",
              "Tool_scripts/Tools_ref")
_SKIP_NAMES = ("__pycache__", "_vendor")

# Every spelling of the recorded project root that appears in action files
# from the Mac era. A relocated copy of a run must import tools and resolve
# assets from THIS folder, otherwise runtime.ROOT points at the synced Mac
# folder and screenshots and JSON reports land there.
OLD_ROOTS = (
    r"C:\Users\render\Joshi\Blenduse\BlendCuaLoop_try",
    r"C:\\Users\\render\\Joshi\\Blenduse\\BlendCuaLoop_try",
    r"C:\Users\render\Joshi\Joshi\Blenduse\BlendCuaLoop_try",
    r"C:\Users\render\Blenduse\BlendCuaLoop_try",
    "C:/Users/render/Joshi/Blenduse/BlendCuaLoop_try",
    # runs built in the previous Version B folder
    r"C:\Users\render\Joshi\Blenduse\BlendCuaLoop1",
    r"C:\\Users\\render\\Joshi\\Blenduse\\BlendCuaLoop1",
    "C:/Users/render/Joshi/Blenduse/BlendCuaLoop1",
    r"C:\Users\render\Joshi\Blenduse\BlendCuav2b_try",
    r"C:\\Users\\render\\Joshi\\Blenduse\\BlendCuav2b_try",
    "C:/Users/render/Joshi/Blenduse/BlendCuav2b_try",
)
NEW_ROOT = str(ROOT)
NEW_ROOT_ESCAPED = NEW_ROOT.replace("\\", "\\\\")

RUN_RE = re.compile(r"^(.*)_run_(\d{3})$")
STEP_RE = re.compile(r"^step_(\d+)$")
ACTION_RE = re.compile(r"^(\d+)_.*\.py$")


# ── small utilities ──────────────────────────────────────────────────────────

def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(p: Path, data) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def file_hash(p: Path) -> str:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return ""


def task_of_run(run: str) -> str:
    m = RUN_RE.match(run)
    return m.group(1) if m else run


def next_run_name(task: str) -> str:
    import blendcua_core as core
    return core.next_run_name(f"{task}_run")


def sh(argv: list, *, cwd: Path = ROOT, log: Path | None = None,
       timeout: float | None = None, env: dict | None = None) -> int:
    """Run a command, streaming output to the console and optionally a log."""
    argv = [str(a) for a in argv]
    print(f"\n$ {' '.join(argv[1:] if argv and argv[0] == PY else argv)}\n", flush=True)
    # Children print arrows and em-dashes; a piped stdout on Windows defaults
    # to cp1252 and a stray glyph would kill a four-hour build.
    env = dict(env or os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    if log is None:
        try:
            return subprocess.call(argv, cwd=str(cwd), timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            print(f"[vb] TIMEOUT after {timeout}s: {argv[:3]}")
            return 124
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8", errors="replace") as fh:
        fh.write(f"\n===== {now()}  $ {' '.join(argv)}\n")
        fh.flush()
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", env=env)
        except OSError as exc:
            fh.write(f"[vb] could not start: {exc}\n")
            return 127
        t0 = time.time()
        try:
            for line in proc.stdout:
                fh.write(line)
                fh.flush()
                if timeout and time.time() - t0 > timeout:
                    proc.kill()
                    fh.write(f"[vb] killed after {timeout}s\n")
                    return 124
        finally:
            proc.wait()
        return proc.returncode


def plan_path(task: str) -> Path:
    mds = sorted((PLANS / task).glob("*_plan.md")) or sorted((PLANS / task).glob("*.md"))
    if not mds:
        raise SystemExit(f"[vb] no plan under plans/{task}")
    return mds[0]


def plan_steps(task: str) -> list[dict]:
    import blendcua_core as core
    return core.parse_plan(plan_path(task).read_text(encoding="utf-8"))


def task_dir(task: str) -> Path:
    for split in ("train", "test"):
        d = TASKS / split / task
        if d.is_dir():
            return d
    raise SystemExit(f"[vb] no task folder for {task} under tasks/")


# ── Blender dispatch ─────────────────────────────────────────────────────────

_SEQ = [0]


def blender_up(timeout: float = 2.0) -> bool:
    try:
        socket.create_connection(("localhost", PORT), timeout=timeout).close()
        return True
    except OSError:
        return False


def dispatch(body: str, timeout_s: float, what: str) -> tuple[dict | None, float]:
    """Send one script and wait for ITS OWN sentinel, or a failure stamped
    after it was sent. Same protocol as save_final_blend.dispatch, kept here
    so vb/ does not depend on that script's module-level state."""
    _SEQ[0] += 1
    token = BLENDS / f".vb_done_{os.getpid()}_{_SEQ[0]}"
    BLENDS.mkdir(exist_ok=True)
    if token.exists():
        token.unlink()
    body = body + f"\n\nopen({str(token)!r}, 'w').close()\n"
    started = time.time()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost", PORT))
        s.sendall(body.encode("utf-8"))
        s.close()
    except OSError as exc:
        print(f"[vb] could not reach Blender on {PORT}: {exc}")
        return None, 0.0
    deadline = started + timeout_s
    while time.time() < deadline:
        if token.exists():
            token.unlink()
            st = read_json(STATUS_FILE, {"ok": True})
            return st, time.time() - started
        try:
            if os.path.getmtime(STATUS_FILE) >= started:
                st = read_json(STATUS_FILE)
                if st and not st.get("ok"):
                    return st, time.time() - started
        except OSError:
            pass
        time.sleep(0.25)
    print(f"[vb] TIMEOUT after {timeout_s}s waiting for {what}")
    return None, time.time() - started


def dispatch_file(path: Path, timeout_s: float, what: str) -> tuple[dict | None, float]:
    return dispatch(Path(path).read_text(encoding="utf-8"), timeout_s, what)


def blender_reset(timeout_s: float = 180.0) -> bool:
    """Empty the live session between builds (datablocks included)."""
    st, dt = dispatch_file(TOOL_SCRIPTS / "reset_blender_state.py", timeout_s, "reset")
    ok = bool(st and st.get("ok"))
    print(f"[vb] blender reset {'ok' if ok else 'FAILED'} in {dt:.1f}s"
          + ("" if ok else f" — {str((st or {}).get('error'))[-300:]}"))
    return ok


def blender_ready(*, fit_viewport: bool = True) -> bool:
    """Server reachable, owned by this folder, responsive; viewport fitted."""
    import blender_health
    if not blender_health.ensure_ready(task="version-b"):
        return False
    if fit_viewport:
        rc = sh([PY, TOOL_SCRIPTS / "win_fit_viewport.py"])
        if rc != 0:
            print("[vb] WARNING: viewport fit did not converge; sculpt-stroke "
                  "actions may diverge from the record")
    return True


def geom_digest(run: str, out_name: str = "geom_digest.json",
                timeout_s: float = 600.0) -> dict | None:
    """Hash every mesh in the LIVE scene into mem/<run>/<out_name>."""
    out = MEM / run / out_name
    out.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(TOOLS_CODE)!r})\n"
        "import geom_digest\n"
        f"geom_digest.write_digest({str(out)!r}, evaluated=True, note={run!r})\n"
    )
    st, dt = dispatch(script, timeout_s, "geometry digest")
    if not st or not st.get("ok") or not out.is_file():
        print(f"[vb] geometry digest failed: {str((st or {}).get('error'))[-200:]}")
        return None
    return read_json(out)


def compare_digests(before: dict | None, after: dict | None) -> dict:
    if not before or not after:
        return {"measured": False, "changed": [], "added": [], "removed": []}
    a = {o["name"]: o.get("hash") for o in before.get("objects", [])}
    b = {o["name"]: o.get("hash") for o in after.get("objects", [])}
    return {
        "measured": True,
        "changed": sorted(n for n in set(a) & set(b) if a[n] != b[n]),
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "identical": before.get("scene_hash") == after.get("scene_hash"),
    }


# ── run folders ──────────────────────────────────────────────────────────────

def relocate_action_text(text: str, old_run: str, new_run: str) -> str:
    """Rewrite a recorded action so it runs under THIS root and THIS run."""
    for old in OLD_ROOTS:
        if "\\\\" in old:
            text = text.replace(old, NEW_ROOT_ESCAPED)
        else:
            text = text.replace(old, NEW_ROOT)
    if old_run != new_run:
        text = re.sub(r'use\(\s*([\'"])' + re.escape(old_run) + r'\1',
                      lambda m: f"use({m.group(1)}{new_run}{m.group(1)}", text)
        text = text.replace(f"mem/{old_run}/", f"mem/{new_run}/")
        text = text.replace(f"mem\\{old_run}\\", f"mem\\{new_run}\\")
        text = text.replace(f"mem\\\\{old_run}\\\\", f"mem\\\\{new_run}\\\\")
    return text


def copy_run(base_run: str, new_run: str, *, upto_step: int | None = None,
             include_non_actions: bool = True) -> list[Path]:
    """Copy mem/<base_run> to mem/<new_run>, relocating every action file.

    upto_step keeps only steps strictly below it (the R2-from-checkpoint
    case). Screenshots and review images are left behind: they are the old
    run's evidence and the new run will make its own.
    """
    src, dst = MEM / base_run, MEM / new_run
    if not src.is_dir():
        raise SystemExit(f"[vb] no run folder mem/{base_run}")
    if dst.exists():
        raise SystemExit(f"[vb] mem/{new_run} already exists — refusing to overwrite")
    (dst / "steps").mkdir(parents=True)
    copied: list[Path] = []
    for item in src.iterdir():
        if item.name in ("steps", "Rollout", "curation", "checkpoints"):
            continue
        if item.is_file() and include_non_actions:
            txt = None
            if item.suffix in (".json", ".md", ".py", ".txt"):
                try:
                    txt = item.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    txt = None
            if txt is not None:
                (dst / item.name).write_text(
                    relocate_action_text(txt, base_run, new_run), encoding="utf-8")
            else:
                shutil.copy2(item, dst / item.name)
    for step_dir in sorted((src / "steps").glob("step_*")):
        m = STEP_RE.match(step_dir.name)
        if not m:
            continue
        n = int(m.group(1))
        if upto_step is not None and n >= upto_step:
            continue
        out = dst / "steps" / step_dir.name
        out.mkdir(parents=True, exist_ok=True)
        for f in sorted(step_dir.iterdir()):
            if f.is_dir():
                if f.name in ("scripts", "overlay_json") and include_non_actions:
                    shutil.copytree(f, out / f.name, dirs_exist_ok=True)
                continue
            if f.suffix == ".py" or (include_non_actions and f.suffix in (".json", ".md", ".txt")):
                try:
                    txt = f.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    shutil.copy2(f, out / f.name)
                    continue
                (out / f.name).write_text(relocate_action_text(txt, base_run, new_run),
                                          encoding="utf-8")
                if ACTION_RE.match(f.name):
                    copied.append(out / f.name)
    write_json(dst / "vb_origin.json", {
        "copied_from": base_run, "at": now(), "upto_step": upto_step,
        "action_files": len(copied)})
    return copied


def action_files(run: str, *, upto_step: int | None = None) -> list[Path]:
    import replay_batch
    return [Path(p) for p in replay_batch.collect_action_files(
        str(MEM), run, before_step=upto_step, before_action=None)]


def batch_replay(run: str, *, upto_step: int | None = None,
                 timeout_s: float = 1800.0, label: str = "vb replay") -> tuple[bool, str, int]:
    """Replay the run's build actions into the live scene in ONE dispatch,
    renders stubbed. Returns (ok, error, n_actions)."""
    import replay_batch
    files = [str(p) for p in action_files(run, upto_step=upto_step)]
    if not files:
        return True, "", 0
    script = replay_batch.build_replay_script(files, str(TOOLS_CODE), render=False,
                                              label=f"{label} {run}")
    st, dt = dispatch(script, timeout_s, f"replay of {run}")
    if st is None:
        return False, f"timeout after {dt:.0f}s", len(files)
    if not st.get("ok"):
        return False, str(st.get("error"))[-2000:], len(files)
    print(f"[vb] replayed {len(files)} action(s) of {run} in {dt:.1f}s")
    return True, "", len(files)


# ── store snapshots ──────────────────────────────────────────────────────────

def _store_roots(task: str | None) -> list[str]:
    roots = list(STORE_DIRS)
    if task:
        roots.append(f"plans/{task}")
    return roots


def _ignored(rel: Path) -> bool:
    return any(part in _SKIP_NAMES or part.endswith(".pyc") for part in rel.parts)


def store_manifest(task: str | None = None, extra_dirs: list[str] | None = None) -> dict[str, str]:
    """relpath -> sha256 over everything a remedy may touch."""
    out: dict[str, str] = {}
    for rel in _store_roots(task) + list(extra_dirs or []):
        base = ROOT / rel
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not _ignored(p.relative_to(base)):
                out[str(rel_to(p, ROOT)).replace("\\", "/")] = file_hash(p)
    return out


def snapshot_store(dest: Path, task: str | None = None,
                   extra_dirs: list[str] | None = None) -> Path:
    """Copy the mutable store so a dropped remedy can be undone file by file."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for rel in _store_roots(task) + list(extra_dirs or []):
        src = ROOT / rel
        if src.is_dir():
            shutil.copytree(src, dest / rel.replace("/", "__"),
                            ignore=shutil.ignore_patterns(*_SKIP_NAMES, "*.pyc"))
    write_json(dest / "_manifest.json", store_manifest(task, extra_dirs))
    return dest


def restore_files(snapshot: Path, files: list[str], keep_dir: Path | None = None) -> list[str]:
    """Put the named repo-relative files back as the snapshot had them.
    A file absent from the snapshot is deleted (it was created by the remedy).

    Every live file about to be overwritten or deleted is first copied, at its
    repo-relative path, into keep_dir (default: <round>/store_after next to the
    store_before snapshot), so a rejected remedy's actual edits and any tool it
    wrote stay readable for comparison after the revert."""
    snapshot = Path(snapshot)
    if keep_dir is None:
        keep_dir = snapshot.parent / "store_after"
    manifest = read_json(snapshot / "_manifest.json", {})
    done = []
    for rel in files:
        rel = rel.replace("\\", "/")
        live = ROOT / rel
        if live.is_file():
            kept = Path(keep_dir) / rel
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, kept)
        root = next((r for r in sorted(manifest_roots(manifest), key=len, reverse=True)
                     if rel.startswith(r + "/")), None)
        if root is None:
            # not inside a snapshotted tree: created outside the store
            if live.is_file():
                live.unlink()
                done.append(f"removed {rel}")
            continue
        saved = snapshot / root.replace("/", "__") / rel[len(root) + 1:]
        if saved.is_file():
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, live)
            done.append(f"restored {rel}")
        elif live.is_file():
            live.unlink()
            done.append(f"removed {rel}")
    return done


def manifest_roots(manifest: dict) -> set[str]:
    roots = set()
    for rel in manifest:
        parts = rel.split("/")
        for root in STORE_DIRS:
            if rel.startswith(root + "/"):
                roots.add(root)
                break
        else:
            if len(parts) > 2 and parts[0] == "plans":
                roots.add("/".join(parts[:2]))
    return roots


def changed_since(manifest_before: dict[str, str], task: str | None = None,
                  extra_dirs: list[str] | None = None) -> dict[str, list[str]]:
    after = store_manifest(task, extra_dirs)
    return {
        "modified": sorted(k for k in after if k in manifest_before and after[k] != manifest_before[k]),
        "created": sorted(k for k in after if k not in manifest_before),
        "deleted": sorted(k for k in manifest_before if k not in after),
    }


def log_event(record: dict) -> None:
    HARNESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": now(), **record}
    with open(HARNESS_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
