"""BlendCUA native tool plugin — write_and_run.

Registered as a real Hermes tool (not an MCP server) specifically so its
result can use the ``_multimodal`` envelope: a native tool's image result
gets attached to the model's context directly and shown on its next turn,
inside the SAME conversation — unlike an MCP tool's result, which we
confirmed empirically only ever reaches the model as a cached file path,
never as actual pixels (see blendcua_core.py's module docstring for the
full story).

This lets the Step-Subagent go back to autonomously calling write_and_run
as many times as it wants inside one continuous run_conversation() call,
seeing every screenshot inline — the same shape BlendCuagent2's Claude SDK
subagent had, instead of the one-call-per-action workaround this port
needed before this plugin existed.

Which step/run this handler writes into is tracked in
blendcua_core.CURRENT_ACTION_CONTEXT, a module-level dict the orchestrator
sets immediately before handing control to the subagent for a given step
(dispatch_step calls are strictly serial within one process, so a plain
module-level dict is safe — no concurrent steps ever share this).
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[3])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import base64
import fnmatch
import json
import os
import re
import shutil
import time
from pathlib import Path

import blendcua_core as core

WRITE_AND_RUN_SCHEMA = {
    "name": "write_and_run",
    "description": (
        "Write ONE Blender action file into this step's directory and run it "
        "immediately. Blocks until Blender finishes and returns "
        "{ok, note, error, screenshot, overlay}. Set show_screenshot=true for "
        "perception/verification actions (overlays, after-transform checks) "
        "— the resulting screenshot (the overlay PNG when the action rendered "
        "one, else the bare viewport shot) is attached as a real image on "
        "your next turn, no separate Read needed. Set show_screenshot=false "
        "for blind setup actions (add object, modifier, mode set, join) to "
        "save tokens. On error, `error` holds the full Python traceback — fix "
        "the content and call again with the SAME filename (edit in place)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "e.g. 'NN_name.py' — no directories.",
            },
            "content": {
                "type": "string",
                "description": "Full Python source for the action file.",
            },
            "show_screenshot": {
                "type": "boolean",
                "description": "Attach the resulting screenshot as an image on your next turn.",
            },
        },
        "required": ["filename", "content"],
    },
}


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}


def _image_part(path: Path) -> dict | None:
    """One image content-part for the _multimodal envelope, or None."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    mime = _MIME.get(path.suffix.lower(), "image/png")
    b64 = base64.standard_b64encode(data).decode("ascii")
    return {"type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _multimodal(status_text: str, paths: list) -> object:
    """Build a multimodal tool result: status text, then each image preceded by
    a line naming it.

    The label matters as much as the pixels. With several images in one result
    the model otherwise has no way to tell the head crop from the right-side
    view, and captioning them is what makes 'render three views and compare'
    a usable move instead of a guess.
    """
    content = [{"type": "text", "text": status_text}]
    attached = []
    for p in paths:
        part = _image_part(p)
        if part is None:
            continue
        try:
            label = str(rel_to(p, ROOT))
        except ValueError:
            label = p.name
        content.append({"type": "text", "text": f"[image] {label}"})
        content.append(part)
        attached.append(label)
    if not attached:
        return status_text
    return {"_multimodal": True, "content": content, "text_summary": status_text}


def _trace(name: str, detail: str) -> None:
    """One line per tool INVOCATION, with its arguments, into terminal.log.

    hermes logs `tool <name> completed (0.6s, N chars)` — the name and timing,
    never the arguments. Reading a rollout afterwards, "13 write_and_run calls"
    says nothing; "write_and_run(07_preview_head_profile.py)" twice says the
    agent re-previewed before committing. That distinction is the whole point
    of keeping a log.
    """
    core.log_print(f"[tool] {name}({detail})")


def _handle_write_and_run(args: dict, **kw) -> object:
    ctx = core.CURRENT_ACTION_CONTEXT
    run_name = ctx.get("run_name")
    step_dir = ctx.get("step_dir")
    if not run_name or step_dir is None:
        return json.dumps({"ok": False, "error": "no active BlendCUA step context — infra bug"})

    filename = str(args.get("filename", "")).strip()
    content = args.get("content", "") or ""
    show = bool(args.get("show_screenshot", True))
    _trace("write_and_run", f"{filename}, show_screenshot={show}")

    result = core.write_and_run_action(
        run_name=run_name, step_dir=step_dir, filename=filename, content=content,
    )
    shown_paths = [Path(p) for p in (result.pop("shown_abs_paths", None) or [])]
    dropped = result.pop("shown_dropped", 0)
    if dropped:
        result["note"] = (result.get("note") or "") + (
            f" [{dropped} further image(s) this action rendered were not "
            f"attached — at most {core.MAX_IMAGES_PER_RESULT} come back per "
            f"call; render fewer views, or read the rest individually]")
    status_text = json.dumps(result)

    if result.get("ok") and show and shown_paths:
        return _multimodal(status_text, shown_paths)

    return status_text


# ── Shell / file access, implemented natively ────────────────────────────────
#
# The agent needs to read a file, search the codebase, and run a scrap of
# Python (crop a screenshot with PIL, scan for an edge, dump a mesh) — doing
# those as Blender actions wastes the step's action budget and, for anything
# slow, freezes the whole Blender session.
#
# Hermes ships `file`, `terminal` and `code_execution` toolsets for exactly
# this, and they are the obvious choice, but they do not work in this
# embedding: every one of them routes through `tools/terminal_tool.py`'s
# environment machinery, which spawns a Git Bash session — and inside the MCP
# dispatch subprocess that spawn never returns. Observed directly on
# bat_newplan_001: the subagent's first move was `read_file` + 3×
# `search_files`, "Creating new local environment for task default..." was
# logged, "environment ready" never was, and the batch sat there for the full
# 420s tool timeout before hermes' own error path crashed on an
# UnboundLocalError. Zero actions ran; Blender stayed empty. It could not be
# reproduced outside the live embedding (tried: isolation, 4-way concurrency,
# an anyio worker thread, the redirected stdout, hermes' filtered subprocess
# env, an unread stdin pipe, HERMES_HOME set, and a console-less spawn — all
# complete in ~1.4s).
#
# So these three do the same jobs with plain Python and no environment
# machinery, in the same plugin as write_and_run, which does work here. They
# are confined to the project directory, which as a side effect keeps them
# away from the API key file (deliberately outside the repo — see
# core.load_api_keys).

ROOT = core.AGENT_DIR

# Directories worth never walking: mem/ holds thousands of screenshots per run
# and would dominate every search.
_SEARCH_SKIP_DIRS = {"mem", ".git", "__pycache__", ".hermes_home", "images",
                     "node_modules", ".venv", "venv"}
_TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".cfg", ".toml"}


