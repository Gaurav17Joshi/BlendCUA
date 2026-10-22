"""Point the running Blender server at THIS folder without restarting Blender.

    python vb/repoint_server.py

Re-sends Tool_scripts/win_blender_server.py over the live socket with ROOT
pinned here, then waits for the handshake in mem/exec_status.json. Use it when
blender_health.verify_server_folder() says the server belongs to another
folder (e.g. it was started from BlendCuavb_run).
"""
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    src = (ROOT / "Tool_scripts" / "win_blender_server.py").read_text(encoding="utf-8")
    pinned = f'ROOT = r"{ROOT}"  # pinned by vb/repoint_server.py'
    a = src.index("_DEFAULT_ROOT = ")
    b = src.index("LOG_FILE = os.path.join(ROOT")
    src2 = src[:a] + pinned + "\n\n" + src[b:]
    port = int(os.environ.get("BLENDCUA_PORT", "6666"))
    status = ROOT / "mem" / ("exec_status.json" if port == 6666 else f"exec_status_{port}.json")
    before = status.stat().st_mtime if status.exists() else 0
    try:
        s = socket.create_connection(("localhost", port), timeout=5)
    except OSError as e:
        print(f"no Blender server on {port}: {e}")
        return 1
    s.sendall(src2.encode("utf-8"))
    s.close()
    t0 = time.time()
    while time.time() - t0 < 20:
        if status.exists() and status.stat().st_mtime > before:
            print(f"handshake in {ROOT.name}/mem: {status.read_text(encoding='utf-8')[:160]}")
            return 0
        time.sleep(0.3)
    print(f"no handshake in {ROOT.name}/mem within 20s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
