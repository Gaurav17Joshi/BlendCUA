"""Rebuild a finished run into the live Blender session and save it as a .blend.

The action files are the only source of truth for what a run built — there is
no saved scene at the end of a run, only screenshots. This replays every build
action in order (batched, renders stubbed) and then writes a packed .blend, so
the finished object survives the session it was built in.

    python Tool_scripts/save_final_blend.py --run 02_cardboard_box_run_001
    python Tool_scripts/save_final_blend.py --all

Output: blends/<run>.blend, plus blends/<run>.png as proof of what was saved.

Blender must be open with win_blender_server.py running.
"""

import argparse
import json
import os
import re
import socket
import stat
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PORT = int(os.environ.get("BLENDCUA_PORT", "6666"))
STATUS = os.path.join(ROOT, "mem", "exec_status.json" if PORT == 6666 else f"exec_status_{PORT}.json")
STEP_RE = re.compile(r"^step_(\d+)$")

sys.path.insert(0, ROOT)
import replay_batch  # noqa: E402


# --- Deliberate, documented skips for the blend pass ----------------------
# replay_batch.build_replay_script is strict on purpose: one failing action
# aborts the whole batch, so a run containing a broken action gets no .blend
# at all. This names actions that were ALREADY BROKEN WHEN RECORDED and that
# contribute no geometry, so the saved scene is identical either way.
#
# The bar for adding an entry is high: everything the action does before the
# point where it fails must be provably state-free. NEVER add an action here
# to get past a failure that actually builds something -- the .blend would
# silently lose that geometry and nothing downstream would say so.
SKIP_ACTIONS = {
    # 15_street_lantern step 1 action 11 calls silhouette_vs_reference()
    # having imported only audit_projected_mesh from reference_audit. That
    # function lives in perceive.py, and every other call site in this run
    # imports it explicitly. The server execs each action in a fresh
    # {"bpy": bpy} namespace, so the name was never in scope on the original
    # machine either: this is a defect in the RECORD, not in the replay setup.
    # Above the failing line there is nothing but imports, use(), a read-only
    # list of mesh names, and a viewport fit that render=False stubs anyway.
    ("15_street_lantern_run_001", "11_audit_lower_silhouette.py"),

    # 19_human_thinker step 1 action 8 evaluates o.rotation_euler.length.
    # mathutils.Euler has no .length -- Vector and Quaternion do, Euler does
    # not -- so this raises AttributeError. As with the lantern, the corpus
    # holds no evaluated output for it anywhere, only the unevaluated f-string
    # template, so it never produced a note on the original machine either.
    # Its own header says "This audit is intentionally read-only": everything
    # before the failing line reads object properties into local variables,
    # and the viewport calls that follow never execute.
    ("19_human_thinker_run_001", "08_verify_handoff.py"),
}


# --- Import the tools under the name the corpus recorded -------------------
# Every action file hardcodes the project root as
# C:/Users/render/Joshi/Blenduse/BlendCuaLoop_try, and the Windows replay makes
# that real with a directory junction. It matters which spelling the batch
# header uses: runtime.ROOT is derived from where runtime.py was imported FROM,
# and is then baked into every output path these actions record in their JSON
# reports. Importing via our own ROOT makes the regenerated reports say
# "BlendCuavb_run" wherever the record says "BlendCuaLoop_try" -- a gratuitous
# diff in every report, on top of any real one.
#
# Only used when it genuinely resolves to this same tree, so a machine without
# the junction falls back to the real path rather than breaking.
RECORDED_ROOT = os.path.join("C:" + os.sep, "Users", "render", "Joshi",
                             "Blenduse", "BlendCuaLoop_try")


def corpus_root():
    """ROOT spelled the way the recorded actions spell it, when equivalent."""
    try:
        if os.path.isdir(RECORDED_ROOT) and os.path.samefile(RECORDED_ROOT, ROOT):
            return RECORDED_ROOT
    except OSError:
        pass
    return ROOT


def _is_reparse(path):
    """True for a Windows directory junction or symlink.

    The replay setup creates junctions under mem/ so the three runs whose
    recorded use(...) name does not match their folder still resolve
    (01_cardboard_box is addressed as "02_cardboard_box_run_001", and so on).
    Those junctions are the SAME run under a second name, so --all must not
    rebuild each of them again under the stale name: that would waste a full
    rebuild and write a .blend named after a run that does not exist.
    os.path.islink() is False for junctions, hence the reparse-point test.
    """
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def send(body):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("localhost", PORT))
    s.sendall(body.encode("utf-8"))
    s.close()


