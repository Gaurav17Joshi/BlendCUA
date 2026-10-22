"""B2's per-task agent when the model is Claude, driven by the Claude Code harness.

    python agent_claude.py --task-dir tasks/test/t01_alien_lizard \
        --run-dir runs_claude/t01_alien_lizard_run_001 --worker 0 --freeze

Same baseline, different driver. The OpenAI/OpenRouter bake-off entrants run
inside agent.py's own conversation loop; Claude runs inside Claude Code, which
is its native harness and bills the account's subscription rather than tokens.
What does NOT change: the Blender session, the seven tools, the system prompt,
the skill library and retrieval, the one review round, the deliverable and every
artefact written under the run folder. Claude Code reaches all of it through
b2_mcp_server.py, which forwards each tool call to this process, where the same
Agent.dispatch() the other entrants use executes it.

    claude.exe -p --mcp-config ...        the builder ("build" toolset)
      -> b2_mcp_server.py  --RPC-->  this process  ->  Blender / host / library
    first finish  ->  a second claude.exe ("review" toolset)  ->  review text
                      returned as that finish call's result, then one more pass.

Budget: there are no dollars to cap, so the caps are wall-clock and tool calls
(b2_config), and a usage-limit reply is waited out and the session resumed
rather than counted as a failure.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import b2_config as CFG
import library as L
import llm
import retrieval
from agent import Agent, jdump

CLAUDE = CFG.PROFILE.get("exe") or os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"


def limit_wait_seconds(text: str) -> float | None:
    """Seconds to wait if `text` says a Claude subscription limit was hit.

    Handles both an epoch ("...limit reached|1774081800") and a wall-clock
    reset ("...resets 3:30am (America/Los_Angeles)"). Returns None if `text`
    is not about a limit at all.
    """
    m = USAGE_LIMIT_RE.search(text or "")
    if not m:
        return None
    if m.group("epoch"):
        ts = int(m.group("epoch"))
        if ts > 1e11:
            ts /= 1000.0
        return max(60.0, ts - time.time() + 60)
    if m.group("clock"):
        from datetime import datetime, timedelta
        hour = int(m.group("clock")) % 12
        if (m.group("ampm") or "").lower() == "pm":
            hour += 12
        minute = int(m.group("min") or 0)
        now = datetime.now()
        tz = m.group("tz")
        if tz:
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(tz))
            except Exception:  # noqa: BLE001
                pass
        reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if reset <= now:
            reset += timedelta(days=1)
        return max(60.0, (reset - now).total_seconds() + 120)
    return 1800.0
# Claude Code says so in more than one way: "Claude AI usage limit reached|<epoch>"
# for the plan limit, and "You've hit your session limit · resets 3:30am
# (America/Los_Angeles)" for the rolling 5-hour one. Both come back as an
# ordinary result with rc=1, so they must be recognised by their text or the
# run burns through every remaining task in seconds.
USAGE_LIMIT_RE = re.compile(
    r"(?:usage|session|rate) limit(?: reached)?\s*(?:\|\s*(?P<epoch>\d{9,13}))?"
    r"(?:[^\"\\]{0,40}?resets?\s+(?P<clock>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ampm>am|pm)?"
    r"[^\"\\]{0,30}?(?:\((?P<tz>[A-Za-z_/]+)\))?)?", re.I)

# A server-side wobble at Anthropic ("API Error: 529 Overloaded", 500, 503...)
# also ends the session with rc=1, but unlike a usage limit it clears in
# minutes. It must not be treated as the model giving up: without this, three
# nudges are spent inside ten minutes and the task is lost mid-build.
TRANSIENT_API_RE = re.compile(
    r"API Error:\s*(?:429|5\d\d)\b|\bOverloaded\b|\bInternal server error\b"
    r"|\bService Unavailable\b|\bBad Gateway\b|\bGateway Time-?out\b", re.I)


# ── usage accounting ─────────────────────────────────────────────────────────

class ClaudeUsage:
    """Same shape as llm.Usage, filled from Claude Code's result messages.

    `cost` is the list-price equivalent Claude Code reports; nothing is billed
    per token, the run draws on the account's subscription. Kept so the
    bake-off table has one comparable column.
    """

    def __init__(self):
        self.calls = 0            # model turns, from num_turns
        self.sessions = 0         # claude.exe invocations
        self.input = 0
        self.cached = 0
        self.output = 0
        self.reasoning = 0
        self.peak_input = 0
        self.api_seconds = 0.0
        self._cost = 0.0

    def add_result(self, msg: dict, seconds: float = 0.0) -> float:
        u = msg.get("usage") or {}
        cost = float(msg.get("total_cost_usd") or 0.0)
        self.sessions += 1
        self.calls += int(msg.get("num_turns") or 0)
        self.api_seconds += seconds
        cached = int(u.get("cache_read_input_tokens") or 0)
        created = int(u.get("cache_creation_input_tokens") or 0)
        inp = int(u.get("input_tokens") or 0) + cached + created
        out = int(u.get("output_tokens") or 0)
        det = u.get("output_tokens_details") or {}
        self.input += inp
        self.cached += cached
        self.output += out
        self.reasoning += int(det.get("thinking_tokens") or 0)
        self.peak_input = max(self.peak_input, inp)
        self._cost += cost
        return cost

    @property
    def cost(self) -> float:
        return self._cost

    def as_dict(self) -> dict:
        return {"api_calls": self.calls, "claude_sessions": self.sessions,
                "input_tokens": self.input, "cached_input_tokens": self.cached,
                "output_tokens": self.output, "reasoning_tokens": self.reasoning,
                "peak_input_tokens": self.peak_input, "api_seconds": round(self.api_seconds, 1),
                "cost_usd": round(self.cost, 4),
                "billing": "Claude subscription (cost_usd is the list-price equivalent "
                           "Claude Code reports, not money spent)"}


# ── the tool RPC server b2_mcp_server.py talks to ────────────────────────────

class _RPCHandler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.settimeout(None)
        head = b""
        while len(head) < 8:
            chunk = sock.recv(8 - len(head))
            if not chunk:
                return
            head += chunk
        (n,) = struct.unpack(">Q", head)
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(min(65536, n - len(buf)))
            if not chunk:
                return
            buf += chunk
        try:
            req = json.loads(buf.decode("utf-8"))
            reply = self.server.agent.serve_tool(req.get("tool", ""), req.get("args") or {})
        except Exception as e:  # noqa: BLE001
            reply = {"text": f"harness error: {type(e).__name__}: {e}\n"
                             f"{traceback.format_exc()[-1200:]}", "is_error": True}
        data = json.dumps(reply).encode("utf-8")
        sock.sendall(struct.pack(">Q", len(data)) + data)


class _RPCServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ── the agent ────────────────────────────────────────────────────────────────

class ClaudeAgent(Agent):
    def __init__(self, task_dir: Path, run_dir: Path, worker: int, freeze: bool):
        super().__init__(task_dir, run_dir, worker, freeze)
        self.usage = ClaudeUsage()
        self.aux_usage = ClaudeUsage()      # retrieval
        self.review_usage = ClaudeUsage()
        self.tool_lock = threading.RLock()  # one tool at a time touches Blender
        self.rpc_port = CFG.WORKERS[worker]["rpc_port"]
        self.server: _RPCServer | None = None
        self.stop_flag = False              # hard cap hit: kill the session
        self.pending_note: list[str] = []   # harness notes to attach to the next result
        self.review_submitted: str | None = None
        self.builder_session: str | None = None
        self.waits = 0                      # usage-limit waits
        self.api_retries = 0                # transient API-error backoffs
        self.procs: list = []               # live claude.exe processes

    # ── RPC entry: one tool call from Claude Code ────────────────────────
    def serve_tool(self, name: str, args: dict) -> dict:
        if name == "submit_review":
            self.review_submitted = args.get("review", "")
            return {"text": "Review submitted. Thank you -- your turn is over."}

        if self.role == "review":
            self.review_calls += 1
            if self.review_calls > CFG.REVIEW_MAX_CALLS:
                return {"text": "[harness] Review budget used up. Call submit_review now with "
                                "the review you have."}
        else:
            over = self.over_cap()
            if over and name != "finish":
                self.stop_flag = True
                self.end_reason = over
                return {"text": f"[harness] {over}. Stop work now: the scene as it stands is "
                                "being saved as the deliverable."}

        if name == "finish":
            # Never under the lock: the reviewer's own tool calls run inside this call.
            text, imgs = self.dispatch(name, args)
        else:
            with self.tool_lock:
                text, imgs = self.dispatch(name, args)

        if self.pending_note and self.role == "build":
            text += "\n\n" + "\n".join(self.pending_note)
            self.pending_note = []
        out = {"text": text, "images": []}
        for p in imgs:
            try:
                out["images"].append(self.image_payload(p))
            except Exception as e:  # noqa: BLE001
                out["text"] += f"\n(could not encode {p}: {type(e).__name__}: {e})"
        return out

    @staticmethod
    def image_payload(p: Path) -> dict:
        part = llm.image_part(p)                       # data:<mime>;base64,<...>
        mime, b64 = part["image_url"][5:].split(";base64,", 1)
        return {"data": b64, "mime": mime}

    def over_cap(self) -> str | None:
        mins, calls = self.minutes(), sum(self.tool_counts.values())
        if mins >= CFG.HARD_WALL_MIN:
            return f"hard cap ({mins:.0f} min elapsed)"
        if calls >= CFG.MAX_TOOL_CALLS:
            return f"hard cap ({calls} tool calls)"
        return None

    def soft_check(self) -> None:
        mins = self.minutes()
        if not self.warned_soft and mins >= CFG.SOFT_WALL_MIN:
            self.warned_soft = True
            self.pending_note.append(
                f"[harness] Budget notice: {mins:.0f} minutes elapsed. The run stops at "
                f"{CFG.HARD_WALL_MIN} minutes. Wrap up: get the scene into its best finished "
                "state and call finish.")

    # ── prompt ───────────────────────────────────────────────────────────
    def build_prompt_text(self) -> tuple[str, str]:
        """(system prompt appended to Claude Code's, first user message).

        Identical in content to agent.build_prompt(); the reference images are
        not inlined here -- Claude is told to open them with view_image, which
        hands it the very same downscaled plates the other entrants are sent.
        """
        task_text = (self.task_dir / "task.md").read_text(encoding="utf-8")
        index = {} if CFG.NO_LIBRARY else L.copy_library(self.skills_dir)
        refs = self.reference_images()
        L.log("task_start", task=self.task, run=self.run, library_size=len(index),
              frozen=self.freeze, no_library=CFG.NO_LIBRARY)
        picked, reason = [], "no library (ablation)" if CFG.NO_LIBRARY else "library empty"
        if index:
            # A limit hit during retrieval must not silently yield an empty
            # pick: that would quietly turn a library run into a no-library one.
            for _ in range(CFG.MAX_USAGE_WAITS + 1):
                picked, reason = retrieval.select(self.task, task_text, refs[0] if refs else None,
                                                  index, usage=self.aux_usage, log=self.log)
                wait = limit_wait_seconds(reason) if not picked else None
                if wait is None:
                    break
                self.waits += 1
                self.log(f"retrieval hit a subscription limit; waiting {wait / 60:.0f} min")
                self.event("usage_limit", where="retrieval", seconds=round(wait))
                self.t0 += wait
                time.sleep(wait)
        for n in picked:
            L.log("retrieve", task=self.task, run=self.run, skill=n)
        self.log(f"library {len(index)} skills; retrieved {picked} ({reason[:200]})")
        self.library_size = len(index)
        self.retrieved = picked
        self.library_names = sorted(index)
        self.event("retrieval", library_size=len(index), selected=picked, reason=reason)

        tmpl = (CFG.ROOT / "prompts" / "system.md").read_text(encoding="utf-8")
        system = tmpl.format(
            blender_version=self.blender_version, default_timeout=CFG.DEFAULT_EXEC_TIMEOUT_S,
            max_timeout=CFG.MAX_EXEC_TIMEOUT_S, **L.prompt_blocks(index, picked),
            task_dir=str(self.task_dir), work_dir=str(self.work), typical_min=60,
            soft_cost=CFG.SOFT_COST_USD, soft_wall=CFG.SOFT_WALL_MIN,
            hard_cost=CFG.HARD_COST_USD, hard_wall=CFG.HARD_WALL_MIN)
        system += (
            "\n\n## This session\n\n"
            "Every tool above is an `mcp__b2__*` tool and they are the only tools you have: "
            "there is no file editing, no shell and no web. Read and write files with "
            "`host_python`, and look at images with `view_image`. Do not ask for permission or "
            "for confirmation -- nobody is watching this session; just do the work and finish. "
            "Keep going until the scene is done: a turn that ends without a tool call is a "
            "turn wasted.")

        text = [f"# Task: {self.task}\n\n{task_text.strip()}\n",
                "Reference images -- open every one of them with `view_image` before you start:\n" +
                "\n".join(f"- {p}" for p in refs)]
        extra = [p for p in self.task_dir.iterdir() if p.is_file()
                 and p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} and p.name != "task.md"]
        if extra:
            text.append("Other task files: " + ", ".join(str(p) for p in extra))
        for n in picked:
            t = L.skill_text(n, self.skills_dir)
            if t:
                text.append(t)
        text.append("Begin: look at the references, then build the scene.")
        return system, "\n\n".join(text)

    # ── driving claude.exe ───────────────────────────────────────────────
    def mcp_config(self, toolset: str) -> str:
        return json.dumps({"mcpServers": {"b2": {
            "type": "stdio", "command": CFG.PY,
            "args": [str(CFG.ROOT / "b2_mcp_server.py")],
            "env": {"B2_RPC_PORT": str(self.rpc_port), "B2_TOOLSET": toolset,
                    "B2_NO_LIBRARY": "1" if CFG.NO_LIBRARY else "",
                    "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONIOENCODING": "utf-8"}}}})

    def child_env(self) -> dict:
        """A clean environment: no inherited Claude Code session, and no API key
        (an ANTHROPIC_API_KEY would silently bill the API instead of the plan)."""
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDE_CODE_", "ANTHROPIC_"))}
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_EFFORT", None)
        env.update(MCP_TOOL_TIMEOUT=str(CFG.MCP_TOOL_TIMEOUT_MS), MCP_TIMEOUT="120000",
                   PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        return env

    def claude_argv(self, system_file: Path, toolset: str, session: str | None,
                    resume: bool) -> list[str]:
        """No prompt and no system text on the command line: Windows caps a
        command line at 32K and both run well past it once the retrieved skills
        are in. The prompt goes in on stdin, the system prompt as a file."""
        argv = [CLAUDE, "-p",
                "--output-format", "stream-json", "--verbose",
                "--model", CFG.MODEL, "--effort", CFG.REASONING_EFFORT,
                "--mcp-config", self.mcp_config(toolset), "--strict-mcp-config",
                "--tools", "",                       # no built-in tools: only B2's
                "--permission-mode", "bypassPermissions",
                "--permission-prompts", "none",
                "--append-system-prompt-file", str(system_file)]
        if resume:
            argv += ["--resume", session]
        elif session:
            argv += ["--session-id", session]
        return argv

    def run_claude(self, *, prompt: str, system: str, toolset: str, role: str,
                   usage: ClaudeUsage, session: str | None = None,
                   resume: bool = False) -> dict:
        """One claude.exe invocation, streamed. Returns its result message."""
        sys_file = self.run_dir / f"system_{role}.md"
        sys_file.write_text(system, encoding="utf-8")
        argv = self.claude_argv(sys_file, toolset, session, resume)
        (self.run_dir / f"claude_argv_{role}.json").write_text(
            jdump([a if len(a) < 400 else a[:400] + "..." for a in argv]), encoding="utf-8")
        (self.run_dir / f"prompt_{role}_{usage.sessions}.txt").write_text(prompt, encoding="utf-8")
        t0 = time.time()
        proc = subprocess.Popen(argv, cwd=str(self.work), env=self.child_env(),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", bufsize=1)
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except OSError as e:
            self.log(f"[claude/{role}] could not send the prompt: {e}")
        self.procs.append(proc)
        result: dict = {}
        killer = None
        if self.stop_flag:
            self.kill(proc)

        def watchdog():
            while proc.poll() is None:
                if self.stop_flag:
                    self.kill(proc)
                    return
                if role == "review" and (time.time() - t0) / 60 > CFG.REVIEW_WALL_MIN:
                    self.log("reviewer over its wall-clock cap; stopping it")
                    self.kill(proc)
                    return
                self.soft_check()
                time.sleep(5)

        killer = threading.Thread(target=watchdog, daemon=True)
        killer.start()
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.log(f"[claude/{role}] non-JSON: {line[:200]}")
                continue
            kind = msg.get("type")
            if kind == "system" and msg.get("subtype") == "init":
                self.log(f"[claude/{role}] session {msg.get('session_id')} "
                         f"model={msg.get('model')} mcp={msg.get('mcp_servers')}")
                if not resume:
                    session = msg.get("session_id") or session
            elif kind == "assistant":
                texts, calls = [], []
                for b in msg["message"].get("content", []):
                    if b.get("type") == "text" and b.get("text", "").strip():
                        texts.append(b["text"])
                    elif b.get("type") == "tool_use":
                        calls.append({"name": b["name"], "arguments": jdump(b.get("input"))[:4000]})
                if texts or calls:
                    self.event("model" if role == "build" else "review_model",
                               text="\n".join(texts), tool_calls=calls)
                if calls:
                    self.log(f"[claude/{role}] {len(calls)} call(s) "
                             f"[{', '.join(c['name'].split('__')[-1] for c in calls)}] "
                             f"{self.minutes():.1f}min")
                elif texts:
                    self.log(f"[claude/{role}] says: {texts[0][:160]}")
            elif kind == "result":
                result = msg
        proc.wait()
        try:
            err = proc.stderr.read()
        except Exception:  # noqa: BLE001
            err = ""
        if err.strip():
            self.log(f"[claude/{role}] stderr: {err[-1500:]}")
        if proc in self.procs:
            self.procs.remove(proc)
        result.setdefault("session_id", session)
        result["_seconds"] = round(time.time() - t0, 1)
        result["_rc"] = proc.returncode
        usage.add_result(result, result["_seconds"])
        self.event("claude_result", role=role, **{k: result.get(k) for k in
                   ("subtype", "is_error", "num_turns", "session_id", "total_cost_usd", "_rc")})
        self.log(f"[claude/{role}] ended: subtype={result.get('subtype')} "
                 f"rc={proc.returncode} turns={result.get('num_turns')} "
                 f"in={usage.input:,} out={usage.output:,} {self.minutes():.1f}min")
        return result

    @staticmethod
    def kill(proc) -> None:
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        except Exception:  # noqa: BLE001
            pass

    # ── usage limits ─────────────────────────────────────────────────────
    def usage_limited(self, result: dict) -> float | None:
        """Seconds to wait if this result hit a subscription limit, else None."""
        return limit_wait_seconds(jdump(result))

    def transient_api(self, result: dict) -> bool:
        """True for a server-side error worth waiting out (not the model failing).

        Checked only for a session that actually ended badly, so an error string
        the model happened to quote in its own prose cannot trigger a backoff.
        """
        if not (result.get("is_error") or result.get("_rc") not in (0, None)):
            return False
        return bool(TRANSIENT_API_RE.search(jdump(result)))

    # ── the builder ──────────────────────────────────────────────────────
    def run_loop(self, system: str, first_prompt: str) -> None:   # type: ignore[override]
        session = str(uuid.uuid4())
        prompt, resume, nudges = first_prompt, False, 0
        while True:
            over = self.over_cap()
            if over:
                self.end_reason = self.end_reason or over
                self.log(self.end_reason)
                return
            r = self.run_claude(prompt=prompt, system=system, toolset="build", role="build",
                                usage=self.usage, session=session, resume=resume)
            self.builder_session = session = r.get("session_id") or session
            if self.finish_summary is not None:
                self.end_reason = "finished"
                return
            if self.stop_flag:
                self.end_reason = self.end_reason or "stopped at the hard cap"
                return
            wait = self.usage_limited(r)
            if wait is not None and wait > CFG.MAX_USAGE_WAIT_S:
                self.end_reason = (f"subscription limit with a {wait / 3600:.1f} h reset "
                                   "(longer than the wait cap): stopping, scene saved")
                self.log(self.end_reason)
                self.event("usage_limit", seconds=round(wait), waited=False)
                return
            if wait is not None:
                self.waits += 1
                if self.waits > CFG.MAX_USAGE_WAITS:
                    self.end_reason = "subscription usage limit, waited too many times"
                    self.log(self.end_reason)
                    return
                self.log(f"subscription usage limit reached; waiting {wait / 60:.0f} min "
                         f"(wait {self.waits}/{CFG.MAX_USAGE_WAITS}) then resuming")
                self.event("usage_limit", seconds=round(wait), wait=self.waits)
                self.t0 += wait          # a wait is not the agent's working time
                time.sleep(wait)
                prompt, resume = ("[harness] Resuming after a usage limit. Carry on with the "
                                  "scene from where you stopped."), True
                continue
            if self.transient_api(r):
                self.api_retries += 1
                if self.api_retries > CFG.MAX_API_RETRIES:
                    self.end_reason = ("Anthropic kept returning server errors "
                                       f"({self.api_retries - 1} backoffs): stopping, scene saved")
                    self.log(self.end_reason)
                    self.event("api_error", retries=self.api_retries - 1, gave_up=True)
                    return
                back = min(CFG.API_BACKOFF_CAP_S,
                           CFG.API_BACKOFF_BASE_S * 2 ** (self.api_retries - 1))
                self.log(f"transient API error; backing off {back / 60:.1f} min "
                         f"(retry {self.api_retries}/{CFG.MAX_API_RETRIES}) then resuming")
                self.event("api_error", seconds=back, retry=self.api_retries)
                self.t0 += back          # an outage is not the agent's working time
                time.sleep(back)
                prompt, resume = ("[harness] The API had a brief outage. Carry on with the "
                                  "scene from where you stopped."), True
                continue
            if r.get("is_error") or r.get("_rc") not in (0, None):
                nudges += 1
                if nudges > 3:
                    self.end_reason = (f"claude ended in error: {r.get('subtype')} "
                                       f"rc={r.get('_rc')}")
                    self.log(self.end_reason)
                    return
                self.log(f"claude ended with {r.get('subtype')} rc={r.get('_rc')}; resuming "
                         f"({nudges}/3)")
                prompt, resume = ("[harness] Your session ended unexpectedly. Continue building "
                                  "the scene; call finish when it is complete."), True
                continue
            nudges += 1
            if nudges > 3:
                self.end_reason = "model stopped working without finishing"
                self.log(self.end_reason)
                return
            self.log(f"claude stopped without finishing; nudging ({nudges}/3)")
            prompt, resume = ("[harness] You stopped without calling `finish`. If the scene is "
                              "complete, call `finish` now. Otherwise keep working on it."), True

    # ── the review round ─────────────────────────────────────────────────
    def run_reviewer(self, builder_summary: str) -> str:   # type: ignore[override]
        self.review_done = True
        self.role = "review"
        self.review_submitted = None
        review_dir = self.run_dir / "review"
        review_dir.mkdir(exist_ok=True)
        t0 = time.time()
        try:
            self.link.save(self.run_dir / "pre_review.blend", copy=True, timeout=600)
        except Exception as e:  # noqa: BLE001
            self.log(f"pre-review save failed: {e}")
        self.log("review round: reviewer starting")
        self.event("review_start", builder_summary=builder_summary)

        tmpl = (CFG.ROOT / "prompts" / "reviewer.md").read_text(encoding="utf-8")
        system = tmpl.format(blender_version=self.blender_version, task_dir=str(self.task_dir),
                             review_dir=str(review_dir), max_calls=CFG.REVIEW_MAX_CALLS)
        system += ("\n\n## This session\n\nYour tools are the `mcp__b2__*` tools and nothing "
                   "else. Open the reference images with `view_image`. Do not ask for "
                   "permission; inspect the scene and call `submit_review` when you are done.")
        task_text = (self.task_dir / "task.md").read_text(encoding="utf-8")
        refs = self.reference_images()
        prompt = (f"# Brief ({self.task})\n\n{task_text.strip()}\n\n"
                  "Reference images -- open each one with `view_image`:\n" +
                  "\n".join(f"- {p}" for p in refs) +
                  f"\n\n# The builder's finish summary\n\n{builder_summary}\n\n"
                  "Inspect the scene now and submit your review.")
        try:
            r = self.run_claude(prompt=prompt, system=system, toolset="review", role="review",
                                usage=self.review_usage, session=str(uuid.uuid4()))
            if self.review_submitted is None and not self.usage_limited(r):
                # It answered in prose instead of calling submit_review.
                text = r.get("result") if isinstance(r.get("result"), str) else None
                if text and len(text) > 200:
                    self.review_submitted = text
        except Exception as e:  # noqa: BLE001
            self.log(f"reviewer failed: {type(e).__name__}: {e}")

        review = self.review_submitted or ("(The reviewer did not produce a review; use your own "
                                           "judgement for this last pass.)")
        self.review_text = review
        (self.run_dir / "review.md").write_text(review, encoding="utf-8")
        self.event("review", review=review, seconds=round(time.time() - t0, 1),
                   usage=self.review_usage.as_dict())
        self.log(f"review round done in {(time.time() - t0) / 60:.1f} min, "
                 f"{self.review_calls} tool calls")
        self.role = "build"
        return review

    # ── entry ────────────────────────────────────────────────────────────
    def execute(self) -> dict:   # type: ignore[override]
        status = {"task": self.task, "run": self.run, "worker": self.worker, "phase": "running",
                  "started_at": L.now(), "freeze": self.freeze, "agent_pid": os.getpid(),
                  "harness": "claude_code", "model": CFG.MODEL}
        (self.run_dir / "status.json").write_text(jdump(status), encoding="utf-8")
        produced, final_note = False, None
        try:
            self.server = _RPCServer(("127.0.0.1", self.rpc_port), _RPCHandler)
            self.server.agent = self
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            self.log(f"tool RPC on 127.0.0.1:{self.rpc_port}")
            self.link.start()
            self.blender_setup()
            system, prompt = self.build_prompt_text()
            (self.run_dir / "system_prompt.md").write_text(system, encoding="utf-8")
            (self.run_dir / "first_message.txt").write_text(prompt, encoding="utf-8")
            self.event("start", task=self.task, model=CFG.MODEL, effort=CFG.REASONING_EFFORT,
                       harness="claude_code")
            self.run_loop(system, prompt)
        except Exception as e:  # noqa: BLE001
            self.end_reason = f"harness error: {type(e).__name__}: {e}"
            self.log(self.end_reason + "\n" + traceback.format_exc())
        for p in list(getattr(self, "procs", [])):
            self.kill(p)
        if self.server:
            self.server.shutdown()

        final = self.run_dir / "final.blend"
        for _ in range(2):
            try:
                if not self.link.alive():
                    self.restart_blender("save at end")
                r = self.link.save(final, copy=False, timeout=1200)
                produced = bool(r.get("ok")) and final.is_file()
                final_note = (r.get("output") or "") + (r.get("error") or "")
                if produced:
                    break
            except Exception as e:  # noqa: BLE001
                final_note = f"{type(e).__name__}: {e}"
                self.link.stop()
        self.log(f"final.blend {'saved' if produced else 'NOT saved'}: {str(final_note)[-300:]}")
        self.link.stop()

        referenced = L.referenced_skills(self.blender_codes, getattr(self, "library_names", []))
        for n in referenced:
            L.log("reference", task=self.task, run=self.run, skill=n,
                  retrieved=n in getattr(self, "retrieved", []), loaded=n in self.loaded_skills)
        usage = {
            "task": self.task, "run": self.run, "model": CFG.MODEL,
            "reasoning_effort": CFG.REASONING_EFFORT, "harness": "claude_code",
            "billing": "Claude subscription (no per-token charge); cost_usd is the list-price "
                       "equivalent Claude Code reports, for comparison only",
            "end_reason": self.end_reason, "finished_by_agent": self.end_reason == "finished",
            "produced_blend": produced, "finish_summary": self.finish_summary,
            "wall_clock_min": round(self.minutes(), 1),
            "agent": self.usage.as_dict(), "retrieval": self.aux_usage.as_dict(),
            "review": {"happened": self.review_done, "usage": self.review_usage.as_dict(),
                       "tool_calls": self.review_calls,
                       "first_finish_summary": self.first_finish_summary, "text": self.review_text},
            "cost_usd": round(self.total_cost(), 4),
            "usage_limit_waits": self.waits,
            "tool_calls": sum(self.tool_counts.values()), "tool_calls_by_name": self.tool_counts,
            "blender_actions": len(self.blender_codes), "blender_restarts": self.restarts,
            "image_generations": self.image_gens, "image_tokens": self.image_usage,
            "skills": {"library_size_at_start": getattr(self, "library_size", 0),
                       "retrieved": getattr(self, "retrieved", []),
                       "loaded_on_demand": self.loaded_skills,
                       "referenced_in_code": referenced},
            "claude_session": self.builder_session,
            "finished_at": L.now(),
        }
        (self.run_dir / "usage.json").write_text(json.dumps(usage, indent=2), encoding="utf-8")
        status.update(phase="agent_done", produced_blend=produced, end_reason=self.end_reason,
                      agent_finished_at=L.now())
        (self.run_dir / "status.json").write_text(jdump(status), encoding="utf-8")
        self.event("end", **{k: usage[k] for k in
                             ("end_reason", "produced_blend", "cost_usd", "wall_clock_min")})
        return usage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    u = ClaudeAgent(Path(a.task_dir), Path(a.run_dir), a.worker, a.freeze).execute()
    print(json.dumps({k: u[k] for k in
                      ("end_reason", "produced_blend", "cost_usd", "wall_clock_min")}))
    sys.exit(0 if u["produced_blend"] else 2)


if __name__ == "__main__":
    main()
