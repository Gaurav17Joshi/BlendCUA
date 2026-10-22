"""Per-worker harness views: one git branch of the store per worker, merged on accept.

    python harness.py init                 # make harness/store.git from the current store (once)
    python harness.py sync 0               # (re)build harness/w0 from main: worker 0's view
    python harness.py publish 0 --task T --files a.md b.py -m "msg"   # commit on w0, merge into main
    python harness.py status               # branches, views, last commits
    python harness.py reset-main <rev>     # put main back to an earlier commit (the store on disk too)

The store = Skills/, Tool_scripts/Tools_code/, Tool_scripts/Tools_ref/, prompt_files/. It is a
git repository whose main worktree is THIS folder (git dir harness/store.git). Worker k gets
harness/wk: a worktree on branch wk holding the store, plus copies of the code (*.py, Checker,
Curator, vb, Tool_scripts scripts, .hermes plugins) and junctions to the shared data folders
(mem, plans, blends, tasks, snapshots, reports, vb/state, .hermes_home*). Every process of
worker k runs with cwd = its view, so agents, tools and Blender see "the" harness at the usual
relative paths, and only the store differs between workers.

Rules:
  * sync only at a task start: the whole task (build, checker, blame, remedy, rebuild, verdict,
    accept) runs on one fixed store, so its verdict is attributable;
  * publish only accepted edits: the files the round's applied.json (or lessons.json) names;
    anything else a worker left in its store is discarded at its next sync and reported;
  * merge into main with git: non-overlapping edits merge on their own, skills and checklists
    are add-only (union merge), generated indexes are regenerated, a real conflict in code goes
    to an agent and, failing that, keeps main's version with the other side saved beside it;
  * main gets a snapshot (snapshots/H_NN) after every merge.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HARNESS = ROOT / "harness"
GIT_DIR = HARNESS / "store.git"
STORE_DIRS = ("Skills", "Tool_scripts/Tools_code", "Tool_scripts/Tools_ref", "prompt_files")
GENERATED = ("Tool_scripts/Tools_ref/INDEX.md", "prompt_files/current_tools.md")
# shared data: junctions into ROOT
DATA_LINKS = ("mem", "plans", "blends", "tasks", "snapshots", "images", "synth_views",
              "Checker/reports", "Curator/reports", "vb/state")
# Of those, the folders keyed by TASK name are linked entry by entry when sync() is given the task,
# leaving out the other tasks queued in the same driver session: a worker's agents can then neither
# read nor write the task running beside it. (2026-09-13 21:12: the robot's round-2 apply agent
# rewrote the turtle's applied.json through the shared Curator/reports and copied the turtle's
# remedies into its own skills; its guard failed and the round was lost.) Folders keyed by RUN
# (mem, blends, Checker/reports) gain new entries mid-round, so they stay whole junctions and the
# write guard Curator/curator_agent.other_task_writes covers them.
PER_TASK_LINKS = ("plans", "Curator/reports", "vb/state")
# code copied into the view at every sync (a task runs on fixed code, like a fixed store)
CODE_DIRS = ("Checker", "Curator", "vb", ".hermes")
CODE_GLOBS = ("*.py", "*.md", "*.txt", "*.json")
EXCLUDE = """# only the store is tracked; everything else in a worktree is a copy or a junction
/*
!/.gitattributes
!/Skills/
!/Tool_scripts/
/Tool_scripts/*
!/Tool_scripts/Tools_code/
# the vendored Pillow is binary and matched to Blender's Python, so it is never part of the
# store: _copy_code puts a copy in every view, and this keeps the sweep from deleting it
Tool_scripts/Tools_code/_vendor/
!/Tool_scripts/Tools_ref/
!/prompt_files/
__pycache__/
*.pyc
"""
ATTRIBUTES = """# skills and checklists are add-only: both sides of an overlap are kept
Skills/**/*.md merge=union
# generated indexes are never merged, they are regenerated after the merge
Tool_scripts/Tools_ref/INDEX.md merge=ours
prompt_files/current_tools.md merge=ours
"""


# ── git plumbing ─────────────────────────────────────────────────────────────

def _git(args, cwd=None, main=False, check=True, capture=True):
    argv = ["git"]
    if main:
        argv += ["--git-dir", str(GIT_DIR), "--work-tree", str(ROOT)]
    argv += list(args)
    r = subprocess.run([str(a) for a in argv], cwd=str(cwd or ROOT), capture_output=capture, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(str(a) for a in args)} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def store_ready() -> bool:
    return (GIT_DIR / "HEAD").is_file()


def init_store(force: bool = False) -> None:
    """Create harness/store.git with THIS folder's store as the first commit on main."""
    if store_ready() and not force:
        print(f"[harness] store exists: {GIT_DIR}")
        return
    HARNESS.mkdir(exist_ok=True)
    _git(["init", "-q", "--bare", "--initial-branch=main", str(GIT_DIR)])
    for k, v in (("core.bare", "false"), ("core.worktree", str(ROOT)), ("core.autocrlf", "false"),
                 ("status.showUntrackedFiles", "no"), ("merge.ours.driver", "true"),
                 ("user.name", "blendcua harness"), ("user.email", "harness@blendcua.local")):
        _git(["config", k, v], main=True)
    (GIT_DIR / "info").mkdir(exist_ok=True)
    (GIT_DIR / "info" / "exclude").write_text(EXCLUDE, encoding="utf-8")
    (ROOT / ".gitattributes").write_text(ATTRIBUTES, encoding="utf-8")
    _git(["add", "-A", "--", ".gitattributes", *STORE_DIRS], main=True)
    _git(["commit", "-q", "-m", f"store as of {time.strftime('%Y-%m-%d %H:%M')} (H_00 accepted)"], main=True)
    print(f"[harness] initialised {GIT_DIR}; main = {_git(['rev-parse', '--short', 'HEAD'], main=True).stdout.strip()}")