def _foreign_run(path: Path) -> str | None:
    """The run name if `path` belongs to a run OTHER than the current one.

    mem/ holds every run this project has ever done, including the failed ones
    the plan quotes as cautionary tales ("a previous build left both at 1.0",
    "the last build had no narrowing at all"). Those references read as an
    invitation to go and look, and on the first bat_gptlunamed6 attempt the
    subagent took it: ~30 tool calls reading three earlier runs' action files,
    their reviewer verdicts, and — the expensive part — their screenshots as
    images, which pushed context past 100k and put the run into permanent TPM
    backoff before it had written a single action of its own.

    Reading a run that FAILED review is worse than useless: it is a worked
    example of the exact geometry the plan is trying to prevent. The current
    run's own files stay readable (that is how a step inspects its earlier
    actions), and so does anything directly in mem/ such as server_errors.log.
    """
    try:
        rel = path.relative_to(ROOT / "mem")
    except ValueError:
        return None
    if not rel.parts:
        return None
    run = rel.parts[0]
    current = str(core.CURRENT_ACTION_CONTEXT.get("run_name") or "")
    # No current run means we are not inside a step (e.g. the Executor
    # process, which loads this same plugin). Fail open rather than break it.
    if not current or run == current:
        return None
    return run


_MEM_REF_RE = re.compile(r"mem[/\\]+([A-Za-z0-9_.-]+)")


