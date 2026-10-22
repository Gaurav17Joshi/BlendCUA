"""Size the Blender window so its 3D viewport matches the recorded one.

    python Tool_scripts/win_fit_viewport.py            # fit to 800x600
    python Tool_scripts/win_fit_viewport.py --measure  # just report

WHY THIS MATTERS -- it is not cosmetic
--------------------------------------
Several actions derive GEOMETRY from the viewport's pixel dimensions. From
04_datestone_1934 step 2 action 3:

    paths2d  = [[project_to_norm(Vector(p), region, rv3d) for p in path] ...]
    size_px  = max(3, int(round(2.0 * sn.world_to_px(region, rv3d, radius_m, center))))
    sn.apply_stroke("Datestone_High", "CREASE", stroke, size=size_px, ...)

The sculpt brush diameter is computed in SCREEN PIXELS from `region`, so a
different viewport gives a different brush, which moves a different set of
vertices and carves to a different depth. Replaying that run in a 1180x722
viewport instead of the recorded 798x604 produced size_px 7 where the record
says 6, and the chip report came back with verts_moved 17 against a recorded
21 and depths up to 1.1 mm out. The grooves in the same run still matched
exactly -- their size_px happened to round to the same integer -- which is
exactly what makes this worth pinning down rather than trusting spot checks.

Seven of the nineteen replayable runs contain such actions: 04, 06, 09, 10,
14, 18 and 20.

The recorded size is not a guess: 40 tracked JSON reports across the corpus
record "viewport_width": 798 and "viewport_height": 604.

Sizing the OS window is the only lever, since Blender exposes area dimensions
read-only. The relationship between window size and viewport size is a fixed
offset for a given workspace layout, so measure, correct, repeat -- it
converges in two or three passes.
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import socket
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PORT = int(os.environ.get("BLENDCUA_PORT", "6666"))
PROBE_OUT = os.path.join(ROOT, "mem", f".viewport_probe_{PORT}.json")

RECORDED_W, RECORDED_H = 800, 600   # this folder's standard viewport (the Mac corpus was 798x604)

_u = ctypes.windll.user32
SW_RESTORE = 9


def blender_hwnds(only_pid=None):
    """Visible top-level windows belonging to a running blender.exe (or to one pid)."""
    import subprocess
    pids = set()
    if only_pid:
        pids.add(int(only_pid))
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq blender.exe", "/FO", "CSV"],
                         capture_output=True, text=True).stdout
    for line in ([] if only_pid else out.splitlines()[1:]):
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith("blender"):
            try:
                pids.add(int(parts[1]))
            except ValueError:
                pass
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _l):
        pid = wt.DWORD()
        _u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids:
            # Match on the WINDOW CLASS, not the title. Blender's process
            # also owns several helper windows -- "BlenderGLEW" (class Static),
            # NVOpenGLPbuffer surfaces, a console -- and some of those carry
            # "Blender" in their title too. Resizing one of those succeeds and
            # changes nothing, which looks exactly like Blender ignoring the
            # resize. The real top-level window is a GHOST_WindowClass.
            cls = ctypes.create_unicode_buffer(256)
            _u.GetClassNameW(h, cls, 256)
            if cls.value == "GHOST_WindowClass":
                found.append(h)
        return True

    _u.EnumWindows(cb, 0)
    return found


def window_rect(hwnd):
    r = wt.RECT()
    _u.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def measure_viewport(timeout_s=20.0):
    """Ask the live Blender for its first VIEW_3D region size."""
    probe = (
        "import bpy, json, os\n"
        "out = {'windows': [], 'pid': os.getpid()}\n"
        "for w in bpy.data.window_managers[0].windows:\n"
        "    v3d = [(a.width, a.height) for a in w.screen.areas if a.type == 'VIEW_3D']\n"
        "    regions = []\n"
        "    for a in w.screen.areas:\n"
        "        if a.type != 'VIEW_3D':\n"
        "            continue\n"
        "        for r in a.regions:\n"
        "            if r.type == 'WINDOW':\n"
        "                regions.append((r.width, r.height))\n"
        "    out['windows'].append({'workspace': w.workspace.name, 'area': v3d,\n"
        "                           'region': regions, 'win': (w.width, w.height)})\n"
        "with open(%r, 'w') as f:\n"
        "    json.dump(out, f)\n" % PROBE_OUT
    )
    try:
        os.remove(PROBE_OUT)
    except OSError:
        pass
    sent = time.time()
    s = socket.create_connection(("localhost", PORT), timeout=10)
    s.sendall(probe.encode("utf-8"))
    s.shutdown(socket.SHUT_WR)
    s.close()
    deadline = sent + timeout_s
    while time.time() < deadline:
        if os.path.exists(PROBE_OUT):
            try:
                with open(PROBE_OUT) as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(0.15)
    raise RuntimeError("Blender did not answer the viewport probe")


def first_area(info):
    for w in info["windows"]:
        if w["area"]:
            return tuple(w["area"][0]), w
    raise RuntimeError("no VIEW_3D area in any Blender window -- "
                       "switch to a workspace that has a 3D viewport")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--width", type=int, default=RECORDED_W)
    p.add_argument("--height", type=int, default=RECORDED_H)
    p.add_argument("--measure", action="store_true", help="Report and exit.")
    p.add_argument("--tries", type=int, default=8)
    a = p.parse_args()

    info = measure_viewport()
    (aw, ah), win = first_area(info)
    print("workspace %r: VIEW_3D area %dx%d, region %s, blender window %s"
          % (win["workspace"], aw, ah, win["region"], win["win"]))
    if a.measure:
        print("recorded corpus viewport: %dx%d" % (RECORDED_W, RECORDED_H))
        return

    hwnds = blender_hwnds(info.get("pid"))
    if not hwnds:
        print("no Blender window found")
        sys.exit(1)
    hwnd = hwnds[0]

    # A minimized window reports a bogus rect (parked at -32000) and cannot be
    # sized meaningfully, so restore it first.
    _u.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.6)

    for attempt in range(1, a.tries + 1):
        info = measure_viewport()
        (aw, ah), _w = first_area(info)
        if (aw, ah) == (a.width, a.height):
            print("viewport is %dx%d -- matches the recorded corpus" % (aw, ah))
            return
        x, y, ww, wh = window_rect(hwnd)
        # The gap between window and viewport is fixed for a given layout.
        dw, dh = ww - aw, wh - ah
        tw, th = a.width + dw, a.height + dh
        print("  try %d: viewport %dx%d -> resizing window %dx%d to %dx%d"
              % (attempt, aw, ah, ww, wh, tw, th))
        _u.MoveWindow(hwnd, max(x, 0), max(y, 0), tw, th, True)
        time.sleep(0.7)

    info = measure_viewport()
    (aw, ah), _w = first_area(info)
    if (aw, ah) == (a.width, a.height):
        print("viewport is %dx%d -- matches the recorded corpus" % (aw, ah))
        return
    print("could not hit %dx%d exactly; closest %dx%d"
          % (a.width, a.height, aw, ah))
    sys.exit(2)


if __name__ == "__main__":
    main()
