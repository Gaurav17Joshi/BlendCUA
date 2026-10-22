"""
Load a reference image as a backdrop empty and orient the viewport to face
it. Used at the start of any object build where a side/profile reference
exists (cup, duck, etc.).

The image Empty has a local X/Y rectangle and a local Z normal.  The rotation
below maps those image axes onto the requested cardinal view instead of using
one rotation for every axis.  In particular, FRONT maps image X to world X
and image Y to world Z; a FRONT reference therefore cannot become edge-on.
"""

import math
import bpy
from mathutils import Matrix, Vector

from lib.view import get_viewport, setup_axis_ortho_view


# Image right, image up, and image-plane normal in world coordinates.  The
# normal chooses which side of a cardinal plane is the image's front; Empty
# images are visible from either side, but the basis also keeps the image
# handedness predictable when the view is changed.
_AXIS_BASIS = {
    "TOP":    (Vector((1, 0, 0)),  Vector((0, 1, 0))),
    "BOTTOM": (Vector((1, 0, 0)),  Vector((0, -1, 0))),
    "FRONT":  (Vector((1, 0, 0)),  Vector((0, 0, 1))),
    "BACK":   (Vector((-1, 0, 0)), Vector((0, 0, 1))),
    "RIGHT":  (Vector((0, 1, 0)),  Vector((0, 0, 1))),
    "LEFT":   (Vector((0, -1, 0)), Vector((0, 0, 1))),
}


def _image_rotation(axis):
    """Return the Euler rotation that maps image local X/Y onto `axis`."""
    key = str(axis).upper()
    try:
        image_right, image_up = _AXIS_BASIS[key]
    except KeyError:
        valid = "|".join(sorted(_AXIS_BASIS))
        raise ValueError("load_reference: axis must be one of " + valid)
    image_normal = image_right.cross(image_up).normalized()
    # Matrix columns are the world directions of local X, Y, and Z.
    basis = Matrix((image_right, image_up, image_normal)).transposed()
    return basis.to_euler()


def load_reference(image_path, axis='RIGHT', name='Reference', display_size=2.0,
                   location=(0.0, 0.0, 0.0), rotation_euler=None):
    """Place an image Empty and set the viewport to the requested ortho axis.

    Args:
        image_path: Absolute path to the PNG/JPG reference.
        axis: Viewport ortho direction the image should face — one of
              ``TOP``|``BOTTOM``|``LEFT``|``RIGHT``|``FRONT``|``BACK``.
              The image plane is oriented to this view.  For example, FRONT
              maps image X/Y to world X/Z instead of placing the plane edge-on.
        name: Object name for the empty.
        display_size: Empty display size in world units along the image's
                      longer axis.
        location: World location of the Empty.  The caller may shift the
                  image datum without changing its orientation.
        rotation_euler: Optional explicit Euler override in radians.  Use only
                        when a reference has a deliberately non-cardinal pose;
                        otherwise `axis` is the source of truth.

    The empty has ``empty_image_depth='BACK'`` so geometry draws in front of
    it, and ``use_empty_image_alpha=True`` so PNG transparency works.

    Returns the created reference Empty.
    """
    img = bpy.data.images.load(image_path, check_existing=True)
    # check_existing returns the datablock already in memory WITHOUT re-reading the file. A long-lived
    # server that loaded an older version of the same path (2026-09-12: the dog's blueprints after the
    # inner strokes were removed on disk) would keep showing the stale pixels. Reload: cheap, always safe.
    try:
        img.reload()
    except Exception:
        pass
    bpy.ops.object.empty_add(type='IMAGE', location=location)
    ref = bpy.context.active_object
    ref.name = name
    ref.data = img

    width, height = (int(v) for v in img.size)
    if width < 1 or height < 1:
        raise ValueError("load_reference: image has no pixels")
    # `empty_display_size` is the image's LONG axis in this toolkit.  A
    # portrait image must therefore keep unit object scale: putting
    # height/width on local Y makes a 6-unit requested height become 9 units
    # after the FRONT rotation.  The old line did exactly that, so a helper
    # call and the calibrated reference projector disagreed about every row.
    ref.empty_display_size = float(display_size)
    ref.scale = (1.0, 1.0, 1.0)
    ref.rotation_euler = (_image_rotation(axis) if rotation_euler is None
                          else rotation_euler)
    ref.empty_image_depth = 'BACK'
    ref.use_empty_image_alpha = True
    if hasattr(ref, 'empty_image_side'):
        try:
            ref.empty_image_side = 'DOUBLE_SIDED'
        except (TypeError, ValueError):
            pass

    area, region, rv3d = get_viewport()
    if area is not None:
        space = area.spaces.active
        if hasattr(space, 'show_background_images'):
            space.show_background_images = True
        space.overlay.show_extras = True
        setup_axis_ortho_view(area, region, rv3d, axis=str(axis).upper())

    return ref
