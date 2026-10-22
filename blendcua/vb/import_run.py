"""Copy a recorded run (and optionally its plan) from another folder into THIS one, re-rooted.

    python vb/import_run.py --from ../BlendCuaLoop_try --run 17_shark_run_001 [--plan]
    python vb/import_run.py --from ../BlendCuaLoop_try --run 04_datestone_1934_run_001 --as 01_datestone_1934_run_001 --plan
        (the task was renumbered here: the run, its plan folder and every mention inside are renamed)
    python vb/import_run.py --relocate mem/17_shark_run_001      # re-root an already copied tree

Every path spelling of the source folders in vb/common.OLD_ROOTS is rewritten to this folder's
root, so the actions import Tools_code from HERE and write their reports HERE. A run copied
with plain cp keeps its old root and, when replayed, silently uses and writes into the OTHER
folder (this happened once; the symptom was a stale tool and screenshots landing elsewhere).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

TEXT = {".py", ".md", ".json", ".txt", ".jsonl", ".log", ".csv", ".yaml", ".yml"}


def relocate_tree(d: Path) -> int:
    n = 0
    for p in d.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT or "__pycache__" in p.parts:
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        t2 = t
        for old in C.OLD_ROOTS:
            t2 = t2.replace(old, C.NEW_ROOT_ESCAPED if "\\\\" in old else C.NEW_ROOT)
        if t2 != t:
            p.write_text(t2, encoding="utf-8", newline="")
            n += 1
    return n


def rename_tree(d: Path, old_task: str, new_task: str) -> int:
    """A task renumbered here: rewrite the old task name (and so the old run name) in every text file,
    and rename files/folders that carry it (plan md, marked json/jpg)."""
    n = 0
    for p in d.rglob("*"):
        if p.is_file() and p.suffix.lower() in TEXT:
            try:
                t = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if old_task in t:
                p.write_text(t.replace(old_task, new_task), encoding="utf-8", newline="")
                n += 1
    for p in sorted(d.rglob(f"*{old_task}*"), key=lambda x: -len(str(x))):
        p.rename(p.with_name(p.name.replace(old_task, new_task)))
    return n


def leftovers(d: Path) -> dict:
    """Any foreign root spelling still present, by folder name."""
    import re
    hits: dict[str, int] = {}
    for p in d.rglob("*.py"):
        try:
            for m in re.findall(r"BlendCua[A-Za-z0-9_]+", p.read_text(encoding="utf-8")):
                if m != C.ROOT.name:
                    hits[m] = hits.get(m, 0) + 1
        except (UnicodeDecodeError, OSError):
            pass
    return hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default=None, help="source project folder")
    ap.add_argument("--run", default=None)
    ap.add_argument("--plan", action="store_true", help="also copy plans/<task>")
    ap.add_argument("--as", dest="as_run", default=None, help="import under this run name (task renamed accordingly)")
    ap.add_argument("--relocate", default=None, help="only re-root this tree (relative to this folder)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.relocate:
        d = (C.ROOT / a.relocate).resolve()
        print(f"[import] re-rooted {relocate_tree(d)} files under {d.relative_to(C.ROOT)}; leftovers: {leftovers(d) or 'none'}")
        return
    if not (a.src and a.run):
        ap.error("--from and --run, or --relocate")
    src = Path(a.src).resolve()
    new_run = a.as_run or a.run
    old_task, new_task = C.task_of_run(a.run), C.task_of_run(new_run)
    targets = [(src / "mem" / a.run, C.MEM / new_run)]
    if a.plan:
        targets.append((src / "plans" / old_task, C.PLANS / new_task))
    for s, d in targets:
        if not s.is_dir():
            raise SystemExit(f"[import] no such source: {s}")
        if d.exists():
            if not a.force:
                raise SystemExit(f"[import] {d.relative_to(C.ROOT)} exists (use --force)")
            shutil.rmtree(d)
        shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        n = relocate_tree(d)
        if new_task != old_task:
            n += rename_tree(d, old_task, new_task)
        print(f"[import] copied {s} -> {d.relative_to(C.ROOT)}; re-rooted/renamed {n} files; "
              f"leftovers: {leftovers(d) or 'none'}")


if __name__ == "__main__":
    main()
