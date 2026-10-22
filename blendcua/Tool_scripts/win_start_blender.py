"""Start the GUI Blender with the BlendCUA server, from code, and fit the viewport.

    python Tool_scripts/win_start_blender.py            # start if not up, repoint if another folder's, fit viewport
    python Tool_scripts/win_start_blender.py --restart  # close any running blender.exe first
    python Tool_scripts/win_start_blender.py --status   # report and exit

What the manual setup was: open Blender, Scripting workspace, drag the 3D view bigger, Text -> Open ->
Tool_scripts/win_blender_server.py -> Run Script, then size the window so the
3D viewport is 800x600. This does the same:

    1. blender.exe --python Tool_scripts/win_blender_server.py   (detached, logs to mem/blender_gui.log)
    2. wait for the server's handshake in mem/exec_status.json
    3. switch the window to the Layout workspace (one big 3D view)
    4. Tool_scripts/win_fit_viewport.py until the viewport is 800x600
    5. blender_health.verify_server_folder()

blender_health.ensure_ready() calls up() when nothing listens on 6666, so a
crash mid-run is recovered without a person.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "Tool_scripts"
SERVER = TOOLS / "win_blender_server.py"
FITTER = TOOLS / "win_fit_viewport.py"
PORT = int(os.environ.get("BLENDCUA_PORT", "6666"))
STATUS = ROOT / "mem" / ("exec_status.json" if PORT == 6666 else f"exec_status_{PORT}.json")
GUI_LOG = ROOT / "mem" / ("blender_gui.log" if PORT == 6666 else f"blender_gui_{PORT}.log")
PID_FILE = ROOT / "mem" / f".blender_{PORT}.pid"

# The Layout workspace: one large 3D view, so sizing the OS window alone reaches
# 800x600 in a few passes. A fresh Scripting workspace gives the 3D view a
# quarter of the window and the window cannot grow enough; area edges cannot
# be dragged from a timer (area_move's poll fails), so Layout it is. Nothing
# in the tools depends on the workspace name, only on the viewport size.
WORKSPACE = "Layout"
SWITCH_WORKSPACE = """import bpy
ws = bpy.data.workspaces.get("{ws}")
win = bpy.context.window_manager.windows[0]
if ws is not None and win.workspace != ws:
    win.workspace = ws
"""


def find_blender() -> str | None:
    if os.environ.get("BLENDER"):
        return os.environ["BLENDER"]
    for base in (r"C:\Program Files\Blender Foundation", r"C:\Program Files (x86)\Blender Foundation"):
        if os.path.isdir(base):
            for name in sorted(os.listdir(base), reverse=True):
                exe = os.path.join(base, name, "blender.exe")
                if os.path.isfile(exe):
                    return exe
    return None


def port_open() -> bool:
    import socket
    try:
        with socket.create_connection(("localhost", PORT), timeout=2.0):
            return True
    except OSError:
        return False


def blender_pids() -> list[int]:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq blender.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == "blender.exe":
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def instance_pid() -> int | None:
    """The blender.exe that serves THIS port: from the pid file, else asked over the socket."""
    try:
        pid = int(PID_FILE.read_text().strip())
        if pid in blender_pids():
            return pid
    except (OSError, ValueError):
        pass
    if port_open():
        import blender_health
        out = ROOT / "mem" / f".pid_probe_{PORT}.txt"
        ok, _e, _dt = blender_health._send(f"import os\nopen(r'{out}', 'w').write(str(os.getpid()))\n", 20)
        try:
            return int(out.read_text().strip())
        except (OSError, ValueError):
            return None
    return None


def kill_blender(all_instances: bool = False) -> None:
    """Close this port's Blender (or every blender.exe with all_instances)."""
    pids = blender_pids() if all_instances else [p for p in [instance_pid()] if p]
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    for _ in range(20):
        if not any(p in blender_pids() for p in pids):
            return
        time.sleep(0.5)


