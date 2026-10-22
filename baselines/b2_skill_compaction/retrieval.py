"""Skill selection before a task.

Method: the library's index (name, description, when-to-use, function names)
is shown to the same model as the agent together with the task brief and its
main reference image, and the model picks up to MAX_PRELOADED_SKILLS names.
Those skills go into the agent's first message in full (doc + code). The whole
index is ALSO listed in the agent's prompt, and any other skill can be pulled
in during the task with the `load_skill` tool; every skill is importable in
Blender regardless. So retrieval decides what is in context up front, never
what is reachable.

Why an LLM pick rather than embeddings: the library is small (tens of skills),
its entries are written by the same model, and the index fits in one prompt,
so the selector can read every candidate; embedding similarity on a
two-sentence brief would add a second model and a threshold to tune.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import b2_config as CFG
import library as L
import llm

SCHEMA = {
    "type": "object",
    "properties": {
        "selected": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["selected", "reason"],
    "additionalProperties": False,
}


def _prompt(task: str, task_text: str, index: dict) -> str:
    return (
        "You are choosing which skills from a Blender skill library to load into an "
        "agent's context before it starts the task below. The agent writes bpy code; each "
        "skill is a Python module of functions plus a doc. Pick every skill that is likely "
        f"to be directly useful for this task (at most {CFG.MAX_PRELOADED_SKILLS}); pick none "
        "if none fit. Return names exactly as listed.\n\n"
        f"## Task {task}\n\n{task_text}\n\n## Library\n\n{L.index_listing(index)}\n"
    )


def select(task: str, task_text: str, ref_image: Path | None, index: dict, *,
           usage, log=print) -> tuple[list[str], str]:
    """Return (selected skill names, reason). Empty library -> ([], ...)."""
    if not index:
        return [], "library empty"
    if CFG.HARNESS == "claude_code":
        return _select_claude(task, task_text, index, usage=usage, log=log)
    prompt = _prompt(task, task_text, index)
    content = [{"type": "input_text", "text": prompt}]
    if ref_image and ref_image.is_file():
        content.append(llm.image_part(ref_image, max_side=1024))
    r, dt = llm.create(
        input=[{"role": "user", "content": content}],
        text={"format": {"type": "json_schema", "name": "skill_selection",
                         "schema": SCHEMA, "strict": True}},
        log=log)
    usage.add(r.usage, dt)
    try:
        data = json.loads(r.output_text)
    except json.JSONDecodeError:
        return [], f"unparseable selection: {r.output_text[:200]}"
    picked = [n for n in data.get("selected", []) if n in index][:CFG.MAX_PRELOADED_SKILLS]
    return picked, data.get("reason", "")


def _select_claude(task: str, task_text: str, index: dict, *, usage, log=print
                   ) -> tuple[list[str], str]:
    """The same pick, made by a headless Claude Code call with no tools, so the
    Claude entrant's retrieval runs on the same account and model as its agent.
    The reference image is left out: this call has no tool with which to open
    one, and the brief alone decides the pick."""
    import os
    import subprocess
    import time

    # The prompt goes in on stdin: the index alone can pass Windows' 32K
    # command-line limit once the library is large.
    argv = [CFG.PROFILE["exe"], "-p",
            "--output-format", "json", "--model", CFG.MODEL, "--effort", "high",
            "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--permission-mode", "bypassPermissions", "--permission-prompts", "none",
            "--no-session-persistence",
            "--json-schema", json.dumps(SCHEMA)]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_CODE_", "ANTHROPIC_"))}
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_EFFORT", None)
    t0 = time.time()
    try:
        p = subprocess.run(argv, input=_prompt(task, task_text, index), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=900, env=env)
        msg = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        log(f"[retrieval] claude call failed: {type(e).__name__}: {e}")
        return [], f"retrieval failed: {type(e).__name__}"
    usage.add_result(msg, time.time() - t0)
    raw = msg.get("result")
    data = raw if isinstance(raw, dict) else None
    if data is None and isinstance(raw, str):
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            data = json.loads(m.group(0) if m else raw)
        except (json.JSONDecodeError, AttributeError):
            return [], f"unparseable selection: {str(raw)[:200]}"
    if not isinstance(data, dict):
        return [], "unparseable selection"
    picked = [n for n in data.get("selected", []) if n in index][:CFG.MAX_PRELOADED_SKILLS]
    return picked, data.get("reason", "")
