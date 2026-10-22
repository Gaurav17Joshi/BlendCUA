# BlendCUA v2 — Worked Examples

Ten complete actions across five steps building a bar-stool seat assembly.
Four overlays, six pure-scripting actions. Read them in order — each action's
header explains *why* this approach, and each overlay's apply action explains
*why that specific tick or factor* was chosen.

Import boilerplate is shown in full in Action 1 only; subsequent actions omit
the `sys.path` block for readability — it is always required in real files.

## How actions are executed

Each action below is delivered as ONE `write_and_run` call — the tool writes
the file, runs it in Blender, waits for completion, and returns the `shot()`
note plus the screenshot (attached inline when `show_screenshot=true`):

```
mcp__blender__write_and_run(
    filename="01_leg_mirror.py",
    content="<the full file source shown in the example>",
    show_screenshot=False,   # True for overlay / verification actions
)
```

The file contents below are unchanged — only the delivery mechanism differs
(no separate Write + Bash + cat + Read sequence).

---

## Step 1 — Leg cylinder with Mirror modifier (1 action)

**Goal:** create one cylinder and one modifier that together give us four legs,
without managing four separate objects.

### Action 1 — add leg + Mirror(X,Y)

```python
# Step 1, Action 1 — Add ONE leg cylinder + Mirror(X+Y) modifier.
#
# One cylinder + Mirror(X, Y) becomes 4 legs once we shift verts
# off-centre in EDIT mode — cheaper than 4 separate objects and keeps
# geometry symmetric by construction (the modifier enforces it, so a
# manual mistake in one quadrant can never desync the others).
# Next: action 2 renders a grab-line ruler so we can pick a Z-lift for
# the base ring.

import sys
TOOLS_CODE = r"C:\Users\render\Joshi\Blenduse\BlendCuavb_run\Tool_scripts\Tools_code"
if TOOLS_CODE not in sys.path:
    sys.path.insert(0, TOOLS_CODE)

from runtime import use, shot
use("bar_stool_run_003", step=1, action=1)

import bpy

# Clean slate. Use clear_scene() — NOT select_all + object.delete, which
# silently leaves objects behind: select_all cannot select anything a later
# action hid (hide_viewport=True), and delete leaves zero-user datablocks in
# bpy.data still holding their names, so the next objects.new("Foo") becomes
# "Foo.001". Every replay then leaks a stray object plus its orphan meshes.
from lib.util import clear_scene
clear_scene()

# Single leg at world origin. depth=0.65 → bottom at z=0, top at z=0.65.
# location.z = depth/2 so the cylinder sits on the floor, not through it.
bpy.ops.mesh.primitive_cylinder_add(
    vertices=22,
    radius=0.015,
    depth=0.65,
    location=(0, 0, 0.325),
)
leg = bpy.context.active_object
leg.name = "Leg"

# Move the OBJECT origin to world (0,0,0) so the Mirror modifier
# reflects across the world XY axes, not across the cylinder centre.
# The mesh stays put; only the pivot point moves.
bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
bpy.ops.object.origin_set(type='ORIGIN_CURSOR')

mir = leg.modifiers.new(name="Mirror_XY", type='MIRROR')
mir.use_axis[0] = True    # X
mir.use_axis[1] = True    # Y
mir.use_axis[2] = False   # Z

shot("Leg cylinder at origin with Mirror(X,Y) — still 1 visible rod until verts are shifted")
```

---

## Step 2 — Lift the base ring above the legs (2 actions)

**Goal:** use a grab-line overlay to read the exact Z value that places the base
floor just above the leg tops, then apply it.

### Action 2 — render Z-lift ruler (OVERLAY — perception only)

```python
# Step 2, Action 2 — Render grab-line ruler along +Z over the Base verts.
#
# We need the Base floor to sit just above the leg tops at ~0.65 m.
# The ruler puts a labelled tick every 0.05 m along +Z so we can read
# the exact target from the PNG rather than guessing.
# We use grab_line_preview (not extrude_ruler) because semantics here
# are translate, not extrude — same underlying ruler, right naming.
# Next: read action_02_exmap.png, pick the tick nearest to 0.65 m,
# write that value as T in action 3.

from runtime import use, shot
from lib.mesh import enter_edit
from lib.view import get_viewport, setup_axis_ortho_view
from perceive import grab_line_preview

use("bar_stool_run_003", step=2, action=2)

obj = enter_edit("Base")   # exits any prior mode, selects Base, enters EDIT, selects all

# FRONT ortho zoomed out so the full leg region is visible alongside the
# ruler ticks. Do NOT call focus_selected after — it overwrites view_distance.
area, region, rv3d = get_viewport()
setup_axis_ortho_view(area, region, rv3d, axis='FRONT', zoom_out=1.5)

grab_line_preview(
    axis=(0, 0, 1),
    kind='world',
    step=0.05,
    k_range=list(range(-15, 16)),   # ticks e-15..e15 → ±0.75 m range
)

shot("Grab-line ruler rendered — FRONT ortho, ticks every 0.05 m along +Z. "
     "Pick the tick nearest to 0.65 m (leg top height) from action_02_exmap.png.")
```

