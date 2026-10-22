import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[0])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)
#!/usr/bin/env python3
"""
BlendCUA-Hermes Executor Agent — port of BlendCuagent2/agent.py onto
hermes-agent instead of the Claude Agent SDK. See blendcua_core.py's module
docstring for the two real architecture differences this port had to work
around (no in-process custom tools; no image-through-tool-result vision).

Usage:
    python blendcua_agent.py --task Duck

One folder under plans/ is one task: it holds the build plan and every asset the
plan names. --task derives the plan path, the reference image (from the plan's
own `<!-- ref-image: ... -->` header, resolved inside that folder) and the
run-name prefix. There is no per-task config file to edit.

Requires ANTHROPIC_API_KEY (or OPENAI_API_KEY, per models.py) in the
environment, and a live Blender session running Tool_scripts/blender_server.py.
"""
import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

import yaml

import blendcua_core as core
from models import MODELS, OPENAI_REASONING_EFFORT

AGENT_DIR = core.AGENT_DIR

# Project-local Hermes home, kept inside the repo so this port never touches
# the user's global ~/.hermes config. Fresh config.yaml written per run
# (mcp_servers env block carries the run's parameters to the dispatch
# subprocess — see mcp_dispatch_server.py).
import agent_env as _agent_env
HERMES_HOME = _agent_env.HERMES_HOME


