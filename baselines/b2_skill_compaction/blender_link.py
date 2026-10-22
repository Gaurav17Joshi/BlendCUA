"""The Blender connection for B2: one GUI Blender per worker, driven over TCP.

Channel: the TCP fallback the brief allows, not BlenderMCP. BlendCuavb_run
already drives Blender through an in-Blender socket server; B2 uses the same
mechanism (blender_server_b2.py) behind a single `run_python(code)` call, so the
two systems reach Blender the same way and differ only in harness.

    link = BlenderLink(worker=0, log_dir=run_dir)
    link.start()                       # fresh --factory-startup Blender
    res = link.run_python("print(len(bpy.data.objects))")
    link.save(path)                    # packed .blend
    link.stop()
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
import time
from pathlib import Path

import b2_config as CFG

SERVER_SCRIPT = CFG.ROOT / "blender_server_b2.py"


class BlenderTimeout(Exception):
    pass


class BlenderDown(Exception):
    pass


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("server closed the connection")
        buf += chunk
    return buf


def ensure_start_blend() -> Path:
    """Blender's factory-default scene (cube, camera, light), saved once."""
    path = CFG.STATE / "factory_start.blend"
    if not path.is_file():
        CFG.STATE.mkdir(parents=True, exist_ok=True)
        expr = f"import bpy; bpy.ops.wm.save_as_mainfile(filepath={str(path)!r})"
        subprocess.run([CFG.BLENDER, "-b", "--factory-startup", "--python-expr", expr],
                       capture_output=True, timeout=300)
    return path


class BlenderLink:
    def __init__(self, worker: int, log_dir: Path):
        self.worker = worker
        self.port = CFG.WORKERS[worker]["port"]
        self.gpus = CFG.WORKERS[worker]["gpus"]
        self.geometry = CFG.WORKERS[worker]["geometry"]
        self.log_dir = Path(log_dir)
        self.proc: subprocess.Popen | None = None
        self.pid_file = CFG.STATE / f"blender_worker{worker}.pid"

    # ── process ────────────────────────────────────────────────────────────
    def port_open(self) -> bool:
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=2).close()
            return True
        except OSError:
            return False

    def _kill_stale(self) -> None:
        try:
            pid = int(self.pid_file.read_text().strip())
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            time.sleep(2)
        except (OSError, ValueError):
            pass

    def start(self, open_blend: Path | None = None, timeout: float = 180) -> None:
        self.stop()
        self._kill_stale()
        if self.port_open():
            raise RuntimeError(f"port {self.port} is taken by something that is not this worker")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log = open(self.log_dir / "blender_console.log", "a", encoding="utf-8", errors="replace")
        log.write(f"\n=== launch {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        log.flush()
        env = dict(os.environ, B2_PORT=str(self.port), CUDA_VISIBLE_DEVICES=self.gpus,
                   PYTHONDONTWRITEBYTECODE="1")
        x, y, w, h = self.geometry
        argv = [CFG.BLENDER, "--factory-startup", "--window-geometry", str(x), str(y), str(w), str(h)]
        # Opening a file on the command line suppresses the splash screen,
        # which would otherwise sit over the viewport in every screenshot.
        # A per-run copy, so a bare save_mainfile() cannot overwrite the shared one.
        if open_blend is None:
            open_blend = self.log_dir / "session_start.blend"
            shutil.copy2(ensure_start_blend(), open_blend)
        argv.append(str(open_blend))
        argv += ["--python", str(SERVER_SCRIPT)]
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.proc = subprocess.Popen(argv, cwd=str(self.log_dir), env=env, stdout=log,
                                     stderr=subprocess.STDOUT, creationflags=flags)
        CFG.STATE.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(self.proc.pid))
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(f"Blender exited during startup (rc={self.proc.returncode})")
            if self.port_open():
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"Blender did not open port {self.port} within {timeout}s")
        time.sleep(2)  # let the window finish its first draw
        r = self.run_python("import bpy; print(bpy.app.version_string)", timeout=60)
        if not r["ok"]:
            raise RuntimeError(f"Blender server not answering: {r}")

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None and self.port_open()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass
        self.proc = None

    # ── calls ──────────────────────────────────────────────────────────────
    def run_python(self, code: str, timeout: float = CFG.DEFAULT_EXEC_TIMEOUT_S) -> dict:
        """Exec `code` in Blender. Returns {ok, output, error, elapsed_s}.
        Raises BlenderTimeout if no answer in `timeout`, BlenderDown if unreachable."""
        data = json.dumps({"code": code}).encode("utf-8")
        try:
            s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        except OSError as e:
            raise BlenderDown(str(e))
        try:
            s.settimeout(timeout)
            s.sendall(struct.pack(">Q", len(data)) + data)
            (n,) = struct.unpack(">Q", _recv_exact(s, 8))
            return json.loads(_recv_exact(s, n).decode("utf-8"))
        except socket.timeout:
            raise BlenderTimeout(f"no result after {timeout:.0f}s")
        except (ConnectionError, OSError) as e:
            if not self.alive():
                raise BlenderDown(f"Blender died during the call: {e}")
            raise BlenderDown(str(e))
        finally:
            s.close()

    def screenshot(self, path: Path) -> dict:
        """Capture the GUI's largest 3D viewport to `path` (PNG)."""
        code = f'''
import bpy
out = {str(path)!r}
win = bpy.context.window_manager.windows[0]
areas = [a for a in win.screen.areas if a.type == "VIEW_3D"]
if not areas:
    raise RuntimeError("no 3D viewport in the window")
area = max(areas, key=lambda a: a.width * a.height)
region = next(r for r in area.regions if r.type == "WINDOW")
with bpy.context.temp_override(window=win, area=area, region=region):
    bpy.ops.screen.screenshot_area(filepath=out)
print("viewport", area.width, "x", area.height)
'''
        return self.run_python(code, timeout=120)

    def save(self, path: Path, *, copy: bool = False, timeout: float = 900) -> dict:
        """Save the scene. The final save (copy=False) packs every image so the
        .blend is self-contained; a checkpoint (copy=True) packs only GENERATED
        images, which would otherwise be lost, and leaves the session's own
        file path and on-disk image links alone."""
        sources = '{"GENERATED"}' if copy else '{"GENERATED", "FILE"}'
        code = f'''
import bpy, os
out = {str(path)!r}
os.makedirs(os.path.dirname(out), exist_ok=True)
packed = 0
for im in bpy.data.images:
    if im.source in {sources} and not im.packed_file:
        try:
            im.pack(); packed += 1
        except Exception as e:
            print("pack failed", im.name, e)
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True, copy={copy!r})
print("saved", out, round(os.path.getsize(out) / 1e6, 2), "MB; packed", packed)
'''
        return self.run_python(code, timeout=timeout)