# ── views ────────────────────────────────────────────────────────────────────

def view_dir(k: int) -> Path:
    return HARNESS / f"w{k}"


def _is_junction(p: Path) -> bool:
    try:
        return bool(os.lstat(p).st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT)
    except (OSError, AttributeError):
        return False


def _junction(link: Path, target: Path) -> None:
    if _is_junction(link):
        return
    if link.exists():
        raise RuntimeError(f"{link} exists and is not a junction")
    link.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    if r.returncode != 0 or not _is_junction(link):
        raise RuntimeError(f"mklink /J {link} -> {target} failed: {r.stdout} {r.stderr}")


def _adopt_real_entries(dv: Path, shared: Path) -> list[str]:
    """Real (non-junction) entries an agent created inside a per-task link folder belong to the
    shared folder: move each there unless a namesake exists (then leave it and return its name).
    Loose files that are copies of the shared folder's own files are left for the refresh."""
    kept = []
    for p in list(dv.iterdir()):
        if _is_junction(p):
            continue
        if p.is_file() and (shared / p.name).is_file():
            continue
        if (shared / p.name).exists():
            kept.append(p.name)
            continue
        shutil.move(str(p), str(shared / p.name))
        print(f"[harness] {dv}: moved {p.name} into the shared folder", flush=True)
    return kept


def _link_whole(view: Path, rel: str) -> None:
    """view/rel as one junction to ROOT/rel, undoing a per-task folder left by an earlier sync."""
    link, shared = view / rel, ROOT / rel
    if link.exists() and not _is_junction(link):
        kept = _adopt_real_entries(link, shared)
        if kept:
            raise RuntimeError(f"{link}: real entries {kept} also exist in {shared}; resolve by hand")
        for p in list(link.iterdir()):
            if _is_junction(p):
                os.rmdir(p)          # removes the link only, never the shared data
            else:
                p.unlink()           # a copied loose file
        link.rmdir()
    _junction(link, shared)


