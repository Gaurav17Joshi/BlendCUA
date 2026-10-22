# BlendCUA Tooling Reference

All tools live in `Tool_scripts/Tools_code/`. The agent imports them directly
inside action files. Overlays (PIL-based) run as subprocesses via `lib/util.py:run_overlay()`
because PIL is not available in Blender's bundled Python.

---

## Transforms

Each transform needs a **perception overlay** so the agent can read a labelled screenshot,
pick a value (tick / grid point / factor), and inline it into the next action.
The overlay produces a JSON sidecar (coordinates + tick labels) alongside the annotated PNG.

Legend: ✅ fully implemented · ⚠️ partial (ruler exists, no overlay) · ❌ not started

| # | Transform | Overlay script | perceive.py wrapper | Modes (V/E/F) | Notes |
|---|-----------|---------------|--------------------|----|-------|
| 1 | **Grab / Move** | `overlays/grab_map_overlay.py` `overlays/grab_grid_overlay.py` | — | V · E · F | Two overlays: `grab_map` draws a world-space destination grid; `grab_grid` draws a screen-space grid for pixel-precise picking |
| 2 | **Scale** | `overlays/scale_map_overlay.py` | `scale_overlay(axis_mask, factors)` | V · E · F | `axis_mask=(1,1,0)` for XY, `(0,0,1)` for Z; `factors` list sets the tick values drawn |
| 3 | **Rotate** | `overlays/rotate_map_overlay.py` | — | V · E · F | Draws candidate rotation-angle ticks around the selection pivot |
| 4 | **Extrude** | `overlays/extrude_map_overlay.py` | `extrude_ruler(axis, kind, step, k_range)` | F | `axis=(0,0,1)` etc.; `kind='screen'` or `'world'`; `step` = pixel or world spacing between ticks |
| 5 | **Bevel (edges)** | ❌ no overlay yet | ❌ | E | `lib/ruler.py:bevel_ruler()` already computes tick data — only the PIL overlay drawing script is missing |
| 6 | **Bevel (vertices)** | ❌ | ❌ | V | Same gap as edge bevel |
| 7 | **Inset** | `overlays/inset_map_overlay.py` | `inset_overlay(px_step)` | F | Works on the currently selected face(s); `px_step` controls tick density |
| 8 | **Loop Cut** | `overlays/loopcut_map_overlay.py` | `loopcut_dirs(seed_loop_indices)` | E (auto) | Renders both candidate ring directions (dirA / dirB) so the agent can pick direction + cut count |
| 9 | **Edge Slide** | ❌ | ❌ | E | Needs a 0.0–1.0 factor ruler drawn along each sliding edge |
| 10 | **Vertex Slide** | ❌ | ❌ | V | Same shape as edge slide but per vertex |
| 11 | **Merge / Weld** | ❌ | ❌ | V | No spatial picker needed — just a mode selector (at center / at cursor / by distance). A simple helper function rather than a full overlay |
| 12 | **Shrink / Fatten** (Alt+S) | ❌ | ❌ | F | Extrude along face normals; same overlay shape as Extrude but radial |

### Overlay input / output contract

Every overlay script follows the contract in `TOOL_AUTHORING.md`:

**Input** (CLI args or JSON file passed by `run_overlay`):
- Screenshot path (PNG already rendered by Blender)
- Ruler / grid JSON produced by the matching `lib/ruler.py` function
- Optional: viewport dims, world→screen projection matrix

**Output**:
- Annotated PNG written next to the input screenshot
- JSON sidecar at `mem/<run>/steps/step_NNN/overlay_json/action_MM_<kind>.json` containing:
  `{ "ticks": [{ "label": "e2", "t": 0.156, "px": [341, 210] }, ...], "viewport": [w, h] }`

The agent reads the annotated PNG, picks a tick by its label, and calls `pick(data, "e2")["t"]`
to get the numeric value to inline into the apply action.

---

## Modifiers

Modifiers mutate the mesh non-destructively (or are applied destructively via `modifier.apply()`).
None have perception overlays yet — the agent sets parameters directly.