def _foreign_runs_named_in(text: str) -> set:
    """Run names other than the current one mentioned as mem/<run> in `text`."""
    current = str(core.CURRENT_ACTION_CONTEXT.get("run_name") or "")
    if not current:
        return set()
    mem = ROOT / "mem"
    return {m for m in _MEM_REF_RE.findall(text or "")
            if m != current and (mem / m).is_dir()}


def _resolve_in_project(path_str: str) -> Path:
    """Resolve a path and refuse anything outside the project directory.

    Also refuses other runs' directories under mem/ — see _foreign_run.
    """
    p = Path(path_str)
    p = p if p.is_absolute() else (ROOT / p)
    p = p.resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError(f"{path_str!r} is outside the project directory")
    other = _foreign_run(p)
    if other:
        raise ValueError(
            f"{path_str!r} belongs to a different run ({other!r}), which is "
            f"off limits. Earlier runs are not reference material — several of "
            f"them failed review, and the plan already tells you what they got "
            f"wrong. Build this step from the plan, the reference photo and "
            f"your own measurements. Your own run's files are readable as usual."
        )
    return p


# ── read ─────────────────────────────────────────────────────────────────────

READ_SCHEMA = {
    "name": "read",
    "description": (
        "Read a file. TEXT files come back with line numbers and pagination. "
        "IMAGES (.png/.jpg/.jpeg/.webp) come back as real pixels you can look "
        "at — the reference photo, a screenshot from an earlier action, a crop "
        "you made with bash. Use it instead of writing a Blender action that "
        "just open()s a file. Paths are relative to the project root."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "e.g. 'plans/bat_new_plan.md' or "
                                    "'mem/<run>/steps/step_001/screenshots/action_12.png'"},
            "offset": {"type": "integer",
                       "description": "Text only: 1-indexed first line (default 1)."},
            "limit": {"type": "integer",
                      "description": "Text only: max lines (default 500, max 2000)."},
        },
        "required": ["path"],
    },
}


def _handle_read(args: dict, **kw) -> object:
    _trace("read", str(args.get("path", "")))
    try:
        path = _resolve_in_project(str(args.get("path", "")))
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if not path.is_file():
        return json.dumps({"ok": False, "error": f"not found: {args.get('path')}"})

    if path.suffix.lower() in _IMAGE_SUFFIXES:
        return _multimodal(json.dumps({"ok": True, "kind": "image",
                                       "path": str(rel_to(path, ROOT))}), [path])
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})

    lines = text.splitlines()
    start = max(1, int(args.get("offset") or 1))
    limit = min(2000, max(1, int(args.get("limit") or 500)))
    chunk = lines[start - 1: start - 1 + limit]
    body = "\n".join(f"{start + i}\t{ln}" for i, ln in enumerate(chunk))
    more = len(lines) - (start - 1 + len(chunk))
    if more > 0:
        body += f"\n... {more} more line(s); pass offset to continue."
    return body or "(empty file)"


# ── write ────────────────────────────────────────────────────────────────────

_ACTION_FILE_RE = re.compile(r"^\d+_.*\.py$")


def _action_file_in_current_step(path: Path) -> bool:
    """True when `path` is a build action of the step being executed right now.

    Those belong to write_and_run: writing one without running it leaves the
    file and the live Blender scene disagreeing, and the next rewind replays a
    version of the action that never actually ran.
    """
    step_dir = core.CURRENT_ACTION_CONTEXT.get("step_dir")
    if step_dir is None:
        return False
    try:
        return (path.parent.resolve() == Path(step_dir).resolve()
                and bool(_ACTION_FILE_RE.match(path.name)))
    except OSError:
        return False


WRITE_SCHEMA = {
    "name": "write",
    "description": (
        "Write a file, replacing it entirely. Creates parent directories. Use "
        "it for helper modules under Tool_scripts/Tools_code/, scratch scripts "
        "in this step's scripts/ folder, notes, JSON you want to keep. NOT for "
        "this step's build actions (NN_name.py) — those go through "
        "write_and_run, which also executes them and rewinds the scene when "
        "you rewrite one."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the project root."},
            "content": {"type": "string", "description": "Full file content."},
        },
        "required": ["path", "content"],
    },
}


