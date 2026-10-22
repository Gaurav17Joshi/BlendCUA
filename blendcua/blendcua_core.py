import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[0])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)
#!/usr/bin/env python3
"""
BlendCUA-Hermes shared core — used by both `blendcua_agent.py` (Executor process) and
`mcp_dispatch_server.py` (the dispatch_step MCP tool subprocess it spawns).

Ported from BlendCuagent2/agent.py (Claude Agent SDK) to hermes-agent. Most
of this file is byte-for-byte identical to the original — plan parsing, the
rollout logger, the reviewer, the review-render script — none of that touches
the harness. Only two things actually changed shape:

1. There is no in-process custom-tool mechanism in hermes-agent (no
   `@tool` decorator running in the same interpreter). Custom tools are
   external MCP servers talking over stdio. So `dispatch_step` — which used
   to be an in-process SDK tool closing over a shared RunContext object —
   is now its own subprocess (mcp_dispatch_server.py) that keeps its own
   run-scoped state for its lifetime and is registered into the Executor's
   hermes-agent session via ~/.hermes (or a project-local HERMES_HOME)
   config.yaml's `mcp_servers` key.

2. hermes-agent's MCP tool-calling loop does not forward image bytes from a
   tool result back into the model's vision context (confirmed empirically:
   an MCP tool returning an image, the model sees a cached file path but not
   the pixels). Real vision only happens via
   `agent.image_routing.build_native_content_parts()`, which the ORCHESTRATOR
   has to call to attach a screenshot to the next outer message. So the
   original single continuous "subagent autonomously calls write_and_run
   many times, seeing each screenshot inline" tool loop is now driven one
   level up: our own Python calls `run_conversation()` once per action,
   executes what the model asked for, and re-attaches the resulting
   screenshot via `build_native_content_parts` + `conversation_history`
   before calling again. Functionally the same loop (model still writes and
   sees every action before deciding the next one); just explicit instead of
   implicit.

Layout of a run (unchanged from BlendCuagent2):

    mem/<run_name>/
    ├── steps/step_NNN/         <- action files, screenshots, review/*.png
    └── Rollout/
        ├── terminal.log            (mirrored stdout)
        ├── rollout.jsonl           (structured events, flush-per-write)
        ├── step_NNN_trace.jsonl    (subagent conversation trace)
        ├── step_NNN_review.txt    (reviewer full response)
        └── usage.json              (cumulative cost/usage snapshot, written
                                      by mcp_dispatch_server.py after every
                                      dispatch_step call so the Executor
                                      process — a different OS process — can
                                      read final totals at the end of a run)
"""

import functools
import json
import os
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TextIO

_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from models import MODELS, OPENAI_REASONING_EFFORT, COST_CORRECTION
import replay_batch

# ── Paths ────────────────────────────────────────────────────────────────────

AGENT_DIR        = _HERE
PROMPT_FILES_DIR = AGENT_DIR / "prompt_files"
PLANS_DIR        = AGENT_DIR / "plans"
MEM_DIR          = AGENT_DIR / "mem"
IMAGES_DIR       = AGENT_DIR / "images"

# Working directory for the agents' shell / execute_code calls. hermes resolves
# these to `os.getcwd()` of whichever process hosts the agent (see
# tools/terminal_tool.py::_get_env_config), and the Step-Subagent is hosted by
# the mcp_dispatch_server.py SUBPROCESS, whose cwd is not guaranteed to be this
# project (hermes already logs a ".env not found" from that subprocess's cwd).
# Pin it so a relative path in an agent-written script means what it looks like.
os.environ.setdefault("TERMINAL_CWD", str(AGENT_DIR))

# Matches Tool_scripts/blender_server.py's listener.
# One Blender per port. BLENDCUA_PORT=6667 selects a second GUI instance with
# its own handshake file and its own Hermes home (see agent_env.hermes_home_name).
_BLENDER_PORT = int(os.environ.get("BLENDCUA_PORT", "6666"))


def exec_status_name(port: int = _BLENDER_PORT) -> str:
    return "exec_status.json" if port == 6666 else f"exec_status_{port}.json"


_EXEC_STATUS_FILE = MEM_DIR / exec_status_name()
_SHOTS_FLAG_FILE = MEM_DIR / ".shots_enabled"

# identity.md is the system prompt, not a reference doc. The *_new.md files are
# the shortened rewrites of current_tools.md / examples.md; they are skipped in
# favour of the full originals, which demonstrate many more worked actions and
# so teach action granularity (one operation per file, preview→apply pairs) far
# better than the trimmed versions did. Only one of each pair may load, or the
# subagent gets both copies.
_REF_SKIP: set[str] = {"identity.md", "current_tools_new.md", "examples_new.md"}

# 20, not 12. This also sets the Step-Subagent's max_iterations
# (max(30, action_budget * 2) in run_step_subagent_with_review), so the two
# move together: at 12 the subagent got only 30 internal tool-calling
# iterations, and bat_gptluna_med5 step 1 spent 26 of them on a step that
# reported exactly 12 actions — i.e. it was running out of room to look at
# its own work, not just to act. Hitting the iteration ceiling ends the turn
# before the result JSON, which is what triggers the "ended without JSON"
# nudge path.
DEFAULT_ACTION_BUDGET = 20
# 1, not 3. The reviewer is consulted at most `retry_budget + 1` times, so this
# caps a step at TWO review rounds: one verdict, one re-check after the fix.
#
# 3 (four rounds) was measured as pure loss. In the 2026-08-27 trial, two of
# three tasks ended with an EXHAUSTED step, and both spent every round on a
# perceptual complaint the reviewer had already measured as correct — chess
# step 5 (3 rounds, 87 min) and wine-glass step 3 (4 rounds, 123 min, 52% of
# that whole task). Rounds 3 and 4 changed no verdict in either case; they only
# repeated round 2's objection. A check that two rounds cannot satisfy is
# almost always a badly worded check, and more rounds do not fix wording.
# 0 since 2026-09-10: review once; on TRY_AGAIN one corrective pass that is NOT
# re-reviewed; then the step closes. The 2026-09-10 run measured the second
# review round as pure loss again: 21 steps, 9 EXHAUSTED, the re-reviewed fix
# plus the second review cost 342 + ~140 min across four builds and changed
# the verdict in 3 steps only. The curator judges the finished build anyway.
# 1 since 2026-09-12 (user's call, dog + human-juggler runs): two review rounds per
# step again — one verdict, one re-check after the fix; steps/step_N/review/round_02.
DEFAULT_RETRY_BUDGET  = 1
# run_v2.py --retry-budget sets this for one session (a test pass uses 0: one review round)
if os.environ.get("BLENDCUA_DEFAULT_RETRY_BUDGET", "").strip().isdigit():
    DEFAULT_RETRY_BUDGET = int(os.environ["BLENDCUA_DEFAULT_RETRY_BUDGET"])

# Upper bound on ONE Blender dispatch. Was 30s, which a Cycles render at the
# default 96 samples blows through routinely — the slowest legitimate action in
# the trial took 251.6s. A 30s ceiling turns those into false "Blender hung?"
# reports, and the agent then retries work that is still running. 2000s is a
# real ceiling: long enough that nothing legitimate trips it, short enough that
# a genuine hang is still caught inside a step rather than at the end of a run.
DISPATCH_TIMEOUT_S = 2000

_PROVIDER_ENV_KEY = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# ── API keys ─────────────────────────────────────────────────────────────────
#
# Keys live in ONE file OUTSIDE this repository and are read into the process
# environment at startup. They are never written into the repo — not into
# .hermes_home/config.yaml, not into mem/, not into a .env here — because a
# secret that never lands inside the project directory cannot be committed by
# a careless `git add -A`, and cannot be read by the build agent, which is
# confined to this directory (TERMINAL_CWD). An earlier version of this
# project leaked a key exactly that way: the key value was copied into the
# per-run MCP config written under the repo.
#
# Only the PATH to that file is ever passed around (to the dispatch
# subprocess, via the MCP env block). A path is not a secret.
#
# Override the location with BLENDCUA_KEY_FILE. Format is one KEY=VALUE per
# line, `#` comments and blank lines ignored.
DEFAULT_KEY_FILE = Path.home() / "blendcua.env.txt"


def key_file_path() -> Path:
    return Path(os.environ.get("BLENDCUA_KEY_FILE") or DEFAULT_KEY_FILE)


def load_api_keys(*, verbose: bool = True) -> list[str]:
    """Read the key file into os.environ. Returns the NAMES that were set.

    Values are never printed, logged, or returned — only names, so a rollout
    log or a screen-share can safely show that a key was loaded without
    showing which secret it was.

    Existing environment variables win (same convention as dotenv), so a key
    exported for a one-off experiment isn't silently overridden by the file.
    """
    path = key_file_path()
    if path.is_absolute() and AGENT_DIR in path.parents:
        raise RuntimeError(
            f"Key file {path} is inside the project directory. Keep it outside "
            f"the repo — that is the whole point of this mechanism."
        )
    if not path.is_file():
        if verbose:
            print(f"[BlendCUA] No key file at {path} — relying on the ambient environment.")
        return []

    loaded: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if not name or not value:
            continue
        if name not in os.environ:
            os.environ[name] = value
        loaded.append(name)
    if verbose:
        print(f"[BlendCUA] Loaded {len(loaded)} key(s) from {path.name}: {', '.join(loaded)}")
    return loaded


def api_key_for(provider: str) -> str | None:
    """Explicit API key for an AIAgent(...) call.

    hermes-agent's own credential resolution (agent.anthropic_adapter.
    resolve_anthropic_token) prefers ambient Claude Code OAuth credentials
    (~/.claude.json / ~/.claude/.credentials.json) over ANTHROPIC_API_KEY —
    confirmed empirically: with only ANTHROPIC_API_KEY set, calls still went
    through the machine's logged-in Claude Code session and hit its plan/
    quota limits ("Third-party apps now draw from your extra usage"). Passing
    api_key explicitly to AIAgent(...) short-circuits that resolution (it's
    checked first, before any ambient-credential lookup), which is what we
    want for a clean, comparable cost measurement against BlendCuagent2.
    """
    env_var = _PROVIDER_ENV_KEY.get(provider)
    return os.environ.get(env_var) if env_var else None


_PROVIDER_BASE_URL = {
    "openai": "https://api.openai.com/v1",
    # anthropic doesn't need this — it's special-cased in hermes-agent's own
    # agent_init.py (native Anthropic handling checks just api_key). openai
    # (and every other non-special-cased provider) only takes the "explicit
    # credentials" fast path when BOTH api_key AND base_url are given
    # together (agent_init.py: `if api_key and base_url:`) — passing api_key
    # alone silently falls through to a router path that, for us, failed to
    # find OPENAI_API_KEY at all. Confirmed by hitting that exact error.
}


def base_url_for(provider: str) -> str | None:
    """Explicit base URL for an AIAgent(...) call — see api_key_for()'s
    docstring for why this needs to be paired with api_key for non-Anthropic
    providers."""
    return _PROVIDER_BASE_URL.get(provider)


# ── Tee — mirror stdout/stderr to terminal.log ───────────────────────────────

class Tee:
    """Duplicate writes to a primary stream and a log file, flushing per write."""

    def __init__(self, primary, log_handle: TextIO):
        self.primary = primary
        self.log = log_handle
        # Lets log_print() detect that print() already reaches this same log
        # file and skip its own direct write, instead of duplicating the line.
        self._blendcua_log_handle = log_handle

    def write(self, data):
        try:
            self.primary.write(data)
        except Exception:
            pass
        try:
            self.log.write(data)
            self.log.flush()
        except Exception:
            pass
        return len(data) if isinstance(data, str) else 0

    def flush(self):
        for s in (self.primary, self.log):
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return getattr(self.primary, "isatty", lambda: False)()

    def fileno(self):
        return self.primary.fileno()


