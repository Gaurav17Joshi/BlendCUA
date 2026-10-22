"""Assemble many action files into ONE Blender script, replayed in one dispatch.

Why
---
Replaying a build one action at a time costs far more in harness overhead than
in Blender. Measured on `bat_gpt56luna_med` steps 1-4 (84 actions):

    win_run_steps.py, one action at a time ......... 51.0 s
    same 84 actions as a single batch, no render .... 4.2 s

...with byte-identical resulting geometry (every mesh hash matched; vertex
positions agreed to 9 decimal places). Of that 4.2 s, ~4.0 s is two heavy
actions; the other 82 total ~0.2 s.

The speedup comes from three places:
  * one socket round trip and one status-file write instead of 84,
  * no per-action PIL upscale of screenshots,
  * no viewport render at all — a rewind does not need pictures, only state.

Nothing is written to disk
--------------------------
The batch is assembled in memory from the action files, which stay the only
source of truth. Keeping a generated `build.py` around would create a second
representation of the same build that can silently drift out of sync — this
repo has already been bitten twice by exactly that (duplicate action-file
generations left behind in steps 1 and 2 of bat_gpt56luna_med, which made a
replay execute two different attempts interleaved).

Assumptions this relies on
--------------------------
* Action files are deterministic. Verified: three consecutive replays produced
  identical vertex positions.
* Actions select geometry by POSITION or landmark, never by hard-coded index.
  Vertex positions replay exactly, but face index ordering does NOT — 16 of
  BatLeg's 34 faces get different vertex indices on each replay. An action that
  hard-codes an index will silently target different geometry.
* Actions do not read back their own rendered screenshot. With rendering
  stubbed out, any PNG on disk is from an earlier run and therefore stale.
  Image analysis belongs in the shell (see prompt_files/terminal.md), not in a
  Blender action.
"""

import os
import re

ACTION_FILE_RE = re.compile(r"^(\d+)_.*\.py$")
STEP_DIR_RE = re.compile(r"^step_(\d+)$")

# Action numbers at or above this are review/render scaffolding
# (`90_review_render.py`), not build steps. They mutate nothing and only cost
# OpenGL renders, so a rewind skips them.
REVIEW_ACTION_MIN = 90


def collect_action_files(mem_dir, run_name, *, before_step=None, before_action=None):
    """Build-action files in execution order, optionally stopping early.

    before_step / before_action, when given, mean "everything that runs
    strictly BEFORE step `before_step` action `before_action`" — i.e. all
    earlier steps in full, plus this step's lower-numbered actions. That is
    exactly the state a retry of that action needs to start from.

    Returns a list of absolute paths.
    """
    steps_root = os.path.join(mem_dir, run_name, "steps")
    if not os.path.isdir(steps_root):
        return []

    out = []
    for step_name in sorted(os.listdir(steps_root)):
        m = STEP_DIR_RE.match(step_name)
        if not m:
            continue
        step_num = int(m.group(1))
        if before_step is not None and step_num > before_step:
            continue
        step_dir = os.path.join(steps_root, step_name)
        if not os.path.isdir(step_dir):
            continue

        acts = []
        for name in os.listdir(step_dir):
            am = ACTION_FILE_RE.match(name)
            if not am:
                continue                      # subdirs + review_*.py fall out here
            num = int(am.group(1))
            if num >= REVIEW_ACTION_MIN:
                continue
            if (before_step is not None and before_action is not None
                    and step_num == before_step and num >= before_action):
                continue
            acts.append((num, name, os.path.join(step_dir, name)))
        # Sort by number, then name — a step should never hold two files with
        # the same number, but if it does, be deterministic about it.
        acts.sort(key=lambda t: (t[0], t[1]))
        out += [p for _, _, p in acts]
    return out


def build_replay_script(files, tools_code, *, render=False, label="rewind"):
    """Return the source of a single script that runs `files` in order.

    render=False stubs the viewport render and the overlay drawer, which is
    what makes the batch fast. Pass True only if you actually need the images.

    Each action executes in its OWN globals dict, so a module-level name in one
    action cannot leak into another — plain concatenation would let action 3's
    `region` or `face` silently satisfy a NameError in action 12.

    A failing action re-raises with its filename attached, so the server's
    exec_status.json (which _dispatch_script already polls) reports which
    action broke rather than an anonymous traceback.
    """
    head = f'''# AUTO-GENERATED batch replay ({label}) — {len(files)} action(s). Do not save.
import sys, time, traceback
TOOLS_CODE = {tools_code!r}
# Force TOOLS_CODE to the FRONT, and drop any other spelling of the same
# directory. On Windows the corpus is reached through a junction, so the very
# same Tools_code can sit on sys.path under two names; whichever comes first
# decides runtime.ROOT, and runtime.ROOT is baked into every output path the
# actions record. A long-lived Blender session accumulates both spellings, so
# "insert only if absent" made the recorded paths depend on which pass had run
# earlier in the session.
for _p in [p for p in sys.path
           if p != TOOLS_CODE and p.replace(chr(92), "/").rstrip("/").endswith("Tools_code")]:
    sys.path.remove(_p)
while TOOLS_CODE in sys.path:
    sys.path.remove(TOOLS_CODE)
sys.path.insert(0, TOOLS_CODE)
import bpy
import runtime as _rt
import lib.view as _view
import lib.util as _util

_RENDER = {bool(render)!r}
_orig_shot = _rt.shot
_orig_render = _view.render_viewport
_orig_overlay = _util.run_overlay

if not _RENDER:
    # Patch the MODULES before any action imports from them. The Blender
    # server drops these modules from sys.modules before every dispatch, so
    # they are freshly imported here and every `from runtime import shot` /
    # `from lib.view import render_viewport` below binds the stub.
    _view.render_viewport = lambda path: None
    _util.run_overlay = lambda *a, **k: _util.OverlayResult(0)
    _rt.shot = lambda note="", enabled=None: None

_t0 = time.perf_counter()
_times = []
try:
'''

    body = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        name = os.path.basename(path)
        body.append(
            f"    _t = time.perf_counter()\n"
            f"    try:\n"
            f"        exec(compile({src!r}, {name!r}, 'exec'),\n"
            f"             {{'__name__': '__blendcua_action__', 'bpy': bpy}})\n"
            f"    except Exception as _e:\n"
            f"        raise RuntimeError(\n"
            f"            'batch replay failed at {name} '\n"
            f"            '(action %d of %d): %s\\n%s'\n"
            f"            % (len(_times) + 1, {len(files)}, _e, traceback.format_exc())\n"
            f"        ) from None\n"
            f"    _times.append(({name!r}, round(time.perf_counter() - _t, 4)))\n"
        )

    tail = f'''
finally:
    _rt.shot = _orig_shot
    _view.render_viewport = _orig_render
    _util.run_overlay = _orig_overlay

_elapsed = time.perf_counter() - _t0
_slow = ", ".join(f"{{n}}={{t}}s" for n, t in sorted(_times, key=lambda x: -x[1])[:3])
print(f"[BlendCUA] {label}: {len(files)} action(s) in {{_elapsed:.2f}}s | slowest: {{_slow}}")
'''
    return head + "".join(body) + tail