def _handle_write(args: dict, **kw) -> str:
    path_str = str(args.get("path", ""))
    _trace("write", path_str)
    try:
        path = _resolve_in_project(path_str)
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if _action_file_in_current_step(path):
        return json.dumps({
            "ok": False,
            "error": f"{path.name} is a build action of the step you are "
                     f"running — writing it without running it would leave the "
                     f"scene out of sync with the file.",
            "hint": "Use write_and_run(filename=..., content=...) to create or "
                    "rewrite it, or edit(...) to change part of it.",
        })
    content = args.get("content", "") or ""
    if path.suffix == ".py":
        content = core.localise_tools_path(content)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})
    return json.dumps({"ok": True, "path": str(rel_to(path, ROOT)),
                       "bytes": len(content.encode("utf-8"))})


# ── edit ─────────────────────────────────────────────────────────────────────

EDIT_SCHEMA = {
    "name": "edit",
    "description": (
        "Change part of a file by replacing an exact string. `old_string` must "
        "appear EXACTLY once unless replace_all is true. This is how you fix a "
        "value — never re-send a whole file to change one number.\n"
        "EDITING ONE OF THIS STEP'S BUILD ACTIONS (NN_name.py) ALSO RE-RUNS IT: "
        "the harness rewinds the scene through the preceding action, replays, "
        "runs your edited version, and returns the new screenshot — exactly as "
        "if you had rewritten it with write_and_run, for a fraction of the "
        "tokens. So correcting a radius or an angle is one cheap call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the project root."},
            "old_string": {"type": "string", "description": "Exact text to replace."},
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {"type": "boolean",
                            "description": "Replace every occurrence (default false)."},
        },
        "required": ["path", "old_string", "new_string"],
    },
}


def _handle_edit(args: dict, **kw) -> object:
    path_str = str(args.get("path", ""))
    old = args.get("old_string", "") or ""
    new = args.get("new_string", "") or ""
    replace_all = bool(args.get("replace_all"))
    _trace("edit", f"{path_str} ({len(old)}->{len(new)} chars"
                   f"{', all' if replace_all else ''})")
    try:
        path = _resolve_in_project(path_str)
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if not path.is_file():
        return json.dumps({"ok": False, "error": f"not found: {path_str}"})
    if not old:
        return json.dumps({"ok": False, "error": "old_string is empty — use "
                                                 "write to create or replace a file"})
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})

    n = text.count(old)
    if n == 0:
        return json.dumps({"ok": False, "error": "old_string not found — it "
                                                 "must match the file exactly, "
                                                 "including indentation"})
    if n > 1 and not replace_all:
        return json.dumps({"ok": False,
                           "error": f"old_string appears {n} times — include "
                                    f"more surrounding text to make it unique, "
                                    f"or pass replace_all=true"})
    updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)

    # A build action of the CURRENT step cannot just be edited on disk: the
    # scene was produced by the old version. Route it through the same path a
    # rewrite takes, which rewinds, replays and re-runs it.
    if _action_file_in_current_step(path):
        ctx = core.CURRENT_ACTION_CONTEXT
        result = core.write_and_run_action(
            run_name=ctx.get("run_name"), step_dir=Path(ctx["step_dir"]),
            filename=path.name, content=updated,
        )
        shown = [Path(p) for p in (result.pop("shown_abs_paths", None) or [])]
        result.pop("shown_dropped", 0)
        result["edited"] = f"{n if replace_all else 1} occurrence(s) replaced, "
        result["edited"] += "action rewound and re-run"
        status = json.dumps(result)
        return _multimodal(status, shown) if result.get("ok") and shown else status

    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})
    return json.dumps({"ok": True, "path": str(rel_to(path, ROOT)),
                       "replaced": n if replace_all else 1})


# ── glob ─────────────────────────────────────────────────────────────────────

GLOB_SCHEMA = {
    "name": "glob",
    "description": (
        "Find files by name pattern, newest first. e.g. '**/*.py', "
        "'mem/<run>/steps/step_001/*.py', '**/screenshots/action_1*.png'. Use "
        "it to see what exists instead of walking directories yourself."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'."},
            "path": {"type": "string",
                     "description": "Directory to search in (default: project root)."},
            "limit": {"type": "integer", "description": "Max results (default 100)."},
        },
        "required": ["pattern"],
    },
}


