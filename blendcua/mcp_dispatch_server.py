import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[0])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)
#!/usr/bin/env python3
"""
MCP server exposing `dispatch_step(step_number)` to the Executor's
hermes-agent session — the Hermes-side replacement for BlendCuagent2's
in-process `mcp__blendcua__dispatch_step` SDK tool.

hermes-agent's MCP client spawns this as a single long-lived stdio
subprocess for the whole run (see tools/mcp_tool.py's per-server connection
lifecycle), so module-level state here (`_STATE`) plays the same role
BlendCuagent2's shared `RunContext` object played in-process: it accumulates
`completed_step_nums` / `prior_step_summaries` across calls for the life of
the run.

Config comes from environment variables (set in the MCP server's `env:`
block in config.yaml, written by blendcua_agent.py per run):
  BLENDCUA_RUN_NAME, BLENDCUA_PLAN_FILE, BLENDCUA_TASK_DIR,
  BLENDCUA_IMAGE_PATH (optional),
  BLENDCUA_ACTION_BUDGET, BLENDCUA_RETRY_BUDGET, BLENDCUA_NO_REVIEWS

After every dispatch_step call, cumulative subagent+reviewer cost/usage is
written to mem/<run>/Rollout/usage.json — the Executor process (a different
OS process) reads that file once at the end of the run to fold this
subprocess's spend into the final printed total.
"""
import json
import os
import sys
from pathlib import Path

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

import blendcua_core as core

# This subprocess makes its own AIAgent calls, so it needs the provider keys
# too. It gets them the same way the parent does — by reading the key file
# outside the repo, whose path arrives via BLENDCUA_KEY_FILE in the MCP env
# block. The key value itself is never written into this project. verbose=False
# because at import time stdout is still the raw MCP JSON-RPC channel; a stray
# print here would corrupt the protocol handshake.
core.load_api_keys(verbose=False)

mcp = FastMCP("blendcua_dispatch")

# Read at import, not per call: the tool's description is baked into the MCP
# schema the Executor sees, so it has to be decided before the @mcp.tool()
# decorator runs. Describing a reviewer that will never run is worse than
# useless — the Executor would keep waiting for a verdict field that says
# SKIPPED and treat the step as broken.
_NO_REVIEWS = os.environ.get("BLENDCUA_NO_REVIEWS", "").strip().lower() in ("1", "true", "yes", "on")

_DISPATCH_DESC_REVIEWED = """Execute one plan step end-to-end. Spawns a fresh Step-Subagent that
writes and runs Blender action files for the requested step, then runs
the visual reviewer. Retries on 'Try again' verdicts up to the configured
retry budget before moving on. Returns compact JSON: {status,
actions_taken, notes, anomalies, reviewer_verdict, attempts}. Call once
per step, in order — never skip or re-order.

`status` is "PASS" or "EXHAUSTED". **EXHAUSTED is not a stop signal** — it
means the review rounds ran out with the reviewer still unsatisfied. Move
straight on to the next step and carry the unresolved point forward as a
note. Never re-dispatch a step that came back EXHAUSTED, and never end the
run early because of one."""

_DISPATCH_DESC_NO_REVIEWS = """Execute one plan step end-to-end. Spawns a fresh Step-Subagent that
writes and runs Blender action files for the requested step, verifies its
own work, and returns. **Visual review is DISABLED for this run** — there
is no reviewer, no retry rounds, and no second opinion. Returns compact
JSON: {status, actions_taken, notes, anomalies, reviewer_verdict,
attempts}. Call once per step, in order — never skip or re-order.

`status` is "UNREVIEWED" (the normal success case: the subagent finished
and self-certified), "UNREVIEWED_FAILED_SELF_CHECK" (it finished but says
a check is unmet), or "NO_RESULT" (it never produced its JSON).
**None of these is a stop signal.** Move straight on to the next step and
carry any unresolved point forward as a note. Never re-dispatch a step,
and never end the run early because of a status."""


def _seed_handover(run_name: str) -> str:
    """Newest handover.md already written for this run, or "".

    Only ever non-empty when resuming a run whose earlier steps ran in a
    previous process; a fresh run has no step folders yet, so this is a no-op.
    """
    steps_dir = core.AGENT_DIR / "mem" / run_name / "steps"
    if not steps_dir.is_dir():
        return ""
    for step_dir in sorted(steps_dir.glob("step_*"), reverse=True):
        for name in ("handover.md", "HANDOVER.md"):
            path = step_dir / name
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                if text:
                    print(f"[dispatch] seeded handover from {path.name} in "
                          f"{step_dir.name} ({len(text)} chars)", file=sys.stderr)
                    return text
    return ""