def _link_per_task(view: Path, rel: str, task: str, hide: set[str]) -> list[str]:
    """view/rel becomes a real folder holding one junction per entry of ROOT/rel except the hidden
    tasks', plus fresh copies of its loose files (plans/EXEMPLARS.txt, written only by the driver
    in the main folder). Returns the hidden names that exist in the shared folder."""
    dv, shared = view / rel, ROOT / rel
    (shared / task).mkdir(parents=True, exist_ok=True)      # the task's own folder always exists
    if _is_junction(dv):
        os.rmdir(dv)                                         # the old whole-folder link only
    dv.mkdir(parents=True, exist_ok=True)
    kept = _adopt_real_entries(dv, shared)
    if kept:
        print(f"[harness] {dv}: real entries left in place, a namesake exists in the shared "
              f"folder: {kept}", flush=True)
    want = {p.name for p in shared.iterdir() if p.is_dir() and p.name not in hide}
    for p in list(dv.iterdir()):
        if _is_junction(p) and p.name not in want:
            os.rmdir(p)
    for name in sorted(want):
        if not (dv / name).exists():
            _junction(dv / name, shared / name)
    for f in shared.iterdir():
        if f.is_file():
            shutil.copy2(f, dv / f.name)
    return sorted(hide & {p.name for p in shared.iterdir()})


def _copy_if_changed(src, dst):
    """copytree's copy_function for _vendor: leave a file alone when the view already has the same
    one. The worker's Blender keeps the vendored Pillow's .pyd files open once it has imported them,
    and Windows will not overwrite a loaded DLL: a plain copy failed the view sync with WinError 32
    and cost 20_low_poly_well its round (2026-09-17)."""
    try:
        s, d = os.stat(src), os.stat(dst)
        if s.st_size == d.st_size and int(s.st_mtime) == int(d.st_mtime):
            return dst
    except OSError:
        pass
    return shutil.copy2(src, dst)


def _copy_code(view: Path) -> int:
    n = 0
    for pat in CODE_GLOBS:
        for src in ROOT.glob(pat):
            if src.is_file() and src.name not in ("run_v2.log", "run_v2_console.log", "blendcua.env"):
                shutil.copy2(src, view / src.name); n += 1
    for src in (ROOT / "Tool_scripts").iterdir():
        if src.is_file():
            shutil.copy2(src, view / "Tool_scripts" / src.name); n += 1
    # Blender ships no Pillow, so the project vendors one built for Blender's Python in
    # Tools_code/_vendor. It is gitignored, so a worktree checkout never brought it and every
    # action that needed Pillow failed in the views; the executor's workaround (the venv's
    # Pillow, built for another Python) then failed on `_imaging` for the rest of that Blender
    # session. Copy it in like the rest of the code. (2026-09-16)
    vendor = ROOT / "Tool_scripts" / "Tools_code" / "_vendor"
    if vendor.is_dir():
        shutil.copytree(vendor, view / "Tool_scripts" / "Tools_code" / "_vendor", dirs_exist_ok=True,
                        copy_function=_copy_if_changed)
        n += 1
    for d in CODE_DIRS:
        sd, dd = ROOT / d, view / d
        dd.mkdir(parents=True, exist_ok=True)
        for src in sd.rglob("*"):
            rel = src.relative_to(sd)
            if any(part in ("reports", "state", "__pycache__", "eval") for part in rel.parts):
                continue
            if src.is_file():
                (dd / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dd / rel); n += 1
    # the Hermes home(s): per-port homes are junctions to the shared ones, so the agents keep
    # their sessions and auth exactly as today
    for h in ROOT.glob(".hermes_home*"):
        if h.is_dir():
            _junction(view / h.name, h)
    return n


