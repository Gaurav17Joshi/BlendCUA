"""
Shared helpers: overlay invocation (`run_overlay`) and scene teardown
(`clear_scene`).

## run_overlay

Historically this shelled out to a subprocess, since Blender's bundled
Python doesn't ship PIL. On this Windows machine, spawning a fresh
python.exe subprocess from *inside* Blender's own process for every
single overlay call reproducibly failed silently under a real agentic
run — isolated tests of the exact same call succeeded 100% of the time
(including a 20-call rapid-fire stress test), yet a real run produced
zero overlay images across 20 real actions, with no error anywhere: the
old `run_overlay` never checked the subprocess's exit code, so a failure
just vanished. Same underlying issue class as the outer dispatch
subprocess bug fixed in blendcua_core.py — spawning a process from
inside a long-lived process is fragile here, so the fix is the same:
stop spawning one.

Pillow is vendored directly for Blender's own interpreter
(Tool_scripts/Tools_code/_vendor, installed via Blender's own
`python.exe -m pip install --target=_vendor Pillow` so the wheel's ABI
matches — Blender 5.2 ships Python 3.13, the system Python here is 3.12,
so a wheel from the wrong interpreter would fail to import). Each
overlay script still reads its args via `argparse`/`sys.argv` exactly as
it did as a subprocess entry point — `run_overlay` just executes it
in-process via `runpy` with `sys.argv` set to match, instead of spawning
a new process for it.
"""

import os
import runpy
import sys
import traceback

_VENDOR_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "_vendor")
)
if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)


def clear_scene(purge=True, keep_images=True):
    """Delete EVERY object and purge orphaned data — a genuinely clean slate.

    Use this instead of the `select_all(action='SELECT')` + `object.delete()`
    idiom at the top of an action-1 file. That idiom silently leaks, and it
    leaks worse the more you replay:

      * `select_all` cannot select an object with `hide_viewport=True`, so any
        object some later action hid (e.g. the reference empty, hidden to get
        a clean render) is never selected and never deleted.
      * `object.delete(use_global=False)` unlinks from the scene but leaves
        the datablock in `bpy.data` with zero users. Blender only purges those
        on file save/reload, and a replay never reloads.

    Either way the NAME stays taken, so the next `bpy.data.objects.new("BatRef",
    ...)` becomes `BatRef.001`, then `.002`. Measured on bat_gpt56luna_med:
    +1 stray object and +12 orphan meshes on every single replay.

    This version goes through `bpy.data` directly, so selection state,
    visibility and collection membership are all irrelevant.

    keep_images  Images are not purged by default: reference photos are
                 loaded with `check_existing=True` and get reused across
                 replays, so they never actually leak — dropping them just
                 forces a redundant reload. Pass False to purge them too.
    """
    import bpy

    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    if not purge:
        return

    collections = [bpy.data.meshes, bpy.data.curves, bpy.data.metaballs,
                   bpy.data.armatures, bpy.data.lattices, bpy.data.materials,
                   bpy.data.node_groups]
    if not keep_images:
        collections.append(bpy.data.images)

    # Loop: removing a mesh can orphan its material, which can orphan a node
    # group, so one pass is not enough. Bounded so a pathological cycle can't
    # spin forever inside Blender's main thread.
    for _ in range(8):
        removed = 0
        for coll in collections:
            for datablock in list(coll):
                if datablock.users == 0:
                    try:
                        coll.remove(datablock)
                        removed += 1
                    except (RuntimeError, ReferenceError):
                        pass
        if not removed:
            break


class OverlayResult:
    """Minimal stand-in for subprocess.CompletedProcess — no caller ever
    used more than this, but keeping the same shape avoids touching every
    call site."""

    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_overlay(script, *args, logger=print):
    """Invoke an overlay script with the given CLI args, in-process.

    Returns an OverlayResult (returncode/stdout/stderr) for parity with
    the old subprocess-based signature. Unlike the old version, a failure
    is always logged (`logger`, default `print`) — never silently
    swallowed.
    """
    prev_argv = sys.argv
    sys.argv = [script] + list(args)
    ok, err_text = True, ""
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            ok = False
            err_text = f"overlay script exited with code {e.code!r}"
    except Exception as e:
        ok = False
        err_text = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    finally:
        sys.argv = prev_argv

    if not ok:
        logger(f"[BlendCUA] overlay FAILED ({os.path.basename(script)}): {err_text}")

    return OverlayResult(0 if ok else 1, stderr=err_text)
