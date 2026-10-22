"""
Shape-key helpers for rigid-rotation poses (wing/leg/head flap states).

  add_rotation_shape_key(obj, key_name, pivot_world, axis_world, angle_deg,
                          vert_filter=None)
      Add (or overwrite) a shape key that's a RIGID rotation of the
      object's Basis vertices around a world-space pivot+axis. Always
      computed fresh from Basis (not from the current mix), so calling
      this again for the same key_name is idempotent — safe to re-run.
      vert_filter(local_co) -> bool restricts which vertices move (e.g.
      only the "head" portion of a body mesh); None = rotate everything.
      Unfiltered-out vertices are set to their exact Basis position (not
      left untouched), so the key is always a complete, correct copy of
      Basis outside the filtered region.

  set_shape_key_values(obj, values)
      values: dict of {key_name: 0.0-1.0}. Sets obj.data.shape_keys
      .key_blocks[key_name].value for each entry; any OTHER non-Basis key
      on the object is set to 0.0 so only the requested pose (or a
      deliberate mix) is visible — avoids stray leftover key weights from
      an earlier preview silently blending into a later one.
"""

import math
import bpy
from mathutils import Vector, Matrix


def ensure_basis(obj):
    """Return the object's Basis shape key, creating it if there is none.

    The Basis holds the rest pose every other key is measured against, so
    it must exist before any key is added — and it must be captured
    BEFORE you deform anything, or the rest pose is already the pose.
    """
    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)
    return obj.data.shape_keys.key_blocks["Basis"]


def add_rotation_shape_key(obj, key_name, pivot_world, axis_world, angle_deg,
                            vert_filter=None):
    """Add a shape key that rigidly rotates part of the mesh.

    Every vertex passing `vert_filter` is rotated `angle_deg` about the
    world-space line through `pivot_world` along `axis_world`; the rest
    are pinned to their Basis position. This is how a wing folds or a leg
    bends without a rig — the pose is a value between 0 and 1 rather than
    geometry you have to rebuild.

    `vert_filter` takes a LOCAL coordinate and returns True to move it.
    Everything else here is world-space, so a filter written in world
    terms picks the wrong verts on any object with a non-identity
    transform — the usual reason a fold hinges in the wrong place.
    """
    basis = ensure_basis(obj)
    key = obj.data.shape_keys.key_blocks.get(key_name)
    if key is None:
        key = obj.shape_key_add(name=key_name, from_mix=False)

    mw = obj.matrix_world
    mw_inv = mw.inverted()
    axis = axis_world.normalized()
    rot = Matrix.Rotation(math.radians(angle_deg), 4, axis)

    for i, bv in enumerate(basis.data):
        local_co = bv.co
        if vert_filter is not None and not vert_filter(local_co):
            key.data[i].co = local_co
            continue
        world_co = mw @ local_co
        rotated = pivot_world + (rot @ (world_co - pivot_world))
        key.data[i].co = mw_inv @ rotated
    return key


def add_bend_shape_key(obj, key_name, pivot_world, axis_world, span_axis_world,
                        max_angle_deg, max_distance, vert_filter=None, power=1.0,
                        min_angle_deg=0.0):
    """Like add_rotation_shape_key, but the rotation angle at each vertex
    is GRADUATED by its distance from the pivot along span_axis_world —
    min_angle_deg right at the pivot, ramping up to max_angle_deg at
    max_distance (and staying at max_angle_deg beyond it) — a smooth
    curve/flex along the object's length instead of one rigid tilt for
    every vertex. Use for something like a wing that should visibly bend
    more toward the tip than right at the shoulder.

    min_angle_deg: rotation right AT the pivot (default 0.0 = perfectly
    flat there). A small non-zero value (same sign as max_angle_deg)
    keeps the region right next to the pivot from looking completely
    rigid/flat while the rest of the object bends — e.g. a wing's root
    should sag/lift a little too, not stay dead flat while everything
    past it curves.

    power: exponent on the normalized distance fraction (0-1) before
    interpolating between min_angle_deg and max_angle_deg. 1.0 = linear
    ramp; >1 concentrates the change toward the far end (flatter near the
    pivot); <1 ramps up faster near the pivot instead.

    Call with the SAME pivot_world/axis_world/span_axis_world/max_distance
    across every object that shares a physical edge (e.g. a wing membrane
    and the finger bones it's attached to) — since the angle at a given
    vertex depends only on its own world position along span_axis_world,
    shared/coincident points across different objects get the exact same
    angle and stay attached, no tearing.
    """
    basis = ensure_basis(obj)
    key = obj.data.shape_keys.key_blocks.get(key_name)
    if key is None:
        key = obj.shape_key_add(name=key_name, from_mix=False)

    mw = obj.matrix_world
    mw_inv = mw.inverted()
    axis = axis_world.normalized()
    span = span_axis_world.normalized()

    for i, bv in enumerate(basis.data):
        local_co = bv.co
        if vert_filter is not None and not vert_filter(local_co):
            key.data[i].co = local_co
            continue
        world_co = mw @ local_co
        offset = world_co - pivot_world
        dist = offset.dot(span)
        t = max(0.0, min(1.0, dist / max_distance))
        angle = min_angle_deg + (max_angle_deg - min_angle_deg) * (t ** power)
        rot = Matrix.Rotation(math.radians(angle), 4, axis)
        rotated = pivot_world + (rot @ offset)
        key.data[i].co = mw_inv @ rotated
    return key


def set_shape_key_values(obj, values):
    """Set the named keys to the given values and every other key to 0.

    `values` is {key_name: 0.0-1.0}. Absent keys are zeroed rather than
    left alone, so one call fully describes the pose instead of layering
    onto whatever the last one left behind. Basis is never touched.
    """
    sk = obj.data.shape_keys
    if sk is None:
        return
    for kb in sk.key_blocks:
        if kb.name == "Basis":
            continue
        kb.value = values.get(kb.name, 0.0)
