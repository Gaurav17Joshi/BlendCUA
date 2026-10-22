# Tool authoring notes (BlendCUA)

How to write a new "map" tool (extrude, scale, inset, loopcut, grab, …)
without falling into the same bugs the existing ones did.

A map tool is two halves:

- **export script** runs inside Blender, reads the bmesh, computes
  world-space anchors, renders a viewport screenshot, projects anchors
  to screen, writes a JSON sidecar.
- **overlay script** runs as plain Python (PIL only), reads the JSON,
  reopens the PNG, draws dots/lines/labels at the projected coords.

The agent never moves the mouse. It picks a tick label ("e2", "s1.5",
"t6") and the export script's metadata translates that label back into
a world-space operation.

---

## 0. Layout

```
Tool_scripts/
├── run.py                     entry point — pipes a .py script to Blender via TCP
├── blender_server.py          run once inside Blender; execs whatever run.py sends
├── scripts/                   high-level "build X" scripts (e.g. build_cup.py)
└── Tools_code/
    ├── TOOL_AUTHORING.md      this file
    ├── lib/                   Blender-side shared helpers (import via sys.path)
    │   ├── view.py            get_viewport, render_viewport, proj_fn,
    │   │                      viewpoint_quality, setup_axis_ortho_view
    │   ├── mesh.py            walk_ring, deselect_all, select_verts_at_z,
    │   │                      z_levels, find_side_face_by_z, centroid
    │   ├── ruler.py           screen_ruler, scale_ruler,
    │   │                      loopcut_polylines, ring_midpoints_polyline
    │   ├── trail.py           Trail — numbered step-by-step screenshot dir
    │   └── util.py            run_overlay — subprocess runner for PIL overlays
    └── overlays/              PIL-side overlay scripts (run as subprocesses)
        ├── extrude_map_overlay.py    scale_map_overlay.py
        ├── inset_map_overlay.py      loopcut_map_overlay.py
        ├── grab_map_overlay.py       edge_map.py
        ├── grid_map.py               vertex_map.py
        ├── screenshot.py             visualize_coords.py
```

A new build script should look like `scripts/build_cup.py`: prepend
`Tools_code/` to `sys.path`, force-reload `lib.*` for dev iteration,
then `from lib.view import …` etc.

```python
import sys, os
TOOLS_CODE = "/Users/gauravjoshi/Desktop/R/Blendcua/BlendCuagent1/Tool_scripts/Tools_code"
if TOOLS_CODE not in sys.path:
    sys.path.insert(0, TOOLS_CODE)
for _k in [k for k in list(sys.modules) if k == "lib" or k.startswith("lib.")]:
    del sys.modules[_k]    # so edits to lib/ take effect each run

from lib.view  import get_viewport, render_viewport, proj_fn, setup_axis_ortho_view
from lib.mesh  import walk_ring, centroid, deselect_all
from lib.ruler import screen_ruler, scale_ruler
from lib.trail import Trail
from lib.util  import run_overlay
```

---

## 1. The one bug that keeps biting: stale `perspective_matrix`

`rv3d` carries two parallel representations of the view:

| Properties (what you set)             | Matrices (what gets read)         |
|---------------------------------------|-----------------------------------|
| `rv3d.view_perspective`               | `rv3d.perspective_matrix`         |
| `rv3d.view_distance`                  | `rv3d.window_matrix`              |
| `rv3d.view_rotation`, `view_location` | `rv3d.view_matrix`                |

Operators (`bpy.ops.view3d.view_axis`, `view_all`, `view_orbit`, …)
update both. Direct writes update only the property — the matrices
stay stale. Blender's own docs say so on `RegionView3D.update()`:
*"Recalculate the view matrices, since the dirty flag is not set when
modifying properties."*

`bpy.ops.render.opengl(view_context=True)` rebuilds its own matrix
internally, so the **rendered image** is fine. But
`bpy_extras.view3d_utils.location_3d_to_region_2d` reads
`rv3d.perspective_matrix` directly — so the **projected coords** are
based on the stale matrix.

The result is the bug we hit: cup rendered in ortho, ticks projected in
perspective, dots land hundreds of pixels off the visible geometry.

**Rule.** After any direct write to `rv3d.view_*`, call
`rv3d.update()`. `lib.view.get_viewport()` and `lib.view.proj_fn()`
already do this for you, but if you write to `rv3d` between calls (e.g.
`rv3d.view_distance *= 0.7`), call `rv3d.update()` yourself.

How to tell at a glance whether you've been bitten: for a pure ortho
axis (e.g. axis `(0,0,1)` in a RIGHT view), `Δscreen.y / Δt` should be
**constant** across ticks. If it grows the further you go, your
projection is perspective, no matter what `view_perspective` says.

