"""Make the blendcua plugin visible to an agent started outside blendcua_agent.py.

The planner and the curator each open their own hermes conversation. Neither goes
through `blendcua_agent.py`, which is where the plugin environment was being set
up — so on the first live run they came up with **zero tools**, and the planner
happily reported having written a plan it had no way to write.

Three things have to be true before `AIAgent(enabled_toolsets=[...])` can see it:

  1. `HERMES_ENABLE_PROJECT_PLUGINS=1` — project plugins are off by default.
  2. `HERMES_HOME` points at this project's `.hermes_home`, not `~/.hermes`.
  3. that `.hermes_home/config.yaml` names the plugin in `plugins.enabled` —
     project plugins are opt-in *by name* even when the env var is set.

And the process has to be running in the project directory, since
`.hermes/plugins/` is resolved relative to the cwd.

Two toolsets are registered, and which one an agent gets is a real decision:

  `blendcua_fs`  read, write, edit, glob, grep, bash
  `blendcua`     write_and_run — drives the live Blender session

The planner gets only `blendcua_fs`: it measures a photograph and writes a
document, and has no business creating geometry. The curator gets both, because
testing a candidate tool means replaying actions against Blender.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent


def hermes_home_name(port: int | None = None) -> str:
    """One Hermes home per Blender port: blendcua_agent.py rewrites config.yaml with
    the run name, so two concurrent builds must not share one."""
    port = port or int(os.environ.get("BLENDCUA_PORT", "6666"))
    return ".hermes_home" if port == 6666 else f".hermes_home_{port}"


HERMES_HOME = AGENT_DIR / hermes_home_name()

PLANNER_TOOLSETS = ["blendcua_fs"]
# No "blendcua": write_and_run is gated on an active step context and the
# curator runs between steps, so it can only ever be refused. Offering it
# cost the whole trial its replay evidence — the curator reached for the
# one tool it knew drove Blender, got "no active BlendCUA step context",
# and gave up instead of falling back to Tool_scripts/run.py.
CURATOR_TOOLSETS = ["blendcua_fs"]

# The checker judges a FINISHED model from its renders. It never builds
# anything, so it gets the filesystem toolset only -- read/write/edit/glob/
# grep/bash is exactly enough to crop an image, measure it and write a report.
# Giving it "blendcua" would be worse than useless: write_and_run is gated on
# an active step context, and there is no step in progress when the checker
# runs, so the tool could only ever refuse (the same trap that cost the
# curator its replay evidence, noted above).
CHECKER_TOOLSETS = ["blendcua_fs"]


import blendcua_core as core


def ensure_plugin_env() -> None:
    """Set the env and config the plugin loader needs. Safe to call repeatedly."""
    os.chdir(AGENT_DIR)                       # .hermes/plugins/ resolves from cwd
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    base = AGENT_DIR / ".hermes_home"
    if HERMES_HOME != base:
        for name in ("config.yaml", "SOUL.md"):
            if not (HERMES_HOME / name).is_file() and (base / name).is_file():
                (HERMES_HOME / name).write_text((base / name).read_text(encoding="utf-8"), encoding="utf-8")
    os.environ["HERMES_HOME"] = str(HERMES_HOME)
    os.environ["HERMES_ENABLE_PROJECT_PLUGINS"] = "1"

    import yaml
    cfg_path = HERMES_HOME / "config.yaml"
    cfg = {}
    if cfg_path.is_file():
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            cfg = {}
    enabled = list((cfg.get("plugins") or {}).get("enabled") or [])
    if "blendcua_tools" not in enabled:
        enabled.append("blendcua_tools")
    # merge rather than replace: blendcua_agent.py writes its mcp_servers block
    # into this same file, and clobbering it would break the next build.
    cfg.setdefault("plugins", {})["enabled"] = enabled
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")


def check_tools(result: dict, who: str) -> None:
    """Fail loudly if the conversation ran with no tools.

    Worth its own check: an agent with no tools does not error, it narrates. The
    planner's first run reported 'Created the plan and measurement artifacts'
    with an empty folder behind it, and only the plan-shape check downstream
    caught it.
    """
    msgs = result.get("messages") or []
    used = any(m.get("tool_calls") or m.get("role") == "tool" for m in msgs)
    if not used:
        print(f"[{who}] WARNING: the conversation made no tool calls at all. "
              f"If the log says 'Available tools: 0' the plugin did not load — "
              f"check .hermes_home/config.yaml and that this ran from {AGENT_DIR}.")

def record_usage(result, wall_s, out_path, *, tag, extra=None):
    """Write this agent's own cost next to its output.

    The executor has kept a usage.json since the start; the planner and the
    curator never did, so a task's real cost was only ever the build. That
    matters now that the harness is snapshotted at milestones for evaluation —
    "what did H_10 cost to reach" cannot be answered from the build alone.

    Same UsageAggregate the executor uses, so the numbers are comparable and
    carry the same per-session `max` correction rather than the old inflated sum.
    """
    u = core.UsageAggregate()
    u.log_conversation_result(result, tag=tag, wall_s=wall_s)
    rec = {
        "stage": tag.lower(),
        "conversations": u.turns,
        "peak_input_tokens": u.peak_input,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cost_usd": round(u.cost_usd, 4),
        "wall_s": round(wall_s, 1),
        "session_id": u.last_session_id,
    }
    rec.update(extra or {})
    out_path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print(f"[{tag.lower()}] cost ${rec['cost_usd']:.4f}  "
          f"in={rec['input_tokens']:,} out={rec['output_tokens']:,}  "
          f"{rec['wall_s']:.0f}s  -> {out_path.name}")
    return rec
