"""
Replay a range of steps from a BlendCUA run by sending each action file
to the Blender server (started in Blender via blender_server.py).

Usage:
    python Tool_scripts/run_steps.py --upto 12
    python Tool_scripts/run_steps.py --upto 12 --run cup_run_001
    python Tool_scripts/run_steps.py --upto 12 --from 5     # play steps 5..12

For each step_NNN in order, sends every NN_*.py action file (sorted by
the leading number) to the server on port 6666, then waits for
mem/<run>/last_step.json to be updated before sending the next one.

Blender must already be open with blender_server.py running.
"""

import argparse
import json
import os
import re
import socket
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PORT = 6666

# ─── Screenshot delivery cap ─────────────────────────────────────────────
# After each action finishes, every PNG it wrote under
# mem/<run>/steps/step_NNN/screenshots/ is capped to this box in place,
# ASPECT PRESERVED and never upscaled. We do it here (not inside Blender's
# render_viewport) so the overlay subprocess still sees the native-size image
# when it draws ticks.
#
# 1440x1080 is the largest 4:3 size neither vision model downscales on its
# own: GPT-5.x tiles 32px patches and caps at 1536 (45x34 = 1530), Claude
# tiles 28px and caps at 4784 tokens (52x39 = 2028).
SHOT_W = 1440
SHOT_H = 1080

ACTION_RE = re.compile(r"^(\d+)_.*\.py$")
STEP_RE   = re.compile(r"^step_(\d+)$")


def send(script_path):
    with open(script_path, "r") as f:
        body = f.read()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("localhost", PORT))
    s.sendall(body.encode("utf-8"))
    s.close()


def wait_for_status(status_path, sent_at, timeout_s, poll_s=0.25):
    """Wait until status_path's mtime is newer than sent_at, or timeout."""
    deadline = sent_at + timeout_s
    while time.time() < deadline:
        try:
            mtime = os.path.getmtime(status_path)
            if mtime >= sent_at:
                # Try to read it — partially-written file is rare but possible.
                try:
                    with open(status_path, "r") as f:
                        return json.load(f)
                except json.JSONDecodeError:
                    pass
        except FileNotFoundError:
            pass
        time.sleep(poll_s)
    return None


def resize_new_pngs(step_dir, since_mtime):
    """Downsize every PNG in step_dir/screenshots/ whose mtime >= since_mtime.

    Caps at SHOT_W x SHOT_H with the aspect ratio preserved, and never
    enlarges: an image already inside the box is left alone. Uses PIL from
    the project venv (run_steps.py is launched from there).
    """
    try:
        from PIL import Image
    except ImportError:
        print(f"[run_steps] PIL not available; skipping resize. "
              f"Install pillow in the venv to cap screenshots at "
              f"{SHOT_W}x{SHOT_H}.")
        return
    shots_dir = os.path.join(step_dir, "screenshots")
    if not os.path.isdir(shots_dir):
        return
    for name in sorted(os.listdir(shots_dir)):
        if not name.lower().endswith(".png"):
            continue
        path = os.path.join(shots_dir, name)
        try:
            if os.path.getmtime(path) < since_mtime:
                continue
            with Image.open(path) as im:
                iw, ih = im.size
                if iw <= SHOT_W and ih <= SHOT_H:
                    continue
                k = min(SHOT_W / iw, SHOT_H / ih)
                new = (max(1, round(iw * k)), max(1, round(ih * k)))
                im = im.convert("RGB") if im.mode == "P" else im
                resized = im.resize(new, Image.LANCZOS)
                resized.save(path, "PNG")
        except (OSError, ValueError) as e:
            print(f"     resize skipped {name}: {e}")


def list_action_files(step_dir):
    out = []
    for name in sorted(os.listdir(step_dir)):
        m = ACTION_RE.match(name)
        if m:
            out.append((int(m.group(1)), os.path.join(step_dir, name)))
    out.sort(key=lambda x: x[0])
    return [p for _, p in out]


def list_step_dirs(run_dir, lo, hi):
    steps_root = os.path.join(run_dir, "steps")
    if not os.path.isdir(steps_root):
        return []
    out = []
    for name in sorted(os.listdir(steps_root)):
        m = STEP_RE.match(name)
        if not m:
            continue
        n = int(m.group(1))
        if lo <= n <= hi:
            out.append((n, os.path.join(steps_root, name)))
    out.sort(key=lambda x: x[0])
    return out


def main():
    p = argparse.ArgumentParser(description="Play a range of BlendCUA steps into Blender.")
    p.add_argument("--run",     default="cup_run_001",
                   help="Run folder under mem/ (default: cup_run_001)")
    p.add_argument("--upto",    type=int, required=True,
                   help="Final step number to play (inclusive).")
    p.add_argument("--from",    dest="from_step", type=int, default=1,
                   help="First step number to play (inclusive, default: 1).")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="Seconds to wait for each action to finish (default: 60).")
    p.add_argument("--gap",     type=float, default=0.1,
                   help="Extra delay after each completed action (default: 0.1s).")
    p.add_argument("--shots", action="store_true",
                   help="Enable the per-action status screenshot (runtime.shot()). "
                        "Off by default — it's a slow OpenGL viewport render on every "
                        "action. Plan-preview images (chain_plan_preview etc.) always "
                        "render regardless of this flag.")
    args = p.parse_args()

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

    run_dir     = os.path.join(ROOT, "mem", args.run)
    status_path = os.path.join(run_dir, "last_step.json")

    if not os.path.isdir(run_dir):
        print(f"[run_steps] Run dir not found: {run_dir}")
        sys.exit(1)

    steps = list_step_dirs(run_dir, args.from_step, args.upto)
    if not steps:
        print(f"[run_steps] No step_NNN dirs in {args.from_step}..{args.upto} under {run_dir}/steps/")
        sys.exit(1)

    total_actions = 0
    for step_n, step_dir in steps:
        actions = list_action_files(step_dir)
        if not actions:
            print(f"[run_steps] step_{step_n:03d}: no action files, skipping")
            continue
        print(f"[run_steps] step_{step_n:03d}: {len(actions)} action(s)")
        for action_path in actions:
            rel = os.path.relpath(action_path, ROOT)
            sent_at = time.time()
            try:
                send(action_path)
            except ConnectionRefusedError:
                print(f"[run_steps] Could not reach Blender on port {PORT}. "
                      "Is blender_server.py running in Blender's Script Editor?")
                sys.exit(1)
            print(f"  -> sent {rel}")
            status = wait_for_status(status_path, sent_at, args.timeout)
            if status is None:
                print(f"     TIMEOUT after {args.timeout}s waiting on {status_path}")
                print( "     (action likely errored before reaching shot(); check Blender's console)")
                sys.exit(2)
            note = status.get("note", "")
            print(f"     ok  step={status.get('step')} action={status.get('action')} :: {note}")
            resize_new_pngs(step_dir, sent_at)
            total_actions += 1
            if args.gap:
                time.sleep(args.gap)

    print(f"[run_steps] done — {total_actions} action(s) across {len(steps)} step(s)")


if __name__ == "__main__":
    main()