class _StampedLog:
    """terminal.log wrapper that stamps every line with a wall-clock time.

    hermes already reports per-API-call `latency=` and per-tool `(0.64s, ...)`,
    so durations of the *work* were never the missing piece — the gaps between
    them were. Nothing in the log said when a line happened, so a 40s hole
    (rate-limit backoff, a Blender render, the model thinking) was
    indistinguishable from no hole at all, and the executor/reviewer streams,
    which interleave line-by-line, could only be demultiplexed by chaining
    cache-prefix arithmetic across the whole file. An absolute timestamp on
    every line makes both trivial: subtract for any interval you want.

    The console copy stays unstamped — this wraps only the file handle.
    """

    def __init__(self, handle: TextIO):
        self._handle = handle
        # Writes arrive as arbitrary chunks, not lines: print() alone sends the
        # text and the "\n" separately. Stamping per write() would put a
        # timestamp mid-line, so track whether we are actually at a line start.
        self._at_line_start = True

    @staticmethod
    def _stamp() -> str:
        t = time.time()
        return time.strftime("[%H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d}] "

    def write(self, data) -> int:
        if not data:
            return 0
        out, stamp = [], self._stamp()
        for i, part in enumerate(str(data).split("\n")):
            if i:
                out.append("\n")
                self._at_line_start = True
            if part and self._at_line_start:
                out.append(stamp)
                self._at_line_start = False
            out.append(part)
        try:
            self._handle.write("".join(out))
            self._handle.flush()
        except (OSError, ValueError):
            pass
        return len(data)

    def flush(self) -> None:
        try:
            self._handle.flush()
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        try:
            self._handle.close()
        except (OSError, ValueError):
            pass

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._handle.fileno()


_TERMINAL_LOG: TextIO | None = None


def attach_terminal_log(path: Path) -> None:
    """Open the run's terminal.log for `log_print` to write to directly.

    Tee-ing sys.stdout is not enough on its own: constructing a hermes-agent
    AIAgent replaces sys.stdout, so everything printed from that point on
    bypasses the tee. Observed on bat_newplan_001 — terminal.log stopped dead
    at the "[dispatch_step] step 1" banner, which is printed just before the
    subagent is built, and the whole step's per-turn accounting was lost while
    step_001_trace.jsonl kept recording normally. Writing to our own handle
    can't be taken away from us.
    """
    global _TERMINAL_LOG
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _TERMINAL_LOG = _StampedLog(
            open(path, "a", encoding="utf-8", errors="replace"))
    except OSError:
        _TERMINAL_LOG = None


_HERMES_LOGGERS = ("agent.conversation_loop", "agent.tool_executor")


def attach_hermes_log_forwarding() -> None:
    """Mirror hermes-agent's own per-API-call lines into the run's terminal.log.

    What BlendCuagent2's terminal.log showed per MODEL CALL — context size,
    new vs cached tokens, output, then the tool that call invoked — hermes
    already logs, but only to .hermes_home/logs/agent.log, which is shared
    across every run and interleaves the Executor, the subagent and the
    reviewer. Forwarding those two loggers gives the run's own log the same
    granularity:

        API call #7: model=gpt-5.6-luna ... in=2429 out=6 latency=3.6s cache=48036/50465 (95%)
        tool write_and_run completed (0.64s, 996957 chars)

    Our own per-turn summary (UsageAggregate) stays — it is the aggregate for
    a whole run_conversation, which is a different and still useful unit.
    Argument-level detail comes from the plugin handlers, which log their own
    calls; hermes's line carries only the tool name.
    """
    import logging

    handle = _TERMINAL_LOG
    if handle is None:
        return

    class _ToRunLog(logging.Handler):
        def emit(self, record):
            try:
                handle.write(f"[hermes] {record.getMessage()}\n")
                handle.flush()
            except (OSError, ValueError):
                pass

    h = _ToRunLog(level=logging.INFO)
    for name in _HERMES_LOGGERS:
        lg = logging.getLogger(name)
        lg.addHandler(h)
        if lg.level > logging.INFO or lg.level == logging.NOTSET:
            lg.setLevel(logging.INFO)


def terminal_log_handle() -> TextIO | None:
    """The handle attach_terminal_log opened, so the stdout Tee can share it."""
    return _TERMINAL_LOG


def log_print(*args) -> None:
    """print() that also lands in the run's terminal.log, whatever owns stdout."""
    text = " ".join(str(a) for a in args)
    print(text)
    if _TERMINAL_LOG is None:
        return
    # While stdout is still our own Tee, print() already wrote this line to the
    # log — writing again would double every entry.
    if getattr(sys.stdout, "_blendcua_log_handle", None) is _TERMINAL_LOG:
        return
    try:
        _TERMINAL_LOG.write(text + "\n")
        _TERMINAL_LOG.flush()
    except (OSError, ValueError):
        pass


def step_dir_for(run_name: str, step_num: int) -> Path:
    """steps/step_NNN/, with every subfolder an agent is expected to use
    already present.

    `scripts/` is for the throwaway Python the agent writes to answer a
    question the Blender session can't (crop a screenshot with PIL, scan for
    an edge, dump a mesh). Those belong on disk with the run — this is a
    self-improving harness, and how something was measured is often the most
    reusable part of a step — but an agent will not invent a folder it has to
    create first, so it gets made up front alongside screenshots/ and
    overlay_json/. It is a SUBdirectory, so `NN_*.py` files inside it are
    invisible to the action collectors in replay_batch.py / win_run_steps.py
    and can never be mistaken for build actions.
    """
    d = MEM_DIR / run_name / "steps" / f"step_{step_num:03d}"
    for sub in ("screenshots", "overlay_json", "scripts"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


# Tool-call argument fields worth showing, by tool name — first match wins.
_TOOL_ARG_KEYS = ("filename", "file_path", "path", "command", "cmd", "code", "query", "pattern")


def _tool_call_summaries(messages: list, since: int) -> list[str]:
    """One short 'name(arg)' string per tool call in messages[since:].

    hermes-agent runs the subagent with quiet_mode=True (its own progress
    output would land on the MCP stdio channel), so without this the log
    records that a turn happened and what it cost, but not one thing the
    agent DID — no way to tell a step that wrote 12 actions from one that
    spent its budget re-reading the plan. Both message shapes are handled:
    OpenAI-style `tool_calls` and Anthropic-style `tool_use` content blocks.
    """
    out: list[str] = []

    def describe(name, args):
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                # Malformed/truncated arguments — don't dump a whole action's
                # source into the log just because it didn't parse. Pull the
                # identifying key out textually, or give up and truncate.
                m = re.search(rf'"({"|".join(_TOOL_ARG_KEYS)})"\s*:\s*"([^"]*)"', args)
                shown = " ".join((m.group(2) if m else args).split())
                return f"{name}({shown[:70]}{'…' if len(shown) > 70 else ''})"
        if not isinstance(args, dict):
            return f"{name}()"
        for key in _TOOL_ARG_KEYS:
            if key in args and args[key]:
                val = " ".join(str(args[key]).split())
                return f"{name}({val[:70]}{'…' if len(val) > 70 else ''})"
        return f"{name}({','.join(list(args)[:3])})" if args else f"{name}()"

    for msg in messages[since:]:
        if not isinstance(msg, dict):
            continue
        for call in msg.get("tool_calls") or []:
            fn = (call or {}).get("function") or {}
            out.append(describe(fn.get("name", "?"), fn.get("arguments")))
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    out.append(describe(block.get("name", "?"), block.get("input")))
    return out


def round_review_dir(run_dir: Path, step_num: int, round_num: int) -> Path:
    """steps/step_NNN/review/round_KK/ — everything about one review round
    (its verdict text, its own inspection action files, its own
    screenshots) lives together here instead of scattered across the step
    dir / overwritten by the next round. Shared between RolloutLogger.
    write_review() and run_agentic_reviewer() so both agree on the path."""
    d = run_dir / "steps" / f"step_{step_num:03d}" / "review" / f"round_{round_num:02d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Rollout logger ───────────────────────────────────────────────────────────

class RolloutLogger:
    """
    Writes to mem/<run>/Rollout/. Every file is opened in append mode and
    flushed after every write so a Ctrl+C or crash leaves complete logs.
    """

    def __init__(self, run_name: str):
        self.run_name    = run_name
        self.run_dir     = MEM_DIR / run_name
        self.rollout_dir = self.run_dir / "Rollout"
        self.rollout_dir.mkdir(parents=True, exist_ok=True)

        self.rollout_path      = self.rollout_dir / "rollout.jsonl"
        self.terminal_log_path = self.rollout_dir / "terminal.log"
        self.usage_path        = self.rollout_dir / "usage.json"

        self._rollout      = open(self.rollout_path,      "a", encoding="utf-8")
        # Stamped, same as the MCP subprocess's handle: both processes append to
        # this one file, so both halves of the run must carry timestamps or the
        # interleaving is unreadable.
        self.terminal_log  = _StampedLog(
            open(self.terminal_log_path, "a", encoding="utf-8"))
        self._step_traces: dict[int, TextIO] = {}
        self._closed = False

    def log_event(self, record: dict) -> None:
        if self._closed:
            return
        record.setdefault("time", datetime.now().isoformat())
        self._rollout.write(json.dumps(record, default=str) + "\n")
        self._rollout.flush()

    def _get_trace(self, step_num: int) -> TextIO:
        if step_num not in self._step_traces:
            path = self.rollout_dir / f"step_{step_num:03d}_trace.jsonl"
            self._step_traces[step_num] = open(path, "a", encoding="utf-8")
        return self._step_traces[step_num]

    def log_step_trace(self, step_num: int, record: dict) -> None:
        if self._closed:
            return
        record.setdefault("time", datetime.now().isoformat())
        f = self._get_trace(step_num)
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()

    def write_review(self, step_num: int, round_num: int, text: str) -> Path:
        """One file per review ROUND, inside that round's own subfolder of
        the step's review/ dir — not overwritten by the next round, so a
        step that needed several rounds keeps every round's actual
        reasoning (and, via run_agentic_reviewer's own file moves, every
        round's own inspection screenshots) on disk, not just the last one.
        See round_review_dir() — same path, used by run_agentic_reviewer
        to know where to move its own action files/screenshots too."""
        path = round_review_dir(self.run_dir, step_num, round_num) / "review.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def write_usage_snapshot(self, snapshot: dict) -> None:
        """Atomic write so a concurrently-reading Executor process never sees
        a half-written file. Called by mcp_dispatch_server.py after every
        dispatch_step — the Executor process reads this at the end of the run
        to fold subagent+reviewer cost into its own Executor-side total."""
        tmp = self.usage_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        tmp.replace(self.usage_path)

    def read_usage_snapshot(self) -> dict:
        try:
            return json.loads(self.usage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for f in [self._rollout, self.terminal_log, *self._step_traces.values()]:
            try:
                f.flush(); f.close()
            except Exception:
                pass


# ── Prompt loading ───────────────────────────────────────────────────────────

def load_system_prompt() -> str:
    """System prompt = identity.md only (short, high-attention)."""
    path = PROMPT_FILES_DIR / "identity.md"
    if not path.exists():
        raise FileNotFoundError(f"System prompt not found: {path}")
    text = path.read_text(encoding="utf-8")
    print(f"[BlendCUA] System prompt: identity.md ({len(text)} chars)")
    return text


def load_reference_docs() -> str:
    """All prompt_files/*.md except identity.md, sorted, joined with dividers.
    This is the FULL reference set — handed to the Step-Subagent only."""
    parts = []
    names = []
    for rf in sorted(PROMPT_FILES_DIR.glob("*.md")):
        if rf.name in _REF_SKIP:
            continue
        parts.append(f"## {rf.name}\n\n{localise_tools_path(rf.read_text(encoding='utf-8').strip())}")
        names.append(rf.name)
    print(f"[BlendCUA] Reference docs (subagent): {names}")
    return "\n\n---\n\n".join(parts)


def load_skills_index(*roles: str) -> str:
    """The Skills block for a prompt: one trigger line per skill, no bodies.

    Skills are role-scoped documents under Skills/<Role>/. Injecting all of
    them would cost several thousand tokens in every subagent and reviewer
    conversation; injecting none of them means an agent cannot find out they
    exist. So the prompt carries the name and the one-line description, and
    the body is one bash call away — the same split of labour tool_help.py
    already uses for the tool docstrings.
    """
    sys.path.insert(0, str(AGENT_DIR / "Tool_scripts"))
    try:
        from skill_help import index_block
    except Exception as exc:               # never let this break a run
        print(f"[BlendCUA] skills index unavailable: {exc}")
        return ""
    block = index_block(*roles)
    if not block or block == "(no skills)":
        return ""
    named = ", ".join(roles) if roles else "all roles"
    print(f"[BlendCUA] Skills index ({named}): {block.count('- `')} skill(s)")
    return f"""\
# Skills

Short documents written after earlier runs went wrong. Each one exists because
something failed once. The list below is names and triggers only — read the
body when its trigger matches what you are doing:

```bash
python Tool_scripts/skill_help.py <name>          # the full skill
python Tool_scripts/skill_help.py --search <word> # find one by what it covers
```

{block}
"""


_TOOLS_PATH_RE = re.compile(r'(TOOLS_CODE\s*=\s*r?["\'])([^"\']*?[\\/]Tool_scripts[\\/]Tools_code)(["\'])')


def localise_tools_path(text: str) -> str:
    r"""Rewrite any `TOOLS_CODE = r"<some folder>\Tool_scripts\Tools_code"` literal to THIS
    folder's tool path. Prompt files carry the main folder's spelling; a worker view
    (harness/wK) must hand its executor, and record in its actions, its own store."""
    here = str(AGENT_DIR / "Tool_scripts" / "Tools_code")
    return _TOOLS_PATH_RE.sub(lambda m: f"{m.group(1)}{here}{m.group(3)}", text)


def load_prompt_file(name: str) -> str:
    """Read a single file from prompt_files/. Used by the executor's slim
    reference set (terminal.md, examples_new.md)."""
    path = PROMPT_FILES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return localise_tools_path(path.read_text(encoding="utf-8").strip())


# ── Plan parser ──────────────────────────────────────────────────────────────

# One to three hashes, not exactly two. The canonical form the planner is
# told to write is `## Step N — title`, but a plan that says `# Step N —`
# is not a different plan, it is the same plan one character off — and
# requiring exactly `##` threw away an 817s, $0.19 plan for 04_datestone
# whose 509 lines were otherwise correct, em-dash and all. Prose mentions
# like "**Step 1** is only the block" cannot match: the hash must start
# the line. `### 1.2 Stepped base` cannot match either — "Step" must be
# followed by a number.
# `--` as well as a single dash: the planner writes ASCII `--` for an
# em-dash about as often as it writes the character, and matching only one
# dash left the second stranded at the head of every title
# ("- closed can body, ...") — parsed, but wrong in every prompt downstream.
_STEP_HDR_RE  = re.compile(r"^#{1,3}\s+Step\s+(\d+)\s*(?:[—–]|-{1,2})\s*(.+?)\s*$", re.MULTILINE)
_REVIEW_RE    = re.compile(r"\*\*Review:\*\*\s*(.+?)(?=\n---|\n##\s|\Z)", re.DOTALL)


_GROUP_RE = re.compile(r"^\*\*(Important|Other)\*\*:?$", re.IGNORECASE)


def _bullets(text: str) -> list[str]:
    """Extract '- ' bullets from a block, joining wrapped continuation lines.

    A `**Important**` / `**Other**` line groups the bullets that follow it, and
    the group is carried onto each check as a `[Important]` / `[Other]` prefix.
    Without this the grouping is silently lost: the reviewer is handed
    `review_checks` as a flat numbered list and cannot tell which checks decide
    the step from which are bookkeeping, so it spends equal effort on "the
    silhouette reads as a pillar" and "no doubled verts".
    """
    out: list[str] = []
    cur = ""
    group = ""

    def flush():
        nonlocal cur
        if cur:
            out.append((f"[{group}] " if group else "") + " ".join(cur.split()))
            cur = ""

    for raw in text.splitlines():
        stripped = raw.strip()
        m = _GROUP_RE.match(stripped)
        if m:
            flush()
            group = m.group(1).capitalize()
            continue
        if stripped.startswith("- "):
            flush()
            cur = stripped[2:].strip()
        elif not stripped:
            flush()
        elif cur:
            cur += " " + stripped
    flush()
    return out


def parse_plan(plan_text: str) -> list[dict]:
    """Return [{step_number, goal, review_checks, section_text, preamble}, ...].

    `preamble` is everything before the first `## Step N` header — the plan's
    shared context: what is being built, the naming contract, the coordinate
    frame, the specialised tools, the traps. It is attached to EVERY step
    because the Step-Subagent is handed one step in isolation and would
    otherwise never see it (build_subagent_prompt used to pass section_text
    alone). That gap had teeth: on bat_newplan_001 the subagent used
    `reference.load_reference` and left its aspect-correcting `scale.y` in
    place — the plan says not to, in the preamble, which the subagent was
    never shown.
    """
    heads = list(_STEP_HDR_RE.finditer(plan_text))
    preamble = plan_text[:heads[0].start()].strip() if heads else ""
    steps: list[dict] = []
    for i, m in enumerate(heads):
        num  = int(m.group(1))
        goal = m.group(2).strip()
        start = m.end()
        end   = heads[i + 1].start() if i + 1 < len(heads) else len(plan_text)
        section = plan_text[start:end].strip()
        checks: list[str] = []
        rev = _REVIEW_RE.search(section)
        if rev:
            checks = _bullets(rev.group(1))
        steps.append({
            "step_number":   num,
            "goal":          goal,
            "review_checks": checks,
            "section_text":  section,
            "preamble":      preamble,
        })
    return steps


# ── Pre-flight ───────────────────────────────────────────────────────────────

def check_blender(host: str = "localhost", port: int | None = None, timeout: float = 2.0) -> bool:
    import socket
    port = port or _BLENDER_PORT
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_REF_IMAGE_RE = re.compile(r"<!--\s*ref-image:\s*(.+?)\s*-->")


class TaskError(Exception):
    """A task folder that cannot be resolved into a runnable task."""


def resolve_task(task: str, plan: str | None = None,
                 image: str | None = None) -> dict:
    """A task folder -> everything a run needs, derived rather than configured.

    `task` is a folder name (`Duck`), a repo-relative path (`plans/Duck`), or
    any path to a directory. Inside it:

      plan   the single `*.md` file, or `plan` if given. Two plans and no
             `--plan` is an error, not a coin toss.
      image  the plan's own `<!-- ref-image: X -->` header, resolved RELATIVE
             TO THE TASK FOLDER, or `image` if given. A task with no header
             simply has no reference image; a header naming a file that is not
             there is an error, because it means the folder is not
             self-contained and the agent would be told to read nothing.
      prefix the folder name, lowercased -> `duck_run_003`.

    Returned paths are repo-relative strings, which is what the prompts, the
    MCP env block and the log all want.
    """
    cand = Path(task)
    for base in (AGENT_DIR / cand, PLANS_DIR / cand, cand):
        if base.is_dir():
            task_dir = base.resolve()
            break
    else:
        raise TaskError(
            f"no task folder {task!r} — looked in {PLANS_DIR} and as a path. "
            f"Available: {', '.join(sorted(p.name for p in PLANS_DIR.iterdir() if p.is_dir())) or '(none)'}"
        )

    if plan:
        plan_path = (task_dir / plan) if (task_dir / plan).exists() else (AGENT_DIR / plan)
        if not plan_path.exists():
            raise TaskError(f"--plan {plan!r} not found in {task_dir} or repo root")
    else:
        mds = sorted(p for p in task_dir.glob("*.md"))
        if not mds:
            raise TaskError(f"no .md build plan in {task_dir}")
        if len(mds) > 1:
            raise TaskError(
                f"{len(mds)} .md files in {task_dir} "
                f"({', '.join(p.name for p in mds)}) — name one with --plan"
            )
        plan_path = mds[0]

    if image:
        img_path = (task_dir / image) if (task_dir / image).exists() else (AGENT_DIR / image)
        if not img_path.exists():
            raise TaskError(f"--image {image!r} not found in {task_dir} or repo root")
    else:
        head = plan_path.read_text(encoding="utf-8")[:2000]
        m = _REF_IMAGE_RE.search(head)
        if m:
            img_path = task_dir / m.group(1)
            if not img_path.exists():
                raise TaskError(
                    f"{plan_path.name} declares ref-image {m.group(1)!r} but that "
                    f"file is not in {task_dir} — a task folder must carry its own assets"
                )
        else:
            img_path = None

    def rel(p: Path | None) -> str | None:
        return str(rel_to(p.resolve(), AGENT_DIR)).replace("\\", "/") if p else None

    slug = re.sub(r"[^a-z0-9]+", "_", task_dir.name.lower()).strip("_")
    return {
        "dir": rel(task_dir),
        "plan": rel(plan_path),
        "image": rel(img_path),
        "prefix": f"{slug}_run",
    }


def next_run_name(prefix: str) -> str:
    MEM_DIR.mkdir(exist_ok=True)
    nums = []
    for p in MEM_DIR.iterdir():
        if p.is_dir() and p.name.startswith(prefix + "_"):
            try:
                nums.append(int(p.name.split("_")[-1]))
            except ValueError:
                pass
    return f"{prefix}_{(max(nums) + 1 if nums else 1):03d}"


# ── Usage aggregator ─────────────────────────────────────────────────────────
#
# hermes-agent's run_conversation() returns real per-call usage/cost directly
# (input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
# estimated_cost_usd) computed by its own per-provider pricing engine
# (agent/usage_pricing.py) — there is no SDK-mispricing bug to correct for
# here, unlike BlendCuagent2's Sonnet-billed-at-Opus-rates issue. This class
# just sums what hermes-agent already reports correctly — the reviewer is
# now a real hermes-agent conversation too (run_agentic_reviewer), so its
# cost comes through the exact same log_conversation_result() path as the
# Executor/Subagent, no separate reviewer-pricing table needed anymore.

class UsageAggregate:
    """Roll up hermes `run_conversation()` returns into a per-run total.

    **hermes returns usage accumulated over the whole SESSION, not over the
    turn that just ended.** A session is re-entered several times per step
    (build, handover, JSON summary), and each return repeats everything before
    it — visible in the log as strictly monotonic `context=`/`out=`/`cost=`
    within one session (0.2384 -> 0.3426 -> 0.3480 -> 0.3919 across one step).
    Adding them made every published figure 2.4-3.2x too high: the 2026-08-27
    trial was billed at $12.83 and actually cost ~$5.44.

    So usage is tracked as `max` per session id and summed across sessions,
    which reproduces the per-API-call log totals exactly (42,040,471 input and
    430,549 output for 02_cardboard_box, to the token).

    `turns` counts whole conversations, not model calls — the real call count
    is ~16x higher. It is named `conversations` in the output now, because the
    old name invited exactly the wrong reading.
    """

    def __init__(self):
        self.turns = 0
        self.peak_input = 0
        self.last_session_id: str | None = None
        # session id -> the largest cumulative figures that session reported
        self._by_session: dict[str, dict] = {}

    @property
    def cost_usd(self) -> float:
        return sum(s["cost"] for s in self._by_session.values())

    @property
    def input_tokens(self) -> int:
        return sum(s["in"] for s in self._by_session.values())

    @property
    def output_tokens(self) -> int:
        return sum(s["out"] for s in self._by_session.values())

    @staticmethod
    def _fmt(n):
        return f"{n:,}" if isinstance(n, int) else str(n)

    def log_conversation_result(self, result: dict, tag: str = "Context",
                                wall_s: float | None = None) -> None:
        """Fold in one hermes-agent run_conversation() return dict.

        `wall_s` is the caller-measured wall time for the whole conversation —
        every API call in it plus every tool it ran plus every rate-limit
        retry. hermes's own `latency=` lines cover only the API calls, so the
        difference between them and this is where a step's time actually goes.
        """
        in_new = int(result.get("input_tokens", 0) or 0)
        out_tok = int(result.get("output_tokens", 0) or 0)
        c_read = int(result.get("cache_read_tokens", 0) or 0)
        c_new  = int(result.get("cache_write_tokens", 0) or 0)
        cost   = result.get("estimated_cost_usd")
        model  = result.get("model")
        sid    = result.get("session_id")
        if sid:
            self.last_session_id = sid
        if not (in_new or out_tok or c_read or c_new):
            return
        self.turns += 1
        total = in_new + c_read + c_new
        if total > self.peak_input:
            self.peak_input = total
        correction = COST_CORRECTION.get(model, 1.0) if model else 1.0
        corrected_cost = (float(cost) * correction) if cost is not None else None

        # max, not +=. These figures are cumulative for the session, so the
        # last return already contains every earlier one. See the class
        # docstring — summing them inflated the trial's cost by 2.4-3.2x.
        key = sid or f"_nosession_{self.turns}"
        prev = self._by_session.setdefault(key, {"cost": 0.0, "in": 0, "out": 0})
        if corrected_cost is not None:
            prev["cost"] = max(prev["cost"], corrected_cost)
        prev["in"] = max(prev["in"], total)
        prev["out"] = max(prev["out"], out_tok)
        pct = (c_read / total * 100.0) if total else 0.0
        note = f" [corrected {correction}x from hermes's stale price]" if correction != 1.0 else ""
        api_n = result.get("api_calls")
        timing = ""
        if wall_s is not None:
            timing = f", wall={wall_s:.1f}s"
            if api_n:
                timing += f" over {api_n} api calls ({wall_s / api_n:.1f}s each)"
        log_print(
            f"[{tag}] turn {self.turns:>3}: "
            f"context={self._fmt(total)} tokens  "
            f"(new={self._fmt(in_new)}, cached={self._fmt(c_read)} {pct:5.1f}%, "
            f"cache_write={self._fmt(c_new)}), out={self._fmt(out_tok)}{timing}, "
            f"cost=${(corrected_cost or 0):.4f}{note} (source={result.get('cost_source')}) | "
            f"run total=${self.cost_usd:.4f}"
        )

    def snapshot(self) -> dict:
        return {
            # `turns` kept for compatibility; `conversations` is the honest name.
            # Neither counts model calls — the real API-call count is ~16x higher.
            "conversations": self.turns,
            "turns": self.turns,
            "peak_input_tokens": self.peak_input,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "last_session_id": self.last_session_id,
            # carried so a merge can union sessions instead of adding totals
            "_by_session": self._by_session,
        }

    def merge_snapshot(self, snap: dict) -> None:
        """Fold in a snapshot written by another process (mcp_dispatch_server.py).

        Unions the per-session table rather than adding totals. The old version
        added `turns` and `cost_usd`, which lost work whenever a snapshot was
        overwritten rather than accumulated: 04_chess_staunton's usage.json
        reported 18 conversations where its log holds 24, six of them simply
        gone. Because that loss pointed the opposite way to the session-sum
        inflation above, the wrong total looked plausible.
        """
        if not snap:
            return
        by = snap.get("_by_session") or {}
        for sid, vals in by.items():
            prev = self._by_session.setdefault(sid, {"cost": 0.0, "in": 0, "out": 0})
            prev["cost"] = max(prev["cost"], float(vals.get("cost", 0.0) or 0.0))
            prev["in"] = max(prev["in"], int(vals.get("in", 0) or 0))
            prev["out"] = max(prev["out"], int(vals.get("out", 0) or 0))
        if not by:
            # older snapshot with no session table — fall back to the old
            # behaviour rather than silently dropping it
            sid = snap.get("last_session_id") or "_legacy"
            prev = self._by_session.setdefault(sid, {"cost": 0.0, "in": 0, "out": 0})
            prev["cost"] = max(prev["cost"], float(snap.get("cost_usd", 0.0) or 0.0))
        self.turns = max(self.turns, int(snap.get("turns", 0) or 0)) \
            if by else self.turns + int(snap.get("turns", 0) or 0)
        self.peak_input = max(self.peak_input, int(snap.get("peak_input_tokens", 0) or 0))
        if snap.get("last_session_id"):
            self.last_session_id = snap["last_session_id"]


# ── Reviewer (agentic — has its own live Blender access) ────────────────────
#
# Was a one-shot `anthropic.Anthropic().messages.create()` call grading two
# fixed renders it had no say in. Replaced with a real hermes-agent
# conversation, the same shape as the Step-Subagent: its own AIAgent
# instance, the write_and_run tool, and the ability to call it repeatedly —
# rotate the view, zoom into a specific area, switch axis — before handing
# down a verdict. It also gets the FULL plan text (not just this step's
# checklist), so it can sanity-check the current state against where the
# build is supposed to be overall, not just the isolated step description.
#
# Contract preserved from the old call_reviewer(): returns
# (verdict, reason, full_review_text) with verdict in
# {PASS, TRY_AGAIN, UNKNOWN, EMPTY} via the same _parse_verdict() — the
# phase-2 loop in run_step_subagent_with_review() below is unchanged.

_TRY_AGAIN_RE = re.compile(r"^try\s*again\s*[:\-—]?\s*(.*)$", re.IGNORECASE)


def _parse_verdict(text: str) -> tuple[str, str]:
    """Return (verdict, reason). verdict in {'PASS','TRY_AGAIN','EMPTY','UNKNOWN'}."""
    if not text or not text.strip():
        return ("EMPTY", "")
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    for l in reversed(lines):
        clean = l.strip("*_ ")
        if clean.upper() == "PASS" or clean.upper().startswith("PASS "):
            return ("PASS", "")
        m = _TRY_AGAIN_RE.match(clean)
        if m:
            return ("TRY_AGAIN", m.group(1).strip() or "no reason given")
    return ("UNKNOWN", lines[-1])


def _build_progress_brief(
    all_steps: list[dict],
    completed_step_nums: list[int],
    current_step_num: int,
) -> str:
    by_num = {s["step_number"]: s for s in all_steps}
    done_lines = []
    for n in sorted(completed_step_nums):
        s = by_num.get(n)
        if s:
            done_lines.append(f"- Step {n} added: {s['goal']}")
    if not done_lines:
        head = "This is Step 1 — nothing in the scene yet before the current step."
    else:
        head = "Build progress through the previous steps (what the plan says should already be in the scene):"
    cur = by_num.get(current_step_num, {}).get("goal", "(unknown)")
    tail = (
        f"You are judging **Step {current_step_num} — {cur}** right now. Any object or "
        "feature from later steps is expected to be MISSING — do not mark that as wrong."
    )
    return head + ("\n" + "\n".join(done_lines) if done_lines else "") + "\n\n" + tail


def _reviewer_inspection_rules(*, run_name: str, step_num: int) -> str:
    tools_code = str(AGENT_DIR / "Tool_scripts" / "Tools_code")
    return f"""\
## Your budget — read this first

**You have 20 turns for this whole review, and you must deliver a verdict
inside them.** Not 20 tool calls — 20 exchanges, each of which may carry
several calls.

Plan for that. Decide up front which two or three checks actually decide the
verdict, run those, and write the verdict. If you spend the budget
investigating you are cut off mid-inspection and your verdict is whatever you
had at the time, which helps nobody.

A useful shape: 2-4 turns to look, 2-4 to measure the deciding checks, then
write. If you are at turn 15 with no verdict drafted, stop investigating and
write one from what you already have — say plainly what you could not check.

## Your tool access

You have the SAME tools the builder used: `write_and_run` for the live Blender
session, plus `read`, `write`, `edit`, `glob`, `grep` and `bash`.

**`write_and_run` is for the 3D scene. Everything else belongs in `bash`.**
That split is not a style preference — an action file runs *inside* Blender and
blocks the whole session while it does, against a 30s timeout. Cropping a
render, thresholding the reference photo, scanning pixels, reading a file,
searching the repo: all of that is fast in a subprocess and ruinous in Blender.
A previous review tried to threshold a 2036x1534 photo through
`bpy.types.Image.pixels` and froze the session for four minutes. Use `bash`.

**Look up a tool instead of reverse-engineering it.** Do not paste
`inspect.getsource` into an action file to find out what something does:

```bash
python Tool_scripts/tool_help.py silhouette_vs_reference   # full docstring
python Tool_scripts/tool_help.py --search crack            # find by purpose
python Tool_scripts/tool_help.py --module perceive         # a whole module
```

`Tool_scripts/Tools_ref/INDEX.md` lists every callable that exists. If a tool
is not in there, it does not exist. `read` these — they cost you nothing and no
Blender time.

**Save your analysis scripts.** Write them into
`mem/{run_name}/steps/step_{step_num:03d}/scripts/` and `bash` them by name, so
a crop or a measurement can be re-run after the next fix instead of retyped.

**Look in the executor's `scripts/` folder first.** If this step built a shape from
the reference and that folder is empty, the verdict is "Try again" whatever the render
looks like: the shape was typed from memory, not read from the reference. Ask for the
read (mask / outline / stations saved as JSON), the trace drawn back on the reference,
and the built outline's residual against it. If the folder has scripts, re-run one and
check that the numbers it prints are the numbers the build used.

Call `write_and_run` to reposition the camera and take more screenshots before
you judge. Don't just grade the two starting renders below if they don't
actually answer a check; rotate to a different angle, switch axis
(TOP/RIGHT/etc.), or zoom into one area.

Every review action file MUST start with EXACTLY this boilerplate (the real
module paths — a wrong import here raises an exception before your script
ever reaches shot(), and this Blender session's completion-detection only
notices a script finished when shot() actually runs, so a wrong import looks
like a 30s hang, not a fast error):

```python
import sys
TOOLS_CODE = {tools_code!r}
if TOOLS_CODE not in sys.path:
    sys.path.insert(0, TOOLS_CODE)
from runtime import use, shot
use({run_name!r}, step={step_num}, action=91)   # bump action by 1 each new file

from lib.view import get_viewport, fit_objects_ortho_view
area, region, rv3d = get_viewport()
fit_objects_ortho_view(area, region, rv3d, axis='FRONT', names='all', ratio=90)
# ... or rv3d.view_rotation / rv3d.view_distance for a custom angle ...

shot("what this view is for")   # MUST be the last line — nothing is detected without it
```

`axis` for `fit_objects_ortho_view` is one of TOP/BOTTOM/FRONT/BACK/LEFT/RIGHT.
`names` is `'all'`, a single object name string, or a list of names.

Every review action file MUST be inspection-only:
- Fine: the viewport/framing calls above, or a read-only perceive/overlay
  call if it helps you judge something precisely.
- FORBIDDEN: bpy.ops.mesh.*, adding/removing/joining objects, adding or
  applying modifiers, any bmesh.ops mutation, moving/scaling/rotating actual
  geometry — you are grading the CURRENT state, not fixing it. A geometry-
  mutating action here silently corrupts the real build.
- ALWAYS end with `shot(...)`, even for a pure measurement/read with nothing
  worth screenshotting — that's the ONLY thing this environment's completion
  check looks for. Put whatever you computed in `shot()`'s own text argument
  (e.g. `shot(f"leg top radius={{r:.4f}}, base radius={{b:.4f}}")`) and read it
  back from the tool result's `note` field. Do NOT `raise` an exception to
  smuggle a value back — an action that ends any way other than a completed
  `shot()` call (an uncaught exception, a bare `print`, hitting the end of
  the file with no `shot()`) will NOT be detected as finished and will
  simply eat a full 30s timeout, indistinguishable from a real hang.
- Name your files `review_NN_<name>.py` (your own local numbering, distinct
  from the builder's) — `action=` in `use()` must match: start at 91 and
  count up by 1 per file, the builder's own action numbers stay well below
  that so this can't overwrite one of its screenshots.
- If a call fails, READ THE ERROR before retrying — fix what it actually
  says, don't just resend a similar script. If several calls in a row all
  report a timeout with no error text, stop trying more angles and note
  that in your review instead of continuing to burn calls.
- Use as many looks as you actually need to answer the checks below — a
  handful is normal, don't pad it.

## Measuring: prefer the silhouette's own numbers over your own

`perceive.silhouette_vs_reference(<names>)` returns a `stations` list — each
entry has `u` and `half_width` as fractions of the reference image, plus
`n_verts` for that slice. Convert with the `image_size` the call returns:
`full_width_px = half_width * 2 * image_size[1]`. **Do not hardcode a pixel
constant** — every build's reference is a different size, and a number carried
over from another build silently scales every measurement you report.

`samples` is an upper bound, not a target: slices are bins of vertices, so the
call clamps to what the mesh actually has and tells you via `samples_used` and
`stations_dropped`. On a low-poly body expect roughly one station per ring
however large a number you pass — that is correct, not a failure.

Those are measurements of what is actually drawn against the photo, and they
are the best evidence available to you.

**Run it yourself and quote the numbers, per part.** A check about the head is
answered by the stations forward of the neck; a check about the torso by the
stations behind it. One overall "the silhouette tracks the photo" sentence
answers neither — a build can be perfect over the torso and 3x too fat over
the muzzle, and that is exactly the failure this instruction exists to catch.

**When a radius you computed from mesh vertices disagrees with the station
widths, the stations win, and you must say so rather than quietly picking
one.** It is easy to query the wrong ring — an interior edge loop instead of
the boundary cap — and get a number that looks reasonable. A previous review
reported a snout cap "approximately 31 pixels across", which matched the
target exactly, while the step's own silhouette measured **113 px** at that
station. It passed the step. Cross-check before you believe your own number.

**If a check names a target number, state the measured value next to it.**
"The snout cap measures 113 px against a 31 px target" is a review. "The snout
reads as a blunt disk" is not — it is true of both a correct cap and one four
times too wide.

## `[Important]` and `[Other]` — spend your effort accordingly

Checks are tagged. **`[Important]` checks decide the step**: they are the ones the
build actually fails on, and each is worth a real look — crop in, measure, quote a
number. If an `[Important]` check fails, the step fails, however clean everything
else is.

**`[Other]` checks are bookkeeping** — object counts, shading flags, nothing loaded
that should not be. Confirm them briefly and move on. A review that spends three
paragraphs on "no doubled vertices" and one sentence on whether the silhouette
matches has graded the wrong step. Do not fail a step on an `[Other]` check alone
unless it is plainly broken; note it and say so instead.

Untagged checks (older plans) are all `[Important]`.

## Output format (mandatory)
1. Go through each check in order — one short paragraph per check.
2. Final line must be exactly one of:
   PASS
   Try again: <one sentence saying what is most wrong>
Be concrete. Reference what you can actually see in your renders."""


def run_agentic_reviewer(
    *,
    step_spec: dict,
    all_steps: list[dict],
    completed_step_nums: list[int],
    prior_step_summaries: list[str],
    subagent_notes: str,
    ref_image: Path,
    front_render: Path,
    persp_render: Path,
    plan_text: str,
    run_name: str,
    step_num: int,
    step_dir: Path,
    round_num: int,
    usage: "UsageAggregate",
) -> tuple[str, str, str]:
    """Agentic reviewer — its own hermes-agent conversation with real
    write_and_run access, so it can navigate the live scene before judging.
    Same (verdict, reason, full_review_text) contract as the old
    call_reviewer() it replaces, so the phase-2 loop below is unchanged.

    Every round's own inspection files (its review_NN_*.py action files and
    the screenshots they produced) get moved into this round's own
    steps/step_NNN/review/round_KK/ folder before returning — see
    round_review_dir(). The starting front/persp renders are copied in
    there too, so one folder holds everything this round actually saw."""
    import shutil
    from run_agent import AIAgent
    from agent.image_routing import build_native_content_parts

    checks_block = "\n".join(
        f"{i+1}. {c}" for i, c in enumerate(step_spec["review_checks"])
    ) or "(no explicit checks — evaluate overall visual fit vs. reference)"
    plan_brief = _build_progress_brief(all_steps, completed_step_nums, step_num)
    prior_block = (
        "\n".join(f"- {s}" for s in prior_step_summaries)
        if prior_step_summaries else "(none — this is the first step)"
    )

    intro_text = f"""\
# BlendCUA — Reviewer role

Run name: {run_name}
You are the visual quality reviewer for **Step {step_num} — {step_spec['goal']}**.

{plan_brief}

Subagent's own notes for the completed steps (its reported outcome):
{prior_block}

Current step result (what the subagent reports having done just now):
{subagent_notes or '(no notes)'}

Visual checks to evaluate:
{checks_block}

## Full build plan (context — do not expect later steps' features yet)

{plan_text}

## Images attached
1. Reference image — the target
2. Front ortho render of the current build (starting point, already rendered)
3. 3/4 ortho render of the current build (starting point, already rendered)

{_reviewer_inspection_rules(run_name=run_name, step_num=step_num)}

{load_skills_index('Reviewer', 'Scripting')}
"""

    first_message, _skipped = build_native_content_parts(
        intro_text, image_paths=[str(ref_image), str(front_render), str(persp_render)],
    )

    reviewer_kwargs = dict(
        provider=MODELS["reviewer"]["provider"],
        model=MODELS["reviewer"]["model"],
        api_key=api_key_for(MODELS["reviewer"]["provider"]),
        base_url=base_url_for(MODELS["reviewer"]["provider"]),
        quiet_mode=True,
        # 20, and the reviewer is TOLD it is 20 (see _reviewer_inspection_rules).
        # At 16 every one of the 22 reviews in the 2026-08-27 trial hit the cap
        # mid-inspection: the model never learned it had a budget, so it planned
        # as if unbounded and was cut off rather than concluding.
        max_iterations=20,
        ephemeral_system_prompt=(
            "You are an exacting but fair visual QA reviewer for a 3D "
            "modelling pipeline. You have real tool access to the live "
            "Blender scene for INSPECTION ONLY — see the rules in your "
            "first message before calling anything."
        ),
        # Same toolset as the Step-Subagent. This line used to read
        # `["blendcua"]` while the comment above it claimed otherwise, and the
        # divergence was expensive: `blendcua` registers write_and_run and
        # NOTHING else, so the reviewer had no read/bash/glob/grep at all. Its
        # only way to look at anything was to execute Python inside Blender and
        # print the result through shot(). Observed on duck_run_001: it paged a
        # tool's source out in 3800-char chunks over two actions, re-learned the
        # same API from scratch in the next round, walked the filesystem with
        # os.walk inside Blender, and finally tried to threshold a 2036x1534
        # photo through bpy.types.Image.pixels one element at a time — 235k RNA
        # accesses, which blew the 30s timeout and took the session down for
        # four minutes. Every one of those is a bash/read call.
        #
        # This adds no new authority: write_and_run is already arbitrary Python
        # inside the live Blender session, strictly more powerful than reading a
        # file. "Inspection only" is enforced by its prompt, not by withholding
        # the shell — and withholding the shell is what pushed the heavy work
        # INTO Blender, where it does damage.
        enabled_toolsets=["blendcua", "blendcua_fs", "todo"],
    )
    if MODELS["reviewer"]["provider"] == "openai":
        reviewer_kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}
    reviewer_agent = AIAgent(**reviewer_kwargs)

    round_dir = round_review_dir(MEM_DIR / run_name, step_num, round_num)
    for src in (front_render, persp_render):
        if src.is_file():
            shutil.copy2(src, round_dir / src.name)

    # write_and_run resolves its target step dir from CURRENT_ACTION_CONTEXT
    # (module-level, since dispatch_step calls are strictly serial) — it's
    # already pointed at this step's dir by the subagent's own run, so no
    # extra wiring needed here; the review_NN_ filename prefix and action=91+
    # numbering (see _reviewer_inspection_rules) are what keep its screenshots
    # from colliding with the builder's own action_NN.png files. They land
    # directly under step_dir/ (and step_dir/screenshots/) same as the
    # builder's own — moved into this round's own folder below, once the
    # conversation is done and nothing will write to them again.
    _t0 = time.time()
    r = reviewer_agent.run_conversation(first_message)
    usage.log_conversation_result(r, tag="Reviewer", wall_s=time.time() - _t0)
    for i, c in enumerate(_tool_call_summaries(r.get("messages") or [], 0), 1):
        log_print(f"[Reviewer]   {i:>3}. {c}")

    for py_file in step_dir.glob("review_*.py"):
        shutil.move(str(py_file), str(round_dir / py_file.name))
    shots_dir = step_dir / "screenshots"
    if shots_dir.is_dir():
        for shot_file in shots_dir.glob("action_9[1-9]*.png"):
            shutil.move(str(shot_file), str(round_dir / shot_file.name))

    full_review = (r.get("final_response") or "").strip()
    if not full_review:
        return ("UNKNOWN", "reviewer returned no response", "(no response)")
    verdict, reason = _parse_verdict(full_review)
    return (verdict, reason, full_review)


# ── Review render (dispatched by Python, not the subagent) — UNCHANGED ──────

def _make_review_render_script(run_name: str, step_num: int) -> str:
    tools_code = str(AGENT_DIR / "Tool_scripts" / "Tools_code")
    return f"""\
import sys
TOOLS_CODE = {tools_code!r}
if TOOLS_CODE not in sys.path:
    sys.path.insert(0, TOOLS_CODE)
from runtime import use, shot
use({run_name!r}, step={step_num}, action=90)
from review import render_review_shots
render_review_shots()
shot("review renders done")
"""


def _read_exec_status() -> dict | None:
    try:
        return json.loads(_EXEC_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dispatch_script(script_path: Path, *, timeout: float = 30.0, shots: bool = False) -> tuple[bool, str]:
    """In-process equivalent of `python Tool_scripts/run.py --file ... --timeout ...`
    — sends the script straight over the Blender socket and polls
    exec_status.json, without spawning a new python.exe subprocess.

    Added because spawning a fresh interpreter per action reproducibly
    stalled 45s+ on this Windows setup: confirmed via `Get-NetTCPConnection`
    that the spawned grandchild process never even reached its
    `socket.socket()` call within the 45s window, while Blender's own
    process stayed fully responsive throughout (`Get-Process -Responding`
    True the entire time). That points at Windows process-creation-level
    interception (real-time AV/behavior-monitoring overhead on this
    specific repeated-spawn-under-load pattern), not Blender or this code
    — so the fix is to stop spawning a subprocess per action at all.
    `Tool_scripts/run.py` itself is untouched, still used for manual/CLI
    replay (win_run_steps.py etc.).
    """
    if shots:
        _SHOTS_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SHOTS_FLAG_FILE.touch()
    else:
        try:
            _SHOTS_FLAG_FILE.unlink()
        except FileNotFoundError:
            pass

    try:
        script = script_path.read_text(encoding="utf-8")
    except OSError as e:
        return False, str(e)

    prev = _read_exec_status()
    prev_seq = prev.get("seq") if prev else None
    sent_at = time.time()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost", _BLENDER_PORT))
        s.sendall(script.encode("utf-8"))
        s.close()
    except OSError as e:
        return False, f"Could not connect to Blender on port {_BLENDER_PORT} — is blender_server.py running? ({e})"

    deadline = sent_at + timeout
    while time.time() < deadline:
        st = _read_exec_status()
        if st is not None and st.get("seq") != prev_seq:
            if st.get("ok"):
                return True, ""
            return False, st.get("error") or "(no traceback captured)"
        time.sleep(0.25)

    return False, f"dispatch did not return within {timeout:.0f}s (Blender hung?)"


def _render_review_images(
    run_name: str, step_num: int, step_dir: Path
) -> tuple[bool, str]:
    step_dir.mkdir(parents=True, exist_ok=True)
    script_path = step_dir / "90_review_render.py"
    script_path.write_text(
        _make_review_render_script(run_name, step_num), encoding="utf-8"
    )
    ok, err = _dispatch_script(script_path, timeout=DISPATCH_TIMEOUT_S, shots=False)
    if not ok:
        return False, err

    review_dir = MEM_DIR / run_name / "steps" / f"step_{step_num:03d}" / "review"
    front = review_dir / "review_front.png"
    persp = review_dir / "review_persp.png"
    deadline = time.time() + 10
    while time.time() < deadline:
        if front.exists() and persp.exists():
            return True, ""
        time.sleep(0.5)
    return False, "script completed but review images not on disk after 10s"


def _resize_png_inplace(path: Path, w: int = 1440, h: int = 1080) -> None:
    """Cap a delivered screenshot at w x h, PRESERVING ASPECT RATIO.

    1440x1080 is the largest 4:3 size that neither vision model resamples on
    arrival: GPT-5.x tiles 32px patches and caps at 1536 of them (45x34 =
    1530); Claude tiles 28px and caps at 4784 tokens (52x39 = 2028). Sending
    more pixels than that just makes the provider downscale them again.
    Renders arrive at 2x the Blender region (see Tools_code/lib/view.py), so
    this is a real downsample, and the antialiasing it brings is a bonus on
    exactly the thin wireframe and silhouette edges the shape checks read.

    This used to resize unconditionally to exactly (w, h). Fine while every
    image was a viewport render of the same 4:3-ish region, but wrong the
    moment anything else is delivered: `silhouette_vs_reference` returns a
    crop crediting the mesh (e.g. 1193x575, 2.07:1), and squashing that into
    4:3 stretches it vertically by ~55% — which would falsify the exact
    width-vs-length judgement the overlay exists to support. An image the
    model is asked to measure must never be anamorphically scaled.

    Anything already within the box is left alone: upscaling adds no
    information and only costs image tokens.
    """
    try:
        from PIL import Image
    except ImportError:
        return
    try:
        with Image.open(path) as im:
            iw, ih = im.size
            if iw <= w and ih <= h:
                return
            scale = min(w / iw, h / ih)
            new = (max(1, round(iw * scale)), max(1, round(ih * scale)))
            if new == (iw, ih):
                return
            im = im.convert("RGB") if im.mode == "P" else im
            im.resize(new, Image.LANCZOS).save(path, "PNG")
    except (OSError, ValueError):
        pass


_BARE_SHOT_RE = re.compile(r"^action_\d+\.png$")

# Ceiling on images returned by ONE tool call (write_and_run's fresh renders,
# run_python's outputs, an explicit show_image call). Four ~1.5MB-of-base64
# frames is already a large turn; the cap exists so a loop that renders twenty
# crops cannot blow the context window in a single result.
MAX_IMAGES_PER_RESULT = 4


# ── Rewind ───────────────────────────────────────────────────────────────────
#
# There is no undo. `use()` saves no .blend checkpoint (removed deliberately —
# and reloading a .blend from inside a bpy.app.timers callback, which is how
# every action executes, would tear down the data the callback is running on).
#
# So a wrong-but-successful action used to be permanent: the agent could only
# write ANOTHER action correcting the scene forward from wherever it landed.
# That cost 3 actions and ~57s of model time for the one mis-centred reference
# in step 1, and each wasted action eats the step's 30-action budget.
#
# The rewind here is simply: rebuild from a clean scene by re-running the
# earlier action files. That works because the action files are a deterministic
# program (verified — three consecutive replays gave identical vertex
# positions), and it is cheap because the whole rebuild goes over the socket as
# one batch: 84 actions in ~4.2s, against ~19s for a single model turn. See
# replay_batch.py.

def _checkpoint_before(run_name: str, step: int) -> int | None:
    """Highest checkpointed step strictly below `step`, or None.

    Read from disk rather than through the Blender-side module, so the client
    can decide what to send without a round trip.
    """
    d = MEM_DIR / run_name / "checkpoints"
    if not d.is_dir():
        return None
    best = None
    for p in d.glob("step_*.blend"):
        try:
            n = int(p.stem.split("_")[-1])
        except ValueError:
            continue
        if n < step and (best is None or n > best):
            best = n
    return best


def save_step_checkpoint(run_name: str, step: int, *, timeout: float = 120.0) -> bool:
    """Write the end-of-step .blend a later rewind can start from. 0.3s, best effort."""
    script = (
        "import sys\n"
        f"sys.path.insert(0, r'{AGENT_DIR / 'Tool_scripts' / 'Tools_code'}')\n"
        "from checkpoint import save_step\n"
        f"save_step({run_name!r}, {step})\n"
    )
    tmp = MEM_DIR / run_name / ".checkpoint.py"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(script, encoding="utf-8")
    ok, err = _dispatch_script(tmp, timeout=timeout, shots=False)
    tmp.unlink(missing_ok=True)
    if not ok:
        log_print(f"[checkpoint] step {step} not saved ({err[:80]}) — rewinds "
                  f"will fall back to replaying from step 1")
    return ok


def replay_scene(
    run_name: str, *, before_step: int, before_action: int, timeout: float = 300.0
) -> tuple[bool, str, int]:
    """Rebuild the scene as it was just before (before_step, before_action).

    Returns (ok, error, actions_replayed).
    """
    files = replay_batch.collect_action_files(
        str(MEM_DIR), run_name,
        before_step=before_step, before_action=before_action,
    )
    if not files:
        return True, "", 0

    # If an earlier step was checkpointed, load that .blend and replay only the
    # actions after it. Re-executing finished steps is the single most expensive
    # thing the harness does: measured on 05_wine_glass step 3, replaying all 14
    # actions took 110.6s, of which 92.8s was rebuilding steps 1-2. Loading their
    # checkpoint instead costs 0.3s, so the same rewind lands in 15.9s.
    ckpt_step = _checkpoint_before(run_name, before_step)
    if ckpt_step is not None:
        # Two dispatches, not one script. Immediately after open_mainfile the
        # context inside the same timer callback has no screen — the first
        # action calling lib.view.solid_shading() dies on
        # `bpy.context.screen.areas` -> NoneType. A second dispatch runs in a
        # fresh callback with a valid context. The extra round trip is ~0.3s
        # against the ~90s this avoids.
        load = (
            "import sys\n"
            f"sys.path.insert(0, r'{AGENT_DIR / 'Tool_scripts' / 'Tools_code'}')\n"
            "from checkpoint import load_step\n"
            f"load_step({run_name!r}, {ckpt_step})\n"
        )
        tmp = MEM_DIR / run_name / ".rewind_load.py"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(load, encoding="utf-8")
        ok, err = _dispatch_script(tmp, timeout=120, shots=False)
        tmp.unlink(missing_ok=True)
        if ok:
            keep = f"step_{before_step:03d}"
            files = [f for f in files if keep in str(f)]
            log_print(f"[rewind] from checkpoint step {ckpt_step}; "
                      f"replaying {len(files)} action(s) of step {before_step}")
            if not files:
                return True, "", 0
        else:
            log_print(f"[rewind] checkpoint load failed ({err[:60]}) — "
                      f"replaying from step 1")

    script = replay_batch.build_replay_script(
        files, str(AGENT_DIR / "Tool_scripts" / "Tools_code"),
        render=False, label=f"rewind to step {before_step} action {before_action}",
    )
    tmp = MEM_DIR / run_name / ".rewind.py"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(script, encoding="utf-8")
    ok, err = _dispatch_script(tmp, timeout=timeout, shots=False)
    return ok, err, len(files)


def _stale_after(step_dir: Path, action_num: int) -> list[str]:
    """Action files in this step numbered ABOVE action_num (build actions only).

    After a rewound retry of action N these were built against the OLD N, so
    they are suspect. They are NOT deleted — that is the agent's call — but the
    tool result says so explicitly rather than letting them look current.
    """
    out = []
    for p in sorted(step_dir.glob("*.py")):
        m = replay_batch.ACTION_FILE_RE.match(p.name)
        if not m:
            continue
        n = int(m.group(1))
        if action_num < n < replay_batch.REVIEW_ACTION_MIN:
            out.append(p.name)
    return out


# ── Action executor — replaces the write_and_run MCP tool ───────────────────
#
# Same contract as BlendCuagent2's write_and_run tool (write one action file
# under the step dir, run it against Blender via run.py, return ok/note/
# screenshot/overlay) — just called directly by our orchestrator loop instead
# of being an autonomously-callable tool, since hermes-agent can't forward
# tool-result images into the model's context anyway (see module docstring).

def write_and_run_action(
    *, run_name: str, step_dir: Path, filename: str, content: str,
) -> dict:
    """Write + execute one action file. Returns {ok, note, error, screenshot, overlay}."""
    if (not filename.endswith(".py")) or "/" in filename or "\\" in filename:
        return {"ok": False, "error": f"bad filename {filename!r} — use 'NN_name.py', no directories"}

    step_dir.mkdir(parents=True, exist_ok=True)
    path = step_dir / filename

    # ── Retry detection ──────────────────────────────────────────────────
    # An existing filename means the agent is REWRITING an action it already
    # ran, not adding a new one — "that scale was too big, make it 1.4". Just
    # executing the new file would compound onto the old result (2.0 then 1.4
    # = 2.8x, not 1.4x), so rewind first: rebuild from a clean scene through
    # the action immediately BEFORE this one, then run the new version
    # normally below. From the agent's side there is no new protocol —
    # rewriting an action and sending it simply means what it looks like.
    step_m = re.match(r"^step_(\d+)$", step_dir.name)
    act_m = replay_batch.ACTION_FILE_RE.match(filename)
    rewind_note = ""
    if path.exists() and step_m and act_m:
        step_num, action_num = int(step_m.group(1)), int(act_m.group(1))
        ok, err, n_replayed = replay_scene(
            run_name, before_step=step_num, before_action=action_num
        )
        if not ok:
            return {"ok": False, "error":
                    f"retry of {filename}: rewind failed while replaying the "
                    f"{n_replayed} preceding action(s) — the scene is now in an "
                    f"unknown state. {err}"}
        rewind_note = f"[retry: rewound through {n_replayed} prior action(s)] "
        stale = _stale_after(step_dir, action_num)
        if stale:
            rewind_note += (
                f"[WARNING: {', '.join(stale)} ran against the PREVIOUS version "
                f"of {filename} and were not re-run — rewrite or delete them] "
            )

    content = localise_tools_path(content)
    path.write_text(content, encoding="utf-8")
    sent_at = time.time()

    # shots=True: runtime.shot() is gated by a sticky flag file
    # (mem/.shots_enabled) that dispatch actively CLEARS whenever shots
    # isn't requested — confirmed empirically (a bare shot() call with no
    # flag wrote "shot": null, no PNG, every time). Without this flag every
    # action's own screenshot silently never renders, and the subagent
    # narrates from its own note text instead of actually seeing anything.
    ok, err = _dispatch_script(path, timeout=DISPATCH_TIMEOUT_S, shots=True)
    if not ok:
        return {"ok": False, "error": err}

    status_path = MEM_DIR / run_name / "last_step.json"
    note = ""
    try:
        note = json.loads(status_path.read_text(encoding="utf-8")).get("note", "")
    except (OSError, json.JSONDecodeError):
        pass

    # Every PNG this action freshly wrote comes back, not just one.
    #
    # This used to be `shown = overlay or bare`, where `overlay` was whichever
    # non-bare PNG happened to sort LAST — so an action that rendered several
    # diagnostic views silently lost all but one, and which one survived was
    # decided by alphabetical order. bat_gptluna_med5's 12_verify_body.py
    # rendered action_12_final_tight.png (a head close-up), action_12_front.png
    # and action_12_right.png; the agent was shown only _right, the head crop
    # it had specifically asked for was discarded, and it then rewrote that
    # verification action three times. Writing multiple views was actively
    # counterproductive, which is the opposite of what the plan asks for.
    #
    # The bare viewport shot is still only sent when nothing named was
    # rendered — when the action produced overlays/crops, those ARE the
    # answer and the bare frame is redundant token weight.
    shots_dir = step_dir / "screenshots"
    bare, overlays = None, []
    if shots_dir.is_dir():
        for p in sorted(shots_dir.glob("*.png")):
            try:
                if p.stat().st_mtime < sent_at - 1:
                    continue
            except OSError:
                continue
            if _BARE_SHOT_RE.match(p.name):
                bare = p
            else:
                overlays.append(p)

    shown_list = overlays or ([bare] if bare else [])
    dropped = 0
    if len(shown_list) > MAX_IMAGES_PER_RESULT:
        dropped = len(shown_list) - MAX_IMAGES_PER_RESULT
        shown_list = shown_list[-MAX_IMAGES_PER_RESULT:]
    for p in shown_list:
        _resize_png_inplace(p)

    return {
        "ok": True,
        "note": rewind_note + note,
        "screenshot": str(rel_to(bare, AGENT_DIR)) if bare else None,
        "overlay": str(rel_to(overlays[-1], AGENT_DIR)) if overlays else None,
        "shown_abs_paths": [str(p) for p in shown_list],
        "shown_dropped": dropped,
    }


# ── Subagent prompt ───────────────────────────────────────────────────────────

# ── Rolling handover between steps ───────────────────────────────────────────
#
# Each step gets a fresh conversation, which keeps context small but used to
# throw away everything the previous subagent learned — the next one inherited
# a 220-character one-liner. So step 3 re-derived facts step 1 had measured,
# and re-made mistakes step 2 had already hit.
#
# Instead, each subagent writes a handover before it exits, and the next one
# receives it. It is ROLLING: the handover a subagent writes folds in the
# handover it was given, so step 3's document covers steps 1 AND 2, and nothing
# falls off the back of the chain.
#
# The compaction turn runs inside the SUBAGENT'S OWN conversation rather than
# in a fresh summariser. Two reasons: it has the whole step in context at full
# fidelity (every screenshot, every traceback, every value it tried and
# rejected), and that context is already cached, so one more turn is nearly
# free on input.

HANDOVER_TARGET_CHARS = 40_000     # ≈ 10k tokens — the ceiling the user asked for
HANDOVER_HARD_CAP = 56_000         # refuse to carry more than this, whatever it wrote


def _handover_instruction(step_num: int, goal: str, next_goal: str | None) -> str:
    nxt = (f"The next subagent's job is **Step {step_num + 1} — {next_goal}**."
           if next_goal else
           "You are the last step, so write this as a record of the finished build.")
    return f"""\
The step is finished. Write a HANDOVER for the next Step-Subagent.

It starts a brand-new conversation and inherits nothing except this document,
so this is the only thing that survives. {nxt}

**Summarise the WORK, not the documentation.** It receives the same system
prompt, the same reference docs (`current_tools_new.md`, `examples_new.md`,
`conventions.md`, `terminal.md`, ...) and the same build plan you did. Do not
restate tool signatures, coding conventions, overlay rules or plan text — that
is wasted space. Write what it cannot get anywhere else: what is actually in
the scene right now, and what you learned building it.

Fold in everything you were told about earlier steps, so this document stands
alone as the state of the whole build so far. Do not drop an earlier fact just
because it did not come up in your step.

Cover, in this order:

1. **Scene state** — every object that exists now, by exact name: what it is,
   its dimensions, where it sits, its modifiers, its shading, its vertex/face
   counts. Enough that the next subagent can act on it without re-measuring.
2. **Key values and where they came from** — the numbers you derived from the
   photo or the mesh and would want reused (ratios, radii, world coordinates,
   u/v landmarks, scale factors). Say how each was obtained, so it is trusted
   rather than re-derived.
3. **What you built, in order** — the action files by name and what each did.
   Note any you rewrote and why the first version was wrong.
4. **What went wrong and what fixed it** — errors, dead ends, values that
   looked right and were not, tools that behaved unexpectedly. This is the most
   valuable section: it is how the next subagent avoids repeating your work.
5. **Verification evidence** — what you checked, how, and the numbers you got.
6. **Warnings and open items** — anything unresolved, approximate, or likely to
   bite later.

Aim for {HANDOVER_TARGET_CHARS // 4:,}–{HANDOVER_TARGET_CHARS // 2:,} words of
substance (roughly {HANDOVER_TARGET_CHARS // 2:,}–{HANDOVER_TARGET_CHARS:,}
characters). Be specific and dense — concrete names and numbers, not
impressions. "The body is about right" is worthless; "BatBody spans Y −0.429 to
+0.313, chest ring radius 0.0925 at Y=+0.09" is what gets used.

Output the handover as markdown. No JSON block, no preamble, no sign-off."""


def _write_handover(*, turn, history, step_num: int, goal: str,
                    next_goal: str | None, run_name: str, logger) -> str:
    """Ask the just-finished subagent to compact its own step. Never fatal."""
    try:
        r = turn(_handover_instruction(step_num, goal, next_goal), history)
        text = (r.get("final_response") or "").strip()
    except Exception as e:                       # rate limits, dropped turn, ...
        log_print(f"[handover] step {step_num}: compaction turn failed ({e}) — "
                  f"falling back to the one-line summary")
        logger.log_event({"type": "handover_failed", "step": step_num, "error": str(e)})
        return ""
    if not text:
        log_print(f"[handover] step {step_num}: subagent returned nothing — "
                  f"falling back to the one-line summary")
        logger.log_event({"type": "handover_failed", "step": step_num,
                          "error": "empty response"})
        return ""
    if len(text) > HANDOVER_HARD_CAP:
        text = (text[:HANDOVER_HARD_CAP]
                + f"\n\n[handover truncated at {HANDOVER_HARD_CAP:,} characters]")
    try:
        path = step_dir_for(run_name, step_num) / "handover.md"
        path.write_text(text, encoding="utf-8")
        log_print(f"[handover] step {step_num}: {len(text):,} chars "
                  f"(~{len(text)//4:,} tokens) -> {rel_to(path, AGENT_DIR)}")
    except OSError as e:
        log_print(f"[handover] step {step_num}: could not save ({e})")
    logger.log_event({"type": "handover", "step": step_num, "chars": len(text)})
    return text


def _one_line_summary(step_num: int, goal: str, notes: str) -> str:
    notes_short = " ".join((notes or "").split())[:220]
    return f"Step {step_num} ({goal}): {notes_short}"


def build_subagent_prompt(
    *,
    run_name: str,
    step_spec: dict,
    prior_step_summaries: list[str],
    image_relpath: str | None,
    action_budget: int,
    no_reviews: bool = False,
    prior_handover: str = "",
    task_relpath: str | None = None,
) -> str:
    step_num = step_spec["step_number"]
    goal     = step_spec["goal"]
    section  = step_spec["section_text"]
    checks   = step_spec["review_checks"]
    preamble_block = step_spec.get("preamble") or "(this plan has no shared preamble)"

    # The handover written by the previous step-subagent, which folded in the
    # one before it, and so on back to step 1. When it exists it replaces the
    # one-line summaries entirely — it contains everything they said and far
    # more. The one-liners remain as the fallback for when a compaction turn
    # died (rate limits, dropped connection) so the chain degrades instead of
    # breaking.
    one_liners = (
        "\n".join(f"- {s}" for s in prior_step_summaries)
        if prior_step_summaries else "(none — this is the first step)"
    )
    if prior_handover:
        prior_block = f"""\
This is the handover written by the subagent that finished the previous step.
It carries the whole build so far — it folded in the handover *it* was given.
**This is the state of the scene you are starting from.** Trust its measured
numbers rather than re-deriving them, and heed its warnings.

---

{prior_handover}

---

(One-line record of the steps behind it: {' | '.join(prior_step_summaries) or 'none'})"""
    else:
        prior_block = one_liners
    # A rebuild (vb/rebuild.py) leaves mem/<run>/prior_attempt.md: where the previous
    # attempt of this task is, that its code may be reused, and what must be built
    # differently. It is part of what the subagent starts from, like the handover.
    _prior_note = MEM_DIR / run_name / "prior_attempt.md"
    if _prior_note.is_file():
        try:
            _txt = _prior_note.read_text(encoding="utf-8").strip()
        except OSError:
            _txt = ""
        if _txt:
            prior_block += "\n\n" + _txt
    checks_block = "\n".join(f"{i+1}. {c}" for i, c in enumerate(checks)) \
        if checks else "(no explicit checks defined)"
    image_line = (
        f"Reference image: `{image_relpath}` — mentioned so you know it exists; "
        "you will be shown it directly if relevant."
        if image_relpath else "(no reference image supplied)"
    )
    if task_relpath:
        image_line += (
            f"\n\nTask folder: `{task_relpath}/` — the build plan is the spec, "
            "and **every asset it names sits beside it in that folder**. If the "
            "plan mentions an annotated image or a data file, `read` it from "
            "there; do not go looking elsewhere in the repo for it."
        )

    # --no-reviews: there is no second pair of eyes on this step. The checks
    # below are still the spec, so they are still handed over — but framed as
    # the subagent's OWN acceptance criteria, and the return contract changes
    # (no reviewer message follows, so `"pass": true` is self-certified and
    # ends the step immediately). Leaving the reviewed-mode wording in place
    # would tell the model to wait for feedback that never arrives, which is
    # exactly how a step ends with no JSON at all.
    if no_reviews:
        checks_heading = (
            "## Acceptance checks — YOU are the only one who will apply these\n\n"
            "There is **no visual reviewer** on this run. Nobody else will look "
            "at your work, so each check below is yours to settle, and you must "
            "report a verdict on every one of them by number.\n\n"
            "**Looking is not verifying.** Rendering a view and moving on is not "
            "a check. A check is settled when you can state what you observed "
            "and whether it meets the criterion. Where a check names a "
            "measurable thing (a ratio, a width, staying inside an outline), "
            "measure it. Where it is about how something looks, `write` a "
            "script into this step's `scripts/` folder that crops in on it, "
            "`bash` it, and look at the crop close up — a detail that is 40 px "
            "wide in a full-frame render cannot be judged from the full "
            "frame.\n\n"
            "**A failed check is work, not a note.** If a check fails, rewrite "
            "the action that caused it (same filename — the harness rewinds and "
            "replays for you, so a fix replaces that action rather than piling a "
            "correction on top of it) and then re-check. "
            'Add a `# REDO N:` line above the existing header and KEEP every comment already in the file — the rewind replaces the geometry, not the record of what you already tried. '
            "Do not carry a known "
            "failure into your result and describe it in `anomalies` — fix it."
        )
        return_format = """\
## Return format

Output a fenced JSON block when, and only when, you have a verdict for every
acceptance check. **No reviewer message follows it — the JSON ends the step.**

```json
{
  "checks": [
    {"check": 1, "verdict": "pass", "evidence": "<what you measured or saw, and the value>"},
    {"check": 2, "verdict": "pass", "evidence": "..."}
  ],
  "notes": "<one-to-two-sentence summary of what was built and what values you chose>",
  "actions_taken": <int>,
  "anomalies": ["<anything unexpected, else empty list>"],
  "pass": true
}
```

One entry per numbered check above, in order. `verdict` is `"pass"` or
`"fail"`. `evidence` is what you actually observed — a number you measured, or
what a cropped render showed. "Looks correct" is not evidence.

`"pass": true` requires every verdict to be `"pass"`. If you submit with any
`"fail"` you will be sent back to fix it, so fix it first. Nothing may follow
the JSON block."""
    else:
        checks_heading = "## Review checks the reviewer will apply to your result"
        return_format = """\
## Return format

When geometry work is done, output a fenced JSON block. After you output it,
you will receive a visual reviewer's analysis as a follow-up message. Read it
carefully and decide whether the work passes. Output another JSON block with
`"pass": true` if satisfied, or fix the issues (using `write_and_run` again)
and then output JSON with `"pass": true` when done.

```json
{
  "notes": "<one-to-two-sentence summary of what was built and what values you chose>",
  "actions_taken": <int>,
  "anomalies": ["<anything unexpected, else empty list>"],
  "pass": false
}
```

Set `"pass": true` only when the reviewer is satisfied. Nothing may follow
the JSON block."""

    return f"""\
# BlendCUA — Step-Subagent Task

Run name: {run_name}
Step number: {step_num}
Goal: {goal}
Actions available for this step: {action_budget} (`write_and_run` calls). This
is headroom, not a target — `read`, `write`, `edit`, `glob`, `grep` and `bash`
do not count against it and are unlimited. Spend whatever it takes to get this
step RIGHT; there is no credit for finishing early or for using few calls.

{image_line}

## The build so far — handover from the previous step

{prior_block}

## The build plan's shared context — applies to every step

{preamble_block}

## Your assignment for this step (from the build plan)

{section}

{checks_heading}

{checks_block}

---

## Scripting — read the reference before you build

"Scripting" means a small `.py` you `write` into `mem/{run_name}/steps/step_{step_num:03d}/scripts/`
and run with `bash`, that reads the reference image or the scene and PRINTS numbers or
draws an overlay (a material mask and its row table, axis and floor rows, a part's outline
traced into a polygon, a thickness, colour medians; `Tool_scripts/Tools_code/outline_trace.py`
has the pieces, `perceive.reference_outline` for the scene side). Nothing goes into the working folder's root (no tmp_*.py, crops or notes beside the code): files left there are deleted at the next sync. It is not the action that
builds the part and it is not prose about what the picture probably shows.

If this step builds a shape: before the first build action, read that shape out of the
reference with such a script, save what it found (`scripts/<part>.json` and the trace
drawn back on the reference as a PNG), look at the PNG, and make the build action read
the file — never retype numbers, never choose "a convenient scale rather than the pixels".
Close the step with the same kind of script (your outline on the reference, residual per
row) and list the scripts and what they printed in the handover. A construction step whose
`scripts/` folder is empty fails review on that alone.

## Working style

For each action, make ONE call to `write_and_run(filename="NN_<name>.py",
content=<full file source>, show_screenshot=<bool>)`. It writes the file into
`mem/{run_name}/steps/step_{step_num:03d}/`, runs it in Blender, waits for
completion, and returns the `shot()` note plus the screenshot — attached as a
real image on your next turn when `show_screenshot=true`. Use `true` for
perception/verification actions (overlays, after-transform checks) and
`false` for blind setup actions (add object, modifier, mode set, join). On
error it returns the full traceback — fix the content and call again with
the SAME filename.

Call it as many times as you need, one action per call. Follow every rule in
the reference documentation in your system prompt (overlay-before-transform,
mode_set guard, edit-in-place for retries, etc.). Do not create files outside
the run's step directory.

{return_format}
"""


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_result_json(text: str) -> dict:
    """Extract the last fenced JSON block from the subagent's final message."""
    for m in reversed(list(_JSON_BLOCK_RE.finditer(text or ""))):
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
    for m in reversed(list(re.finditer(r"\{[^{}]*\}", text or "", re.DOTALL))):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return {}


# Module-level context the write_and_run plugin tool reads to know which
# run/step it's currently writing into (see .hermes/plugins/blendcua_tools/
# __init__.py). dispatch_step calls are strictly serial within one process,
# so a plain dict is safe — no two steps ever run concurrently here.
CURRENT_ACTION_CONTEXT: dict = {"run_name": None, "step_dir": None}


# ── Step-Subagent runner (hermes-agent) ──────────────────────────────────────
#
# Ported from BlendCuagent2's _run_subagent_with_review. Same two phases
# (geometry work, then a review loop that injects the reviewer's full text
# and lets the model decide pass/fail itself), same budgets. Phase 1 is now
# ONE continuous run_conversation() call again — the model autonomously
# calls the write_and_run PLUGIN tool (see .hermes/plugins/blendcua_tools/)
# as many times as it needs, seeing each screenshot inline via Hermes's
# native multimodal tool-result mechanism. This only works because
# write_and_run is a real plugin tool, not an MCP server — MCP tool results
# are confirmed (empirically) to never reach the model as actual pixels, only
# a cached file path. See the module docstring and the plugin's own
# docstring for the full story.

def _check_problems(result: dict, n_checks: int) -> tuple[list, list]:
    """(failed checks, contract violations) in a --no-reviews result JSON."""
    raw = result.get("checks")
    if not isinstance(raw, list) or not raw:
        return [], [f"no `checks` array — one entry required for each of the "
                    f"{n_checks} acceptance checks"]

    entries, problems = [], []
    for i, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            problems.append(f"checks[{i}] is not an object")
            continue
        verdict = str(c.get("verdict", "")).strip().lower()
        num = c.get("check", i)
        if verdict not in ("pass", "fail"):
            problems.append(f"check {num}: verdict must be \"pass\" or \"fail\" "
                            f"(got {c.get('verdict')!r})")
        if not str(c.get("evidence", "")).strip():
            problems.append(f"check {num}: no evidence given")
        entries.append((num, verdict, str(c.get("evidence", ""))))

    if n_checks and len(raw) != n_checks:
        problems.append(f"{len(raw)} check entries for {n_checks} acceptance "
                        f"checks — report on every one, in order")

    failed = [(n, e) for n, v, e in entries if v == "fail"]
    if failed and result.get("pass") is True:
        problems.append("\"pass\": true is not allowed while any verdict is "
                        "\"fail\"")
    return failed, problems


def _enforce_self_checks(*, result, history, turn, step_spec, step_num,
                         max_rounds, logger):
    """Send the subagent back while its own checks say the step isn't done.

    --no-reviews removes the reviewer, and with it the only thing in this
    harness that ever made the subagent redo work: across bat_gpt56luna_med4,
    12 of its 15 geometry revisions happened only after a TRY_AGAIN, and in
    phase 1 of steps 3-5 it made none at all. The plan asks for self-checking
    in plain terms ("Fix the radius by rewriting this action") and it is not
    enough on its own.

    So the result contract is enforced rather than requested: a `checks` array
    with a verdict and evidence per acceptance check, and `pass` withheld while
    any verdict is "fail". This is a contract check, not a judgement — the
    model still decides what passes. It only removes the option of noticing a
    failure and shipping anyway.
    """
    n_checks = len(step_spec.get("review_checks") or [])
    for rnd in range(max_rounds):
        failed, problems = _check_problems(result, n_checks)
        if not failed and not problems:
            if rnd:
                log_print(f"[self-check] step {step_num}: all {n_checks} "
                          f"check(s) pass after {rnd} fix round(s)")
            return result, history
        remaining = max_rounds - rnd - 1
        log_print(f"[self-check] step {step_num} round {rnd+1}/{max_rounds}: "
                  f"{len(failed)} failed check(s), {len(problems)} contract "
                  f"problem(s) — sending it back")
        logger.log_event({"type": "self_check", "step": step_num,
                          "round": rnd + 1, "failed": [n for n, _ in failed],
                          "problems": problems})

        bits = []
        if failed:
            bits.append(
                "Your own verdicts say this step is not done:\n"
                + "\n".join(f"  - check {n}: FAIL — {e}" for n, e in failed)
                + "\n\nFix these. Rewrite the action that produced each problem "
                  "(same filename — the harness rewinds and replays, so the fix "
                  "replaces that action). "
                  'Add a `# REDO N:` line above the existing header and KEEP every comment already in the file — the rewind replaces the geometry, not the record of what you already tried. '
                  "Then re-verify it and report the "
                  "checks again. Measure or crop in to confirm the fix actually "
                  "landed; do not assume it did."
            )
        if problems:
            bits.append(
                "Problems with your result JSON:\n"
                + "\n".join(f"  - {p}" for p in problems)
                + "\n\nRe-emit the full JSON block in the required shape."
            )
        bits.append(f"You have {remaining} more fix round(s) after this one."
                    if remaining else
                    "This is your LAST round — fix what you can, then emit your "
                    "final JSON with honest verdicts. Anything still failing "
                    "goes in `anomalies` with `\"pass\": false`.")

        r = turn("\n\n".join(bits), history)
        history = r["messages"]
        new = _extract_result_json(r.get("final_response", ""))
        if new:
            result = new

    failed, problems = _check_problems(result, n_checks)
    if failed or problems:
        log_print(f"[self-check] step {step_num}: exhausted {max_rounds} fix "
                  f"round(s) with {len(failed)} check(s) still failing")
        logger.log_event({"type": "self_check_exhausted", "step": step_num,
                          "failed": [n for n, _ in failed],
                          "problems": problems})
        if failed:
            result["pass"] = False
            anom = result.get("anomalies")
            result["anomalies"] = (anom if isinstance(anom, list) else []) + [
                f"self-check {n} still failing: {e}" for n, e in failed]
    return result, history


def run_step_subagent_with_review(
    *,
    initial_prompt: str,
    system_prompt: str,
    step_num: int,
    run_name: str,
    step_spec: dict,
    all_steps: list[dict],
    completed_step_nums: list[int],
    prior_step_summaries: list[str],
    ref_image: Path,
    image_relpath: str | None,
    plan_text: str,
    logger: RolloutLogger,
    usage: UsageAggregate,
    action_budget: int,
    retry_budget: int,
    no_reviews: bool = False,
    next_goal: str | None = None,
) -> dict:
    from run_agent import AIAgent
    from agent.image_routing import build_native_content_parts

    tag = f"Sub#{step_num:03d}"
    step_dir     = step_dir_for(run_name, step_num)
    front_render = step_dir / "review" / "review_front.png"
    persp_render = step_dir / "review" / "review_persp.png"

    CURRENT_ACTION_CONTEXT["run_name"] = run_name
    CURRENT_ACTION_CONTEXT["step_dir"] = step_dir

    subagent_kwargs = dict(
        provider=MODELS["executor"]["provider"],
        model=MODELS["executor"]["model"],
        api_key=api_key_for(MODELS["executor"]["provider"]),
        base_url=base_url_for(MODELS["executor"]["provider"]),
        quiet_mode=True,
        # One call for the whole geometry-work phase (many internal
        # write_and_run tool calls) and one more per review round.
        #
        # 60, not max(30, action_budget*2). This ceiling is not an action
        # budget — it counts every LLM round-trip in the step, so looking at
        # something costs the same as building something. At 30 the subagent
        # was running out of room to inspect its own work: bat_gptluna_med5
        # step 1 spent 26 of 30 iterations on a step that only committed 12
        # actions, i.e. more than half its budget went on perception and it
        # still stopped after one verification pass. Hitting the ceiling ends
        # the turn before the result JSON, which is what triggers the "ended
        # without JSON" nudge path. Checking your work has to be affordable
        # for the agent to do it, so the ceiling is now well clear of any
        # plausible action count.
        max_iterations=max(60, action_budget * 3),
        ephemeral_system_prompt=system_prompt,
        # "blendcua" alone (write_and_run only) left the subagent unable to
        # read a file or run a command, which the reference docs actively
        # tell it to do ("use Bash/a scratch script with PIL/bmesh/numpy" in
        # the plan; the crop-and-zoom / pixel-scan diagnostics table). With
        # no way to comply it did those jobs as BLENDER ACTIONS instead —
        # step_004's 16_read_wing_plan / 17_read_wing_steps /
        # 18_extract_wing_procedure exist only to read text files, and
        # step_005's 09_correct_photo_uv ran a 60k-sample image scan inside
        # Blender and froze the whole session. Both classes of work belong
        # in a separate process.
        #
        # Those jobs are now served by read_project_file / search_project /
        # run_python, which live in our own plugin alongside write_and_run and
        # so are all in the "blendcua" toolset. Hermes' own `file`, `terminal`
        # and `code_execution` toolsets are deliberately NOT enabled: they all
        # route through terminal_tool's environment machinery, whose Git Bash
        # spawn never returns inside the MCP dispatch subprocess and hung
        # bat_newplan_001 for the full 420s tool timeout without running a
        # single action. See the plugin's own comment for the evidence.
        #   blendcua -> write_and_run, read_project_file, search_project, run_python
        #   todo     -> todo (plan tracking across a 30-action step)
        # NOTE: this list is TOOLSET names, not tool names — see the note on
        # the Executor's disabled_toolsets in blendcua_agent.py.
        #   blendcua    -> write_and_run (the one domain primitive)
        #   blendcua_fs -> read, write, edit, glob, grep, bash
        #   todo        -> todo (plan tracking across a long step)
        # blendcua_fs is deliberately the Claude Code surface, name for name.
        # Hermes' own `file`, `terminal` and `code_execution` stay off: they all
        # route through terminal_tool's persistent login-shell environment,
        # which never finishes starting inside the MCP dispatch subprocess (see
        # the plugin's bash comment for the evidence).
        enabled_toolsets=["blendcua", "blendcua_fs", "todo"],
    )
    if MODELS["executor"]["provider"] == "openai":
        subagent_kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}
    subagent = AIAgent(**subagent_kwargs)

    def _turn(user_message, history):
        since = len(history)
        _t0 = time.time()
        r = subagent.run_conversation(user_message, conversation_history=history)
        wall_s = time.time() - _t0
        usage.log_conversation_result(r, tag=tag, wall_s=wall_s)
        calls = _tool_call_summaries(r.get("messages") or [], since)
        logger.log_step_trace(step_num, {
            "type": "turn", "wall_s": round(wall_s, 2),
            "final_response": r.get("final_response"),
            "input_tokens": r.get("input_tokens"), "output_tokens": r.get("output_tokens"),
            "cache_read_tokens": r.get("cache_read_tokens"),
            "cache_write_tokens": r.get("cache_write_tokens"),
            "reasoning_tokens": r.get("reasoning_tokens"),
            "estimated_cost_usd": r.get("estimated_cost_usd"),
            "api_calls": r.get("api_calls"), "tool_calls": calls,
        })
        for i, c in enumerate(calls, 1):
            log_print(f"[{tag}]   {i:>3}. {c}")
        log_print(f"\n[{tag}] {r.get('final_response', '')}")
        return r

    # ── Phase 1: geometry work — one continuous call ────────────────────────
    history: list[dict] = []
    if ref_image is not None and Path(ref_image).is_file():
        first_message, _skipped = build_native_content_parts(
            initial_prompt, image_paths=[str(ref_image)]
        )
    else:
        first_message = initial_prompt
    r = _turn(first_message, history)
    history = r["messages"]
    result = _extract_result_json(r.get("final_response", ""))

    # A dropped connection (or hitting max_iterations) can end the turn
    # before the model output its JSON — nudge it to finish rather than
    # reviewing half-done work.
    for recover in range(2):
        if result:
            break
        log_print(f"[dispatch_step] step {step_num} — subagent ended without "
              f"JSON, asking it to finish ({recover+1}/2)")
        r = _turn(
            "Your previous response ended without the required JSON block. "
            "If the step's geometry work is complete, output your JSON now. "
            "If actions remain, finish them first, then output the JSON.",
            history,
        )
        history = r["messages"]
        result = _extract_result_json(r.get("final_response", ""))

    logger.log_event({
        "type": "subagent_return", "step": step_num,
        "notes": result.get("notes", ""), "actions_taken": result.get("actions_taken", 0),
    })

    # ── Phase 2: review loop (skipped entirely under --no-reviews) ───────────
    #
    # The review loop is where most of a run's spend lives: on
    # bat_gpt56luna_med4 the reviewer made 231 of the 413 successful API calls
    # and 160 of the 257 Blender script runs, and every reviewed step also
    # cost the subagent an extra injection turn per round on top of its
    # already-large context. --no-reviews cuts all of that.
    #
    # The review RENDER is still produced (it costs no tokens — one Blender
    # dispatch) so the run still leaves review_front.png / review_persp.png
    # behind for a human to look at afterwards. That matters more, not less,
    # when no model is checking the work.
    if no_reviews:
        result, history = _enforce_self_checks(
            result=result, history=history, turn=_turn, step_spec=step_spec,
            step_num=step_num, max_rounds=max(1, retry_budget), logger=logger,
        )
        result["_handover"] = _write_handover(
            turn=_turn, history=history, step_num=step_num,
            goal=step_spec["goal"], next_goal=next_goal,
            run_name=run_name, logger=logger,
        )
        render_ok, render_err = _render_review_images(run_name, step_num, step_dir)
        if render_ok:
            log_print(f"[dispatch_step] step {step_num} — reviews disabled; "
                      f"render saved for inspection, skipping reviewer")
        else:
            log_print(f"[dispatch_step] step {step_num} — reviews disabled; "
                      f"record render failed ({render_err}) — continuing anyway")
        logger.log_event({"type": "reviewer_disabled", "step": step_num,
                          "render_ok": bool(render_ok)})
        return result

    last_verdict = None
    for attempt in range(retry_budget + 1):
        log_print(f"\n[dispatch_step] step {step_num} — review round {attempt+1}/{retry_budget+1}")

        render_ok, render_err = _render_review_images(run_name, step_num, step_dir)
        if not render_ok:
            log_print(f"[Reviewer] render failed — {render_err}")
            logger.log_event({"type": "reviewer_skip", "step": step_num,
                              "attempt": attempt + 1, "reason": render_err})
            if attempt >= retry_budget:
                break
            r = _turn(
                f"Review render failed: {render_err}. Ensure geometry was "
                "committed to the scene, then output your final result JSON.",
                history,
            )
            history = r["messages"]
            result = _extract_result_json(r.get("final_response", "")) or result
            continue

        verdict, _reason, full_review = run_agentic_reviewer(
            step_spec=step_spec, all_steps=all_steps,
            completed_step_nums=completed_step_nums,
            prior_step_summaries=prior_step_summaries,
            subagent_notes=str(result.get("notes", "") or ""),
            ref_image=ref_image, front_render=front_render, persp_render=persp_render,
            plan_text=plan_text, run_name=run_name, step_num=step_num, step_dir=step_dir,
            round_num=attempt + 1, usage=usage,
        )

        last_verdict = verdict
        review_path = logger.write_review(step_num, attempt + 1, full_review)
        log_print(f"[Reviewer] step {step_num} round {attempt+1}: logged to "
              f"{rel_to(review_path, AGENT_DIR)}")
        # Both keys on purpose: consumers were reading `round`, which never
        # existed here, so every reviewer event parsed as round=None and
        # rollout.jsonl read as though no step was ever reviewed twice.
        rounds_used = attempt + 1
        logger.log_event({"type": "reviewer", "step": step_num,
                          "attempt": rounds_used, "round": rounds_used,
                          "verdict": verdict})

        remaining = retry_budget - attempt
        if verdict == "UNKNOWN":
            injection = (
                "The visual reviewer could not be reached this round (API "
                "errors), so no feedback is available. Output your final "
                "result JSON now with \"pass\": true — do not investigate."
            )
        elif verdict == "PASS":
            injection = (
                f"The visual reviewer is satisfied — this step is done:\n\n"
                f"{full_review}\n\n"
                f"Output your final result JSON now with \"pass\": true. Do "
                f"not call write_and_run again and do not investigate further."
            )
        elif remaining > 0:
            injection = (
                f"Here is the visual reviewer's analysis of your renders:\n\n"
                f"{full_review}\n\n"
                f"The reviewer is NOT satisfied. Fix what it named — rewrite "
                f"the action that produced the problem (same filename; the "
                f"harness rewinds for you) rather than adding a corrective "
                f"action. " 'Add a `# REDO N:` line above the existing header and KEEP every comment already in the file — the rewind replaces the geometry, not the record of what you already tried. ' f"Then output your result JSON.\n"
                f"Your fix WILL BE RE-RENDERED AND RE-REVIEWED. Setting "
                f"\"pass\": true does not end the step, so do not claim the "
                f"issue is resolved unless you have actually looked at a "
                f"render showing it resolved. Measure rather than assume: "
                f"write a script into this step's scripts/ folder that crops "
                f"and zooms to the part in question, `bash` it, and look at "
                f"what comes back. That is the only way to know whether your "
                f"change went far enough — and you can re-run the same script "
                f"after the next fix.\n"
                f"You have {remaining} more review round(s) available."
            )
        else:
            # Last round, reviewer still unsatisfied. Spend it on a fix rather
            # than on a shrug: the subagent gets one corrective pass that will
            # NOT be re-reviewed, then the step closes. Under --retry-budget 0
            # this is the whole "review once, fix once, move on" contract.
            #
            # Telling it to fix and telling it to self-certify are different
            # things — it emits "pass": true because the loop needs a result
            # JSON, but the step's status comes from `last_verdict` below, so
            # an unverified fix cannot launder itself into PASS.
            injection = (
                f"Here is the visual reviewer's analysis of your renders — "
                f"this was the LAST review round, so your fix will NOT be "
                f"re-reviewed:\n\n{full_review}\n\n"
                f"Make one corrective pass now on what it named. Rewrite the "
                f"action that produced the problem (same filename; the harness "
                f"rewinds for you) rather than adding a corrective action. " 'Add a `# REDO N:` line above the existing header and KEEP every comment already in the file — the rewind replaces the geometry, not the record of what you already tried. ' f"Then "
                f"look at the resulting render to confirm the change actually "
                f"landed, then output your final result JSON with "
                f"\"pass\": true and put anything still unresolved in "
                f"\"anomalies\" so the next step inherits it.\n"
                f"If the reviewer's point is one you have already verified is "
                f"wrong, change nothing and say so in \"notes\"."
            )

        r = _turn(injection, history)
        history = r["messages"]
        new_result = _extract_result_json(r.get("final_response", ""))
        if new_result:
            result = new_result

        # The REVIEWER decides when the step is done, not the subagent.
        #
        # This used to break on the subagent's own `"pass": true`, which the
        # injection above had just told it to emit after fixing — so a
        # TRY_AGAIN was always followed by exactly one unverified edit and the
        # step was recorded PASS. Step 1 of bat_newplan_001 did precisely
        # that: the reviewer failed the head silhouette, the subagent changed
        # one ring scale, self-certified, and the run stored PASS with the
        # muzzle still ~3x too wide. The retry budget existed but could never
        # be reached.
        #
        # Now only a PASS verdict (or exhausting the rounds) ends the loop; a
        # fix always gets re-rendered and re-reviewed.
        if verdict == "PASS":
            break
        if verdict == "UNKNOWN" and result.get("pass") is True:
            break   # reviewer unreachable — nothing to re-verify against

    # The reviewer's last word, carried out for the status decision. Without it
    # the caller can only see the subagent's own "pass", which the final-round
    # injection asks for unconditionally — so a step that ended on a TRY_AGAIN
    # would report PASS. None means no verdict was ever obtained (render
    # failure), which is treated the same as UNKNOWN: fall back to self-report.
    result["_final_verdict"] = last_verdict

    # Same handover as the --no-reviews path, written after the review loop so
    # it describes the scene as finally left, including anything the reviewer
    # sent back for a fix.
    result["_handover"] = _write_handover(
        turn=_turn, history=history, step_num=step_num,
        goal=step_spec["goal"], next_goal=next_goal,
        run_name=run_name, logger=logger,
    )
    return result


def do_dispatch_step(
    *,
    step_spec: dict,
    run_name: str,
    all_steps: list[dict],
    completed_step_nums: list[int],
    prior_step_summaries: list[str],
    reference_docs: str,
    image_relpath: str | None,
    ref_image: Path | None,
    system_prompt: str,
    plan_text: str,
    logger: RolloutLogger,
    usage: UsageAggregate,
    action_budget: int,
    retry_budget: int,
    no_reviews: bool = False,
    prior_handover: str = "",
    task_relpath: str | None = None,
) -> dict:
    """One plan step end-to-end. Ported from BlendCuagent2's _do_dispatch_step.

    The returned dict carries `_handover` — this step's rolling summary, for
    the caller to hold and pass into the next step as `prior_handover`. It is
    private: the caller strips it before the result goes back to the Executor,
    which has no use for tens of thousands of characters about a scene it never
    touches.
    """
    step_num = step_spec["step_number"]

    logger.log_event({
        "type": "step_start", "step": step_num,
        "goal": step_spec["goal"], "checks": step_spec["review_checks"],
    })
    log_print("\n" + "=" * 60)
    log_print(f"[dispatch_step] step {step_num} — {step_spec['goal']}"
              + ("  [no reviews]" if no_reviews else ""))
    log_print("=" * 60)

    if prior_handover:
        log_print(f"[handover] step {step_num}: inheriting "
                  f"{len(prior_handover):,} chars (~{len(prior_handover)//4:,} "
                  f"tokens) from the previous step")

    prompt = build_subagent_prompt(
        run_name=run_name, step_spec=step_spec,
        prior_step_summaries=prior_step_summaries,
        image_relpath=image_relpath, action_budget=action_budget,
        no_reviews=no_reviews, prior_handover=prior_handover,
        task_relpath=task_relpath,
    )
    sub_system_prompt = (
        system_prompt
        + "\n\n# Reference documentation (tools, conventions, examples)\n\n"
        + reference_docs
        + "\n\n---\n\n"
        + load_skills_index("Executor", "Scripting")
    )

    # What the NEXT subagent will be doing — lets the handover be written for a
    # known audience ("the next one places the legs") rather than in a vacuum.
    later = [s for s in all_steps if s["step_number"] > step_num]
    next_goal = later[0]["goal"] if later else None

    result = run_step_subagent_with_review(
        initial_prompt=prompt, system_prompt=sub_system_prompt,
        step_num=step_num, run_name=run_name, step_spec=step_spec,
        all_steps=all_steps, completed_step_nums=completed_step_nums,
        prior_step_summaries=prior_step_summaries, ref_image=ref_image,
        image_relpath=image_relpath, plan_text=plan_text,
        logger=logger, usage=usage, action_budget=action_budget,
        retry_budget=retry_budget, no_reviews=no_reviews, next_goal=next_goal,
    )
    handover = str(result.pop("_handover", "") or "")
    final_verdict = result.pop("_final_verdict", None)

    notes = str(result.get("notes", "") or "")
    actions = int(result.get("actions_taken", 0) or 0)
    anom = result.get("anomalies", []) or []
    anomalies = [str(x) for x in anom] if isinstance(anom, list) else [str(anom)]
    passed = result.get("pass") is True

    # The reviewer outranks the subagent's self-report. The final-round
    # injection asks for "pass": true so the loop gets a well-formed result
    # JSON out of the corrective pass — that request must not turn a step the
    # reviewer never approved into a PASS. Only a real PASS verdict (or no
    # verdict at all, i.e. the reviewer was unreachable) leaves `passed` alone.
    if final_verdict is not None and final_verdict not in ("PASS", "UNKNOWN"):
        passed = False

    # --no-reviews: nothing independent verified this step, so do not launder
    # the subagent's self-report into the same "PASS" the reviewed path emits.
    # UNREVIEWED says exactly what happened; NO_RESULT means the subagent
    # never produced its JSON at all (on bat_gpt56luna_med4 that happened on
    # 3 of 5 steps and was silently recorded as PASS).
    if no_reviews:
        if not result:
            status = "NO_RESULT"
        elif passed:
            status = "UNREVIEWED"
        else:
            status = "UNREVIEWED_FAILED_SELF_CHECK"
        out = {
            "status": status,
            "actions_taken": actions,
            "notes": notes,
            "anomalies": anomalies,
            "reviewer_verdict": "SKIPPED (--no-reviews)",
            "attempts": 1,
            "next": (
                "Reviews are disabled for this run. UNREVIEWED is the normal "
                "success status — it means the subagent finished and "
                "self-certified, with no independent check. Continue to the "
                "next step regardless of status; never re-dispatch a step and "
                "never end the run early."
            ),
            "_handover": handover,
        }
        return out

    # Report exhaustion honestly. This used to return "PASS" unconditionally,
    # so a step that burned every review round without satisfying the reviewer
    # was indistinguishable from one that passed cleanly — both in the run log
    # and in the context handed to later steps. But EXHAUSTED must NOT stop the
    # build: an unsatisfiable check (step 2 of bat_gpt56luna_med3 spent three
    # rounds on an ear check the template geometry made impossible) should cost
    # its rounds and then let the run move on.
    # Freeze the scene so a rewind in a LATER step does not have to re-execute
    # this one. Saved whatever the verdict: an EXHAUSTED step still leaves the
    # geometry a later step builds on. Costs ~0.3s; see save_step_checkpoint.
    save_step_checkpoint(run_name, step_num)

    out = {
        "status": "PASS" if passed else "EXHAUSTED",
        "actions_taken": actions,
        "notes": notes,
        "anomalies": anomalies,
        "reviewer_verdict": "PASS" if passed else "EXHAUSTED",
        # Was hardcoded 1, so rollout.jsonl claimed every step passed first
        # time even when it took two rounds. `rounds_used` is set in the review
        # loop above; fall back to 1 only if the loop never ran.
        "attempts": locals().get("rounds_used", 1),
    }
    if not passed:
        out["next"] = (
            "EXHAUSTED means the review rounds ran out, not that the build is "
            "unusable. CONTINUE to the next step — do not retry this one and "
            "do not stop the run. Carry the unresolved point forward as a note."
        )
    out["_handover"] = handover
    return out


def write_store_baseline(run_name: str) -> dict:
    """Freeze the tool/skill listing at the moment a run starts.

    Cheap — names and mtimes, not contents — because its only job is to let the
    curator afterwards say "this file did not exist when the build began", which
    is the difference between the builder's own work and someone else's.
    """
    tools_code = AGENT_DIR / "Tool_scripts" / "Tools_code"
    skills = AGENT_DIR / "Skills"
    base = {
        "run": run_name,
        "recorded": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tools": sorted(p.name for p in tools_code.glob("*.py")),
        "skills": sorted(str(p.relative_to(skills)).replace("\\", "/")
                         for p in skills.rglob("*.md")),
    }
    out = MEM_DIR / run_name / "store_baseline.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(base, indent=2), encoding="utf-8")
    return base