| # | Modifier | Status | Notes |
|---|----------|--------|-------|
| 1 | **Mirror** | ❌ no helper | Most commonly needed; symmetrical objects (cups, faces) should have a one-liner `apply_mirror(axis='X')` helper |
| 2 | **Subdivision Surface** | ❌ no helper | Smooths the final form; usually applied last at levels=2 |
| 3 | **Solidify** | ❌ no helper | Adds wall thickness; needs a thickness overlay (same shape as Inset) |
| 4 | **Array** | ❌ no helper | For repetitive geometry (teeth, rungs, bolts) |
| 5 | **Screw** | ❌ no helper | Revolve / helix from a profile curve — useful for turned objects |
| 6 | **Boolean** | ❌ no helper | Union / difference / intersect; landmarks need re-derivation post-op (see `BLENDCUA_AGENT.md §12.6`) |

---

## Selection

Three kinds of selection tool are needed. Perception tools only label — they do not
change mesh selection state. Selection tools change state.

### 1. Labeled window (perception — label what is visible in a region)

Draw a rectangle defined by **top-left / bottom-right in normalised image coords** (0–1, origin top-left).
Every element inside the rectangle gets a short label drawn next to it in the overlay PNG.
The JSON sidecar maps each label to its world coordinate (and index).

| Mode | Script | Status | Output JSON key |
|------|--------|--------|-----------------|
| **Vertices** | `overlays/vertex_map.py` | ✅ | `vertices: [{label, px, world}]` |
| **Edges** | `overlays/edge_map.py` + `overlays/edge_map_overlay.py` | ✅ | `edges: [{label, px_mid, v0_world, v1_world}]` |
| **Faces** | `overlays/grid_map.py` | ✅ | `faces: [{label, px_center, world_center}]` |

**Inputs:** `tl_norm (x,y)`, `br_norm (x,y)`, screenshot path, projection JSON
**Outputs:** annotated PNG + JSON sidecar with labelled elements

### 2. Select in region (action — mutates Blender selection state)

`lib/select.py : select_in_region(tl_norm, br_norm, mode='EDGE', include_occluded=False)`

Selects all elements of the given type whose screen projection falls inside the
normalised rectangle. `include_occluded=False` by default (only front-facing, visible
elements); pass `True` to also select geometry behind the visible surface.

**Inputs:** `tl_norm`, `br_norm`, `mode` ∈ `{'VERT', 'EDGE', 'FACE'}`, `include_occluded`
**Output:** selection state mutated in Blender; returns count of selected elements

### 3. Grid-point picker (perception — coarse spatial reference)

`perceive.face_grid(tl_norm, br_norm, rows, cols)` + `perceive.face_at_grid(row, col)`

Draws an evenly-spaced grid of labelled red dots over the viewport region.
The agent reads the PNG, picks a `(row, col)` dot that sits on the desired geometry,
then calls `face_at_grid(row, col)` to raycast that pixel and return the hit BMFace.

**Inputs:** `tl_norm`, `br_norm`, `rows`, `cols` (grid density)
**Output:** annotated PNG with `row,col` labels · `face_at_grid` returns a `BMFace` or `None`

---

## Observation / Navigation

Tools for moving and orienting the viewport so the agent sees what it needs.

| # | Tool | Status | How |
|---|------|--------|-----|
| 1 | **Axis-aligned ortho snap** | ✅ | `lib/view.py : setup_axis_ortho_view(area, region, rv3d, axis)` — `axis` ∈ `'RIGHT' 'LEFT' 'TOP' 'BOTTOM' 'FRONT' 'BACK'`. Zoom controlled by `zoom_out` multiplier. Standard 6 directions with one call. |
| 2 | **Viewport dot-drag** (pan by clicking a dot) | ❌ | Overlay draws red dots across the viewport; agent picks one; next action sets `rv3d.view_location` so that dot becomes the center. Useful for large scenes where the target is off-screen. |
| 3 | **Focus on selection** (Numpad `.` equivalent) | ❌ | `bpy.ops.view3d.view_selected()` — centers and fits the view on the active selection. One-liner helper; no overlay needed. |
| 4 | **Zoom step** | ✅ (inline) | Modify `rv3d.view_distance` directly then call `rv3d.update()`. Convention: `*= 0.7` to zoom in, `/= 0.7` to restore. |

---

## Primitive Library (`lib/`)

Low-level helpers imported by overlays, perceive.py, and action files.
These are not used directly by the agent — they are building blocks for the tools above.

### `lib/view.py` — viewport & projection