_SEQ = [0]


def dispatch(body, timeout_s, what):
    """Send one script and wait for *that script's own* sentinel file.

    Waiting on the shared mem/exec_status.json is wrong whenever anything else
    is talking to the same Blender: the server writes one marker per exec, so a
    leftover script from a killed run satisfies this run's wait and every
    subsequent step reads the previous step's result. Observed twice while
    building these blends — a "fit render 0.5s" that had not started, and a
    .blend saved under a name whose render never appeared. Each dispatch now
    appends a line that stamps a unique file, so a wait can only ever be
    satisfied by its own script.
    """
    _SEQ[0] += 1
    token = os.path.join(ROOT, "blends", f".done_{os.getpid()}_{_SEQ[0]}")
    if os.path.exists(token):
        os.remove(token)
    body = body + f"\n\nopen({token!r}, 'w').close()\n"
    started = time.time()
    send(body)
    deadline = started + timeout_s
    while time.time() < deadline:
        if os.path.exists(token):
            os.remove(token)
            # The script ran to its last line, so exec_status is ours as well.
            try:
                with open(STATUS, "r", encoding="utf-8") as f:
                    return json.load(f), time.time() - started
            except (FileNotFoundError, json.JSONDecodeError):
                return {"ok": True}, time.time() - started
        # A script that RAISED never reaches the appended sentinel line, so the
        # token alone can only ever detect success -- a failed batch would sit
        # here for the entire timeout. 19_human_thinker's rebuild failed in
        # seconds and then burned 30 minutes proving it. The server's own
        # marker is the only record of the failure, so watch it too, but only
        # accept it as OURS when it is a FAILURE stamped at or after we sent:
        # the success case still requires the unique token, which is what keeps
        # a leftover script from another process satisfying this wait.
        try:
            if os.path.getmtime(STATUS) >= started:
                with open(STATUS, "r", encoding="utf-8") as f:
                    st = json.load(f)
                if not st.get("ok"):
                    return st, time.time() - started
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    # No sentinel: either still queued behind someone else, or it raised. The
    # server's own marker is the only place the traceback exists.
    print(f"  TIMEOUT after {timeout_s}s waiting for {what}")
    try:
        with open(STATUS, "r", encoding="utf-8") as f:
            print(f"  last server status: {f.read().strip()[:300]}")
    except OSError:
        pass
    return None, time.time() - started


def last_step(run):
    steps_root = os.path.join(ROOT, "mem", run, "steps")
    nums = [int(m.group(1)) for m in
            (STEP_RE.match(n) for n in os.listdir(steps_root)) if m]
    return max(nums)


# `bpy.data.images` written by a paint/bake action live only in memory until
# they are packed — an unpacked .blend reopens with pink missing textures.
SAVE_TMPL = '''
import bpy, os, json
out = {out!r}
os.makedirs(os.path.dirname(out), exist_ok=True)
# clear_scene() unlinks objects but leaves image/mesh datablocks behind, so a
# rebuild inherits every texture any earlier run in this session loaded.
before = len(bpy.data.images)
bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
purged = before - len(bpy.data.images)
packed, skipped = [], []
for im in bpy.data.images:
    if im.source in {{"GENERATED", "FILE"}} and not im.packed_file:
        try:
            im.pack()
            packed.append(im.name)
        except Exception as e:
            skipped.append(f"{{im.name}}: {{e}}")
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True, copy=False)
report = {{
    "blend": out,
    "size_mb": round(os.path.getsize(out) / 1e6, 2),
    "objects": sorted(o.name for o in bpy.data.objects),
    "meshes": {{o.name: len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH"}},
    "materials": sorted(m.name for m in bpy.data.materials),
    "images": sorted(im.name for im in bpy.data.images),
    "packed": packed,
    "pack_failed": skipped,
    "cameras": sorted(o.name for o in bpy.data.objects if o.type == "CAMERA"),
    "orphan_images_purged": purged,
}}
with open({report!r}, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)
print("[save] " + json.dumps(report))
'''