---

## 2. Render and project at the SAME view state

The screenshot and the projected coords must describe the same view.
If you zoom, render, restore zoom, then project — your dots are for the
un-zoomed view but the image is zoomed. Same hazard with any other
view mutation between the two steps.

Order matters:

```python
rv3d.view_distance *= 0.7        # mutate view
rv3d.update()
render_viewport(path)            # render at this view
payload = scale_ruler(pivot, spoke, axis, region, rv3d, path, factors)  # project here
json.dump(payload, open(json_path, "w"))
rv3d.view_distance = orig_dist   # restore AFTER projection
rv3d.update()
```

If you have to mutate the view between render and project, you've made
a mistake — go back and do all projections before restoring.

Step 5 of `build_cup.py` is the canonical example.

---

## 3. World-space first, screen-space second

Compute everything you need in world space **before** rendering. The
render call can re-enter Blender's event loop, can flush selection in
some builds, and can perturb state in general. The build_cup script
already learned this the hard way — it always rederives selection from
a stable geometric predicate (e.g. "all verts whose Z is in this set of
intermediate levels") after a render, via `lib.mesh.select_verts_at_z`.

Safer pattern:

```python
# A. world-space measurements
sel_w   = [mw @ v.co for v in bm.verts if v.select]
pivot   = centroid(sel_w)
spoke   = (max(sel_w, key=lambda w: (w - pivot).dot(axis_hat)) - pivot).project(axis_hat)
# B. render
render_viewport(IMG)
# C. project (uses only pivot + spoke from step A — no bmesh access)
payload = scale_ruler(pivot, spoke, axis, region, rv3d, IMG, factors)
```

Touch bmesh once, before render. Touch rv3d only for render + project.

---

## 4. bmesh selection: face.select does NOT auto-flush

```python
bpy.ops.mesh.select_all(action='DESELECT')
top_face.select = True
bmesh.update_edit_mesh(obj.data)
```

This *happens to work* because setting `face.select = True` propagates
down to edges/verts via bmesh's internal coercion. But the inverse is
not true: `vert.select = True` does NOT mark the face selected. And in
some Blender builds the propagation has bugs.

Use the helpers in `lib.mesh`:

```python
deselect_all(bm)                          # direct + flush outward
select_verts_at_z(bm, mw, [z1, z2])       # predicate + flush inward
select_verts_where(bm, pred, mw=mw)       # generic
```

After any selection write, follow with `bmesh.update_edit_mesh(obj.data)`
to sync to Blender.

---

## 5. Selection invariants across renders

`bpy.ops.render.opengl` can clear `v.select` on some platforms/builds.
The build_cup script defends against this by **rederiving** selection
from a stable geometric predicate (Z-level membership) each time,
instead of trusting that `v.select` survived the render.

Whenever a tool needs to re-select between render and op, derive
selection from world-space geometry, not from the previous selection
flag. `select_verts_at_z` exists exactly for this.

---

## 6. JSON contract

Every export writes a JSON file with at least:

```json
{
  "viewport_width":  1623,
  "viewport_height": 1092,
  "image":           "/.../viewport_xxx.png",
  "pivot_screen":    {"x": 811.5, "y": 496.68},
  "ticks":           [
    {"ordinal": "e1", "t": 0.408, "screen": {"x": 811.5, "y": 464.48}}
  ]
}
```

- `viewport_width/height` are `region.width / region.height` at the
  moment of render. The overlay scales by `W/vp_w, H/vp_h`, so as long
  as the aspect ratio matches the image, mismatched resolution
  (Retina, HiDPI, percentage scaling) is harmless. This is what makes
  `lib.view.SHOT_SCALE` free: renders come out at 2× the region and every
  overlay rescales itself. If you write a new overlay, derive coordinates
  and font/dot sizes from the image's own size — never assume the PNG is
  region-sized.
- All `screen` coords use **image convention** (origin top-left, y
  growing **down**). `proj_fn` flips Y via `region.height - s.y`.
  Never mix region-space (y up) and image-space (y down) coords in the
  same field.
- **Emit picks as normalised 0–1, not pixels.** The PNG the agent is
  finally shown has been capped at 1440×1080 (aspect preserved) by
  `run_steps.resize_new_pngs()` / `blendcua_core._resize_png_inplace()`
  *after* your overlay drew on it, so any absolute pixel you label
  becomes meaningless the moment the agent reads it back. Normalised
  coords survive the rescale untouched. When the agent hands a pick
  back, resolve it with `lib.view.unproject_norm()` — never
  `region_2d_to_location_3d()` on raw pixels, which is wrong in both
  scale and Y sign and fails silently.
- `ordinal` is what the agent picks. The export script owns the mapping
  from `ordinal` → world-space transform; the overlay only needs it to
  draw the label.

The builders in `lib.ruler` (`screen_ruler`, `scale_ruler`,
`loopcut_polylines`) all return dicts that already match this contract.

---

## 7. Viewpoint quality

A ruler along an axis nearly parallel to the view direction degenerates
(everything projects to a single point). Compute and write a quality
score; the harness can use it to reject a screenshot and ask for a
different view.

```python
from lib.view import viewpoint_quality
q = viewpoint_quality(axis_world, rv3d)   # 1.0 = ideal, 0.0 = head-on
```

Below ~0.3 the ruler is basically unusable — re-orient the camera
first. `screen_ruler` and `scale_ruler` already include this in their
output payload.

---

## 8. Overlay rule: fade the background 50% before drawing

Every `*_overlay.py` script must blend the source screenshot with a
black image at `alpha=0.5` before drawing anything else. Red ticks /
yellow handles / blue axis lines vanish into the bright grey of
Blender's default viewport otherwise.

```python
img  = Image.open(data["image"]).convert("RGB")
W, H = img.size
img  = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), alpha=0.5)
draw = ImageDraw.Draw(img)
```

This is in every overlay (extrude, scale, inset, loopcut, grab). If
you add a new overlay, copy this block first.

---

## 9. Overlay scripts (PIL-side) still duplicate a lot

The five `*_overlay.py` files in `Tools_code/overlays/` (and to a
lesser extent `edge_map.py`, `vertex_map.py`, `grid_map.py`) share
~50 lines of identical boilerplate each:

- argparse `--json`/`--output`
- `to_px(sp) = sp.x*W/vp_w, sp.y*H/vp_h`
- `load_font(size)` searching macOS font paths
- `fs / fs_l / r / lw` from `min(W, H)`
- the color palette (`AXIS`, `DOT`, `PIVOT`, `HANDLE`, …)
- "blue line through pivot, full image span" (identical math in extrude
  + scale + inset)
- "background fade 50%, then draw" (scale + inset)
- `viewport_x.png` → `viewport_x_{suffix}.png` save

A future `Tools_code/overlays/lib_overlay.py` could expose:

```python
load_payload(json_path)              -> (data, img, W, H)
to_px(sp, W, H, vp_w, vp_h)          -> (px, py)
load_font(size)                      -> ImageFont
style_for(W, H)                      -> {fs, fs_l, r, lw, font, font_l}
PALETTE                              ≡ namespace with AXIS, DOT, PIVOT, ...
draw_axis_through(draw, p, q, ...)   -> None
save_with_suffix(data, img, suffix)  -> str
```

Shrinking each overlay to ~30 lines. Not done yet because the existing
files work and the user's brief was to extract from `build_cup.py`
first.

---

## 10. Checklist for a new tool

Before committing a new map tool (export logic in your script + matching
`*_overlay.py`):

- [ ] Uses `lib.view.get_viewport()` (auto-`rv3d.update()`)
- [ ] Renders via `lib.view.render_viewport(path)`
- [ ] Projects via `lib.view.proj_fn(region, rv3d)` or a `lib.ruler.*`
      builder
- [ ] If you write to `rv3d.view_*` directly, call `rv3d.update()` after
- [ ] Render and project happen at the same view state (no mutation in
      between)
- [ ] All world-space measurements (pivot, axis, spoke, ring edges)
      computed **before** `render_viewport()`
- [ ] If selection is needed after render, re-derive from geometry
      (`select_verts_at_z` / `select_verts_where`), not from `v.select`
- [ ] `bmesh.update_edit_mesh(obj.data)` after any selection write
- [ ] JSON has `viewport_width`, `viewport_height`, `image`, and all
      screen coords in image-down convention
- [ ] `viewpoint_quality` written when the tool depends on an axis
      direction
- [ ] Sanity check: for an axis-aligned ortho view, `Δscreen / Δt`
      along that axis is constant across ticks
- [ ] Overlay script starts with the 50% black-blend fade (see §8)

---

## 11. Debugging projections quickly

The fastest way to find a projection bug without re-running Blender is
to inspect the JSON. From the project root:

```python
import json
d = json.load(open('screenshots/your_map.json'))
pivot_y = d['pivot_screen']['y']
for t in d.get('ticks') or d['screen_ruler']['ticks']:
    dy = t['screen']['y'] - pivot_y
    v  = t.get('t') or t.get('factor') or t.get('thickness')
    print(f"{t['ordinal']:6s} v={v:+.3f} dy={dy:+.2f} ratio={dy/v if v else 0:.2f}")
```

For a true ortho ruler the ratio is constant. Drift means perspective
crept in — almost always `rv3d.update()` missing somewhere.