def _handle_glob(args: dict, **kw) -> str:
    pattern = str(args.get("pattern", ""))
    _trace("glob", f"{pattern} in {args.get('path') or '.'}")
    try:
        base = _resolve_in_project(str(args.get("path") or "."))
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    limit = min(1000, max(1, int(args.get("limit") or 100)))
    try:
        # _resolve_in_project guards the BASE; this guards the RESULTS, which
        # a base of 'mem' or '.' would otherwise rake in from every past run.
        hits = [p for p in base.glob(pattern)
                if p.is_file() and not _foreign_run(p)]
    except (ValueError, OSError) as e:
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})
    hits.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    total = len(hits)
    out = [str(rel_to(p, ROOT)) for p in hits[:limit]]
    if total > limit:
        out.append(f"... {total - limit} more (raise limit to see them)")
    return "\n".join(out) if out else "(no matches)"


# ── grep ─────────────────────────────────────────────────────────────────────

GREP_SCHEMA = {
    "name": "grep",
    "description": (
        "Search file contents with a regular expression. Use it to find a "
        "helper's definition or every call site of something. By default it "
        "skips mem/ (thousands of screenshots) — pass a path inside your own "
        "run's directory explicitly when you do want to search its files. "
        "Other runs' directories under mem/ are off limits."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "path": {"type": "string",
                     "description": "File or directory to search (default: project root)."},
            "glob": {"type": "string",
                     "description": "Only search files matching this name pattern, e.g. '*.py'."},
            "case_insensitive": {"type": "boolean", "description": "Default false."},
            "output_mode": {"type": "string",
                            "description": "'content' (default), 'files_with_matches', or 'count'."},
            "limit": {"type": "integer", "description": "Max results (default 60)."},
        },
        "required": ["pattern"],
    },
}


def _handle_grep(args: dict, **kw) -> str:
    pattern = str(args.get("pattern", ""))
    path_arg = str(args.get("path") or ".")
    _trace("grep", f"{pattern!r} in {path_arg}")
    try:
        rx = re.compile(pattern, re.IGNORECASE if args.get("case_insensitive") else 0)
        base = _resolve_in_project(path_arg)
    except (re.error, ValueError) as e:
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})

    limit = min(1000, max(1, int(args.get("limit") or 60)))
    mode = str(args.get("output_mode") or "content")
    name_glob = args.get("glob")
    # Only skip mem/ when the caller did NOT deliberately point into it.
    searching_mem = "mem" in rel_to(base, ROOT).parts if base != ROOT else False
    skip = _SEARCH_SKIP_DIRS - ({"mem"} if searching_mem else set())

    candidates = [base] if base.is_file() else sorted(base.rglob("*"))
    hits, files, counts = [], [], {}
    for p in candidates:
        if len(hits) >= limit or len(files) >= limit:
            break
        if not p.is_file() or p.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if _foreign_run(p):     # same guard as glob: a base of 'mem' or '.'
            continue            # would otherwise sweep in every past run
        rel = rel_to(p, ROOT)
        if skip & set(rel.parts[:-1]):
            continue
        if name_glob and not fnmatch.fnmatch(p.name, name_glob):
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n_here = 0
        for n, line in enumerate(body.splitlines(), 1):
            if rx.search(line):
                n_here += 1
                if mode == "content" and len(hits) < limit:
                    hits.append(f"{rel}:{n}: {line.strip()[:180]}")
        if n_here:
            files.append(str(rel))
            counts[str(rel)] = n_here

    if mode == "files_with_matches":
        return "\n".join(files[:limit]) if files else "(no matches)"
    if mode == "count":
        return "\n".join(f"{f}: {c}" for f, c in list(counts.items())[:limit]) or "(no matches)"
    return "\n".join(hits) if hits else "(no matches)"


# ── bash ─────────────────────────────────────────────────────────────────────
#
# One-shot, exactly like Claude Code's Bash: spawn, run, collect, exit. The
# working directory is remembered between calls; no shell process is kept
# alive. That distinction is the whole reason this exists instead of hermes'
# own `terminal` toolset, which builds a PERSISTENT login-shell environment
# (tools/terminal_tool.py's _create_environment -> _LocalEnvironment ->
# `bash -l -c`) and, inside the MCP dispatch subprocess this runs in, never
# finishes starting: bat_newplan_001 logged "Creating new local environment",
# never logged "environment ready", and burned its whole step on the 420s tool
# timeout with zero actions run. A one-shot subprocess with a hard timeout
# cannot do that — the worst case is losing `timeout` seconds.