def _write_hermes_config(*, run_name: str, plan_file: str, image_path: str | None,
                         task_dir: str | None = None) -> None:
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    env = {
        "BLENDCUA_RUN_NAME": run_name,
        "BLENDCUA_PLAN_FILE": plan_file,
        "BLENDCUA_TASK_DIR": task_dir or "",
        "BLENDCUA_ACTION_BUDGET": str(_ARGS.action_budget),
        "BLENDCUA_RETRY_BUDGET": str(_ARGS.retry_budget),
        "BLENDCUA_NO_REVIEWS": "1" if _ARGS.no_reviews else "0",
        # Loads .hermes/plugins/blendcua_tools/ (the write_and_run native
        # tool) — resolved relative to the subprocess's cwd, which it
        # inherits from us (AGENT_DIR), not from HERMES_HOME.
        "HERMES_ENABLE_PROJECT_PLUGINS": "1",
        # HERMES_HOME isn't in mcp_tool.py's baseline env allowlist (PATH,
        # HOME, USER, LANG, LC_ALL, TERM, SHELL, TMPDIR) — without forwarding
        # it explicitly, the subprocess would fall back to ~/.hermes and
        # never see our config.yaml's plugins.enabled entry, silently
        # skipping the plugin again via a different path than before.
        "HERMES_HOME": str(HERMES_HOME),
        # which Blender this build talks to (core reads it at import)
        "BLENDCUA_PORT": str(core._BLENDER_PORT),
    }
    if image_path:
        env["BLENDCUA_IMAGE_PATH"] = image_path
    # hermes-agent filters the parent's environment when spawning MCP server
    # subprocesses (tools/mcp_tool.py's stdio env-filtering, a sane default
    # for third-party MCP servers) — confirmed empirically: ANTHROPIC_API_KEY
    # did NOT reach mcp_dispatch_server.py's process without being forwarded,
    # so its AIAgent calls silently fell back to ambient Claude Code OAuth
    # credentials instead of the key we actually want billed.
    #
    # We forward the key file's PATH, never the key itself. This config.yaml
    # is written INSIDE the repo, so putting a secret in it — which an earlier
    # version of this function did — is one `git add -A` away from publishing
    # it. mcp_dispatch_server.py reads the same file at import and loads it
    # into its own environment. See core.load_api_keys().
    env["BLENDCUA_KEY_FILE"] = str(core.key_file_path())
    if sys.platform == "win32":
        # hermes-agent's MCP-subprocess env allowlist (PATH, HOME, USER,
        # LANG, LC_ALL, TERM, SHELL, TMPDIR) is POSIX-oriented and drops
        # SystemRoot — confirmed empirically that this breaks Winsock in
        # the grandchild `python Tool_scripts/run.py` subprocess dispatch_
        # step spawns: socket.socket() raises "WinError 10106: The
        # requested service provider could not be loaded or initialized"
        # without it, which manifested as every action/review dispatch
        # hanging until blendcua_core.py's own 45s subprocess timeout hit,
        # not a live Blender socket. Forward the Windows system vars that
        # process creation and networking actually need.
        for win_env_var in ("SystemRoot", "windir", "ComSpec", "PATHEXT",
                             "TEMP", "TMP", "USERPROFILE", "USERNAME",
                             "APPDATA", "LOCALAPPDATA",
                             "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"):
            if os.environ.get(win_env_var):
                env[win_env_var] = os.environ[win_env_var]
    config = {
        "mcp_servers": {
            "blendcua_dispatch": {
                "command": sys.executable,
                "args": [str(AGENT_DIR / "mcp_dispatch_server.py")],
                "env": env,
                # keepalive_interval must comfortably exceed the longest
                # stretch dispatch_step can go without yielding to the event
                # loop. Confirmed empirically: the default (180s) fired mid
                # -call and killed/reconnected the server before step 1 even
                # finished its first action, silently resetting the
                # subprocess's in-memory run state.
                "keepalive_interval": 3600,
                # A step with several review rounds can run many minutes —
                # well past the 300s default per-call timeout. 1800 was not
                # enough either: 06_iron_gate's four steps took 31, 68, 40 and
                # 60 minutes, so every one of them timed out here and the
                # Executor re-dispatched it. dispatch_step now answers a repeat
                # call from cache, so a timeout is no longer destructive — but
                # the Executor still wastes turns polling when it happens, so
                # the ceiling is raised past any plausible step.
                "timeout": 7200,
                "connect_timeout": 60,
            }
        },
        # Plugins are opt-in by name even when HERMES_ENABLE_PROJECT_PLUGINS=1
        # gets the manifest discovered — confirmed empirically (debug log:
        # "Skipping 'blendcua_tools' (not in plugins.enabled)"). This is the
        # config.yaml living under HERMES_HOME, which is what
        # _get_enabled_plugins() actually reads.
        "plugins": {"enabled": ["blendcua_tools"]},
    }
    (HERMES_HOME / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def _build_executor_intro(*, run_name: str, image_relpath: str | None,
                           plan_text: str, all_steps: list[dict],
                           no_reviews: bool = False,
                           task_relpath: str | None = None) -> str:
    steps_list = "\n".join(f"  {s['step_number']}. {s['goal']}" for s in all_steps)
    step_numbers = [s["step_number"] for s in all_steps]
    terminal_md = core.load_prompt_file("terminal.md")
    examples_md = core.load_prompt_file("examples.md")

    # Keep this in step with mcp_dispatch_server's two tool descriptions and
    # with do_dispatch_step's status vocabulary. The Executor stalling on an
    # unexpected status is the main failure mode worth designing against here:
    # it has no reviewer verdict to key off any more.
    if no_reviews:
        dispatch_para = (
            "1. Call `mcp__blendcua_dispatch__dispatch_step(step_number=K)`. This spawns a\n"
            "   fresh Step-Subagent that writes and runs the action files for step K\n"
            "   against the live Blender socket and renders screenshots for the record.\n"
            "   **Visual review is DISABLED on this run** — there is no reviewer and no\n"
            "   retry rounds. It returns compact JSON: `{\"status\", \"actions_taken\",\n"
            "   \"notes\", \"anomalies\", \"reviewer_verdict\", \"attempts\"}`, where\n"
            "   `reviewer_verdict` is always `\"SKIPPED (--no-reviews)\"` and `status` is\n"
            "   `UNREVIEWED` (normal success), `UNREVIEWED_FAILED_SELF_CHECK`, or\n"
            "   `NO_RESULT`. **None of those is an error or a stop signal** — note it and\n"
            "   keep going."
        )
    else:
        dispatch_para = (
            "1. Call `mcp__blendcua_dispatch__dispatch_step(step_number=K)`. This spawns a\n"
            "   fresh Step-Subagent that writes and runs the action files for step K\n"
            "   against the live Blender socket, renders review screenshots, and runs an\n"
            "   independent visual reviewer. It returns compact JSON: `{\"status\",\n"
            "   \"actions_taken\", \"notes\", \"anomalies\", \"reviewer_verdict\", \"attempts\"}`."
        )

    return f"""\
# BlendCUA — Executor role

Run name: {run_name}
Task folder: {task_relpath or '(none)'} — the plan below is the spec, and every
asset it names sits beside it in that folder.
Reference image: {image_relpath or '(none)'}

You are the **Executor**. You do NOT write action files or drive Blender
yourself — a fresh **Step-Subagent** does that for each step, via the tool
`mcp__blendcua_dispatch__dispatch_step(step_number=int)`. Your job is to walk
through the plan step by step, invoking the subagent per step and reflecting
between.

## How to work through the run

For each step in the plan, **in order**:

{dispatch_para}

2. Once the tool returns, reflect briefly in **3-6 sentences** of text:
   does the reported result align with what the plan intended? any anomalies
   to watch for? any adjustment for upcoming steps? your confidence in
   continuing.

3. Move on to the next step's dispatch_step call. Never skip or re-order.

When all {len(step_numbers)} steps are done, write a final wrap-up paragraph
summarising the build and the reviewer verdicts. Then stop.

## Steps to execute (call dispatch_step in this order)

{steps_list}

## Build plan (authoritative spec — the full text is also passed to each subagent)

{plan_text}

## How the subagent operates against Blender (terminal.md)

{terminal_md}

## Worked action-file examples (examples.md)

{examples_md}

## Start now

Begin with `mcp__blendcua_dispatch__dispatch_step(step_number={step_numbers[0]})`.
No preamble needed — the tool call is your first output.
"""


# Toolsets the Executor keeps. It supervises: it calls dispatch_step, reads
# what came back, and reflects. It never builds geometry, so it gets no `bash`,
# `write`, `edit` or `write_and_run` — only the read-only half of the plugin's
# Claude-Code surface, plus todo.
_EXECUTOR_KEEP_TOOLSETS = {"todo"}
_EXECUTOR_KEEP_PLUGIN_TOOLS = ["read", "glob", "grep"]


def _executor_disabled_toolsets() -> list[str]:
    """Every hermes toolset except the few the Executor actually needs.

    This is a subtraction, not a whitelist, for one specific reason:
    `enabled_toolsets=[...]` replaces hermes' default toolset resolution
    wholesale and — confirmed empirically — takes MCP-discovered tools with it.
    dispatch_step lives outside the named toolset system, so a whitelist would
    silently remove the only tool this agent exists to call.

    Computing the list from toolsets.TOOLSETS rather than hard-coding it means
    a toolset added by a future hermes upgrade is excluded by default instead
    of silently appearing in the Executor's hands. The previous hard-coded list
    subtracted 5 of 57 and handed it the other 52 — delegation, skills, memory,
    kanban, cron, a dozen chat integrations — for a job that is five tool calls
    and a paragraph. (An earlier version was worse still: 25 of its 31 entries
    were tool names, not toolset names, and were silently ignored.)

    `blendcua` and `blendcua_fs` are plugin toolsets and are not in
    TOOLSETS, so they are not disabled here — `blendcua` is removed explicitly
    so the Executor cannot write and run Blender actions behind the subagent's
    back, while `blendcua_fs` is kept for read/glob/grep.
    """
    try:
        from toolsets import TOOLSETS
    except ImportError:          # hermes internals moved — fail open, not shut
        return ["computer_use", "clarify", "file", "terminal", "code_execution",
                "blendcua"]
    return [t for t in TOOLSETS if t not in _EXECUTOR_KEEP_TOOLSETS] + ["blendcua"]


def run_executor(*, run_name: str, image_relpath: str | None, plan_text: str,
                  all_steps: list[dict], system_prompt: str,
                  logger: "core.RolloutLogger", usage: "core.UsageAggregate",
                  no_reviews: bool = False, task_relpath: str | None = None) -> None:
    from tools.mcp_tool import discover_mcp_tools
    from run_agent import AIAgent

    registered = discover_mcp_tools()
    print(f"[BlendCUA] MCP tools registered: {registered}")
    if not any("dispatch_step" in t for t in registered):
        print("[BlendCUA] ERROR: dispatch_step MCP tool did not register — "
              "check .hermes_home/config.yaml and mcp_dispatch_server.py for errors.")
        sys.exit(1)

    executor_kwargs = dict(
        provider=MODELS["executor"]["provider"],
        model=MODELS["executor"]["model"],
        api_key=core.api_key_for(MODELS["executor"]["provider"]),
        base_url=core.base_url_for(MODELS["executor"]["provider"]),
        quiet_mode=True,
        ephemeral_system_prompt=system_prompt,
        # Generous: len(steps) dispatch_step calls + a reflection turn each,
        # plus headroom for the wrap-up.
        max_iterations=max(90, len(all_steps) * 4),
        # See _executor_disabled_toolsets() for why this is a computed
        # subtraction rather than an enabled_toolsets whitelist.
        disabled_toolsets=_executor_disabled_toolsets(),
    )
    if MODELS["executor"]["provider"] == "openai":
        executor_kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}
    executor = AIAgent(**executor_kwargs)

    print(f"[BlendCUA] Executor model: {MODELS['executor']}")
    print(f"[BlendCUA] Reviewer model: "
          + ("DISABLED (--no-reviews)" if no_reviews else str(MODELS['reviewer'])))
    print(f"[BlendCUA] Run:            {run_name}")
    print(f"[BlendCUA] Steps parsed:   {[s['step_number'] for s in all_steps]}")
    print("-" * 60)

    intro = _build_executor_intro(
        run_name=run_name, image_relpath=image_relpath,
        plan_text=plan_text, all_steps=all_steps, no_reviews=no_reviews,
        task_relpath=task_relpath,
    )
    _t0 = time.time()
    result = executor.run_conversation(intro)
    usage.log_conversation_result(result, tag="Executor", wall_s=time.time() - _t0)
    print(f"\n[Executor] {result.get('final_response', '')}")

    logger.log_event({
        "type": "executor_turn_done",
        "final_response": result.get("final_response"),
        "completed": result.get("completed"),
    })