class _State:
    def __init__(self):
        run_name = os.environ["BLENDCUA_RUN_NAME"]
        plan_file = os.environ["BLENDCUA_PLAN_FILE"]
        image_path = os.environ.get("BLENDCUA_IMAGE_PATH") or None
        task_dir = os.environ.get("BLENDCUA_TASK_DIR") or None
        action_budget = int(os.environ.get("BLENDCUA_ACTION_BUDGET", core.DEFAULT_ACTION_BUDGET))
        retry_budget = int(os.environ.get("BLENDCUA_RETRY_BUDGET", core.DEFAULT_RETRY_BUDGET))
        no_reviews = _NO_REVIEWS

        plan_path = core.AGENT_DIR / plan_file
        plan_text = plan_path.read_text(encoding="utf-8")

        self.run_name = run_name
        self.plan_text = plan_text
        self.all_steps = core.parse_plan(plan_text)
        self.step_by_num = {s["step_number"]: s for s in self.all_steps}
        self.completed_step_nums: list[int] = []
        self.prior_step_summaries: list[str] = []
        # The rolling handover: each step's subagent compacts its own work and
        # folds in whatever it inherited, so this single string carries the
        # whole build forward. Lives here because this module-level state is
        # what survives across dispatch_step calls for the life of the run.
        self.rolling_handover: str = ""
        # step_number -> the JSON string that call returned, so a repeat
        # call can be answered from memory instead of re-running the step.
        self.step_results: dict[int, str] = {}
        # Resuming mid-build (--only-steps 4 against a run whose steps 1-3 were
        # replayed into Blender) leaves the chain empty, so the subagent would
        # inherit nothing about a scene that is already populated. Seed it from
        # the newest handover.md already on disk for this run.
        self.rolling_handover = _seed_handover(run_name)

        self.reference_docs = core.load_reference_docs()
        self.system_prompt = core.load_system_prompt()
        self.image_relpath = (
            str(rel_to((core.AGENT_DIR / image_path), core.AGENT_DIR)) if image_path else None
        )
        self.ref_image = (core.AGENT_DIR / image_path) if image_path else None
        # The task folder, so each subagent is told where its plan's own
        # assets live rather than hunting the repo for them.
        self.task_relpath = task_dir

        self.action_budget = action_budget
        self.retry_budget = retry_budget
        self.no_reviews = no_reviews

        self.logger = core.RolloutLogger(run_name)
        self.usage = core.UsageAggregate()


_STATE: _State | None = None


def _state() -> _State:
    global _STATE
    if _STATE is None:
        _STATE = _State()
    return _STATE


# Step numbers currently executing. Guards against the Executor issuing a
# second dispatch_step while one is still in flight — see the block inside
# dispatch_step() for what that did to duck_run_001.
_IN_FLIGHT: set[int] = set()


@mcp.tool(description=(_DISPATCH_DESC_NO_REVIEWS if _NO_REVIEWS
                       else _DISPATCH_DESC_REVIEWED))
