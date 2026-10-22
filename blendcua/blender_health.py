"""Keep Blender healthy across a multi-task run, without needing a human.

Two things, both used by run_v2.py:

    probe()            how long a trivial script takes to round-trip
    cleanup()          empty the scene between tasks, keep the window layout
    wait_until_healthy()   pause the loop and wait for a restart, if it comes to that

Why this exists. Scripts execute on Blender's main thread via `bpy.app.timers`,
so a heavy scene slows every dispatch. `_dispatch_script` gives up at 30 s and
reports "Blender hung?" — but the action is still running, and the agent retries
it. On the 2026-08-27 cardboard-box run that produced four attempts at one
action and a step that advanced with no review at all.

Restarting Blender between tasks fixes it, but a restart is manual: the window
layout and viewport size have to be set up by hand afterwards. So the order of
preference is

    1. cleanup()  after every task  — automatic, keeps the window, handles most of it
    2. probe()    before every task — catch the case cleanup did not fix
    3. ask the human, and wait     — only when 1 and 2 say it is genuinely degraded
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import blendcua_core as core

ROOT = Path(__file__).resolve().parent

# A trivial script should round-trip in well under a second. Two seconds means
# the main thread is busy; five means the next real action is at risk of the
# 30 s timeout, because a render is far more work than `pass`.
SLOW_S = 2.0
CRITICAL_S = 5.0

_PROBE = """import bpy
"""

_CLEANUP = """import sys
TOOLS_CODE = r"{tools}"
if TOOLS_CODE not in sys.path:
    sys.path.insert(0, TOOLS_CODE)
from cleanup import reset_scene
reset_scene()
"""


def _send(script: str, timeout: float) -> tuple[bool, str, float]:
    """Dispatch a raw script (no use()/shot()). Returns (ok, err, seconds)."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     dir=str(ROOT / "mem"), encoding="utf-8") as fh:
        fh.write(script)
        path = Path(fh.name)
    t0 = time.time()
    try:
        ok, err = core._dispatch_script(path, timeout=timeout, shots=False)
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return ok, err, time.time() - t0


def verify_server_folder(timeout: float = 25.0) -> tuple[bool, str]:
    """Check the running server belongs to THIS project folder.

    `blender_server.py` writes its handshake to `<its own ROOT>/mem/
    exec_status.json`, and `_dispatch_script` polls `<our ROOT>/mem/
    exec_status.json`. Start the server from a different checkout — easy to do
    when several exist side by side — and the two never meet: the script runs,
    the screenshots and renders land correctly (they resolve from the script's
    own TOOLS_CODE path), and the client still reports

        dispatch did not return within 30s (Blender hung?)

    for every action, forever. The agent then retries work that already
    succeeded. This cost a whole cardboard-box run on 2026-08-27, and looked
    exactly like Blender being overloaded.

    The test: dispatch a script that writes a marker into *our* mem/. If the
    marker appears but our exec_status.json never moves, the server is alive and
    executing our scripts but keeping its books somewhere else.
    """
    marker = ROOT / "mem" / ".server_folder_probe"
    marker.unlink(missing_ok=True)
    nonce = str(time.time())
    script = (f"open(r'{marker}', 'w').write({nonce!r})\n")

    before = core._read_exec_status() or {}
    ok, err, dt = _send(script, timeout)
    after = core._read_exec_status() or {}

    ran = marker.exists() and marker.read_text(encoding="utf-8").strip() == nonce
    marker.unlink(missing_ok=True)

    if ok:
        return True, f"server is this folder's ({dt:.1f}s)"
    if ran:
        return False, (
            "MISMATCH: Blender ran the script (the marker was written) but the "
            "handshake never arrived. blender_server.py is running from a "
            "DIFFERENT project folder, so every dispatch will time out while "
            "actually succeeding. Re-run blender_server.py from:\n"
            f"    {ROOT / 'Tool_scripts' / 'blender_server.py'}"
        )
    return False, f"no response and no marker — Blender may genuinely be stuck ({err})"


def probe(timeout: float = 20.0) -> tuple[bool, float, str]:
    """(healthy, seconds, note) for a trivial round trip."""
    ok, err, dt = _send(_PROBE, timeout)
    if not ok:
        return False, dt, f"probe failed: {err}"
    if dt >= CRITICAL_S:
        return False, dt, f"round trip {dt:.1f}s (critical above {CRITICAL_S:g}s)"
    if dt >= SLOW_S:
        return True, dt, f"round trip {dt:.1f}s — slow but usable"
    return True, dt, f"round trip {dt:.1f}s"


