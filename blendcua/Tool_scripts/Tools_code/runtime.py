"""
Slim per-action helpers for BlendCUA. Hides the boilerplate every action
file would otherwise repeat: sys.path setup, mem/ folder creation,
checkpoint save, viewport render, status JSON write.

See BLENDCUA_AGENT.md (sections 4, 5, 6) for the convention. A Step is a
logical plan unit (a directory `steps/step_NNN/`); an Action is one
atomic code file inside that directory.

Typical usage at the top of an action file:

    from runtime import use, shot
    use("cup_run_001", step=2, action=1)
    # ... bpy work ...
    shot("top face selected and tagged")
"""

import bpy
import json
import os
import sys

import os as _os
ROOT       = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
TOOLS_CODE = _os.path.join(ROOT, "Tool_scripts", "Tools_code")

_RUN    = None
_STEP   = None
_ACTION = None

# ─── Screenshot toggle ────────────────────────────────────────────────────
# shot() used to always render the viewport (an OpenGL render + PNG write)
# after every single action, which is slow across a long replay. It's now
# OFF by default and controlled via a flag FILE (not a module global —
# blender_server.py drops this module from sys.modules and re-imports it
# fresh before every action, so any in-process state would not survive
# between actions). Toggle with `python Tool_scripts/run.py --shots ...` or
# `python Tool_scripts/run_steps.py --shots ...` (both write this flag file
# before sending scripts to Blender); omit --shots to keep it off.
_SHOTS_FLAG = os.path.join(ROOT, "mem", ".shots_enabled")


def shots_enabled():
    """True if per-action screenshots are currently switched on.

    The toggle is a file on disk rather than a module global because
    run.py and the Blender process are different processes — see the note
    above `set_shots`.
    """
    return os.path.exists(_SHOTS_FLAG)


def set_shots(enabled):
    """Flip the cross-process screenshot toggle. Called by run.py /
    run_steps.py at the start of an invocation (not from inside action
    scripts — see the note above on why a module global wouldn't stick).
    """
    if enabled:
        os.makedirs(os.path.dirname(_SHOTS_FLAG), exist_ok=True)
        open(_SHOTS_FLAG, "w").close()
    else:
        try:
            os.remove(_SHOTS_FLAG)
        except FileNotFoundError:
            pass


def use(run_name, step, action):
    """Initialize paths for this run/step/action and checkpoint the top of this action.

    Idempotent — safe to call at the top of every action file.
    Sets module-level state so `shot(...)` and `perceive.*` know which
    step+action this is.

    Returns (run_dir, step, action).
    """
    global _RUN, _STEP, _ACTION
    _RUN    = f"{ROOT}/mem/{run_name}"
    _STEP   = step
    _ACTION = action

    step_dir = f"{_RUN}/steps/step_{step:03d}"
    # scripts/ holds the agent's own throwaway diagnostic Python (PIL crops,
    # edge scans, mesh dumps). Nothing in here writes to it — it's created so
    # the agent never has to mkdir before saving one. Being a subdirectory, its
    # NN_*.py files are invisible to the action collectors.
    for sub in ("screenshots", "overlay_json", "scripts"):
        os.makedirs(f"{step_dir}/{sub}", exist_ok=True)

    if TOOLS_CODE not in sys.path:
        sys.path.insert(0, TOOLS_CODE)

    return _RUN, step, action


def shot(note="", enabled=None):
    """Render the current viewport for this action and write the status JSON.

    Step/action numbers come from the prior `use(...)` call. Overwrites any
    prior screenshot/status for this action — that's intentional (see §6
    of BLENDCUA_AGENT.md: edit-in-place retries).

    The actual viewport render is OFF by default (see shots_enabled() above)
    — the status JSON (which run.py/run_steps.py poll on) is always written
    either way, just with "shot": None when skipped. Pass `enabled=True` to
    force a render for THIS action only (e.g. one you specifically want to
    inspect), regardless of the global --shots flag; `enabled=False` to
    force-skip it even if --shots is on.
    """
    step_dir = f"{_RUN}/steps/step_{_STEP:03d}"
    path     = f"{step_dir}/screenshots/action_{_ACTION:02d}.png"

    do_render = shots_enabled() if enabled is None else enabled
    if do_render:
        from lib.view import render_viewport
        render_viewport(path)
    else:
        path = None

    with open(f"{_RUN}/last_step.json", "w") as f:
        json.dump(
            {"step": _STEP, "action": _ACTION,
             "ok": True, "shot": path, "note": note},
            f,
        )
    return path


def run_dir():
    """Return the current run directory (after `use(...)` has been called)."""
    return _RUN


def step_dir():
    """Return the current step directory `<run>/steps/step_NNN`."""
    return f"{_RUN}/steps/step_{_STEP:03d}"


def current():
    """Return (run, step, action) tuple."""
    return _RUN, _STEP, _ACTION
