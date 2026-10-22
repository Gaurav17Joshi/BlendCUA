"""Per-step .blend checkpoints, so a rewind does not re-execute earlier steps.

    from checkpoint import save_step, load_step

A rewind to step N action M currently replays *every* action from step 1
onward — compiled into one script with renders stubbed, which is already the
cheap version, but still real Blender work. Measured over the 2026-08-27 trial,
`edit` (which triggers a rewind) cost 138 minutes of the 240 minutes of Blender
time across three tasks, from half as many calls as `write_and_run`.

The work that a rewind repeats is entirely deterministic and already done once.
Saving the scene at the end of a step lets a later rewind start from that file
instead: load step N-1's checkpoint, replay only step N's earlier actions.

`save_as_mainfile(copy=True)` writes the file without making it the session's
current file, so the live session is untouched. `open_mainfile(load_ui=False)`
is what makes the load safe to use here: without it Blender adopts the saved
window layout, and the viewport size and editor split that were set up by hand
would be replaced on every rewind.
"""
import os
import time

import bpy


def _dir(run_name: str) -> str:
    root = os.environ.get("BLENDCUA_MEM") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "mem")
    d = os.path.join(root, run_name, "checkpoints")
    os.makedirs(d, exist_ok=True)
    return d


def path_for(run_name: str, step: int) -> str:
    """Return the absolute checkpoint path for ``run_name`` and ``step``."""
    return os.path.join(_dir(run_name), f"step_{step:03d}.blend")


def save_step(run_name: str, step: int) -> dict:
    """Write the scene as it stands at the end of `step`."""
    p = path_for(run_name, step)
    t0 = time.time()
    bpy.ops.wm.save_as_mainfile(filepath=p, copy=True, compress=True)
    dt = time.time() - t0
    size = os.path.getsize(p) if os.path.exists(p) else 0
    print(f"[checkpoint] saved step {step} -> {p} ({size/1e6:.1f} MB, {dt:.2f}s)")
    return {"ok": True, "path": p, "bytes": size, "seconds": dt}


def load_step(run_name: str, step: int) -> dict:
    """Restore the scene to the end of `step`. Keeps the current window layout."""
    p = path_for(run_name, step)
    if not os.path.exists(p):
        return {"ok": False, "error": f"no checkpoint for step {step}"}
    t0 = time.time()
    # load_ui=False is load-bearing: the saved file carries its own window
    # layout, and adopting it would undo the viewport setup done by hand.
    bpy.ops.wm.open_mainfile(filepath=p, load_ui=False)
    dt = time.time() - t0
    print(f"[checkpoint] loaded step {step} from {p} ({dt:.2f}s)")
    return {"ok": True, "path": p, "seconds": dt}


def latest_before(run_name: str, step: int) -> int | None:
    """Highest checkpointed step strictly below `step`, or None."""
    d = _dir(run_name)
    best = None
    for name in os.listdir(d):
        if name.startswith("step_") and name.endswith(".blend"):
            try:
                n = int(name[5:8])
            except ValueError:
                continue
            if n < step and (best is None or n > best):
                best = n
    return best
