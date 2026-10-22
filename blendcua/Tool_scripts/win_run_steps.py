"""
WINDOWS VERSION — replay a range of steps from a BlendCUA run by sending each
action file to the Blender server (started in Blender via win_blender_server.py).

Usage:
    python Tool_scripts\\win_run_steps.py --upto 12
    python Tool_scripts\\win_run_steps.py --upto 12 --run cup_run_001
    python Tool_scripts\\win_run_steps.py --upto 12 --from 5     # play steps 5..12

For each step_NNN in order, sends every NN_*.py action file (sorted by
the leading number) to the server on port 6666, then waits for
mem/<run>/last_step.json to be updated before sending the next one.

Blender must already be open with win_blender_server.py running.
"""

import argparse
import json
import os
import re
import socket
import sys
import time

# Windows' console defaults stdout to the system codepage (e.g. cp1252), not
# UTF-8 like macOS/Linux terminals — action status notes can contain
# non-ASCII characters (≈, —, etc.) that would otherwise raise
# UnicodeEncodeError mid-run. errors="replace" so an odd glyph degrades to
# "?" instead of crashing the whole replay.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PORT = int(os.environ.get("BLENDCUA_PORT", "6666"))
EXEC_STATUS = os.path.join(ROOT, "mem", "exec_status.json" if PORT == 6666 else f"exec_status_{PORT}.json")

# ─── Screenshot delivery cap ─────────────────────────────────────────────
# After each action finishes, every PNG it wrote under
# mem/<run>/steps/step_NNN/screenshots/ is capped to this box in place,
# ASPECT PRESERVED and never upscaled. We do it here (not inside Blender's
# render_viewport) so the overlay subprocess still sees the native-size image
# when it draws ticks.
#
# 1440x1080 is the largest 4:3 size neither vision model downscales on its
# own: GPT-5.x tiles 32px patches and caps at 1536 (45x34 = 1530), Claude
# tiles 28px and caps at 4784 tokens (52x39 = 2028). Going bigger buys
# nothing — the provider just resamples it back down.
SHOT_W = 1440
SHOT_H = 1080

ACTION_RE = re.compile(r"^(\d+)_.*\.py$")
STEP_RE   = re.compile(r"^step_(\d+)$")


def send(script_path):
    # encoding="utf-8" explicit — Windows' default text encoding is the
    # locale codepage (often cp1252), not UTF-8, unlike macOS/Linux.
    with open(script_path, "r", encoding="utf-8") as f:
        body = f.read()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("localhost", PORT))
    s.sendall(body.encode("utf-8"))
    s.close()


def _read_if_fresh(path, sent_at):
    """Return the JSON at `path` if it was rewritten at/after sent_at, else None."""
    try:
        if os.path.getmtime(path) < sent_at:
            return None
    except OSError:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # A partially-written file is rare but possible; try again next poll.
        return None


def wait_for_status(status_path, sent_at, timeout_s, poll_s=0.25):
    """Back-compat single-file wait, still used by the --batch path."""
    deadline = sent_at + timeout_s
    while time.time() < deadline:
        got = _read_if_fresh(status_path, sent_at)
        if got is not None:
            return got
        time.sleep(poll_s)
    return None


def wait_for_action(last_step_path, exec_status_path, sent_at, timeout_s,
                    poll_s=0.25):
    """Wait for one dispatched action. Returns (outcome, last_step, exec_status).

    outcome is "ok", "error" or "timeout".

    This watches TWO files, because either one on its own is a trap:

    * mem/<run>/last_step.json is written by runtime.shot(). An action that
      raises BEFORE reaching shot() never writes it — and neither does one
      that legitimately never calls shot(). Waiting on this file alone burns
      the whole timeout on a script that failed in milliseconds, which is
      exactly the failure the runbook describes in section 7.1: a failure
      that is indistinguishable from slowness, where raising the timeout only
      makes it fail more slowly.
    * mem/exec_status.json is bumped by the server after EVERY exec, success
      or failure, so it always arrives — but it carries no step/action/note.

    So exec_status decides ok-vs-failed and bounds the wait, while last_step
    supplies the human-readable note whenever it is present.
    """
    deadline = sent_at + timeout_s
    last = None
    while time.time() < deadline:
        if last is None:
            last = _read_if_fresh(last_step_path, sent_at)
        status = _read_if_fresh(exec_status_path, sent_at)
        if status is not None:
            if not status.get("ok"):
                return "error", last, status
            # Success. shot() runs inside the action, so last_step.json is
            # already on disk by the time the server marks the exec done;
            # re-read once in case we sampled between the two writes.
            if last is None:
                last = _read_if_fresh(last_step_path, sent_at)
            return "ok", last, status
        time.sleep(poll_s)
    return "timeout", last, None