async def dispatch_step(step_number: int) -> str:
    """Execute one plan step end-to-end. See the description= above, which is
    what the model actually receives — it branches on BLENDCUA_NO_REVIEWS."""
    st = _state()

    step_spec = st.step_by_num.get(step_number)
    if step_spec is None:
        return json.dumps({
            "error": f"Unknown step_number {step_number}. "
                     f"Valid step numbers: {sorted(st.step_by_num)}"
        })

    # A completed step is never re-run. The Executor asking twice does not mean
    # it wants the work done twice — it means it lost the first answer, which is
    # exactly what happens when a step outlives the MCP client's per-call
    # timeout. 06_iron_gate: every one of its four steps ran past the 1800s
    # limit (31, 68, 40 and 60 minutes), so the Executor timed out, polled the
    # filesystem with `sleep` calls to see whether the work had landed, then
    # re-dispatched. Every step executed twice; the task took 4.4 hours and 187
    # inspection scripts against 55 for the task before it.
    #
    # _IN_FLIGHT below catches the concurrent case. This catches the sequential
    # one, which is more common and was silently permitted.
    if step_number in st.completed_step_nums:
        cached = st.step_results.get(step_number)
        print(f"[dispatch_step] step {step_number} already completed — returning "
              f"the stored result instead of re-running", file=sys.stderr)
        st.logger.log_event({"type": "dispatch_deduped", "step": step_number})
        if cached:
            return cached
        return json.dumps({
            "step": step_number,
            "already_completed": True,
            "note": (f"Step {step_number} already ran to completion in this run. "
                     f"Its result was not retained, but the work is done and the "
                     f"scene reflects it. Do not dispatch it again — move to the "
                     f"next step."),
        })

    # ── One step at a time, enforced ─────────────────────────────────────
    #
    # A step takes ~20 minutes. If the Executor decides that is too long and
    # re-issues dispatch_step, the call below hands the work to a worker
    # thread and returns — so BOTH copies run, against one Blender socket and
    # one module-level CURRENT_ACTION_CONTEXT. Several places in this codebase
    # are written on the assumption that "dispatch_step calls are strictly
    # serial"; nothing enforced it, and the assumption is load-bearing for
    # where write_and_run puts its files.
    #
    # duck_run_001 is what that looks like: rollout.jsonl records step_start
    # for step 1 at 10:59:09 and AGAIN at 11:29:15, while round 1's reviewer
    # was still judging. A step begins by clearing the scene, so the second
    # copy wiped the finished duck and rebuilt from a bare 12-vert circle
    # underneath the reviewer, which measured the same object at 204, then
    # 132, then 12 verts and produced a verdict on none of them. The two
    # 'Blender hung?' reviewer_skips in that log are the two copies
    # contending for the socket.
    #
    # Refusing the second call is strictly better than serving it: the first
    # is still running and will still return. The check-and-add pair has no
    # await between them, so on the single-threaded event loop it is atomic.
    if _IN_FLIGHT:
        busy = ", ".join(str(n) for n in sorted(_IN_FLIGHT))
        print(f"[dispatch_step] REFUSED step {step_number}: step(s) {busy} "
              f"still running", file=sys.stderr)
        st.logger.log_event({"type": "dispatch_refused", "step": step_number,
                             "in_flight": sorted(_IN_FLIGHT)})
        return json.dumps({
            "error": f"step {busy} is still running — dispatch_step refused.",
            "hint": "Steps run one at a time and a step can take 20+ minutes; "
                    "silence is normal and does NOT mean it failed. Your "
                    "earlier call is still working and will return its own "
                    "result. Do not call dispatch_step again for any step "
                    "until it does.",
        })

    _IN_FLIGHT.add(step_number)
    try:
        # core.do_dispatch_step is fully synchronous and does many blocking
        # subprocess.run() calls (one per Blender action) plus its own LLM
        # calls. FastMCP calls sync @mcp.tool() functions inline on the
        # event-loop thread (confirmed by reading func_metadata.py — no
        # thread offload for tool calls, only for resource reads), so those
        # blocking calls used to run directly on the loop thread. On
        # Windows, asyncio's default ProactorEventLoop pumps stdio via IOCP;
        # starving it for the length of a whole step (many sequential
        # blocking subprocess calls) reproducibly left the MCP stdio
        # channel desynced, and individual run.py dispatches that complete
        # in <1s standalone (confirmed via direct testing) were reported as
        # hung past their 45s subprocess timeout. Running the blocking work
        # in a worker thread keeps the loop thread free to service stdio
        # throughout. Harmless on macOS/Linux too — same sync logic, just
        # off the loop thread.
        result = await anyio.to_thread.run_sync(
            lambda: core.do_dispatch_step(
                step_spec=step_spec,
                run_name=st.run_name,
                all_steps=st.all_steps,
                completed_step_nums=st.completed_step_nums,
                prior_step_summaries=st.prior_step_summaries,
                reference_docs=st.reference_docs,
                image_relpath=st.image_relpath,
                ref_image=st.ref_image,
                system_prompt=st.system_prompt,
                plan_text=st.plan_text,
                logger=st.logger,
                usage=st.usage,
                action_budget=st.action_budget,
                retry_budget=st.retry_budget,
                task_relpath=st.task_relpath,
                no_reviews=st.no_reviews,
                prior_handover=st.rolling_handover,
            )
        )
    except Exception as e:
        st.logger.log_event({"type": "dispatch_error", "step": step_number, "error": str(e)})
        return json.dumps({
            "error": f"dispatch_step infrastructure failure: {e}",
            "hint": "This is a harness bug, not a geometry problem. Retry AT MOST "
                    "once; if it fails again, stop and report to the human instead "
                    "of looping.",
        })
    finally:
        _IN_FLIGHT.discard(step_number)
        st.logger.write_usage_snapshot(st.usage.snapshot())

    # Strip the handover before the result goes back to the Executor: it is
    # for the NEXT subagent, not for the supervisor, and it is tens of
    # thousands of characters about a scene the Executor never touches. An
    # empty one (a compaction turn that died) leaves the previous handover in
    # place rather than wiping the chain — stale context beats none.
    handover = str(result.pop("_handover", "") or "")
    if handover:
        st.rolling_handover = handover
    elif st.rolling_handover:
        print(f"[dispatch_step] step {step_number}: no handover produced — "
              f"carrying the previous one forward", file=sys.stderr)

    summary = core._one_line_summary(step_number, step_spec["goal"], result.get("notes", ""))
    st.prior_step_summaries.append(summary)
    if step_number not in st.completed_step_nums:
        st.completed_step_nums.append(step_number)

    st.logger.log_event({"type": "step_end", "step": step_number, "result": result, "summary": summary})

    payload = json.dumps(result, indent=2)
    # Kept so a repeat call — the Executor having lost this answer to a client
    # timeout — can be handed the same result rather than re-running the step.
    st.step_results[step_number] = payload
    return payload