BASH_SCHEMA = {
    "name": "bash",
    "description": (
        "Run a shell command and get back its stdout/stderr. This is where PIL "
        "crops, pixel scans, file wrangling and any loop over more than a few "
        "thousand items belong — the same work inside a Blender action freezes "
        "the whole session. Every call starts at the project root and keeps no "
        "state between calls, so a relative path always means the same thing.\n"
        "IMAGES COME BACK AS REAL PIXELS: any image the command writes into "
        "this step's directory is attached to your next turn automatically, and "
        "echoing `SHOW_IMAGE: <path>` attaches an image from anywhere in the "
        "project. So cropping a render to inspect one detail is a normal move — "
        "crop it, save it, and you will SEE the crop.\n"
        "This CANNOT reach Blender: `bpy` does not exist here, and you must NOT "
        "open a socket to the Blender server on port 6666 — it sends no reply, "
        "so the read blocks until the timeout. Anything that inspects or "
        "changes the scene goes through write_and_run instead. Keep commands "
        "non-interactive: stdin is closed, so anything that prompts will fail "
        "rather than wait."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
            "timeout": {"type": "integer", "description": "Seconds, default 45, max 600."},
            "cwd": {"type": "string",
                    "description": "Working directory for THIS call only "
                                   "(default: the project root)."},
        },
        "required": ["command"],
    },
}

_SHOW_MARKER_RE = re.compile(r"^\s*SHOW_IMAGE:\s*(.+?)\s*$", re.MULTILINE)


