---
name: coordinate-frames-and-units
description: The conversions that silently produce plausible wrong answers — screen vs world, crop offsets, resolutions, UV's flipped axis, brush pixels.
evidence: 08_desk_chair_run_001 step_003; 14_sneaker_run_001 steps 1, 3, and 4
---

# Coordinate frames and units

None of these are hard. All of them have produced real mistakes here, and they
share one property: **the wrong answer looks plausible.** Defend by habit — print
or assert the size and the convention you are assuming, immediately before using
it.

## Screenshot resolution is not one number

`run.py` (single-action replay) renders at native viewport resolution, which
varies — around 1595 × 1207 on one machine. `run_steps.py` (full replay)
additionally **resizes every screenshot afterwards** to a fixed `SHOT_W`/`SHOT_H`.

A pixel coordinate computed against one does not line up with the other. Always
check `im.size` before doing pixel maths on a screenshot whose provenance you are
not certain of, and prefer normalised (0–1) coordinates for anything you intend to
persist.

## Keep one authoritative image frame

A reference file, a camera render, and a viewport screenshot can all have
different dimensions and coordinate conventions. Before reusing a measured
point, record its source image size and its top-left/bottom-left origin. For a
non-square product render, divide by that render's actual width and height, not
a remembered reference height or a capped viewport height. If the view must be
camera view, set `rv3d.view_perspective = 'CAMERA'` and call `rv3d.update()`;
`bpy.ops.view3d.view_camera()` is a toggle and can leave camera view.

## Crop-local, full-image, normalised

A pixel found *inside* a crop needs the crop's offset added back before it means
anything:

```python
x_norm = (crop_x0 + local_x) / full_width
```

Name variables for which frame they are in. `x_px_crop` and `x_norm` never get
confused; `x` and `x2` always do.

## Screen picks only mean anything in one view

`apply_chain` unprojects each point against the depth of the previous one, so a
traced point is defined *by the view it was read in*. Pin the view explicitly and
re-establish it at the top of every action that reads one:

```python
setup_axis_ortho_view(area, region, rv3d, axis='RIGHT')
rv3d.view_location = (0.0, 0.023, 0.033); rv3d.view_distance = 0.42
```

The same applies to painting: `apply_paint_lines` projects through the *current*
view, so an edge map read in one framing and painted in another lands somewhere
plausible and wrong. Set the view longhand in both actions, identically.

And do not use `region_2d_to_location_3d` with pixels read off a delivered PNG —
the PNG and the live region are different sizes with opposite Y. Use
`lib.view.unproject_norm(x_norm, y_norm, region, rv3d)`.

## UV's V axis is bottom-up; image rows are top-down

```python
pixel_xy = (u * img_w, (1 - v) * img_h)
```

Get it backwards and you produce a vertically flipped overlay that still looks
like a plausible wireframe over a plausible photo.

## Local is not world

An object's origin is not necessarily at the world origin, and its axes are not
necessarily the scene's:

- The gravestone's base was lifted by half its height to stand on the ground, so
  `v.co.z` is not world Z, and a filter for "the base's top ring" silently matched
  nothing.
- The duck's seed circle was created with a 90° object rotation, so the mesh's
  local axes are not the scene's — asking for the face with the largest local Y
  returned a side quad off the flank. Three separate bugs in that one build had
  this cause.

**Anything comparing positions between objects, or against the view, uses
`matrix_world`.** Always.

For rotated geometry, a transformed `obj.bound_box` is a conservative axis-aligned
box around the local bound-box corners, not the exact set of evaluated vertices.
When floor contact or an intersection depends on the true surface, update the
depsgraph and compute min/max from evaluated mesh vertices in world space. This
matters for wheels and other curved parts: an empty bound-box corner can appear
below the floor even when no actual vertex does.

## `matrix_world` is stale inside the script that made the object

The depsgraph has not run yet, so a freshly created object's `matrix_world` is
still the identity. Derive from `rotation_euler` instead. A light's aim vector
computed from `matrix_world` in its own creation script points straight down.

## Brush size is in screen pixels

Native sculpt brushes size in **screen pixels**, not world units, and do not scale
with the object: a 50 mm brush is 7 px with a whole pillar in frame and 35 px with
one block in frame. Frame the piece, take the `px/m` that `frame_ortho` returns,
convert, and state every size in metres in your own code.

How much of its radius a brush actually cuts also varies by brush — `DRAW_SHARP`
about 90%, `PLANE` about 17%. They cannot be sized alike.

## Two image widths, not one

When measuring off a reference in fractions of its own size, a non-square image
has **two** conversion factors — one per axis. Using the wrong one on the chilli
plant would have been a 68% error. Expose them as two named functions, one per
axis, so the mistake cannot be made silently.