def resize_new_pngs(step_dir, since_mtime):
    """Downsize every PNG in step_dir/screenshots/ whose mtime >= since_mtime.

    Caps at SHOT_W x SHOT_H with the aspect ratio preserved, and never
    enlarges: an image already inside the box is left alone. Upscaling would
    add patches without adding information, and forcing an exact size would
    distort every proportion the agent is trying to measure. Uses PIL from
    the project venv (win_run_steps.py is launched from there).
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
    p.add_argument("--keep-going", dest="keep_going", action="store_true",
                   help="On a failed or timed-out action, log it and carry on to "
                        "the next one instead of exiting. An unattended pass has "
                        "nobody to restart it. Failures are appended to "
                        "mem/_replay.log and summarised at the end.")
    p.add_argument("--shots", action="store_true",
                   help="Enable the per-action status screenshot (runtime.shot()). "
                        "Off by default — it's a slow OpenGL viewport render on every "
                        "action. Plan-preview images (chain_plan_preview etc.) always "
                        "render regardless of this flag.")
    p.add_argument("--batch", action="store_true",
                   help="Send every action as ONE script in a single dispatch, with "
                        "rendering skipped. ~12x faster (84 actions: 51s -> 4.2s) and "
                        "produces identical geometry, but writes no screenshots and "
                        "no per-action status. Use it to rebuild a scene to a known "
                        "state; use the normal path when you want to watch it.")
    args = p.parse_args()

    if args.batch:
        sys.path.insert(0, ROOT)
        import replay_batch
        files = replay_batch.collect_action_files(
            os.path.join(ROOT, "mem"), args.run,
            before_step=args.upto, before_action=None)
        files = [f for f in files
                 if int(STEP_RE.match(os.path.basename(os.path.dirname(f))).group(1))
                 >= args.from_step]
        if not files:
            print(f"[run_steps] no action files in {args.from_step}..{args.upto}")
            sys.exit(1)
        script = replay_batch.build_replay_script(
            files, os.path.join(ROOT, "Tool_scripts", "Tools_code"),
            render=False, label=f"steps {args.from_step}..{args.upto}")
        tmp = os.path.join(ROOT, "mem", args.run, ".batch_replay.py")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(script)
        started = time.time()
        try:
            send(tmp)
        except ConnectionRefusedError:
            print(f"[run_steps] Could not reach Blender on port {PORT}.")
            sys.exit(1)
        # The batch does not call shot(), so poll the SERVER's own completion
        # marker (bumped after every exec) rather than last_step.json.
        status = wait_for_status(EXEC_STATUS,
                                 started, args.timeout)
        elapsed = time.time() - started
        if status is None:
            print(f"[run_steps] TIMEOUT after {args.timeout}s")
            sys.exit(2)
        if not status.get("ok"):
            print(f"[run_steps] BATCH FAILED after {elapsed:.1f}s:\n{status.get('error')}")
            sys.exit(1)
        print(f"[run_steps] batch OK — {len(files)} action(s) in {elapsed:.1f}s")
        return

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

    exec_status_path = EXEC_STATUS
    replay_log = os.path.join(ROOT, "mem", "_replay.log")

    def log_failure(kind, rel, detail):
        """Append a failure to mem/_replay.log. print() supplies the newlines."""
        try:
            with open(replay_log, "a", encoding="utf-8") as f:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {kind} "
                      f"run={args.run} {rel}", file=f)
                print(detail, file=f)
        except OSError:
            pass

    total_actions = 0
    failures = []
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
                      "Is win_blender_server.py running in Blender's Script Editor?")
                sys.exit(1)
            print(f"  -> sent {rel}")
            outcome, last, status = wait_for_action(
                status_path, exec_status_path, sent_at, args.timeout)

            if outcome == "ok":
                note = (last or {}).get("note", "")
                step_id = (last or {}).get("step")
                act_id = (last or {}).get("action")
                if last is None:
                    # Succeeded without calling shot(). Legitimate for some
                    # actions; previously this burned the full timeout.
                    print(f"     ok  (no shot) :: exec completed")
                else:
                    print(f"     ok  step={step_id} action={act_id} :: {note}")
            elif outcome == "error":
                err = (status or {}).get("error") or "(no traceback captured)"
                tail = err.strip().splitlines()[-1] if err.strip() else err
                print(f"     FAILED :: {tail}")
                print(f"     (full traceback in mem/server_errors.log)")
                log_failure("FAILED", rel, err)
                failures.append((rel, "FAILED", tail))
                if not args.keep_going:
                    sys.exit(2)
            else:
                print(f"     TIMEOUT after {args.timeout}s")
                print( "     (no completion marker at all — Blender may be busy,"
                       " blocked on a modal, or the action is genuinely slow)")
                log_failure("TIMEOUT", rel, f"no completion after {args.timeout}s")
                failures.append((rel, "TIMEOUT", f"{args.timeout}s"))
                if not args.keep_going:
                    sys.exit(2)

            resize_new_pngs(step_dir, sent_at)
            total_actions += 1
            if args.gap:
                time.sleep(args.gap)

    ok_count = total_actions - len(failures)
    print(f"[run_steps] done — {ok_count}/{total_actions} action(s) OK "
          f"across {len(steps)} step(s)")
    if failures:
        print(f"[run_steps] {len(failures)} problem action(s):")
        for rel, kind, detail in failures:
            print(f"    {kind:8} {rel} :: {detail}")
        print(f"[run_steps] logged to {os.path.relpath(replay_log, ROOT)}")
        sys.exit(0 if args.keep_going else 2)


if __name__ == "__main__":
    main()