def _discard_untracked(view: Path) -> list[str]:
    """Files a worker left in its store that no accepted remedy claimed (the executor's
    'write a helper into Tools_code' path). Never touches junctions: only the tracked dirs
    are considered by the exclude rules."""
    r = _git(["ls-files", "--others", "--exclude-standard", "--", *STORE_DIRS], cwd=view)
    gone = []
    for rel in r.stdout.split("\n"):
        rel = rel.strip()
        if rel:
            p = view / rel
            if p.is_file():
                p.unlink(); gone.append(rel)
    return gone


def _clean_scratch(view: Path) -> int:
    """Delete loose files at the view root. The agents work with the view as their cwd and, whatever
    the prompts say, drop `tmp_*.py`, `_crop_*.png` and notes there (500+ files per worker after a
    day, 2026-09-12). The root should hold only the code copies, the store folders and the junctions;
    real outputs live in the step's or the report's scripts/ folder, which this never touches."""
    keep = {p.name for pat in CODE_GLOBS for p in ROOT.glob(pat)} | {".gitattributes", ".git"}
    # ".git" is the worktree link file: sweeping it (2026-09-12) made git forget the view and the next
    # sync failed with "worktree add: already exists"
    n = 0
    for p in view.iterdir():
        if p.is_file() and p.name not in keep:
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    return n


def sync(k: int, keep_store: bool = False, task: str | None = None, hide=()) -> Path:
    """Make worker k's view equal to main: store from the branch, code copied fresh, data linked.

    task/hide: with a task, the task-keyed data folders (PER_TASK_LINKS) are linked entry by entry
    and the `hide` tasks (the others queued in the same driver session) are left out; without a
    task every data folder is one junction, as before.

    keep_store: the view's store is left exactly as it is (no discard, no reset) — for a task
    whose round is mid-flight (remedy applied, not yet accepted): its uncommitted remedy edits
    live in this view and the restart must find them. Code copies and junctions are refreshed."""
    if not store_ready():
        init_store()
    view = view_dir(k)
    branch = f"w{k}"
    if not (view / ".git").exists():
        view.parent.mkdir(exist_ok=True)
        if view.exists():
            # a folder without its .git link is an orphaned view: git would refuse "already exists"
            print(f"[harness] view w{k} has no .git link: removing the orphaned folder and pruning", flush=True)
            for p in sorted(view.rglob("*"), key=lambda x: -len(x.parts)):
                if _is_junction(p):
                    os.rmdir(p)
            for p in view.iterdir():  # empty it; the folder itself may be a Blender's cwd (locked)
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            _git(["worktree", "prune"], main=True)  # git accepts an empty folder for "worktree add"
        if _git(["rev-parse", "--verify", "-q", f"refs/heads/{branch}"], main=True, check=False).returncode == 0:
            _git(["worktree", "add", "-f", str(view), branch], main=True)
        else:
            _git(["worktree", "add", "-b", branch, str(view), "main"], main=True)
    gone = []
    if keep_store and (view / ".git").exists():
        print(f"[harness] view w{k}: store kept as it is (a round is mid-flight)", flush=True)
    else:
        gone = _discard_untracked(view)
        _git(["reset", "-q", "--hard", "main"], cwd=view)
    hide = set(hide or ()) - ({task} if task else set())
    hidden: set[str] = set()
    for d in DATA_LINKS:
        if task and d in PER_TASK_LINKS:
            hidden |= set(_link_per_task(view, d, task, hide))
        else:
            _link_whole(view, d)
    n = _copy_code(view)
    swept = _clean_scratch(view)
    # the view's per-port hermes home names are junctions to ROOT's; the code copies read them
    msg = f"[harness] view w{k} synced to main {_git(['rev-parse', '--short', 'main'], main=True).stdout.strip()}: {n} code files copied"
    if swept:
        msg += f", {swept} scratch file(s) swept from the view root"
    if gone:
        msg += f"; discarded {len(gone)} unreviewed file(s) left in the store: {gone[:6]}"
    if task:
        msg += (f"; {'/'.join(PER_TASK_LINKS)} linked per task for {task}"
                + (f", hiding {sorted(hidden)}" if hidden else ""))
    print(msg, flush=True)
    return view