| Function | What it does |
|----------|-------------|
| `get_viewport()` | Returns `(area, region, rv3d)` for the active VIEW_3D; calls `rv3d.update()` to flush pending matrix writes |
| `render_viewport(path)` | Saves a PNG of the current viewport to `path` at region resolution |
| `proj_fn()` | Returns a closure `world_vec → (px_x, px_y)` in image-down pixel coords, consistent with the last `render_viewport` call |
| `setup_axis_ortho_view(area, region, rv3d, axis, zoom_out)` | Snaps to an axis-aligned orthographic view |
| `viewpoint_quality(normal)` | Scores how head-on the current view is to a face normal (1.0 = perpendicular = best; 0.0 = edge-on = worst) |

### `lib/mesh.py` — bmesh selection & topology

| Function | What it does |
|----------|-------------|
| `walk_ring(edge)` | Walks the loop-cut ring through `edge`, returns edges in order |
| `selected_verts_world(bm, mw)` | World-space coords of all currently selected verts |
| `centroid(points)` | Average of a list of world Vectors |
| `representative_spoke(bm, mw)` | Picks the longest radial spoke from selection centroid (for scale axis) |
| `deselect_all(bm)` | Deselects all verts/edges/faces and flushes |
| `select_verts_where(bm, fn)` | Selects verts matching predicate `fn(BMVert) → bool` |
| `select_verts_at_z(bm, mw, z_list)` | Selects all verts whose world-Z is in `z_list` (±1e-4 tolerance) |
| `z_levels(bm, mw)` | Returns sorted list of all unique world-Z values in the mesh |
| `GeoHistory` | Class — snapshots vertex world positions before a topological op so you can query where geometry moved after |
| `find_side_face_by_z(bm, mw, z_low, z_high)` | Finds a quad face whose verts span `z_low` to `z_high` (legacy; prefer `face_at_grid` for new actions) |

### `lib/ruler.py` — tick / polyline builders

These functions do **no drawing** — they return JSON-ready dicts that overlay scripts consume.

| Function | What it does |
|----------|-------------|
| `screen_ruler(proj, verts_world, axis_screen, px_step, k_range)` | Ticks spaced `px_step` pixels apart along a screen axis |
| `world_ruler(proj, origin_world, axis_world, step, k_range)` | Ticks at fixed world-unit intervals |
| `scale_ruler(proj, centroid, spoke, factors)` | Ticks at world-space multiples of a radial spoke vector |
| `bevel_ruler(proj, edge_verts_world, factors)` | One-sided ruler for symmetric ops (bevel, inset); tick 0 = original, tick N = max |
| `loopcut_polylines(proj, bm, ring_edges, n_cuts)` | Projects the cut-line polylines for `n_cuts` loop cuts |
| `rotate_ruler(proj, pivot_world, normal_world, angles_deg)` | Draws candidate rotation angles around a pivot |
| `grab_grid(proj, origin_world, u_axis, v_axis, steps)` | 2-D grid of destination points for Grab overlays |
| `ring_midpoints_polyline(proj, ring_edges, mw)` | Projects the midpoint spine of a ring (used by loopcut overlay) |

### `lib/select.py` — region selection

| Function | What it does |
|----------|-------------|
| `select_in_region(tl_norm, br_norm, mode, include_occluded)` | Selects VERT/EDGE/FACE elements whose screen projection falls inside the normalised box |

### `lib/util.py` — subprocess runner

| Function | What it does |
|----------|-------------|
| `run_overlay(script, *args, logger)` | Spawns `script` (an overlay .py) in the project venv with `args`; used because PIL is unavailable in Blender's Python |

### `lib/trail.py` — viewport trail

| Class / function | What it does |
|----------|-------------|
| `Trail(run, step)` | Saves a numbered viewport PNG each time `.snap(note)` is called; useful for multi-action steps that want a visual history without overwriting the main screenshot |

---

## All Tools in `Tools_code/` (top-level)

These are the modules the agent imports directly in action files.

### `runtime.py` — per-action boilerplate

The first import in every action file. Hides sys.path setup, mem/ folder creation,
checkpoint saving, viewport rendering, and status JSON writes.

| Function | Signature | What it does |
|----------|-----------|-------------|
| `use` | `use(run_name, step, action)` | Initialises paths for this action, saves a `.blend` checkpoint to `steps/step_NNN/checkpoints/action_MM.blend` |
| `shot` | `shot(note="")` | Renders the viewport to `steps/step_NNN/screenshots/action_MM.png` and writes `last_step.json` with `note` |
| `run_dir` | `run_dir()` | Returns `Path` to `mem/<run>/` |
| `step_dir` | `step_dir()` | Returns `Path` to `mem/<run>/steps/step_NNN/` |
| `current` | `current()` | Returns `{run, step, action}` dict |