**After this action:** open `screenshots/action_02_exmap.png`. Find the tick
label whose position aligns with the top of the legs. At step=0.05 m, e13
lands at 0.65 m — the right clearance. Write that as `T` in action 3.

### Action 3 — apply the picked Z-lift (apply action)

```python
# Step 2, Action 3 — Translate Base verts up by T picked from action 2's ruler.
#
# T = 0.65 m → tick e13 on action_02_exmap.png.
# e13 puts the base floor right at leg-top height with a thin clearance.
# e14 (0.70 m) would leave a visible gap under the seat; e12 (0.60 m)
# would clip slightly through the leg ends. e13 is the right call.

from runtime import use, shot
use("bar_stool_run_003", step=2, action=3)

import bpy

# ───────── Tick picked from action_02_exmap.png ─────────
T = 0.65    # e13 — base floor just clears the leg tops
# ────────────────────────────────────────────────────────

if bpy.context.mode != 'EDIT_MESH':
    bpy.ops.object.mode_set(mode='EDIT')

bpy.ops.transform.translate(value=(0.0, 0.0, T))
shot(f"Base verts lifted by T={T} m (e13) — base floor now sits at leg-top height.")
```

---

## Step 3 — Cushion: add cylinder, loop cut, apply (4 actions)

**Goal:** create the cushion cylinder, use a face-grid overlay to pick a seed
face on its side wall, pick the correct loop-cut ring direction with a second
overlay, then apply the cut.

### Action 4 — add cushion cylinder (scripting)

```python
# Step 3, Action 4 — Add the cushion cylinder above the base ring.
#
# Radius 0.22 m slightly overhangs the base ring (r=0.18) for a proper
# seated look — the cushion should be wider than the frame below it.
# Z position: base sits at 0.65 m; cushion depth 0.09 m → centre at
# 0.65 + 0.045 = 0.695.  Using 32 verts: smooth enough after subsurf,
# few enough that the face-grid overlay in action 5 can label them clearly.

from runtime import use, shot
use("bar_stool_run_003", step=3, action=4)

import bpy

if bpy.context.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.object.select_all(action='DESELECT')

bpy.ops.mesh.primitive_cylinder_add(
    vertices=32,
    radius=0.22,
    depth=0.09,
    location=(0, 0, 0.695),
)
cushion = bpy.context.active_object
cushion.name = "Cushion"

shot("Cushion cylinder added — r=0.22, depth=0.09, centre Z=0.695.")
```

### Action 5 — render face-grid over cushion side wall (OVERLAY — perception only)

```python
# Step 3, Action 5 — FRONT ortho, 8×8 face-grid overlay over the cushion.
#
# loopcut_dirs (action 6) needs a seed face on the SIDE WALL — not the top
# or bottom cap. The grid dots land on whatever face is under them in screen
# space; picking a dot in the left or right half of the silhouette reliably
# hits a side quad. Picking a dot at the very top or bottom risks hitting a
# cap face, which sends loopcut_dirs walking the wrong ring.
# Next: read action_05_grid.png, pick (ROW, COL) of a dot on a visible
# side quad, write it into action 6's ROW / COL constants.

from runtime import use, shot
from lib.mesh import enter_edit
from lib.view import get_viewport, fit_objects_ortho_view
from perceive import face_grid

use("bar_stool_run_003", step=3, action=5)

import bpy

# select_all=False: we want the deselected state so the grid screenshot
# is clean — no orange highlight obscuring face boundaries.
enter_edit("Cushion", select_all=False)
bpy.ops.mesh.select_all(action='DESELECT')

# fit_objects_ortho_view centres and zooms tight on the Cushion so side
# faces fill the frame — more reliable raycasting than a loose zoom.
area, region, rv3d = get_viewport()
fit_objects_ortho_view(area, region, rv3d, axis='FRONT', names='Cushion', ratio=85)

face_grid(
    tl_norm=(0.20, 0.20),
    br_norm=(0.80, 0.80),
    rows=8,
    cols=8,
    labels=True,
)

shot("face_grid rendered on Cushion — FRONT ortho 85%. "
     "Pick (ROW, COL) of a dot on a SIDE face (not top/bottom cap) "
     "from action_05_grid.png.")
```