def cleanup(timeout: float = 120.0) -> tuple[bool, str]:
    """Empty the scene and free its data. The window layout is left alone."""
    script = _CLEANUP.format(tools=str(ROOT / "Tool_scripts" / "Tools_code"))
    ok, err, dt = _send(script, timeout)
    print(f"[health] cleanup {'ok' if ok else 'FAILED'} in {dt:.1f}s"
          + ("" if ok else f" — {err}"))
    return ok, err


def wait_until_healthy(*, poll_s: float = 15.0, max_wait_s: float = 3600.0) -> bool:
    """Ask for a restart, then wait for one. Returns False if nobody came.

    Deliberately polls rather than reading stdin: the loop is usually running
    in the background, where there is nothing to read from. Restarting Blender
    and re-running blender_server.py is detected on its own.
    """
    print("\n" + "=" * 72)
    print("[health] Blender is too slow to continue safely.")
    print("[health] Please restart it:")
    print("[health]   1. close Blender")
    print("[health]   2. reopen it and set the viewport up as usual")
    print("[health]   3. or just: python Tool_scripts/win_start_blender.py --restart")
    print("[health] The loop resumes on its own once it responds again.")
    print("=" * 72 + "\n", flush=True)

    waited = 0.0
    while waited < max_wait_s:
        time.sleep(poll_s)
        waited += poll_s
        healthy, dt, note = probe()
        if healthy:
            print(f"[health] back after {waited/60:.1f} min — {note}", flush=True)
            return True
        if int(waited) % 300 < poll_s:
            print(f"[health] still waiting ({waited/60:.0f} min) — {note}", flush=True)
    print("[health] gave up waiting for a restart", flush=True)
    return False


def ensure_ready(*, task: str = "") -> bool:
    """Called by run_v2.py before a task. Cleans, probes, escalates if needed."""
    if not core.check_blender():
        print(f"[health] Blender is not listening on {core._BLENDER_PORT} — starting it")
        try:
            sys.path.insert(0, str(ROOT / "Tool_scripts"))
            import win_start_blender
            if win_start_blender.up():
                return ensure_ready(task=task)
        except Exception as e:  # noqa: BLE001
            print(f"[health] automatic start failed: {e}")
        return wait_until_healthy()

    # Before anything else: is the server even ours? A mismatch is silent and
    # looks identical to Blender being overloaded, so it has to be ruled out
    # first rather than diagnosed after an hour of timeouts.
    ok, msg = verify_server_folder()
    if not ok:
        print(f"[health] {msg} — repointing it at this folder")
        try:
            sys.path.insert(0, str(ROOT / "Tool_scripts"))
            import win_start_blender
            if win_start_blender.up():
                ok, msg = verify_server_folder()
        except Exception as e:  # noqa: BLE001
            print(f"[health] repoint failed: {e}")
        if not ok:
            print(f"[health] {msg}")
            return wait_until_healthy()

    healthy, dt, note = probe()
    print(f"[health] before {task or 'task'}: {note}")
    if healthy and dt < SLOW_S:
        return True

    # One cleanup is worth trying before troubling anyone.
    print("[health] running cleanup and re-probing")
    cleanup()
    healthy, dt, note = probe()
    print(f"[health] after cleanup: {note}")
    if healthy:
        return True
    return wait_until_healthy()


# ── CLI ──────────────────────────────────────────────────────────────────────
#
# The curator has `bash` but not `write_and_run`, so its only way to ask "is
# Blender up before I try a replay?" is a shell command.

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Blender server health")
    ap.add_argument("--probe", action="store_true", help="time a trivial round-trip")
    ap.add_argument("--cleanup", action="store_true", help="purge the scene, then probe")
    ap.add_argument("--ensure", action="store_true", help="clean/escalate until healthy")
    a = ap.parse_args()

    if a.ensure:
        raise SystemExit(0 if ensure_ready() else 1)
    if a.cleanup:
        cleanup()
    if not core.check_blender():
        print(f"[health] Blender is not listening on {core._BLENDER_PORT}")
        raise SystemExit(1)
    ok, dt, note = probe()
    print(f"[health] {note}")
    raise SystemExit(0 if ok else 1)