### `perceive.py` — one-call perception steps

Wraps the screenshot → ruler JSON → overlay subprocess pipeline.
All functions operate on the **currently selected** geometry and return the parsed JSON dict.

| Function | Signature | What it does |
|----------|-----------|-------------|
| `extrude_ruler` | `(axis, kind='screen', step=40, k_range=None)` | Renders a ruler along `axis` for Extrude; `kind='screen'` spaces ticks in pixels, `'world'` in metres |
| `scale_overlay` | `(axis_mask, factors)` | Renders scale factor ticks for Scale; `axis_mask=(1,1,0)` = XY plane |
| `loopcut_dirs` | `(seed_loop_indices=(0,1))` | Renders both candidate loop-cut ring directions so agent can pick one |
| `inset_overlay` | `(px_step=12)` | Renders inset thickness ticks on the selected face |
| `face_grid` | `(tl_norm, br_norm, rows, cols)` | Draws a labelled dot-grid over the viewport region for coarse face picking |
| `face_at_grid` | `(row, col)` | Raycasts the pixel under grid dot `(row,col)` and returns the hit `BMFace` or `None` |
| `pick` | `(data, ordinal)` | Looks up a tick by its label string (e.g. `"e2"`, `"s3"`) in any ruler JSON payload |

### `landmarks.py` — stable geometry references

Vertex-group–backed landmarks that survive extrude, subdivide, and bevel.
See `BLENDCUA_AGENT.md §7` for the full rationale.

| Function | Signature | What it does |
|----------|-----------|-------------|
| `tag` | `(name, description)` | Creates vertex group `bc_<name>` from current selection; appends to `landmarks.json` |
| `resolve` | `(name)` | Returns list of `BMVert` objects for landmark `name` |
| `select` | `(name)` | Deselects all, then selects the landmark verts in EDIT mode |
| `select_edges_among` | `(name)` | Selects all edges whose both endpoints belong to landmark `name` |

### `reference.py` — backdrop reference image

| Function | Signature | What it does |
|----------|-----------|-------------|
| `load_reference` | `(path, name, size, location)` | Loads an image as an Empty → Image object so it appears as a viewport backdrop for the agent to trace against |

### `handle.py` — curved handle segments

Higher-level helper for building cup / jug handles. Each segment is a prepare + apply pair.

| Function | Signature | What it does |
|----------|-----------|-------------|
| `prepare_segment` | `(angle_deg, grab_steps)` | Extrudes the selected face, rotates it by `angle_deg`, renders a grab-grid overlay so the agent can pick a destination |
| `apply_grab` | `(row, col)` | Translates the selected face to the grab-grid point `(row, col)` picked from the overlay |
| `extrude_rotate` | `(angle_deg)` | Extrude + rotate in one shot with no perception step (used when the angle is known in advance) |

---

## What Is Still Missing

Ordered by impact on modelling quality:

| Priority | Gap | What to build |
|----------|-----|---------------|
| 🔴 High | **Bevel overlay** | `overlays/bevel_map_overlay.py` + `perceive.bevel_overlay()`. `lib/ruler.py:bevel_ruler()` already exists — only the PIL drawing code is missing. |
| 🔴 High | **Focus on selection** | One-liner helper wrapping `bpy.ops.view3d.view_selected()`. No overlay needed. |
| 🟠 Medium | **Shrink/Fatten overlay** | `overlays/shrink_fatten_overlay.py` + `perceive.shrink_fatten_overlay()`. Same shape as Extrude overlay but driven by face normals outward. |
| 🟠 Medium | **Edge Slide overlay** | Factor ruler (0.0–1.0) drawn along each candidate edge. |
| 🟠 Medium | **Mirror modifier helper** | `apply_mirror(obj, axis='X')` — one function, no overlay needed. |
| 🟡 Low | **Viewport dot-drag** | Overlay of red dots across the viewport; agent picks one; action pans `rv3d.view_location` to that world point. |
| 🟡 Low | **Subdivide count overlay** | Simple integer picker (1–8 cuts) drawn over the selected edges. |
| 🟡 Low | **Solidify overlay** | Thickness ruler — same shape as Inset overlay. |
| ⚪ Later | **Boolean helper** | Complex: needs landmark re-derivation post-op. Document in `skills/` first. |