### Action 6 — render loop-cut direction overlay (OVERLAY — perception only)

```python
# Step 3, Action 6 — Raycast the picked (ROW, COL) dot to a face, then
# render the two candidate loop-cut ring directions on that face.
#
# loopcut_dirs shows dirA and dirB as coloured polylines over the mesh.
# On a cushion side quad, one direction wraps HORIZONTALLY around the
# cushion equator (the ring we want — it creates the mid-height edge loop
# we'll scale outward in step 4) and the other walks VERTICALLY through
# the face columns (wrong — this would give us a meridian ring).
# dirA vs dirB is ambiguous without seeing the overlay; the ring_len
# values in the shot message give a cross-check (the horizontal ring
# has 32 edges; the vertical one has far fewer).
# Next: read action_06_lcmap.png, identify the horizontal ring,
# note whether it's dirA (index 0) or dirB (index 1), write into action 7.

from runtime import use, shot
from lib.mesh import enter_edit
from lib.view import get_viewport, fit_objects_ortho_view
from perceive import face_grid, face_at_grid, loopcut_dirs

use("bar_stool_run_003", step=3, action=6)

import bpy, bmesh

# ───────── Picks from action_05_grid.png ─────────
ROW, COL = 4, 2   # a dot on the left-side wall of the cushion
# ─────────────────────────────────────────────────

enter_edit("Cushion", select_all=False)
bpy.ops.mesh.select_all(action='DESELECT')

# Re-render the same view so the raycast projection matches action 5's grid.
area, region, rv3d = get_viewport()
fit_objects_ortho_view(area, region, rv3d, axis='FRONT', names='Cushion', ratio=85)

# face_grid writes the dot→screen-coord mapping; face_at_grid raycasts it.
face_grid(tl_norm=(0.20, 0.20), br_norm=(0.80, 0.80), rows=8, cols=8, labels=True)

cushion = bpy.data.objects["Cushion"]
face_idx = face_at_grid(row=ROW, col=COL)
bm = bmesh.from_edit_mesh(cushion.data)
bm.faces.ensure_lookup_table()

if face_idx is None:
    shot(f"Raycast missed at ({ROW},{COL}) — adjust ROW/COL and re-run.")
else:
    bm.faces[face_idx].select = True
    bmesh.update_edit_mesh(cushion.data)
    payload, _ = loopcut_dirs(seed_loop_indices=(0, 1))
    shot(f"Face {face_idx} selected. loopcut dirs rendered — "
         f"dirA: {payload['directions'][0]['ring_len']} edges, "
         f"dirB: {payload['directions'][1]['ring_len']} edges. "
         f"Pick the direction that wraps HORIZONTALLY (expect 32 edges) "
         f"from action_06_lcmap.png.")
```

### Action 7 — apply loop cut in picked direction (apply action)

```python
# Step 3, Action 7 — Apply the loop cut in the horizontal direction.
#
# DIR_INDEX = 0 (dirA) was confirmed from action_06_lcmap.png —
# dirA's polyline runs around the equator (32 edges, as expected).
# dirB ran vertically through the face columns (8 edges only) — wrong ring.
# N_CUTS = 1: a single mid-height ring gives us one equatorial band
# to scale outward. More cuts would compress the puff geometry
# unnecessarily and add cost to the bevel in a later step.

from runtime import use, shot
from lib.mesh import enter_edit, walk_ring
use("bar_stool_run_003", step=3, action=7)

import bpy, bmesh

# ───────── Picked from action_06_lcmap.png ─────────
DIR_INDEX = 0   # 0 = dirA (horizontal equatorial ring)
N_CUTS    = 1   # one ring at mid-height
# ───────────────────────────────────────────────────

enter_edit("Cushion", select_all=False)

cushion = bpy.data.objects["Cushion"]
bm = bmesh.from_edit_mesh(cushion.data)
bm.faces.ensure_lookup_table()

face = next((f for f in bm.faces if f.select), None)
if face is None:
    shot("No face selected — re-check action 6's (ROW, COL) and re-run.")
else:
    ring = walk_ring(face.loops[DIR_INDEX].edge)
    bmesh.ops.subdivide_edges(bm, edges=ring, cuts=N_CUTS, use_grid_fill=True)
    bmesh.update_edit_mesh(cushion.data)
    shot(f"Loop cut dirA × {N_CUTS} applied ({len(ring)} ring edges). "
         f"Middle ring now exists at local z≈0.")
```

