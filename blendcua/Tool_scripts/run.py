"""
Usage:
    python run.py --file scripts/make_cube.py [--timeout 60]

Sends the given bpy script to the Blender server started by blender_server.py,
then BLOCKS until Blender reports completion via mem/exec_status.json.
Make sure blender_server.py has been run inside Blender first.

Exit codes:
    0  script completed OK in Blender
    1  script raised an exception (traceback printed) / file or connection error
    2  timed out — script hung or Blender is frozen
"""

import argparse
import glob
import json
import os
import socket
import sys
import time

PORT = 6666
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
STATUS_FILE = os.path.join(ROOT, "mem", "exec_status.json")


def read_status():
    try:
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Send a bpy script to the running Blender instance and wait for completion."
    )
    parser.add_argument("--file", required=True, help="Path to the .py script with bpy commands")
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="Seconds to wait for Blender to finish the script (default: 60)")
    parser.add_argument("--shots", action="store_true",
                        help="Enable the per-action status screenshot (runtime.shot()). "
                             "Off by default — it's a slow OpenGL viewport render on every "
                             "action. Plan-preview images (chain_plan_preview etc.) always "
                             "render regardless of this flag.")
    args = parser.parse_args()

    # Flip the cross-process screenshot toggle by writing/removing a flag
    # file directly (can't `import runtime` here — that module imports bpy,
    # which only exists inside Blender's own Python).
    shots_flag = os.path.join(ROOT, "mem", ".shots_enabled")
    if args.shots:
        os.makedirs(os.path.dirname(shots_flag), exist_ok=True)
        open(shots_flag, "w").close()
    else:
        try:
            os.remove(shots_flag)
        except FileNotFoundError:
            pass

    try:
        with open(args.file, "r") as f:
            script = f.read()
    except FileNotFoundError:
        print(f"[BlendCUA] File not found: {args.file}")
        sys.exit(1)

    prev = read_status()
    prev_seq = prev.get("seq") if prev else None
    sent_at = time.time()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost", PORT))
        s.sendall(script.encode("utf-8"))
        s.close()
        print(f"[BlendCUA] Sent: {args.file}")
    except ConnectionRefusedError:
        print(f"[BlendCUA] Could not connect to Blender on port {PORT}.")
        print("  Make sure you ran blender_server.py in Blender's Script Editor first.")
        sys.exit(1)

    # Block until the server bumps exec_status.json (written after every
    # script execution, success or error).
    # Legacy fallback: an older blender_server.py (without exec-status
    # support) never bumps the seq — detect completion via a fresh
    # last_step.json write instead (only covers scripts that reach shot()).
    deadline = sent_at + args.timeout
    while time.time() < deadline:
        st = read_status()
        if st is not None and st.get("seq") != prev_seq:
            if st.get("ok"):
                print("[BlendCUA] Completed OK.")
                sys.exit(0)
            print("[BlendCUA] Script ERROR in Blender:")
            print(st.get("error") or "(no traceback captured)")
            sys.exit(1)
        for lsj in glob.glob(os.path.join(ROOT, "mem", "*", "last_step.json")):
            try:
                if os.path.getmtime(lsj) >= sent_at:
                    print("[BlendCUA] Completed (legacy detection via last_step.json — "
                          "re-run Tool_scripts/blender_server.py in Blender for full "
                          "error reporting).")
                    sys.exit(0)
            except OSError:
                pass
        time.sleep(0.25)

    print(f"[BlendCUA] TIMEOUT after {args.timeout:.0f}s — Blender did not finish the script.")
    print("  Either the script hung (blocking op / infinite loop) or Blender is frozen.")
    print("  Do NOT retry with sleeps — write a simpler replacement action instead.")
    sys.exit(2)


if __name__ == "__main__":
    main()