_INTERRUPT_STATE: dict = {"logger": None, "usage": None, "start": None}


def _install_sigint(logger, usage, start_ts: float) -> None:
    _INTERRUPT_STATE.update(logger=logger, usage=usage, start=start_ts)

    def handler(signum, frame):
        print("\n[Interrupted]")
        duration = time.time() - _INTERRUPT_STATE["start"]
        usage.merge_snapshot(logger.read_usage_snapshot())
        record = {
            "type": "interrupted",
            "turns": usage.turns,
            "peak_input_tokens": usage.peak_input,
            "cost_usd": round(usage.cost_usd, 4),
            "duration_s": round(duration, 1),
            "session_id": usage.last_session_id,
        }
        try:
            logger.log_event(record)
        except Exception:
            pass
        print(f"[BlendCUA] Turns:     {usage.turns}")
        print(f"[BlendCUA] Peak ctx:  {usage.peak_input:,} tokens")
        print(f"[BlendCUA] Cost:      ${usage.cost_usd:.4f}")
        print(f"[BlendCUA] Duration:  {duration:.1f}s ({duration/60:.1f} min)")
        try:
            logger.close()
        except Exception:
            pass
        sys.exit(130)

    signal.signal(signal.SIGINT, handler)


_ARGS = None


def main():
    global _ARGS
    parser = argparse.ArgumentParser(
        description="BlendCUA-Hermes Executor — hermes-agent port of the two-layer agent that builds objects in Blender."
    )
    parser.add_argument("--task", required=True,
                        help="Task folder under plans/ (e.g. 'Duck'). The plan, the "
                             "reference image and the run prefix are all derived from "
                             "it — see core.resolve_task.")
    parser.add_argument("--run", default=None,
                        help="Run name (e.g. duck_run_001). Auto-increments if omitted.")
    parser.add_argument("--prefix", default=None,
                        help="Override the auto-generated run-name prefix "
                             "(default: the task folder's name, e.g. 'duck_run').")
    parser.add_argument("--plan", default=None,
                        help="Override which .md in the task folder is the plan. Only "
                             "needed when the folder holds more than one.")
    parser.add_argument("--image", default=None,
                        help="Override the reference image (default: the plan's own "
                             "<!-- ref-image: ... --> header, resolved inside the "
                             "task folder).")
    parser.add_argument("--only-steps", default=None,
                        help="Comma-separated step numbers to run (e.g. '1,2,3'). Default: all.")
    parser.add_argument("--action-budget", type=int, default=core.DEFAULT_ACTION_BUDGET,
                        help="Max actions per subagent attempt (default: %(default)s).")
    parser.add_argument("--retry-budget", type=int, default=core.DEFAULT_RETRY_BUDGET,
                        help="Max 'Try again' retries per step before moving on "
                             "(default: %(default)s). N gives N+1 review rounds, so "
                             "0 means the reviewer is consulted exactly once: on a "
                             "TRY_AGAIN the subagent makes one corrective pass that "
                             "is not re-reviewed, and the step closes as EXHAUSTED.")
    parser.add_argument("--no-reviews", "--noreviews", dest="no_reviews",
                        action="store_true",
                        help="Skip the visual reviewer entirely. Each step runs the "
                             "Step-Subagent, which must report a pass/fail verdict "
                             "with evidence for every acceptance check; it is sent "
                             "back to fix anything it failed, up to --retry-budget "
                             "rounds. Review renders are still saved for humans.")
    _ARGS = parser.parse_args()

    core.load_api_keys()

    # One folder is one task: the plan, its reference image and the run prefix
    # all come from it, so there is nothing to keep in sync between runs and no
    # per-task config file to edit. Anything wrong with the folder is fatal here
    # rather than mysterious three prompts later.
    try:
        task = core.resolve_task(_ARGS.task, plan=_ARGS.plan, image=_ARGS.image)
    except core.TaskError as exc:
        print(f"[BlendCUA] ERROR: {exc}")
        sys.exit(1)

    run_name = _ARGS.run or core.next_run_name(_ARGS.prefix or task["prefix"])
    plan_path = AGENT_DIR / task["plan"]
    image_path = (AGENT_DIR / task["image"]) if task["image"] else None
    print(f"[BlendCUA] Task {task['dir']} -> plan {task['plan']}, "
          f"image {task['image'] or '(none)'}, run {run_name}")

    os.chdir(AGENT_DIR)
    os.environ["HERMES_HOME"] = str(HERMES_HOME)
    # The Executor process needs this too, not just the MCP subprocess: without
    # it hermes never discovers the project plugin here, so the Executor gets
    # no read/glob/grep and can only stare at dispatch_step's JSON. (The MCP
    # subprocess gets its own copy via the env block in _write_hermes_config.)
    os.environ["HERMES_ENABLE_PROJECT_PLUGINS"] = "1"

    if not core.check_blender():
        print("[BlendCUA] ERROR: Cannot reach Blender on localhost:6666.")
        print("           Open Blender -> Script Editor -> run Tool_scripts/blender_server.py")
        sys.exit(1)
    print("[BlendCUA] Blender server reachable OK")

    logger = core.RolloutLogger(run_name)
    sys.stdout = core.Tee(sys.__stdout__, logger.terminal_log)
    sys.stderr = core.Tee(sys.__stderr__, logger.terminal_log)

    # What the store looked like before this run touched anything. The curator
    # used to infer this by diffing against the newest snapshot, which is only
    # the run-start state if nobody edited the harness in between — and when
    # somebody did, it credited those files to the builder and called them "the
    # strongest evidence in the whole record". Recorded here so the question is
    # answered by fact rather than by inference.
    if not (_ARGS.only_steps and (core.MEM_DIR / run_name / "store_baseline.json").is_file()):
        # a continued run (--only-steps into an existing folder) keeps the baseline of its
        # real start, or the files the first attempt wrote into the store would look original
        core.write_store_baseline(run_name)

    plan_text = plan_path.read_text(encoding="utf-8")
    all_steps = core.parse_plan(plan_text)
    if _ARGS.only_steps:
        keep = {int(x) for x in _ARGS.only_steps.split(",") if x.strip()}
        all_steps = [s for s in all_steps if s["step_number"] in keep]
    if not all_steps:
        print(f"[BlendCUA] ERROR: no steps parsed from {plan_path}")
        sys.exit(1)

    system_prompt = core.load_system_prompt()
    image_relpath = str(rel_to(image_path, AGENT_DIR)) if image_path else None

    _write_hermes_config(
        run_name=run_name, plan_file=task["plan"], image_path=image_relpath,
        task_dir=task["dir"],
    )

    usage = core.UsageAggregate()
    start_ts = time.time()
    _install_sigint(logger, usage, start_ts)

    logger.log_event({
        "type": "start", "run": run_name,
        "task": task["dir"],
        "plan_file": task["plan"], "image": image_relpath,
        "steps": [s["step_number"] for s in all_steps],
        "executor_model": MODELS["executor"],
        "reviewer_model": None if _ARGS.no_reviews else MODELS["reviewer"],
        "action_budget": _ARGS.action_budget, "retry_budget": _ARGS.retry_budget,
        "no_reviews": bool(_ARGS.no_reviews),
    })

    try:
        run_executor(
            run_name=run_name, image_relpath=image_relpath, plan_text=plan_text,
            all_steps=all_steps, system_prompt=system_prompt,
            logger=logger, usage=usage, no_reviews=_ARGS.no_reviews,
            task_relpath=task["dir"],
        )
    finally:
        duration = time.time() - start_ts
        # Fold in the dispatch subprocess's subagent+reviewer spend (a
        # different OS process — see blendcua_core.RolloutLogger.usage_path).
        usage.merge_snapshot(logger.read_usage_snapshot())

    print("\n" + "=" * 60)
    print(f"[BlendCUA] Run finished: {run_name}")
    print(f"[BlendCUA] Duration:     {duration:.1f}s ({duration/60:.1f} min)")
    print(f"[BlendCUA] Cost:         ${usage.cost_usd:.4f}")
    print(f"[BlendCUA] Turns:        {usage.turns}")
    print(f"[BlendCUA] Peak context: {usage.peak_input:,} tokens")
    print(f"[BlendCUA] Rollout:      {rel_to(logger.rollout_dir, AGENT_DIR)}")
    print("=" * 60)

    logger.log_event({
        "type": "finished", "duration_s": round(duration, 1),
        "cost_usd": round(usage.cost_usd, 4), "turns": usage.turns,
        "peak_input_tokens": usage.peak_input,
    })
    logger.close()


if __name__ == "__main__":
    main()
