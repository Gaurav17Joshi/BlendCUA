"""
Cross-LLM review renders — two angles per step.

Called at the end of a step to produce the two viewport screenshots the
reviewer LLM compares against `Images/bar_stool.png`:

  review_front.png  — FRONT ortho (camera at −Y, looking toward +Y)
  review_persp.png  — 3/4   ortho (camera in the +X+Y+Z octant, ~(1,1,1)
                                   direction, looking toward the origin)

Files land in `mem/<run>/steps/step_NNN/review/`.

Usage (as the last action of a step):

    from review import render_review_shots
    render_review_shots()
    shot("review shots rendered to review/review_{front,persp}.png")

The function is idempotent — running it twice overwrites the previous
renders. Restores the viewport rotation on exit so a later action doesn't
inherit the aerial view.
"""

import bpy
import math
import os
from mathutils import Euler, Quaternion

from lib.view import get_viewport, setup_axis_ortho_view, render_viewport

import runtime as _rt

# Match the run_steps.py resize policy so review renders tokenize the
# same as viewport screenshots when sent to a VLM.
SHOT_W = 1440
SHOT_H = 1080


def _review_dir():
    d = f"{_rt._RUN}/steps/step_{_rt._STEP:03d}/review"
    os.makedirs(d, exist_ok=True)
    return d


def _resize_to_shot(path):
    """Cap `path` in place at SHOT_W × SHOT_H via PIL, aspect preserved and
    never enlarged. No-op if PIL is unavailable in Blender's bundled Python."""
    try:
        from PIL import Image
    except Exception as e:
        print(f"[review] PIL unavailable, skipping resize: {e}")
        return
    try:
        with Image.open(path) as im:
            iw, ih = im.size
            if iw <= SHOT_W and ih <= SHOT_H:
                return
            k = min(SHOT_W / iw, SHOT_H / ih)
            new = (max(1, round(iw * k)), max(1, round(ih * k)))
            resized = im.resize(new, Image.LANCZOS)
            resized.save(path, "PNG")
    except Exception as e:
        print(f"[review] resize skipped {path}: {e}")


def _render_at(area, region, rv3d, axis, path, zoom_out=1.2):
    """FRONT / LEFT / etc. via setup_axis_ortho_view, then render + resize."""
    setup_axis_ortho_view(area, region, rv3d, axis=axis, zoom_out=zoom_out)
    render_viewport(path)
    _resize_to_shot(path)


def _render_three_quarter(area, region, rv3d, path, zoom_out=1.2):
    """Aerial 3/4 ortho — camera in the (+X, +Y, +Z) octant looking at
    the origin (~(1,1,1) direction). Uses direct view_rotation set so we
    don't rely on view_orbit sequences.

    Euler(elevation, 0, azimuth), XYZ order:
      azimuth   = 45° around world Z (rotates view around vertical)
      elevation = 54.735° around resulting X (arctan(sqrt(2))) → looking
                  down at exactly the (1,1,1) direction
    """
    rv3d.view_perspective = 'ORTHO'
    rv3d.view_rotation = Euler(
        (math.radians(54.7356), 0.0, math.radians(45.0)), 'XYZ'
    ).to_quaternion()
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.view3d.view_all(center=False)
        rv3d.view_distance *= zoom_out
    rv3d.update()
    render_viewport(path)
    _resize_to_shot(path)


def render_review_shots(zoom_out=1.2, restore_view=True, front_axis='FRONT'):
    """Render the three review PNGs into mem/<run>/steps/step_NNN/review/.

    zoom_out       multiplier on view_distance after fit-all for each
                   render (>1 = more headroom around the model). Same
                   value applied to all three renders so they compare
                   like-for-like.
    restore_view   if True, put the viewport rotation back to whatever
                   it was before the call (so a subsequent action doesn't
                   inherit the 3/4 view).
    front_axis     which ortho axis to use for the "front" review render
                   (default 'FRONT'). Pass 'LEFT' for side-profile builds
                   (e.g. the duck plan) where the reference backdrop is
                   set up in LEFT ortho.
    """
    out_dir = _review_dir()

    # Clean stage: OBJECT mode, nothing selected, so no orange highlights
    # or edit-mode overlays contaminate the renders.
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    prev_active = bpy.context.view_layer.objects.active
    bpy.ops.object.select_all(action='DESELECT')

    area, region, rv3d = get_viewport()
    if area is None:
        raise RuntimeError("no VIEW_3D area — can't render review shots")

    # Snapshot the current view so we can restore it after.
    saved_rot   = Quaternion(rv3d.view_rotation)
    saved_dist  = rv3d.view_distance
    saved_loc   = rv3d.view_location.copy()
    saved_persp = rv3d.view_perspective

    try:
        _render_at(area, region, rv3d, front_axis,
                   f"{out_dir}/review_front.png", zoom_out=zoom_out)
        _render_three_quarter(area, region, rv3d,
                              f"{out_dir}/review_persp.png",
                              zoom_out=zoom_out)
    finally:
        if restore_view:
            rv3d.view_rotation    = saved_rot
            rv3d.view_distance    = saved_dist
            rv3d.view_location    = saved_loc
            rv3d.view_perspective = saved_persp
            rv3d.update()
        if prev_active is not None:
            bpy.context.view_layer.objects.active = prev_active

    return {
        "front": f"{out_dir}/review_front.png",
        "persp": f"{out_dir}/review_persp.png",
    }