# ── publish ──────────────────────────────────────────────────────────────────

def _in_store(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return any(rel == d or rel.startswith(d + "/") for d in STORE_DIRS)


def _conflicted(cwd=None, main=False) -> list[str]:
    r = _git(["diff", "--name-only", "--diff-filter=U"], cwd=cwd, main=main)
    return [l.strip().replace("\\", "/") for l in r.stdout.splitlines() if l.strip()]


def _resolve_conflict(rel: str, branch: str) -> str:
    """A real conflict (both sides changed the same lines of a code file). Try an agent; fall
    back to main's version with the other side saved next to it."""
    live = ROOT / rel
    ours = _git(["show", f"HEAD:{rel}"], main=True, check=False).stdout
    theirs = _git(["show", f"{branch}:{rel}"], main=True, check=False).stdout
    how = "fallback"
    try:
        sys.path.insert(0, str(ROOT))
        import agent_env  # noqa: E402
        # plugins are discovered when run_agent is first imported: enable them BEFORE that import
        agent_env.ensure_plugin_env()
        from run_agent import AIAgent  # noqa: E402
        import blendcua_core as core  # noqa: E402
        from models import MODELS, OPENAI_REASONING_EFFORT  # noqa: E402
        core.load_api_keys(verbose=False)
        cfg = MODELS.get("curator") or MODELS["planner"]
        kwargs = dict(provider=cfg["provider"], model=cfg["model"], api_key=core.api_key_for(cfg["provider"]),
                      base_url=core.base_url_for(cfg["provider"]), quiet_mode=True, max_iterations=12,
                      ephemeral_system_prompt="You merge conflicting edits carefully and minimally.",
                      enabled_toolsets=agent_env.CURATOR_TOOLSETS)
        if cfg["provider"] == "openai":
            kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}
        msg = (f"Two workers changed the same file of a Blender build harness and git could not merge them.\n"
               f"File: {rel}\n\nRead it now: it contains git conflict markers (<<<<<<<, =======, >>>>>>>).\n"
               f"Write the merged file back to the same path: keep BOTH intents (both tools/functions/"
               f"sections must remain usable), remove the markers, keep it valid Python or Markdown, do not "
               f"drop either side's additions. Change nothing else. Then reply with one line: MERGED.")
        res = AIAgent(**kwargs).run_conversation(msg)
        txt = live.read_text(encoding="utf-8", errors="replace")
        if "<<<<<<<" not in txt and ">>>>>>>" not in txt and txt.strip():
            how = "agent"
        else:
            print(f"[harness] agent left {rel} unresolved; its reply: "
                  f"{(res.get('final_response') or '')[:300]!r}")
    except Exception as e:  # noqa: BLE001
        print(f"[harness] agent merge failed for {rel}: {e!r}")
    if how == "fallback":
        live.write_text(ours, encoding="utf-8", newline="")
        side = live.with_name(live.stem + f".from_{branch}" + live.suffix)
        side.write_text(theirs, encoding="utf-8", newline="")
        _git(["add", "--", str(side.relative_to(ROOT))], main=True)
    _git(["add", "--", rel], main=True)
    return how


def regenerate_indexes() -> None:
    subprocess.run([sys.executable, str(ROOT / "Tool_scripts" / "gen_tool_index.py")], cwd=str(ROOT),
                   capture_output=True, text=True)


def snapshot_main(note: str) -> str | None:
    """snapshots/H_NN from main's store (feedback_agent --snapshot), with a note."""
    before = {p.name for p in (ROOT / "snapshots").glob("H_*")}
    subprocess.call([sys.executable, str(ROOT / "feedback_agent.py"), "--snapshot"], cwd=str(ROOT))
    new = sorted({p.name for p in (ROOT / "snapshots").glob("H_*")} - before)
    if not new:
        return None
    (ROOT / "snapshots" / new[-1] / "VERSION_B_NOTE.md").write_text(note, encoding="utf-8")
    return new[-1]