---

## Step 4 — Bulge middle ring outward (2 actions)

**Goal:** select the new equatorial ring by world-Z predicate, render a radial
XY scale overlay, then apply the chosen factor to puff the cushion sides.

### Action 8 — select middle ring + render XY scale overlay (OVERLAY — perception only)

```python
# Step 4, Action 8 — Select the equatorial ring at local z≈0, render XY
# scale overlay to pick a bulge factor.
#
# We identify the ring by local Z (≈0) rather than by landmark or screen
# rect because the ring's world position can shift slightly if the cushion
# object was moved; local Z is invariant to object translation.
# Factors 1.00–1.40 span no-change to a heavy puff. Target: 1.15 gives
# a recognisable padded-cushion silhouette — 15% equatorial overhang — 
# without looking over-inflated. 1.10 is too subtle; 1.25+ starts to look
# like a balloon. The overlay confirms which one visually fits.
# Next: read action_08_smap.png, note the factor label, write it as
# SCALE in action 9.

from runtime import use, shot
from lib.mesh import enter_edit
from lib.view import get_viewport, fit_objects_ortho_view
from perceive import scale_overlay

use("bar_stool_run_003", step=4, action=8)

import bpy, bmesh

enter_edit("Cushion", select_all=False)

cushion = bpy.data.objects["Cushion"]
bm = bmesh.from_edit_mesh(cushion.data)
bm.verts.ensure_lookup_table()

# Select only the verts at local z≈0 (the equatorial ring from action 7).
# Tolerance 1e-4 is tight enough to exclude adjacent rings (they sit at
# local z ≈ ±0.045, i.e. at the top/bottom caps of this 0.09 m disc).
bpy.ops.mesh.select_all(action='DESELECT')
n_sel = 0
for v in bm.verts:
    if abs(v.co.z) < 1e-4:
        v.select = True
        n_sel += 1
bm.select_flush(True)
bmesh.update_edit_mesh(cushion.data)

# FRONT view tight on the cushion — scale ticks need to be readable against
# the silhouette, not lost in a wide shot with legs visible.
area, region, rv3d = get_viewport()
fit_objects_ortho_view(area, region, rv3d, axis='FRONT', names='Cushion', ratio=90)

scale_overlay(
    axis_mask=(1, 1, 0),
    factors=[1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40],
)

shot(f"Middle ring selected ({n_sel} verts at local z≈0). "
     f"XY scale overlay rendered — pick SCALE from action_08_smap.png.")
```

### Action 9 — apply the picked XY scale (apply action)

```python
# Step 4, Action 9 — Scale the equatorial ring outward by the picked factor.
#
# SCALE = 1.15 — confirmed from action_08_smap.png as the s4 tick.
# 1.15 pushes the equator 15% wider in XY while leaving Z untouched,
# giving the classic padded-cushion puff. The selection from action 8
# is still live so no re-selection is needed here.

from runtime import use, shot
use("bar_stool_run_003", step=4, action=9)

import bpy

# ───────── Factor from action_08_smap.png ─────────
SCALE = 1.15    # s4 tick — 15% equatorial bulge
# ──────────────────────────────────────────────────

if bpy.context.mode != 'EDIT_MESH':
    bpy.ops.object.mode_set(mode='EDIT')

bpy.ops.transform.resize(
    value=(SCALE, SCALE, 1.0),
    constraint_axis=(True, True, False),
    orient_type='GLOBAL',
)

shot(f"Middle ring scaled {SCALE}× in XY — cushion sides now bulge outward.")
```

---

## Step 5 — Select seam ring by vertex connectivity (1 action)

**Goal:** given a landmark of seam-vert indices and a face picked from a prior
overlay, grow the selection to the full 32-face seam ring using geometry — not
`bpy.ops.mesh.loop_multi_select`, which fails here.

### Action 10 — resolve seam ring by connectivity