PROOF_TMPL = '''
import bpy, os
out = {png!r}
os.makedirs(os.path.dirname(out), exist_ok=True)
sc = bpy.context.scene
sc.render.filepath = out
sc.render.image_settings.file_format = "PNG"
# Keep the scene's OWN resolution. The plan camera is framed for the reference
# photo's aspect; forcing 4:3 here crops the object and invents a framing bug
# that is not in the build.
sc.render.resolution_percentage = 100
cam = sc.camera or next((o for o in bpy.data.objects if o.type == "CAMERA"), None)
if cam is None:
    raise RuntimeError("no camera in the rebuilt scene")
sc.camera = cam
bpy.ops.render.render(write_still=True)
print("[proof] wrote %s at %dx%d" % (out, sc.render.resolution_x, sc.render.resolution_y))
'''

# The plan camera is the only view the reviewer ever saw. A three-quarter fit of
# the whole bounding box is how you find out what it never looked at.
FIT_TMPL = '''
import bpy, os, math
from mathutils import Vector
out = {png!r}
os.makedirs(os.path.dirname(out), exist_ok=True)
sc = bpy.context.scene
cands = [o for o in bpy.data.objects
         if o.type in {{"MESH", "CURVE", "FONT"}} and o.visible_get()]
# The backdrop is a mesh too, and it is enormous. Framing the union of every
# mesh puts the camera far enough back to see the studio wall and nothing else
# — the box's first fit render came out as 1200x900 of flat grey. Drop the
# scenery by name, then drop anything still wildly larger than its neighbours.
SCENERY = ("backdrop", "floor", "wall", "ground", "studio", "plane", "sweep")
meshes = [o for o in cands if not any(w in o.name.lower() for w in SCENERY)] or cands


def _ext(o):
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(p.x for p in bb), min(p.y for p in bb), min(p.z for p in bb)))
    hi = Vector((max(p.x for p in bb), max(p.y for p in bb), max(p.z for p in bb)))
    return hi - lo


def _diag(o):
    return _ext(o).length


def _planar(o, ratio=0.12):
    # Flatness, not size, is what identifies scenery. A backdrop is a plane;
    # a dominant subject is not. Dropping on size alone deleted SharkBody and
    # Datestone_Cage from their own fit renders.
    d = _ext(o)
    mx = max(d)
    return mx > 0 and (min(d) / mx) <= ratio


for _ in range(3):
    if len(meshes) < 2:
        break
    ranked = sorted(meshes, key=_diag, reverse=True)
    if _diag(ranked[0]) > 2.5 * _diag(ranked[1]) and _planar(ranked[0]):
        meshes = ranked[1:]
    else:
        break
if not meshes:
    raise RuntimeError("nothing visible to frame")
print("[fit] framing %d object(s): %s" % (len(meshes), ", ".join(o.name for o in meshes[:6])))
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
mid = (lo + hi) / 2.0
radius = max((hi - lo).length / 2.0, 1e-4)

prev_res = (sc.render.resolution_x, sc.render.resolution_y)
sc.render.resolution_x, sc.render.resolution_y = 1200, 900
cam_data = bpy.data.cameras.new("FitCam")
cam_data.lens = 50.0
cam = bpy.data.objects.new("FitCam", cam_data)
sc.collection.objects.link(cam)
# Fit on the NARROWER axis. A 50mm lens spans ~40 deg horizontally but only
# ~30 deg vertically, so a distance derived from the horizontal angle crops the
# subject top and bottom — which is exactly what the box's first good-looking
# fit render did. 1.15 leaves a margin.
half = min(cam_data.angle_x, cam_data.angle_y) / 2.0
d = 1.15 * radius / math.tan(half)
# Derive the direction from the scene camera rather than picking one. A studio
# backdrop only covers the hemisphere the plan camera shoots from; a fixed
# direction put the fit camera BEHIND the box's backdrop, and the render came
# back as 1200x900 of flat grey. Swing 35 deg round and 12 deg up from the
# plan camera so the view is genuinely different but still in front of the set.
scene_cam = sc.camera or next((o for o in bpy.data.objects if o.type == "CAMERA"), None)
if scene_cam is not None:
    base = (scene_cam.matrix_world.translation - mid)
    base = base.normalized() if base.length > 1e-6 else Vector((0.62, -0.70, 0.42)).normalized()
else:
    base = Vector((0.62, -0.70, 0.42)).normalized()
import mathutils
base = mathutils.Matrix.Rotation(math.radians(35.0), 3, "Z") @ base
axis = base.cross(Vector((0.0, 0.0, 1.0)))
if axis.length > 1e-6:
    base = mathutils.Matrix.Rotation(math.radians(-12.0), 3, axis.normalized()) @ base
cam.location = mid + base.normalized() * d
cam.rotation_euler = (mid - cam.location).to_track_quat("-Z", "Y").to_euler()

prev_cam, prev_path = sc.camera, sc.render.filepath
sc.camera = cam
sc.render.filepath = out
sc.render.image_settings.file_format = "PNG"
sc.render.resolution_percentage = 100
try:
    bpy.ops.render.render(write_still=True)
finally:
    sc.camera, sc.render.filepath = prev_cam, prev_path
    sc.render.resolution_x, sc.render.resolution_y = prev_res
    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.cameras.remove(cam_data)
print("[fit] wrote " + out)
'''