def _collect_images(stdout: str, started: float) -> tuple[list, str]:
    """Images a command produced, and its stdout with the markers stripped.

    Two ways to get pixels back, because both are natural to reach for:
      1. echo "SHOW_IMAGE: path" — explicit, works anywhere in the project.
      2. any image freshly written into this step's directory — so the obvious
         `im.crop(box).save('mem/<run>/steps/step_001/scripts/head.png')` just
         works without knowing about the marker.
    """
    paths, seen = [], set()

    def add(p: Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            return
        if rp in seen or not rp.is_file() or rp.suffix.lower() not in _IMAGE_SUFFIXES:
            return
        if _foreign_run(rp):    # never hand back another run's screenshot
            return
        seen.add(rp)
        paths.append(rp)

    for m in _SHOW_MARKER_RE.finditer(stdout or ""):
        raw = m.group(1).strip().strip('"').strip("'")
        cand = Path(raw)
        add(cand if cand.is_absolute() else ROOT / cand)

    step_dir = core.CURRENT_ACTION_CONTEXT.get("step_dir")
    if step_dir is not None:
        for p in sorted(Path(step_dir).rglob("*")):
            if p.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            try:
                # Tight window on purpose: we launched the writing process
                # ourselves, so anything older than this call belongs to some
                # earlier call and re-attaching it just wastes context.
                if p.stat().st_mtime < started - 0.25:
                    continue
            except OSError:
                continue
            add(p)

    return paths, _SHOW_MARKER_RE.sub("", stdout or "").strip()


def _shell_argv(command: str) -> list:
    """Prefer a real shell; fall back to cmd.exe so Windows without Git Bash
    still works rather than failing at the first tool call."""
    bash = shutil.which("bash")
    if bash:
        return [bash, "-c", command]
    if os.name == "nt":
        return [os.environ.get("ComSpec", "cmd.exe"), "/c", command]
    return ["/bin/sh", "-c", command]


def _handle_bash(args: dict, **kw) -> object:
    import subprocess

    command = args.get("command", "") or ""
    timeout = min(600, max(5, int(args.get("timeout") or 45)))
    # bash takes an arbitrary string, so the path guard in _resolve_in_project
    # cannot see into it. This is a text check, not a sandbox — it catches the
    # obvious `cat mem/<other-run>/...` rather than a determined workaround,
    # which is the right level: the point is to answer a wrong turn with the
    # reason, not to defend against an adversary.
    if (bad := _foreign_runs_named_in(command)):
        return json.dumps({"ok": False, "error": (
            f"this command names another run ({', '.join(sorted(bad))}). "
            f"Earlier runs are off limits — several of them failed review, and "
            f"the plan already says what they got wrong. Build from the plan, "
            f"the reference photo and your own measurements."
        )})
    # cwd is per-call, NOT sticky. Claude Code's Bash remembers it between
    # calls, but every other tool here resolves relative to the project root,
    # and so do the plan and the reference docs. A cwd that quietly persisted
    # would make `read('images/Bat.jpg')` and `bash('... images/Bat.jpg')` mean
    # different things depending on what the previous call happened to do —
    # which is exactly how this test suite first broke.
    cwd = str(ROOT)
    if args.get("cwd"):
        try:
            cwd = str(_resolve_in_project(str(args["cwd"])))
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})
    # One line per invocation with the command, before it runs — a command that
    # hangs is otherwise invisible until it times out, and its text never
    # reaches the log at all.
    _trace("bash", f"{timeout}s limit | " + " ".join(command.split())[:110])

    started = time.time()
    try:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        # stdin=DEVNULL, never inherited. This runs inside the MCP dispatch
        # subprocess, whose stdin IS the JSON-RPC channel — a child that reads
        # stdin would block forever AND eat protocol bytes.
        proc = subprocess.run(_shell_argv(command), cwd=cwd, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=timeout, encoding="utf-8",
                              errors="replace")
    except subprocess.TimeoutExpired:
        print(f"[bash] TIMEOUT after {timeout}s")
        return (f"TIMEOUT after {timeout}s — the command was killed, nothing is "
                f"still running. It began:\n{command[:300]}\n"
                f"Common causes: waiting on Blender (use write_and_run for "
                f"anything touching the scene), or far too much data. Make it "
                f"cheaper, or pass a larger `timeout` if it is genuinely slow.")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})

    out = (proc.stdout or "")[-6000:]
    err = (proc.stderr or "")[-3000:]
    images, out = _collect_images(out, started)
    parts = [f"exit={proc.returncode}  cwd={rel_to(Path(cwd), ROOT) if Path(cwd) != ROOT else '.'}"]
    if out:
        parts.append(f"--- stdout ---\n{out}")
    if err:
        parts.append(f"--- stderr ---\n{err}")
    if not out and not err and not images:
        parts.append("(no output — did the command print anything?)")
    if len(images) > core.MAX_IMAGES_PER_RESULT:
        parts.append(f"[{len(images) - core.MAX_IMAGES_PER_RESULT} more image(s) "
                     f"written but not attached — at most "
                     f"{core.MAX_IMAGES_PER_RESULT} per call; read them "
                     f"individually to see the rest]")
        images = images[:core.MAX_IMAGES_PER_RESULT]
    status = "\n".join(parts)
    return _multimodal(status, images) if images else status


# ── registration ─────────────────────────────────────────────────────────────
#
# Two toolsets on purpose. `blendcua` is the one domain primitive — the thing
# that drives Blender and owns the rewind/replay contract. `blendcua_fs` is the
# general Claude-Code-shaped surface, which the Executor can be given without
# also handing it the ability to build geometry behind the subagent's back.

def register(ctx) -> None:
    ctx.register_tool(name="write_and_run", toolset="blendcua",
                      schema=WRITE_AND_RUN_SCHEMA, handler=_handle_write_and_run,
                      emoji="🔧")
    for name, schema, handler, emoji in (
        ("read",  READ_SCHEMA,  _handle_read,  "📖"),
        ("write", WRITE_SCHEMA, _handle_write, "✍️"),
        ("edit",  EDIT_SCHEMA,  _handle_edit,  "✏️"),
        ("glob",  GLOB_SCHEMA,  _handle_glob,  "🗂️"),
        ("grep",  GREP_SCHEMA,  _handle_grep,  "🔎"),
        ("bash",  BASH_SCHEMA,  _handle_bash,  "🐚"),
    ):
        ctx.register_tool(name=name, toolset="blendcua_fs", schema=schema,
                          handler=handler, emoji=emoji)