_KEY_STOP = {"low", "poly", "run", "the", "of", "a", "and"}


def _subject_words(name: str) -> set[str]:
    import re
    return {w for w in re.split(r"[_\W]+", name.lower()) if w and not w.isdigit() and w not in _KEY_STOP}


def hide_answer_keys(view: Path, task: str) -> list[str]:
    """Delete from the view the good_context judgement(s) of this task's own subject.

    Skills/Curator/good_context/ holds a person's verdict on nine finished builds; for a task
    on one of those subjects that file is the answer key and must not be in any agent's
    reach (the README asks for it; this does it). Matching is by subject word: 08_shark hides
    17_shark.txt, 09_thors_hammer hides both hammer files, 10_low_poly_dog hides
    20_low_poly_dog.txt. The deletion is an uncommitted change in the worker's view only;
    the next sync's reset brings the file back. general_rules.txt and README.txt stay."""
    words = _subject_words(task)
    gc = view / "Skills" / "Curator" / "good_context"
    hidden: list[str] = []
    if not gc.is_dir() or not words:
        return hidden
    for f in sorted(gc.glob("*.txt")):
        if f.name in ("README.txt", "general_rules.txt"):
            continue
        if words & _subject_words(f.stem):
            f.unlink()
            hidden.append(f.name)
    return hidden


def publish(k: int, task: str, files: list[str], message: str, *, snapshot_note: str | None = None) -> dict:
    """Commit the named store files on worker k's branch and merge them into main."""
    view = view_dir(k)
    branch = f"w{k}"
    files = [f.replace("\\", "/") for f in files if _in_store(f)]
    rep = {"worker": k, "task": task, "files": files, "merged": False, "conflicts": {}, "snapshot": None}
    if not files:
        print(f"[harness] w{k}: nothing in the store to publish for {task}")
        return rep
    existing = [f for f in files if (view / f).exists()]
    deleted = [f for f in files if not (view / f).exists()]
    if existing:
        _git(["add", "-f", "--", *existing], cwd=view)
    if deleted:
        _git(["rm", "-q", "--cached", "--ignore-unmatch", "--", *deleted], cwd=view)
    if _git(["diff", "--cached", "--quiet"], cwd=view, check=False).returncode == 0:
        print(f"[harness] w{k}: the named files are unchanged against {branch}; nothing to publish")
        return rep
    _git(["commit", "-q", "-m", message], cwd=view)
    rep["commit"] = _git(["rev-parse", "--short", "HEAD"], cwd=view).stdout.strip()
    # merge into main (this folder's store). Serial by construction: the driver holds a lock.
    r = _git(["merge", "--no-ff", "--no-edit", "-m", f"merge {branch}: {message}", branch], main=True, check=False)
    if r.returncode != 0:
        for rel in _conflicted(main=True):
            rep["conflicts"][rel] = _resolve_conflict(rel, branch)
        if _conflicted(main=True):
            _git(["merge", "--abort"], main=True, check=False)
            rep["error"] = "unresolved conflicts, merge aborted"
            print(f"[harness] merge of {branch} aborted: {rep['conflicts']}")
            return rep
        _git(["commit", "-q", "--no-edit"], main=True)
    regenerate_indexes()
    _git(["add", "-A", "--", *STORE_DIRS], main=True)
    if _git(["diff", "--cached", "--quiet"], main=True, check=False).returncode != 0:
        _git(["commit", "-q", "-m", f"regenerate indexes after {branch}"], main=True)
    rep["merged"] = True
    rep["main"] = _git(["rev-parse", "--short", "main"], main=True).stdout.strip()
    # the branch now equals main (fast-forward), so the worker's next sync is a no-op reset
    _git(["reset", "-q", "--hard", "main"], cwd=view)
    if snapshot_note is not None:
        rep["snapshot"] = snapshot_main(snapshot_note)
    print(f"[harness] w{k} -> main {rep['main']}: {len(files)} file(s) from {task}"
          + (f"; conflicts {rep['conflicts']}" if rep["conflicts"] else "")
          + (f"; snapshot {rep['snapshot']}" if rep["snapshot"] else ""), flush=True)
    _log(rep)
    return rep


