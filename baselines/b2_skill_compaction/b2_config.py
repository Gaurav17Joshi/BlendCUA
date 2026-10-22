"""Paths, model, prices and budget caps for baseline B2. One place to change them."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Importing blendcua_core must not drop .pyc files into the main repo.
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parent                       # Blend_baselinB2/
MAIN = ROOT.parent / "BlendCuavb_run"                        # read-only: system under test
TASKS = ROOT / "tasks"
# B2_RUN_TAG keeps a side experiment (e.g. the model bake-off) out of the real
# curriculum's folders: runs_<tag>/, blends_<tag>/, state_<tag>/, RESULTS_<tag>.md.
# The library is NOT scoped — a bake-off runs with --freeze, so it writes none.
RUN_TAG = os.environ.get("B2_RUN_TAG", "")
_SFX = f"_{RUN_TAG}" if RUN_TAG else ""
RUNS = ROOT / f"runs{_SFX}"
BLENDS = ROOT / f"blends{_SFX}"
RESULTS = ROOT / f"RESULTS{_SFX}.md"
LIBRARY = ROOT / "library"
SKILLS = LIBRARY / "skills"
SNAPSHOTS = LIBRARY / "snapshots"
LIBRARY_LOG = LIBRARY / "library_log.jsonl"
STATE = ROOT / f"state{_SFX}"

PY = r"C:\Users\kunal\AppData\Local\Programs\Python\Python312\python.exe"
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

# Two workers, never 6666/6667 (the main experiment's). Each worker gets two of
# the machine's four GPUs for Cycles. `rpc_port` is the Claude-Code entrant's
# tool bridge (agent_claude.py <- b2_mcp_server.py); unused by the others.
WORKERS = {
    0: {"port": 6680, "gpus": "0,1", "geometry": (0, 0, 1400, 950), "rpc_port": 6690},
    1: {"port": 6681, "gpus": "2,3", "geometry": (500, 60, 1400, 950), "rpc_port": 6691},
}
# Another experiment on this machine holds ports and GPUs of its own, and which
# ones move. B2_PORT0 / B2_RPC_PORT0 / B2_GPUS0 retarget worker 0 for a run
# without editing the defaults above (check with `netstat -ano` and
# `nvidia-smi` first).
if os.environ.get("B2_PORT0"):
    WORKERS[0]["port"] = int(os.environ["B2_PORT0"])
if os.environ.get("B2_RPC_PORT0"):
    WORKERS[0]["rpc_port"] = int(os.environ["B2_RPC_PORT0"])
if os.environ.get("B2_GPUS0"):
    WORKERS[0]["gpus"] = os.environ["B2_GPUS0"]
# Same for worker 1 (e.g. a one-GPU machine: B2_GPUS0=0 B2_GPUS1=0).
if os.environ.get("B2_PORT1"):
    WORKERS[1]["port"] = int(os.environ["B2_PORT1"])
if os.environ.get("B2_RPC_PORT1"):
    WORKERS[1]["rpc_port"] = int(os.environ["B2_RPC_PORT1"])
if os.environ.get("B2_GPUS1"):
    WORKERS[1]["gpus"] = os.environ["B2_GPUS1"]

# ── Model: same as the main system's executor (BlendCuavb_run/models.py) ─────
if str(MAIN) not in sys.path:
    sys.path.insert(0, str(MAIN))
from models import MODELS, OPENAI_REASONING_EFFORT  # noqa: E402

assert MODELS["executor"]["provider"] == "openai", "B2's client speaks the OpenAI Responses API"

# Profiles for the model bake-off. `luna` is the default and is the main
# system's executor, called directly at OpenAI. The others go through
# OpenRouter, which serves the same Responses API (stateless), so only the
# base URL, the key and the price table change. Prices are USD per million
# tokens, from each model's OpenRouter entry (checked 2026-09-18); `effort`
# is what that model accepts — OpenRouter takes low/medium/high, `max` is
# OpenAI-only. Select with B2_MODEL=<name>; usage.json records what ran.
PROFILES = {
    "luna": {
        "model": MODELS["executor"]["model"], "base_url": None, "key_env": "OPENAI_API_KEY",
        "effort": OPENAI_REASONING_EFFORT, "openai_native": True,
        "price": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    },
    # GPT-6 Luna at OpenAI, same B2 loop as `luna`, at its own published prices
    # (2026-10-22; cache writes at the 30-minute rate). The earlier BLENDER-1
    # luna6 runs were priced with luna-5.6's table instead (an equivalent).
    "luna6": {
        "model": "gpt-6-luna", "base_url": None, "key_env": "OPENAI_API_KEY",
        "effort": "max", "openai_native": True,
        "price": {"input": 0.10, "cached_input": 0.01, "output": 0.50, "cache_write": 0.125},
    },
    "deepseek": {
        "model": "deepseek/deepseek-v4.1-flash", "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY", "effort": "high", "openai_native": False,
        "price": {"input": 0.15, "cached_input": 0.003, "output": 0.60},
    },
    "muse": {
        "model": "meta/muse-spark-1.3-contributor", "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY", "effort": "high", "openai_native": False,
        "price": {"input": 0.10, "cached_input": 0.002, "output": 0.20},
    },
    # Claude runs in its own harness (Claude Code, headless) rather than in
    # agent.py's loop -- see agent_claude.py. It is driven by the claude.exe
    # that ships with the VS Code extension and authenticates with the
    # account's Claude subscription, so the run costs plan usage, not money;
    # `price` is only there to keep the reporting code total. Claude Code
    # reports its own list-price equivalent, which is what RESULTS shows.
    "claude": {
        "model": "claude-opus-5", "base_url": None, "key_env": None,
        "effort": "max", "openai_native": False, "harness": "claude_code",
        "exe": None,        # resolved by claude_exe() below
        "price": {"input": 0.0, "cached_input": 0.0, "output": 0.0},
    },
    # The other Claude entrants: same harness, same effort, different model.
    "fable": {
        "model": "claude-fable-5-1", "base_url": None, "key_env": None,
        "effort": "max", "openai_native": False, "harness": "claude_code",
        "exe": None,
        "price": {"input": 0.0, "cached_input": 0.0, "output": 0.0},
    },
    "sonnet": {
        "model": "claude-sonnet-5", "base_url": None, "key_env": None,
        "effort": "max", "openai_native": False, "harness": "claude_code",
        "exe": None,
        "price": {"input": 0.0, "cached_input": 0.0, "output": 0.0},
    },
}
def claude_exe() -> str:
    """The Claude Code binary: the one that launched us, else the newest the VS
    Code extension ships, else whatever is on PATH."""
    p = os.environ.get("CLAUDE_CODE_EXECPATH")
    if p and Path(p).is_file():
        return p
    found = sorted(Path.home().glob(
        ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe"))
    return str(found[-1]) if found else "claude"


PROFILE_NAME = os.environ.get("B2_MODEL", "luna")
if PROFILE_NAME not in PROFILES:
    raise SystemExit(f"B2_MODEL={PROFILE_NAME!r}: pick one of {', '.join(PROFILES)}")
PROFILE = PROFILES[PROFILE_NAME]

MODEL = PROFILE["model"]
REASONING_EFFORT = PROFILE["effort"]
# Override the profile's effort for one run (e.g. B2_EFFORT=xhigh); usage.json records it.
if os.environ.get("B2_EFFORT"):
    REASONING_EFFORT = os.environ["B2_EFFORT"]
PRICE = PROFILE["price"]
IMAGE_MODEL = "gpt-image-2"          # always OpenAI: the task briefs name it
HARNESS = PROFILE.get("harness", "b2")
AGENT_SCRIPT = "agent_claude.py" if HARNESS == "claude_code" else "agent.py"
if HARNESS == "claude_code":
    PROFILE["exe"] = claude_exe()

# ── Budget (fairness rule 3) ─────────────────────────────────────────────────
# Main-system builds: median $2.00 and ~515K output tokens. B2 gets the same
# order of budget with a stated hard cap; it is told when it crosses the soft
# line so it can wrap up and save rather than being cut off mid-edit.
SOFT_COST_USD = 2.50
HARD_COST_USD = 4.00
SOFT_WALL_MIN = 100
HARD_WALL_MIN = 180
MAX_TOOL_CALLS = 600

# Per run_python call. The agent may ask for up to MAX; past it Blender is
# restarted from the last checkpoint.
DEFAULT_EXEC_TIMEOUT_S = 600
MAX_EXEC_TIMEOUT_S = 2400
CHECKPOINT_EVERY_S = 300

# Context control: when a request's input passes this, older images and tool
# outputs are stubbed (see agent.prune_context).
PRUNE_AT_TOKENS = 200_000

# Review round: tool-call budget for the reviewer agent
REVIEW_MAX_CALLS = 40
REVIEW_WALL_MIN = 30           # claude_code harness: reviewer's own wall-clock cap

# claude_code harness only: how long an MCP tool call may block (the builder's
# first `finish` blocks for the whole review round), and how many times a run
# waits out a subscription usage limit before giving up.
MCP_TOOL_TIMEOUT_MS = 3_600_000
MAX_USAGE_WAITS = 6
# A session limit resets within hours and is worth waiting out; a weekly limit
# is not, so a wait longer than this ends the run instead (the scene is saved
# and the task is redone later) rather than holding Blender open for days.
MAX_USAGE_WAIT_S = int(os.environ.get("B2_MAX_USAGE_WAIT_S", 3 * 3600))
# A transient server error at Anthropic (529 Overloaded, 500, 503) is not the
# model giving up: it clears in minutes. These retries are counted separately
# from the three "you stopped without finishing" nudges, and the time spent
# waiting is added back to the run's clock. Worst case here is ~75 min of
# backoff before a run gives up and saves the scene.
MAX_API_RETRIES = 8
API_BACKOFF_BASE_S = 60
API_BACKOFF_CAP_S = 900

if HARNESS == "claude_code":
    # Nothing is billed per token, so money is not the budget: wall-clock and
    # tool calls are. The dollar caps are left effectively off, and usage.json
    # records the list-price equivalent Claude Code reports.
    SOFT_COST_USD, HARD_COST_USD = 1e9, 1e9

# Retrieval
MAX_PRELOADED_SKILLS = 8

# Ablation: B2_NO_LIBRARY=1 runs the identical agent with no skill library at
# all -- nothing copied in, no retrieval, no `load_skill` tool and no mention of
# skills in the prompt. Everything else (tools, review round, caps, bundling) is
# unchanged, so a no-library run is directly comparable with its normal run.
# Use a distinct B2_RUN_TAG so the two do not share output folders.
NO_LIBRARY = bool(os.environ.get("B2_NO_LIBRARY"))

# Plumbing tests only (B2_SMOKE=1): cheap effort and tiny caps. Never set for
# a real run; usage.json records the effort actually used.
if os.environ.get("B2_SMOKE"):
    REASONING_EFFORT = "low"
    SOFT_WALL_MIN, HARD_WALL_MIN = 8, 15
    if HARNESS != "claude_code":
        # A dollar cap would cut a subscription run short for no reason, and
        # would also skip its review round (see Agent.dispatch).
        SOFT_COST_USD, HARD_COST_USD = 0.3, 0.6


def load_keys() -> None:
    """API keys via the main system's loader (reads a file outside the repo)."""
    from blendcua_core import load_api_keys
    load_api_keys(verbose=False)


def cost_usd(uncached_in: int, cached_in: int, out: int, cache_write: int = 0) -> float:
    """`uncached_in` includes any `cache_write` tokens; those are billed at the
    profile's cache-write rate when it has one, else as plain input."""
    write_rate = PRICE.get("cache_write", PRICE["input"])
    return ((uncached_in - cache_write) * PRICE["input"] + cache_write * write_rate
            + cached_in * PRICE["cached_input"] + out * PRICE["output"]) / 1e6
