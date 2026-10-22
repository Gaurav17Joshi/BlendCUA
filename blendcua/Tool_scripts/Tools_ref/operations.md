<!-- moved out of prompt_files/current_tools.md — read on demand, not in any prompt -->

# Operation tools — worked examples

The summary table, the mandatory render-then-apply rule, and the O1 example
that establishes the idiom all live in `current_tools.md`, which you already
have. This file is the rest of the worked examples: O2-O8 follow O1's shape
exactly, so read O1 first and come here for the specific call.

---

## O2 — Scale verts / edges / faces

Renders radial scale factor ticks around the selection centroid. `axis_mask`
controls which axes are scaled — `(1,1,0)` scales XY only (keeps Z), `(1,1,1)`
scales uniformly. Provide `factors` as a list of candidates around 1.0.

```python
# Action N: render scale overlay
from perceive import scale_overlay, pick
data = scale_overlay(axis_mask=(1, 1, 0), factors=[0.8, 0.9, 1.0, 1.1, 1.3, 1.5])
shot("XY scale overlay rendered — pick factor from _smap.png")

# Action N+1: apply
F = 1.3   # read from s4 tick in the PNG
bpy.ops.transform.resize(value=(F, F, 1.0),
                         constraint_axis=(True, True, False))
shot(f"scaled XY by {F}")
```

## O3 — Inset a face

Renders a one-sided ruler of inset thickness candidates from the selected face's
edges inward. Ticks are labeled `i1`, `i2`, …

```python
# Action N: render inset overlay
from perceive import inset_overlay, pick
data = inset_overlay(px_step=12)
shot("inset overlay rendered — pick thickness from _imap.png")

# Action N+1: apply
T = 0.025   # read from i3 tick in the PNG
bpy.ops.mesh.inset(thickness=T, depth=0)
shot(f"inset at T={T}")
```

## O4 — Loop cut (direction + count)

Shows both candidate ring-cut directions over the selected face so you can pick
which one cuts horizontally vs vertically. Apply via `bmesh.ops.subdivide_edges`
on the chosen ring.

```python
# Action N: render direction preview
from perceive import loopcut_dirs
from lib.mesh import walk_ring
payload, rings = loopcut_dirs(seed_loop_indices=(0, 1))
shot("loop cut directions rendered — pick dirA or dirB from _lcmap.png")

# Action N+1: apply chosen direction (0 = dirA, 1 = dirB)
DIR = 0
bm = bmesh.from_edit_mesh(obj.data)
ring = rings[DIR]
bmesh.ops.subdivide_edges(bm, edges=ring, cuts=1, use_grid_fill=True)
bmesh.update_edit_mesh(obj.data)
shot("loop cut applied — dirA, 1 cut")
```

## O5 — Grab to a 2D grid point (translate in a plane)

Renders a labeled N×N grid of destination dots in a world-space plane. Each dot
carries the exact `(dx, dy)` translation needed to move the selection centroid
to that point. Use for planar placements: XY (top view), ZX (front view), ZY
(side view).

```python
# Action N: render grab grid
from perceive import grab_preview, grab_at
from mathutils import Vector
grab_preview(plane_axes=(Vector((1,0,0)), Vector((0,1,0))),
             n_dots=7, px_step=40)
shot("XY grab grid rendered — pick (i, j) from _ggrid.png")

# Action N+1: translate to picked point
I, J = 2, 3   # read from the PNG
grab_at(i=I, j=J)   # reads the JSON written by grab_preview, applies translation
shot(f"selection moved to grid point ({I}, {J})")
```

## O6 — Grab along a single axis (1D line ruler)

Renders a linear ruler of tick marks along a world axis — same visual as the
extrude ruler but semantics are for translate, not extrude. Use for single-axis
lifts (Z), side-shifts (X or Y), or any move where you know the direction.

```python
# Action N: render Z-lift ticks every 0.05 m
from perceive import grab_line_preview, pick
data = grab_line_preview(axis=(0, 0, 1), kind='world', step=0.05)
shot("Z grab ruler rendered — pick tick from _exmap.png")

# Action N+1: apply
T = pick(data, "g4")["t"]   # world-space Z distance
bpy.ops.transform.translate(value=(0.0, 0.0, T))
shot(f"selection lifted by {T}m")
```

## O7 — Rotate around a single axis

Renders angle tick marks around the selection centroid for a single rotation
axis. Ticks are labeled `r1`, `r2`, … and carry the angle in degrees.

```python
# Action N: render rotation preview around Z
from perceive import rotate_preview, pick
data = rotate_preview(axis=(0, 0, 1), reference_pt=None, pivot=None)
shot("Z rotation overlay rendered — pick angle from _rmap.png")

# Action N+1: apply
DEG = pick(data, "r3")["angle_deg"]   # read from PNG
bpy.ops.transform.rotate(value=math.radians(DEG), orient_axis='Z')
shot(f"rotated {DEG}° around Z")
```