```python
# Step 5, Action 10 — Select the full seam ring from a landmark + a face pick.
#
# Why NOT bpy.ops.mesh.loop_multi_select: on this mesh the seam ring sits
# between a bevel edge below and a domed face above, both causing sharp
# normal discontinuities. Blender's loop-select operator follows normal
# continuity heuristics and consistently mis-walks onto the bevel faces,
# selecting the wrong ring or silently deselecting everything.
#
# Why connectivity instead: every seam vert has exactly 4 link edges —
# 2 to adjacent seam verts (horizontal ring) and 2 to "wall" neighbours
# (one outer-rim, one inner-rim). We identify outer vs inner by XY radius.
# A seam-ring face is then a quad with exactly {2 seam verts + 2 outer-rim
# verts}. This is deterministic regardless of normal or selection state.
#
# The SEAM_LABEL face pick (from a prior face_map overlay) is still used as
# a sanity check: we assert the picked face is in the collected ring. If it
# isn't, the shot message surfaces a diagnostic rather than silently selecting
# the wrong thing.

from runtime import use, shot
from perceive  import face_at_label
from landmarks import resolve

use("bar_stool_run_003", step=5, action=10)

import bpy, bmesh

# ───────── Face label picked from a prior face_map overlay ─────────
SEAM_LABEL = "F18"    # any face in the 32-face seam ring
# ───────────────────────────────────────────────────────────────────

cushion    = bpy.data.objects["Cushion"]
picked_idx = face_at_label(SEAM_LABEL, prior_action=7)

bpy.ops.mesh.select_mode(type='FACE')
bpy.ops.mesh.select_all(action='DESELECT')

# resolve() manages its own bmesh internally — call it BEFORE we take
# our own bmesh reference to avoid reference aliasing.
seam_ids = set(resolve("seam_verts"))

bm = bmesh.from_edit_mesh(cushion.data)
bm.faces.ensure_lookup_table()
bm.verts.ensure_lookup_table()

# Classify each seam vert's non-seam neighbours by XY radius:
# the one with the larger radius is the outer-rim vert, the smaller is inner.
outer_rim_ids = set()
for vid in seam_ids:
    v = bm.verts[vid]
    non_seam = [e.other_vert(v) for e in v.link_edges
                if e.other_vert(v).index not in seam_ids]
    if len(non_seam) < 2:
        continue
    by_r = sorted(non_seam, key=lambda w: w.co.x**2 + w.co.y**2)
    outer_rim_ids.add(by_r[-1].index)

# Seam-ring faces: quads with exactly 2 seam verts + 2 outer-rim verts.
seam_ring_faces = [
    f for f in bm.faces
    if len(f.verts) == 4
    and len({v.index for v in f.verts} & seam_ids)     == 2
    and len({v.index for v in f.verts} & outer_rim_ids) == 2
]

for f in seam_ring_faces:
    f.select = True
bm.select_flush(True)
bmesh.update_edit_mesh(cushion.data)

picked_in_ring = picked_idx is not None and any(
    f.index == picked_idx for f in seam_ring_faces
)

shot(f"Seam ring selected — {len(seam_ring_faces)} faces (expect 32). "
     f"Picked {SEAM_LABEL}=face_idx={picked_idx} "
     f"{'✓ in ring' if picked_in_ring else '✗ NOT in ring — try a different label'}.")
```

---

## Quick-reference: action file skeleton

Every action file follows this skeleton:

```python
import sys
TOOLS_CODE = r"C:\Users\render\Joshi\Blenduse\BlendCuavb_run\Tool_scripts\Tools_code"
if TOOLS_CODE not in sys.path:
    sys.path.insert(0, TOOLS_CODE)

from runtime  import use, shot
from lib.mesh import enter_edit          # always for object-specific actions
use("run_name", step=N, action=M)        # must be first; creates dirs + checkpoint

import bpy, bmesh
from mathutils import Vector
import math

# ───────── constants picked from the prior overlay (overlay actions only) ─────
TICK  = 0.65    # or SCALE = 1.15, or DIR_INDEX = 0, etc.
# ──────────────────────────────────────────────────────────────────────────────

obj = enter_edit("ObjectName")           # or enter_edit("Name", select_all=False)
bm  = bmesh.from_edit_mesh(obj.data)
mw  = obj.matrix_world

# ... do work ...

shot("one-line note: what changed and any key numeric results")
```

**The two-action overlay rule:** every spatial operation spans exactly two
actions — a *render* action (perception only, no mesh change) followed by an
*apply* action (no overlay call). Never write the apply action before running
the render action and reading the screenshot.
