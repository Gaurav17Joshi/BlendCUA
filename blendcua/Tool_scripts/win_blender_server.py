"""
WINDOWS VERSION — run this ONCE in Blender's Script Editor (Text Editor -> Run Script).
It starts a TCP server on port 6666 that listens for bpy scripts sent
from run.py / run_steps.py, then executes them safely on Blender's main thread.

Errors from execed scripts go to mem/server_errors.log (cat it after a
TIMEOUT to see the traceback — Blender's GUI build hides stdout).
"""

import bpy
import json
import socket
import sys
import threading
import traceback
import os
import importlib
from datetime import datetime

# Blender's console on Windows defaults stdout to the system codepage (e.g.
# cp1252), not UTF-8 like macOS — action scripts can print non-ASCII status
# text that would otherwise raise UnicodeEncodeError inside the exec'd script.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = int(os.environ.get("BLENDCUA_PORT", "6666"))

# Project root. __file__ is unreliable in Blender's Text Editor (a pasted /
# unlinked text block resolves to a bogus path like "/Text"), so verify the
# derived root actually looks like the project and fall back to the hardcoded
# location otherwise.
_DEFAULT_ROOT = r"C:\Users\render\Joshi\Blenduse\BlendCuavb_run"
try:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    ROOT = _DEFAULT_ROOT
if not os.path.isdir(os.path.join(ROOT, "Tool_scripts")):
    ROOT = _DEFAULT_ROOT

LOG_FILE = os.path.join(ROOT, "mem", "server_errors.log" if PORT == 6666 else f"server_errors_{PORT}.log")

# Completion marker — bumped after EVERY script execution (success or error)
# so run.py can block until the script actually finishes instead of
# fire-and-forget. {"seq": N, "ok": bool, "error": str|None, ...}
STATUS_FILE = os.path.join(ROOT, "mem", "exec_status.json" if PORT == 6666 else f"exec_status_{PORT}.json")

# ─── Vendored Pillow ──────────────────────────────────────────────────────
# Nine actions across runs 08, 09, 14 and 18 do a bare `from PIL import Image`.
# Blender ships no Pillow, so the project vendors it into Tools_code/_vendor.
# lib/util.py is what normally puts _vendor on sys.path — but those nine
# actions import only `runtime`, and runtime imports just bpy/json/os/sys.
# Whether they find Pillow therefore depended on whether something ELSE had
# already imported lib.util into this Blender session, i.e. on dispatch order.
# Do it once here so it is true for every action however the run is sliced.
_VENDOR = os.path.join(ROOT, "Tool_scripts", "Tools_code", "_vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

# ─── Working directory ────────────────────────────────────────────────────
# Some actions use relative literals ("plans/...", "mem/...").  Those resolved
# on the original machine because the recording process's cwd was the project
# root.  A Blender started from Explorer inherits its own install directory
# instead (C:\Program Files\Blender Foundation\Blender 5.2), so the same
# literals would resolve under Program Files and raise.  Anchor them.
try:
    os.chdir(ROOT)
except OSError as _e:
    print(f"[BlendCUA] could not chdir to {ROOT}: {_e}")


def _init_seq():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("seq", 0))
    except Exception:
        return 0


_EXEC_SEQ = {"n": _init_seq()}