def _log(rep: dict) -> None:
    HARNESS.mkdir(exist_ok=True)
    with (HARNESS / "publish_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **rep}) + "\n")


def files_from_applied(applied: dict) -> list[str]:
    """The store files a remedy round claimed (applied.json)."""
    out = set()
    ch = (applied or {}).get("changes") or {}
    for key in ("modified", "created", "deleted"):
        out |= {str(f).replace("\\", "/") for f in ch.get(key, [])}
    for r in (applied or {}).get("remedies") or []:
        for part in ("local_fix", "durable_record"):
            out |= {str(f).replace("\\", "/") for f in ((r.get(part) or {}).get("files") or [])}
    return sorted(f for f in out if _in_store(f))


def status() -> None:
    if not store_ready():
        print("[harness] no store yet (python harness.py init)"); return
    print(_git(["log", "--oneline", "-8", "main"], main=True).stdout)
    print(_git(["worktree", "list"], main=True).stdout)
    for v in sorted(HARNESS.glob("w*")):
        if (v / ".git").exists():
            head = _git(["rev-parse", "--short", "HEAD"], cwd=v).stdout.strip()
            dirty = _git(["status", "--porcelain", "--", *STORE_DIRS], cwd=v).stdout.strip()
            print(f"  {v.name}: {head}{'  (dirty: ' + str(len(dirty.splitlines())) + ' files)' if dirty else ''}")


def remove_view(k: int) -> None:
    """Delete a view safely: junctions are unlinked (never descended into), then the rest goes."""
    view = view_dir(k)
    if not view.exists():
        print(f"[harness] no view w{k}"); return
    for p in sorted(view.rglob("*"), key=lambda x: -len(x.parts)):
        if _is_junction(p):
            os.rmdir(p)
    for p in view.rglob("*"):
        if _is_junction(p):
            raise RuntimeError(f"junction survived: {p}")
    shutil.rmtree(view)
    _git(["worktree", "prune"], main=True)
    _git(["branch", "-D", f"w{k}"], main=True, check=False)
    print(f"[harness] removed view w{k} and branch w{k}")


def reset_main(rev: str) -> None:
    _git(["reset", "-q", "--hard", rev], main=True)
    regenerate_indexes()
    print(f"[harness] main reset to {rev}: {_git(['rev-parse', '--short', 'HEAD'], main=True).stdout.strip()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").add_argument("--force", action="store_true")
    sub.add_parser("sync").add_argument("k", type=int)
    p = sub.add_parser("publish"); p.add_argument("k", type=int); p.add_argument("--task", required=True)
    p.add_argument("--files", nargs="+", required=True); p.add_argument("-m", dest="message", required=True)
    p.add_argument("--snapshot-note", default=None)
    sub.add_parser("status")
    sub.add_parser("reset-main").add_argument("rev")
    sub.add_parser("remove").add_argument("k", type=int)
    a = ap.parse_args()
    if a.cmd == "init":
        init_store(force=a.force)
    elif a.cmd == "sync":
        sync(a.k)
    elif a.cmd == "publish":
        print(json.dumps(publish(a.k, a.task, a.files, a.message, snapshot_note=a.snapshot_note), indent=1))
    elif a.cmd == "status":
        status()
    elif a.cmd == "reset-main":
        reset_main(a.rev)
    elif a.cmd == "remove":
        remove_view(a.k)


if __name__ == "__main__":
    main()