def rebuild(run, timeout_s, fit_only=False):
    upto = last_step(run)
    files = replay_batch.collect_action_files(os.path.join(ROOT, "mem"), run,
                                              before_step=upto, before_action=None)
    skipped = [f for f in files if (run, os.path.basename(f)) in SKIP_ACTIONS]
    if skipped:
        files = [f for f in files
                 if (run, os.path.basename(f)) not in SKIP_ACTIONS]
        for f in skipped:
            print("  SKIPPING %s (known-broken in the record, builds no geometry)"
                  % os.path.basename(f))
    print(f"\n=== {run} — {len(files)} build actions across steps 1..{upto}")
    script = replay_batch.build_replay_script(
        files, os.path.join(corpus_root(), "Tool_scripts", "Tools_code"),
        render=False, label=f"final rebuild of {run}")
    status, dt = dispatch(script, timeout_s, "replay")
    if status is None:
        return False
    if not status.get("ok"):
        print(f"  REPLAY FAILED after {dt:.1f}s:\n{status.get('error')}")
        return False
    print(f"  replay OK in {dt:.1f}s")

    if fit_only:
        fit = os.path.join(ROOT, "blends", f"{run}_fit.png")
        status, dt = dispatch(FIT_TMPL.format(png=fit), 900, "fit render")
        if status is None or not status.get("ok"):
            print(f"  fit render failed: {status and status.get('error')}")
            return False
        print(f"  fit render   {dt:.1f}s -> {fit}")
        return True

    blend = os.path.join(ROOT, "blends", f"{run}.blend")
    report = os.path.join(ROOT, "blends", f"{run}.json")
    status, dt = dispatch(SAVE_TMPL.format(out=blend, report=report), 300, "save")
    if status is None or not status.get("ok"):
        print(f"  SAVE FAILED: {status and status.get('error')}")
        return False
    with open(report, encoding="utf-8") as f:
        r = json.load(f)
    print(f"  saved {r['size_mb']} MB in {dt:.1f}s — "
          f"{len(r['objects'])} objects, {len(r['materials'])} materials, "
          f"{len(r['images'])} images ({len(r['packed'])} packed)")

    png = os.path.join(ROOT, "blends", f"{run}.png")
    status, dt = dispatch(PROOF_TMPL.format(png=png), 900, "proof render")
    if status is None or not status.get("ok"):
        print(f"  proof render failed (the .blend is still saved): "
              f"{status and status.get('error')}")
    else:
        print(f"  proof render {dt:.1f}s -> {png}")

    fit = os.path.join(ROOT, "blends", f"{run}_fit.png")
    status, dt = dispatch(FIT_TMPL.format(png=fit), 900, "fit render")
    if status is None or not status.get("ok"):
        print(f"  fit render failed: {status and status.get('error')}")
    else:
        print(f"  fit render   {dt:.1f}s -> {fit}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", action="append", default=[])
    p.add_argument("--all", action="store_true")
    p.add_argument("--timeout", type=float, default=1800.0)
    p.add_argument("--fit-only", action="store_true",
                   help="Replay and re-render only the fitted view. Leaves the "
                        "existing .blend and camera render untouched.")
    a = p.parse_args()
    runs = a.run
    if a.all:
        mem_dir = os.path.join(ROOT, "mem")
        runs = sorted(n for n in os.listdir(mem_dir)
                      if n.endswith("_run_001") and not n.startswith("_")
                      and not _is_reparse(os.path.join(mem_dir, n)))
    if not runs:
        p.error("give --run <name> or --all")
    ok = [rebuild(r, a.timeout, a.fit_only) for r in runs]
    print(f"\n{sum(ok)}/{len(ok)} runs rebuilt and saved into blends/")
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    main()