def _redirect_output_to_log() -> None:
    """Point stdout AND stderr at `mem/<run>/Rollout/terminal.log` (plus the
    real stderr), so the run's own log actually contains the run.

    Two separate concerns are being handled here:

    1. stdout must stop carrying text. It is the MCP JSON-RPC channel — see
       the caller's docstring.
    2. Everything the step actually did has to end up somewhere readable.
       Nearly all of this project's logging (per-turn token/cost lines from
       UsageAggregate, the per-action tool-call summaries, the reviewer's
       verdict paths, tracebacks) is printed from THIS process, not from the
       Executor process that owns terminal.log's other writer. Before this,
       stdout was simply aliased to stderr and all of it vanished with the
       console — `terminal.log` held only the Executor's own two startup
       lines, and there was no way to see how a turn went after the fact.

    Both processes append to the same file with per-write flushes, which is
    what BlendCuagent2 produced from a single process. Interleaving is not a
    concern in practice: the Executor writes a handful of lines around the
    edges of the run and is blocked inside `dispatch_step` for everything in
    between.

    Note this captures `print()`, not the `logging` module — hermes-agent's
    own `logger.warning(...)` calls hold a reference to the original stderr
    and bypass the tee. Those are rare and non-essential; the agent-visible
    behaviour all comes through print.
    """
    run_name = os.environ.get("BLENDCUA_RUN_NAME")
    if not run_name:
        sys.stdout = sys.stderr
        return
    path = core.MEM_DIR / run_name / "Rollout" / "terminal.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Own handle for core.log_print — survives hermes-agent replacing sys.stdout
    # when an AIAgent is constructed, which silently truncated this log at the
    # start of step 1 on the first run that used it.
    core.attach_terminal_log(path)
    core.attach_hermes_log_forwarding()
    handle = core.terminal_log_handle()
    if handle is None:
        sys.stdout = sys.stderr
        return
    # Capture the real stderr BEFORE reassigning, or the Tee would recurse.
    tee = core.Tee(sys.stderr, handle)
    sys.stdout = tee
    sys.stderr = tee


async def _run_stdio_with_stdout_guard() -> None:
    """Replaces FastMCP's `mcp.run(transport="stdio")` convenience call.

    `stdio_server()` binds the JSON-RPC write stream to the raw
    `sys.stdout.buffer` object ONCE, at server-start time, and keeps that
    reference for the server's whole life — it does not re-read `sys.stdout`
    on every write. So once we're inside this context, `sys.stdout` is safe
    to repoint for the rest of the process: doing so stops every later
    `print()` — ours (blendcua_core.py logs a lot) AND hermes-agent's own
    internal debug/warning prints during a dispatch_step call — from landing
    on the same fd as the protocol stream and corrupting it. Confirmed
    empirically without this guard: the parent's MCP client logged
    `Failed to parse JSONRPC message from server` on our own log lines and
    on hermes-agent's own "Request debug dump" / "API call failed" prints,
    which killed the keepalive and forced a server reconnect mid-run.
    """
    async with stdio_server() as (read_stream, write_stream):
        _redirect_output_to_log()
        await mcp._mcp_server.run(
            read_stream, write_stream, mcp._mcp_server.create_initialization_options(),
        )


if __name__ == "__main__":
    anyio.run(_run_stdio_with_stdout_guard)
