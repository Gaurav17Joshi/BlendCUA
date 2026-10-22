"""B2's Blender-side server. Started by blender_link.py as

    blender.exe --factory-startup --python blender_server_b2.py

with B2_PORT in the environment. It is the same idea as
BlendCuavb_run/Tool_scripts/win_blender_server.py (a TCP socket that execs bpy
scripts on Blender's main thread via bpy.app.timers) with three differences
that a single `run_python` tool needs:

  * the result goes back over the SAME socket (stdout, stderr, traceback), so the
    agent sees what its code printed -- no status files;
  * scripts share one persistent namespace, like a REPL, until Blender restarts;
  * none of the main system's Tools_code / vendored modules are put on sys.path.

Protocol: 8-byte big-endian length + UTF-8 JSON {"code": str}; reply is the
same framing with {"ok", "output", "error", "elapsed_s"}.
"""

import bpy
import contextlib
import io
import json
import os
import socket
import struct
import sys
import threading
import time
import traceback

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PORT = int(os.environ.get("B2_PORT", "6680"))
NAMESPACE = {"bpy": bpy, "__name__": "__b2__"}
MAX_OUT = 200_000


def _recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("client closed")
        buf += chunk
    return buf


def _send(conn, obj):
    data = json.dumps(obj).encode("utf-8")
    conn.sendall(struct.pack(">Q", len(data)) + data)


def _enable_gpu():
    """Cycles in a fresh Blender renders on CPU. Turn on OPTIX (else CUDA) for
    every device this process can see; CUDA_VISIBLE_DEVICES picks the worker's GPUs."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = backend
                prefs.refresh_devices()
                devs = [d for d in prefs.devices if d.type == backend]
                if devs:
                    for d in prefs.devices:
                        d.use = d.type == backend
                    for sc in bpy.data.scenes:
                        sc.cycles.device = "GPU"
                    print(f"[b2] Cycles GPU: {backend} x{len(devs)}")
                    return
            except Exception:
                continue
    except Exception as e:
        print(f"[b2] GPU enable failed: {e}")


def _handle(conn):
    try:
        (n,) = struct.unpack(">Q", _recv_exact(conn, 8))
        req = json.loads(_recv_exact(conn, n).decode("utf-8"))
    except Exception as e:
        try:
            _send(conn, {"ok": False, "output": "", "error": f"bad request: {e}", "elapsed_s": 0})
        finally:
            conn.close()
        return

    code = req.get("code", "")
    done = threading.Event()
    result = {}

    def execute():
        out = io.StringIO()
        t0 = time.time()
        ok, err = True, None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                exec(compile(code, "<run_python>", "exec"), NAMESPACE)
        except BaseException:
            ok = False
            err = traceback.format_exc()
        text = out.getvalue()
        if len(text) > MAX_OUT:
            text = text[:MAX_OUT // 2] + "\n...[output truncated]...\n" + text[-MAX_OUT // 2:]
        result.update(ok=ok, output=text, error=err, elapsed_s=round(time.time() - t0, 2))
        done.set()
        return None

    bpy.app.timers.register(execute)
    done.wait()
    try:
        _send(conn, result)
    except OSError:
        pass
    finally:
        conn.close()


def _loop(sock):
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            break
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


def start():
    import builtins
    old = getattr(builtins, "_b2_server_sock", None)
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", PORT))
    s.listen(8)
    builtins._b2_server_sock = s
    threading.Thread(target=_loop, args=(s,), daemon=True).start()
    _enable_gpu()
    print(f"[b2] server listening on {PORT}")


start()