def _write_status(ok, err_text, script_preview):
    """Atomically write the per-execution completion marker."""
    _EXEC_SEQ["n"] += 1
    payload = {
        "seq":    _EXEC_SEQ["n"],
        "ok":     ok,
        "error":  (err_text[-4000:] if err_text else None),
        "script": script_preview,
        "time":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        tmp = STATUS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        # os.replace (not os.rename) — on Windows, rename fails outright if
        # the destination already exists, whereas replace overwrites it
        # atomically like POSIX rename does.
        os.replace(tmp, STATUS_FILE)
    except Exception as e:
        print(f"[BlendCUA] could not write exec status: {e}")

# Tool modules whose disk edits we want every script to pick up without
# restarting Blender. Drop them from sys.modules before each exec so the
# action's `from runtime/perceive/landmarks import ...` re-reads the file.
# This used to be a hand-maintained list of module names, which meant any tool
# written after the list was last edited stayed cached: the curator would write
# a tool, import it, fix it, re-dispatch, and Blender would keep serving the
# first version with no error to say so. The set is now derived from the
# directory, so a tool authored ten minutes ago reloads like any other.
# Derived from ROOT, not from __file__: ROOT is already validated with a
# fallback above, and __file__ is undefined when this script is re-sent
# through the socket to replace a running server.
_TOOLS_CODE = os.path.join(ROOT, "Tool_scripts", "Tools_code")
_TOOL_PKGS  = ("lib",)


def _tool_module_names():
    """Every top-level module living in Tools_code, read fresh each dispatch."""
    try:
        return {f[:-3] for f in os.listdir(_TOOLS_CODE)
                if f.endswith(".py") and not f.startswith("__")}
    except OSError:
        return set()


def _prioritise_tools_path():
    """Make _TOOLS_CODE the first Tools_code on sys.path, every dispatch.

    On Windows the corpus is reached through a directory junction, so the very
    same Tools_code directory can sit on sys.path under two different names
    (the junction spelling and the real folder). Whichever appears first is
    where `import runtime` resolves from -- and runtime.ROOT, derived from that
    file's location, is then baked into every output path the actions record in
    their JSON reports.

    Actions insert their own path only "if not already present", so once both
    spellings were on sys.path the recorded paths depended on which pass had
    happened to run earlier in this Blender session. Reports from the same run
    disagreed with each other. Pinning the order here makes every dispatch
    resolve identically no matter what ran before it.
    """
    canonical = os.path.normcase(os.path.abspath(_TOOLS_CODE))
    for entry in list(sys.path):
        norm = os.path.normcase(os.path.abspath(entry)) if entry else ""
        if norm.endswith(os.path.normcase("Tools_code")) and norm != canonical:
            try:
                if os.path.isdir(entry) and os.path.samefile(entry, _TOOLS_CODE):
                    sys.path.remove(entry)
            except OSError:
                pass
    while _TOOLS_CODE in sys.path:
        sys.path.remove(_TOOLS_CODE)
    sys.path.insert(0, _TOOLS_CODE)
    if os.path.isdir(_VENDOR):
        while _VENDOR in sys.path:
            sys.path.remove(_VENDOR)
        sys.path.insert(0, _VENDOR)


def _drop_cached_tool_modules():
    names = _tool_module_names()
    for k in list(sys.modules):
        if k in names:
            del sys.modules[k]
        elif k in _TOOL_PKGS or any(k.startswith(p + ".") for p in _TOOL_PKGS):
            del sys.modules[k]
    importlib.invalidate_caches()


def _log_error(script_preview):
    """Append the current exception's full traceback to mem/server_errors.log."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 70 + "\n")
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
        f.write(f"first line of script: {script_preview}\n")
        f.write(traceback.format_exc())
        f.write("\n")


def receive_script(conn):
    chunks = []
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    conn.close()
    script = b"".join(chunks).decode("utf-8")
    first_line = next((ln for ln in script.splitlines() if ln.strip()), "<empty>")

    def execute():
        _drop_cached_tool_modules()
        _prioritise_tools_path()
        ok, err = True, None
        try:
            exec(compile(script, "<blendcua>", "exec"), {"bpy": bpy})
        except Exception as e:
            ok = False
            err = traceback.format_exc()
            print(f"[BlendCUA] Error executing script: {e}")
            _log_error(first_line)
        _write_status(ok, err, first_line)
        return None  # returning None unregisters the timer

    bpy.app.timers.register(execute)


def server_loop(server_sock):
    print(f"[BlendCUA] Server listening on port {PORT}")
    while True:
        try:
            conn, _ = server_sock.accept()
            t = threading.Thread(target=receive_script, args=(conn,), daemon=True)
            t.start()
        except OSError:
            break


def start_server():
    # Re-running this script must REPLACE the old server, not die with
    # "Address already in use" while the stale listener keeps serving.
    # The previous socket is stashed on builtins (survives this script's
    # globals being torn down); closing it makes the old server_loop's
    # accept() raise OSError and exit.
    import builtins
    old = getattr(builtins, "_blendcua_server_sock", None)
    if old is not None:
        try:
            old.close()
            print("[BlendCUA] closed previous server socket — replacing server")
        except Exception:
            pass

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("localhost", PORT))
    server_sock.listen(5)
    builtins._blendcua_server_sock = server_sock
    t = threading.Thread(target=server_loop, args=(server_sock,), daemon=True)
    t.start()

    # Startup marker: proves from OUTSIDE Blender that THIS version of the
    # server is the one listening (check: cat mem/exec_status.json).
    _write_status(True, None, "<server start>")
    print(f"[BlendCUA] exec status file: {STATUS_FILE}")


start_server()
