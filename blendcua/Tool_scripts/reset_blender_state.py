"""Return the Blender session to a clean slate between runs.

Send this to the server (it is a plain script, not a module) before starting a
new run's replay.

WHY
---
The corpus was recorded one run per Blender session. Replaying twenty runs
back-to-back in one long-lived session is much faster, but `clear_scene()`
only unlinks OBJECTS -- image, material and mesh datablocks survive it. So each
run inherits every texture every earlier run loaded, and the actions notice:
04_datestone's `step2_scene_state.json` recorded

    "images": ["CardboardBox_Color", "Datestone_Color", "Datestone_Normal", ...]

with run 01's carton texture at the head of the list, shifting every entry
after it. Left alone this compounds, so by run 20 the recorded image list is
mostly other runs' leftovers and no run after the first matches its record.

Deliberately NOT `bpy.ops.wm.read_homefile()`: that reloads the startup file's
screen layout as well, which would discard the Layout workspace and the large
window the screenshots depend on, and can take the server's background timers
with it.
"""

import os
import sys

import bpy

# --- Run-local helper modules ---------------------------------------------
# Some runs keep their own helper next to the actions (06 uses gate_geom, 19
# uses human_helpers) and put steps/<n>/scripts on sys.path themselves. The
# server only drops modules that live in Tools_code, so a run-local helper
# stays cached in sys.modules for the rest of the session and the stale copy
# would serve any later run that imports the same name. Drop anything imported
# out of mem/ or plans/, and take those directories back off sys.path.
_LOCAL_MARKERS = (os.sep + "mem" + os.sep, os.sep + "plans" + os.sep)
for _name, _mod in list(sys.modules.items()):
    _f = getattr(_mod, "__file__", None) or ""
    if any(m in _f for m in _LOCAL_MARKERS):
        del sys.modules[_name]
for _entry in list(sys.path):
    if any(m in (_entry or "") for m in _LOCAL_MARKERS):
        sys.path.remove(_entry)

_KEEP_IMAGES = {"Render Result", "Viewer Node"}   # auto-recreated by rendering


def _sizes():
    return (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials),
            len(bpy.data.images), len(bpy.data.curves), len(bpy.data.node_groups))


# 1. Objects first. Everything else becomes orphaned only once these are gone.
for _ob in list(bpy.data.objects):
    try:
        bpy.data.objects.remove(_ob, do_unlink=True)
    except (RuntimeError, ReferenceError):
        pass

# 2. Collections the actions created, so the outliner does not keep stale
#    empties alive across runs.
for _coll in list(bpy.data.collections):
    try:
        bpy.data.collections.remove(_coll)
    except (RuntimeError, ReferenceError):
        pass

# 3. Purge repeatedly. One pass is not enough: an image is only orphaned once
#    the material referencing it is gone, and that only once its object is.
for _ in range(8):
    _before = _sizes()
    try:
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True,
                                       do_recursive=True)
    except RuntimeError:
        break
    if _sizes() == _before:
        break

# 4. Anything with a fake user survives a purge, and paint/bake actions set
#    fake users on their textures. Take those explicitly.
for _coll in (bpy.data.images, bpy.data.materials, bpy.data.meshes,
              bpy.data.curves, bpy.data.metaballs, bpy.data.armatures,
              bpy.data.actions, bpy.data.node_groups, bpy.data.textures,
              bpy.data.particles, bpy.data.cameras, bpy.data.lights,
              bpy.data.lattices, bpy.data.grease_pencils, bpy.data.brushes,
              bpy.data.palettes, bpy.data.texts):
    for _item in list(_coll):
        if _coll is bpy.data.images and _item.name in _KEEP_IMAGES:
            continue
        try:
            _item.use_fake_user = False
        except AttributeError:
            pass
        try:
            _coll.remove(_item, do_unlink=True)
        except (RuntimeError, ReferenceError, TypeError):
            pass

# 5. Scene-level state the actions assume is at its default.
_scene = bpy.context.scene
try:
    _scene.frame_start, _scene.frame_end = 1, 250
    _scene.frame_set(1)
except (AttributeError, RuntimeError):
    pass
try:
    _scene.render.resolution_percentage = 100
    _scene.render.film_transparent = False
    _scene.view_settings.exposure = 0.0
    _scene.view_settings.view_transform = "Standard"
    _scene.view_settings.look = "None"
except (AttributeError, TypeError):
    pass
try:
    _scene.unit_settings.system = "METRIC"
    _scene.unit_settings.scale_length = 1.0
except (AttributeError, TypeError):
    pass
_scene.camera = None
if _scene.world is not None:
    try:
        bpy.data.worlds.remove(_scene.world, do_unlink=True)
    except (RuntimeError, ReferenceError):
        pass
_scene.world = bpy.data.worlds.new("World")

print("[BlendCUA] reset: objects=%d meshes=%d materials=%d images=%d" %
      (len(bpy.data.objects), len(bpy.data.meshes),
       len(bpy.data.materials), len(bpy.data.images)))