## O8 — Rotate trackball (yaw + pitch grid)

Renders a 2D grid of (yaw, pitch) outcome dots. Each dot shows where a reference
point lands after that rotation about a pivot. Use for tilting legs inward,
angling handles, etc., where you need simultaneous yaw and pitch control.

```python
# Action N: render trackball grid
from perceive import rotate_trackball, trackball_at
rotate_trackball(
    reference_pt=Vector((0.18, 0.18, 0.0)),   # the point that moves (leg bottom)
    pivot=Vector((0.18, 0.18, 0.65)),          # the point it rotates around (leg top)
    n_dots=5, deg_step=5
)
shot("trackball grid rendered — pick (i, j) from _ggrid.png")

# Action N+1: apply rotation around the same pivot
I, J = -1, -1   # read from PNG (negative = tilt inward)
yaw_deg, pitch_deg = trackball_at(i=I, j=J)
bpy.context.scene.cursor.location = (0.18, 0.18, 0.65)
bpy.context.scene.tool_settings.transform_pivot_point = 'CURSOR'
bpy.ops.transform.trackball(
    value=(math.radians(yaw_deg), math.radians(pitch_deg))
)
shot(f"legs tilted: yaw={yaw_deg}° pitch={pitch_deg}°")
```


---

## O12 — Handle arc segments (composite helper)

For building arched handles or any arc-extruded feature. Each segment is one
prepare → grab cycle.

```python
from handle import prepare_segment, apply_grab, extrude_rotate

# Action N: extrude one segment, rotate it −20°, render grab grid
prepare_segment(label="seg1", extrude_t=0.08, rotate_deg=-20)
shot("seg1 grab grid rendered — pick (row, col)")

# Action N+1: translate the segment to the picked grid point
apply_grab(label="seg1", grab_row=3, grab_col=4)
shot("seg1 placed at (3, 4)")

# Subsequent arc segments that don't need a grid pick:
extrude_rotate(angle_deg=−20)   # extrude + rotate in one call, no grid
shot("next arc segment added")
```

## O13 — Reference backdrop

Places the reference photo in the scene as an image-empty at the origin and
snaps the viewport to face it, so screen picks and the photo share one frame.

```python
from reference import load_reference
load_reference(
    "/abs/path/to/plans/<Task>/<image>",   # absolute; it lives in the task folder
    axis='RIGHT',        # which ortho view the image faces
    name="DuckRef",
    display_size=0.60,   # WORLD WIDTH in metres — this sets the whole build's scale
)
shot("reference loaded at 0.60 m wide")
```

`display_size` is the one number the rest of the build hangs off: it decides how
many world metres a pixel of the photograph is worth, so every distance you
later trace off it is wrong by whatever factor this is wrong by. Set it from the
real object's size, and write it down.

**Two traps.** The empty sits at the origin — `load_reference` takes no
`location`, so offset the *model*, not the photo, if they overlap. And it sets
`scale.y` from the image aspect, which is right for a vertical backdrop and
wrong for a flat blueprint-style trace where the photo must pass through the
model's mid-depth: for that case build the empty by hand and leave the scale
alone, or every proportion measured off it is stretched.

---

## lib/mesh.py — worked examples

The function table is in `current_tools.md`. These are the two patterns worth
copying.

```python
from lib.mesh import z_levels, select_verts_at_z, deselect_all, walk_ring

bm  = bmesh.from_edit_mesh(obj.data)
mw  = obj.matrix_world

all_zs = z_levels(bm, mw)
top_z  = max(all_zs)

deselect_all(bm)
select_verts_at_z(bm, mw, z_levels=[top_z])
bmesh.update_edit_mesh(obj.data)
```

### Custom-position loop cuts: `loopcut_at_fractions`

Use this instead of a bare `bmesh.ops.subdivide_edges(cuts=N, ...)` whenever
the new rings should NOT be evenly spaced — e.g. two rings crowded toward
each end of a band (`[0.2, 0.8]`) so the middle stays a wide, flat-radius
section once scaled, rather than `cuts=2`'s default even 1/3, 2/3 spacing.

```python
from lib.mesh import walk_ring, loopcut_at_fractions

face = next(f for f in bm.faces if f.select)   # seed face, direction already
                                                # confirmed via loopcut_dirs
ring_edges = walk_ring(face.loops[DIR_INDEX].edge)

rings = loopcut_at_fractions(
    obj, bm, ring_edges,
    fractions=[0.2, 0.8],   # measured from top_z downward (from_top=True)
    top_z=CUP_H, bottom_z=BASE_H,
)
# rings[0] = the ring at 0.2 (near the top), rings[1] = the ring at 0.8
bmesh.update_edit_mesh(obj.data)   # already called inside, but a fresh
bm = bmesh.from_edit_mesh(obj.data)  # re-fetch before any further bmesh.ops
```

---

