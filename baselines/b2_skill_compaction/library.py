"""The skill library on disk.

    library/skills/<name>.py      the skill's code: a module of documented functions
    library/skills/<name>.md      the skill's prose: what it does, when to use it, how
    library/skills/index.json     {name: {description, when_to_use, functions, source_task,
                                          version, created_at, updated_at, history}}
    library/snapshots/NN/         copy of skills/ after task NN's compaction
    library/library_log.jsonl     every write, update, retrieval, on-demand load and reference

index.json is written last, atomically, so a reader never sees an entry whose
files are not there yet.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

import b2_config as CFG

INDEX = CFG.SKILLS / "index.json"
_LOCK = threading.Lock()
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,60}$")


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_index(skills_dir: Path = CFG.SKILLS) -> dict:
    try:
        return json.loads((Path(skills_dir) / "index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_index(index: dict) -> None:
    CFG.SKILLS.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2), encoding="utf-8")
    os.replace(tmp, INDEX)


def log(event: str, **fields) -> None:
    CFG.LIBRARY.mkdir(parents=True, exist_ok=True)
    rec = {"at": now(), "event": event, **fields}
    with _LOCK, open(CFG.LIBRARY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


LOAD_SKILL_TOOL = ("- `load_skill(name)`: shows the full documentation and code of a skill "
                   "from your skill\n  library (see below).\n")

LIBRARY_PROSE = """## Your skill library

You keep a library of reusable skills that you wrote yourself after earlier tasks. Each skill
is a Python module of documented functions plus a short description of when to use it. The
modules are importable inside Blender with a plain `import <skill_name>` (their folder is on
`sys.path`). Skills are there to save you work, but use your judgement: adapt or ignore a
skill that does not fit this task.

{skills_section}

"""


def prompt_blocks(index: dict, picked: list[str]) -> dict:
    """The two prompt blocks that differ between a normal run and a no-library
    ablation (CFG.NO_LIBRARY). Both agents build them from here so the variants
    can never drift apart in any other wording."""
    if CFG.NO_LIBRARY:
        return {"load_skill_tool": "", "library_section": ""}
    if index:
        skills = ("Skills available now (all importable; the ones marked * are shown in full "
                  "in the first message, use `load_skill` for the others):\n\n" + "\n".join(
                      ("* " if n in picked else "  ") + line for n, line in
                      zip(sorted(index), index_listing(index).splitlines())))
    else:
        skills = "The library is empty: this is the first task you have done."
    return {"load_skill_tool": LOAD_SKILL_TOOL,
            "library_section": LIBRARY_PROSE.format(skills_section=skills)}


def index_listing(index: dict) -> str:
    """One line per skill: the menu the retriever and the agent both see."""
    if not index:
        return "(the library is empty)"
    lines = []
    for name, e in sorted(index.items()):
        fns = ", ".join(e.get("functions", [])[:8])
        lines.append(f"- `{name}` — {e.get('description', '').strip()} "
                     f"(when: {e.get('when_to_use', '').strip()}) [functions: {fns}]")
    return "\n".join(lines)


def skill_text(name: str, skills_dir: Path = CFG.SKILLS) -> str | None:
    d = Path(skills_dir)
    py, md = d / f"{name}.py", d / f"{name}.md"
    if not py.is_file():
        return None
    doc = md.read_text(encoding="utf-8") if md.is_file() else ""
    return (f"### Skill `{name}`\n\n{doc.strip()}\n\n"
            f"Code (`import {name}` inside run_python):\n```python\n"
            f"{py.read_text(encoding='utf-8').strip()}\n```\n")


def copy_library(dest: Path) -> dict:
    """Copy the current library to dest (a run's skills folder); returns its index."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    index = read_index()
    for name in index:
        for ext in (".py", ".md"):
            src = CFG.SKILLS / f"{name}{ext}"
            if src.is_file():
                shutil.copy2(src, dest / src.name)
    (dest / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def put_skill(name: str, *, code: str, doc: str, description: str, when_to_use: str,
              functions: list[str], task: str, run: str, replaces: str | None) -> str:
    """Write or update one skill. Returns 'write' or 'update'."""
    with _LOCK:
        index = read_index()
        CFG.SKILLS.mkdir(parents=True, exist_ok=True)
        kind = "update" if name in index else "write"
        if replaces and replaces != name and replaces in index:
            # renamed on update: retire the old entry
            for ext in (".py", ".md"):
                p = CFG.SKILLS / f"{replaces}{ext}"
                if p.exists():
                    p.unlink()
            old = index.pop(replaces)
            kind = "update"
        else:
            old = index.get(name)
        (CFG.SKILLS / f"{name}.py").write_text(code.rstrip() + "\n", encoding="utf-8")
        (CFG.SKILLS / f"{name}.md").write_text(doc.rstrip() + "\n", encoding="utf-8")
        hist = list((old or {}).get("history", []))
        hist.append({"task": task, "run": run, "at": now(), "kind": kind})
        index[name] = {
            "description": description, "when_to_use": when_to_use, "functions": functions,
            "source_task": (old or {}).get("source_task", task),
            "version": int((old or {}).get("version", 0)) + 1,
            "created_at": (old or {}).get("created_at", now()), "updated_at": now(),
            "history": hist,
        }
        _write_index(index)
    return kind


def snapshot(label: str) -> Path:
    dest = CFG.SNAPSHOTS / label
    with _LOCK:
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if CFG.SKILLS.is_dir():
            shutil.copytree(CFG.SKILLS, dest)
        else:
            dest.mkdir()
    return dest


def referenced_skills(codes: list[str], names: list[str]) -> list[str]:
    """Skills whose module name appears as an identifier in the agent's code."""
    blob = "\n".join(codes)
    return sorted(n for n in names if re.search(rf"\b{re.escape(n)}\b", blob))