def launch(blender: str) -> subprocess.Popen:
    GUI_LOG.parent.mkdir(exist_ok=True)
    log = open(GUI_LOG, "a", encoding="utf-8")
    log.write(f"\n=== launch {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    env = dict(os.environ, BLENDCUA_PORT=str(PORT))
    proc = subprocess.Popen([blender, "--python", str(SERVER)], cwd=str(ROOT), env=env,
                            stdout=log, stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
    PID_FILE.write_text(str(proc.pid))
    return proc


def wait_for_server(since: float, timeout: float = 120.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if STATUS.is_file() and STATUS.stat().st_mtime >= since and port_open():
            try:
                if "<server start>" in STATUS.read_text(encoding="utf-8"):
                    return True
            except OSError:
                pass
        time.sleep(1.0)
    return False


def fit_viewport(width: int = 800, height: int = 600) -> bool:
    import blender_health
    ok, err, dt = blender_health._send(SWITCH_WORKSPACE.format(ws=WORKSPACE), 30)
    if not ok:
        print(f"[start] workspace switch failed: {str(err)[-200:]}")
    time.sleep(1.0)
    rc = subprocess.call([sys.executable, str(FITTER), "--width", str(width), "--height", str(height)], cwd=str(ROOT))
    return rc == 0


def status() -> dict:
    import blender_health
    d = {"port_number": PORT, "pids": blender_pids(), "this_instance_pid": instance_pid(), "port": port_open(), "ours": None, "viewport": None}
    if d["port"]:
        ok, msg = blender_health.verify_server_folder()
        d["ours"] = ok
        d["ours_msg"] = msg
        r = subprocess.run([sys.executable, str(FITTER), "--measure"], capture_output=True, text=True, cwd=str(ROOT))
        d["viewport"] = (r.stdout or "").strip().splitlines()[:1]
    return d


def up(*, restart: bool = False, width: int = 800, height: int = 600) -> bool:
    """Make sure THIS folder's server is listening in a GUI Blender with the viewport fitted."""
    import blender_health
    if restart:
        print("[start] closing running Blender")
        kill_blender()
    if port_open():
        ok, msg = blender_health.verify_server_folder()
        if ok:
            print(f"[start] server already up: {msg}")
            return fit_viewport(width, height)
        print(f"[start] server belongs to another folder ({msg}); repointing")
        rc = subprocess.call([sys.executable, str(ROOT / "vb" / "repoint_server.py")], cwd=str(ROOT))
        if rc == 0:
            return fit_viewport(width, height)
        print("[start] repoint failed; restarting Blender")
        kill_blender()
    elif instance_pid():
        print(f"[start] this port's blender.exe (pid {instance_pid()}) is up but nothing listens on {PORT}; restarting it")
        kill_blender()

    blender = find_blender()
    if not blender:
        print("[start] no blender.exe found (set BLENDER)")
        return False
    print(f"[start] launching {blender} --python {SERVER.relative_to(ROOT)}")
    since = time.time()
    launch(blender)
    if not wait_for_server(since):
        print(f"[start] no handshake within 120 s; see {GUI_LOG.relative_to(ROOT)}")
        return False
    print(f"[start] server handshake in {time.time() - since:.0f}s")
    ok, msg = blender_health.verify_server_folder()
    if not ok:
        print(f"[start] {msg}")
        return False
    time.sleep(2.0)  # let the window finish drawing before it is resized
    return fit_viewport(width, height)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restart", action="store_true", help="close this port's blender.exe first")
    ap.add_argument("--kill-all", action="store_true", help="with --restart: close every blender.exe")
    ap.add_argument("--port", type=int, default=None, help="Blender port (default BLENDCUA_PORT or 6666)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=600)
    a = ap.parse_args()
    if a.port and a.port != PORT:
        # os.execv on Windows spawns and returns, so re-run as a child and wait for it
        env = dict(os.environ, BLENDCUA_PORT=str(a.port))
        argv = [sys.executable, __file__] + [x for x in sys.argv[1:] if not x.startswith("--port") and x != str(a.port)]
        sys.exit(subprocess.call(argv, env=env, cwd=str(ROOT)))
    if a.status:
        for k, v in status().items():
            print(f"  {k}: {v}")
        return
    if a.restart and a.kill_all:
        kill_blender(all_instances=True)
    ok = up(restart=a.restart, width=a.width, height=a.height)
    print("[start] READY" if ok else "[start] NOT READY")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
