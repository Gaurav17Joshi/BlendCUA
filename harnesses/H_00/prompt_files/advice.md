# General Working Advice

## Before writing any code

1. **Read the reference image.** Note the proportions, how the parts divide up,
   and anything the plan singles out.
2. **Read the build plan.** It is the authoritative spec, and it is written to
   give you the tool to use and the shape to aim for rather than exact
   coordinates — use its preview tools and judge against the reference by eye.

**The image is the ground truth. The plan is how to get there.**

Both live in the task folder named at the top of your prompt, along with every
other asset the plan mentions — an annotated reference, a landmark JSON, a
partial screenshot of a stage. If the plan names a file, it is in that folder;
`read` it from there rather than searching the repo.

## Check whether the tool already exists

`current_tools.md` carries the tools every build needs — viewport, selection,
transforms. It is deliberately not the whole toolkit: there are ~195 callables
under `Tool_scripts/Tools_code/`, and cracking, weathering, baking, lighting,
painting and sculpting all live outside your prompt.

So before you hand-roll anything, spend one `bash` call finding out:

```bash
python Tool_scripts/tool_help.py --search crack     # find it by what it does
python Tool_scripts/tool_help.py apply_chain        # its FULL docstring
python Tool_scripts/tool_help.py --module handle    # everything in one module
```

`Tool_scripts/Tools_ref/INDEX.md` is the complete list — if a tool is not in
there it does not exist. `Tools_ref/operations.md`, `sculpting.md` and
`wear_and_texture.md` are the worked examples and the traps for the parts that
were moved out of your prompt; the module map in `current_tools.md` says which
one to open.

**Read a tool's full docstring before the first time you call it.** A one-line
summary tells you a tool exists; it does not tell you that brush size is in
screen pixels, or that a preview's `scales` are ratios rather than radii. Fifty
lines of bmesh reimplementing a call that already exists is the most expensive
mistake available to you, and one grep prevents it.

## Set the viewport first

Before doing any mesh work, snap to a meaningful ortho axis and fit the objects:

```python
from lib.view import fit_objects_ortho_view, get_viewport
area, region, rv3d = get_viewport()
fit_objects_ortho_view(area, region, rv3d, axis='FRONT', names=['Cushion'], ratio=80)
```

A well-framed screenshot is the only way to judge whether the result is correct.
A badly zoomed or off-axis view makes the feedback useless.

**Use `fit_objects_ortho_view` for essentially every view you set**, and name
the objects or the reference image you want framed. It focuses the camera on
exactly those things and fills the frame with them, which is what makes a
screenshot readable. `setup_axis_ortho_view` is the rare fallback — it fits the
whole scene and cannot see an image Empty at all, so with a reference photo
loaded it leaves the subject at about a quarter of the frame.

```python
fit_objects_ortho_view(area, region, rv3d, axis='TOP', names=['BatBody'], ratio=85)
fit_objects_ortho_view(area, region, rv3d, axis='TOP', names=['BatRef'],  ratio=90)
```

## Overlays before every spatial transform

Never hardcode a dimension you could measure with an overlay. Before applying any
transform that has a spatial degree of freedom:

| Operation | Overlay call | Suffix |
|---|---|---|
| Extrude along axis | `extrude_ruler(axis, kind, step)` | `_exmap` |
| Scale verts/faces | `scale_overlay(axis_mask, factors)` | `_smap` |
| Loop cut direction | `loopcut_dirs(seed_loop_indices)` | `_lcmap` |
| Pick a face | `face_map(tl_norm, br_norm)` | `_fmap` |
| Pick face by grid | `face_grid(tl_norm, br_norm, rows, cols)` | `_grid` |
| Grab / translate | `grab_preview(plane_axes, n_dots, px_step)` | `_ggrid` |
| Grab along axis | `grab_line_preview(axis, kind, step)` | `_exmap` |

The table above is mesh transforms, but the rule is about **any** action with a
spatial degree of freedom. A sculpt stroke has one: where the path runs and how
big the brush is on screen. Preview it with `paint.stroke_lines_preview` before
you cut, and **preview every pass, not just the first** — the pass you skip is
the one that goes wrong, and a cut cannot be undone by looking at it afterwards.

Exception: operations with no spatial degree of freedom — join, delete,
mode_set, adding a modifier.

**A plan giving you numbers is NOT an exception.** This is the trap: a good plan
hands you radii, strengths and depths, and that makes a step feel scripted —
values already decided, nothing left to look at. But the numbers are in world
millimetres and the brush is in screen pixels, so what a "25 mm brush" actually
does depends on framing the plan cannot know. Measured on pillar_run_002: the
plan supplied every number, the agent previewed the first corner and then cut
eleven more times blind. The previews are how you find out the numbers landed —
the more precisely a plan specifies a step, the more there is to check, not
less.

## The core loop

Write one action → run it → read the screenshot → write the next action.
Never write two actions ahead without running the first.
Overlay actions especially cannot be pre-written — the apply action is written
only after you see the overlay PNG.

## ⚠️ The redo rule — mandatory

**Every preview, overlay or `silhouette_vs_reference` must be followed by a
second pass at the thing it measured.** One pass is never enough.

1. Run the preview / silhouette.
2. **Look at what came back** — crop in if the part is small.
3. **Redo that action** under the same filename, adding a new `REDO` note
   **above the existing header, without deleting anything already there**:

```python
# REDO 2: "<what was off this time, and what you changed because of it>"
# REDO 1: "<what was off last time, and what you changed because of it>"
#
# Step 2, Action 11 — Apply the six back-face horizontal creases.
# <the original header, untouched>
```

then new parameters.

**The comments accumulate; only the code changes.** Same filename means the
harness rewinds and replays, so the redo replaces the first attempt *in the
Blender scene* — that is about geometry, not about the file's comments. Keep
the original header and every earlier `REDO` line exactly as written and add
yours on top, so the file reads as a history: what this action was for, then
each thing that was wrong and what you did about it.

Deleting the previous comments destroys the only record of why the earlier
values were rejected. The next person to touch this action — including you,
two steps later — then has no way to know that the value they are about to
"fix" is one you already tried and measured. Observed on pillar_run_002 and
gravestone_run_001: every redo wrote a fresh header and erased the reasoning
of the attempt before it, so a step with four redos ended up documenting one.

This holds **even when the first attempt looks fine** — looking again with the
result in front of you is a different act from looking at a preview and
guessing. If nothing genuinely needs changing, still write the comment and say
so, naming what you looked at and what you compared it against.

A step whose action files contain no `REDO LOGIC:` comments has not been
checked, whatever its report says.

## Looking properly — the part builds actually fail on

**Write your own Python to look at things** — crop a screenshot with PIL, scan
for an edge, overlay a grid. Not in an action file: an action runs inside
Blender and a slow one freezes the session.

**`write` the script into your step's `scripts/` folder**
(`mem/<run>/steps/step_NNN/scripts/`, created for you) and then `bash` it by
name. **Do not pipe it in with `python - <<'PY'` or `python -c`** — that leaves
nothing behind, and you will want the same crop again after every fix. A saved
script re-runs in one short call. A step that produced no `.py` files in
`scripts/` almost certainly did not look closely enough at what it built.

**A screenshot cannot tell you how far off you are.** Solid shading covers the
reference exactly where you need to compare. Use
`perceive.silhouette_vs_reference("<name>")` — it draws your mesh's outline onto
the reference photo and returns the measured half-width at stations along the
object. Pass a list once there is more than one object, so Mirror modifiers show
up. It runs inside Blender, so it costs an action; spend it.

**One zoom is never enough.** Crop to the part you are judging before you judge
it — a full-frame render spends nearly all its detail on background. A detail
40 px wide cannot be assessed at full frame, and this is the single most common
way a build passes review while being badly wrong.

**Take the time to get it right.** There is no reward for finishing a step
quickly or in few calls. Every check you skip, every "that looks about right",
every value you leave in because re-running feels like effort — those are the
only things that make a step fail.

## Building on a flat reference photo

- **The Z datum is zero, for everything.** The reference Empty lies at z = 0 and
  the first body mesh is centred on it, so the photo passes through the model's
  mid-depth like a blueprint slice. Every part added later is placed in Z
  relative to that same plane. **No part gets a "sit it on top of the reference"
  offset.** If you inherit a build whose body is not centred on z = 0, say so in
  your report rather than matching the offset.
- Build the reference Empty **by hand** — not with `reference.load_reference`,
  which is for vertical backdrops and sets `scale.y` to the image aspect. Leave
  that in and the photo is stretched, so every proportion measured off it is
  wrong.
- Keep the model inside the reference silhouette. If something pokes out, keep
  it small.
- To fix a value, **rewrite that action file and send it again with the same
  name** — the harness rewinds and re-runs it. Don't add a new action to correct
  the previous one forward.
- Screen picks are normalised 0–1 coords through `unproject_norm`, never raw
  screenshot pixels.

## Fixed values are starting points

Parameters like `SPLAY`, `ANGLE_DEG`, `EXTRUDE_Z` and scale factors are reasonable
defaults. If the screenshot shows a proportion that looks off against the reference
image, adjust the value and re-run. Use your visual judgement.

## Choosing view axis

- `'TOP'` — camera at +Z, looking down; shows XY plane (bird's eye).
- `'FRONT'` — camera at +Y, looking back; shows XZ plane (X right, Z up).
- `'RIGHT'` — camera at +X, looking left; shows YZ plane.

Use FRONT for extrude/lift steps. Use TOP for XY scale and face-picking.
Use a 3/4 ortho (manual `rv3d.view_rotation`) for dome/top operations.

## Diagnosing errors and hangs

`write_and_run` reports both cases directly in its result:

- **`ok=false` with a traceback in `error`** → Python exception in Blender.
  Fix the file content, call `write_and_run` again with the same filename.
- **Timeout reported** → the script hung (blocking call / infinite loop) — it
  will never finish. Do NOT sleep, poll, or search logs. Write a simpler
  replacement action and run it immediately. If Blender itself appears frozen,
  tell the human to restart the Blender server.

## Keep actions small

One logical operation per action. If an action is exceeding ~30 lines of actual
work, split it. Smaller actions are easier to retry and cleaner in the rollout.

## Landmarks for key geometry

```python
from landmarks import tag, select
tag("seam_verts", list_of_vert_indices)
# later:
select("seam_verts")
```

Landmarks survive extrude/subdivide/bevel. They do NOT survive deleting the
tagged verts.

## Extract tools after two uses

If you write the same prep code in two action files, extract it into a helper
under `Tool_scripts/Tools_code/`. Name it with an action verb. Add the module
name to `_TOOL_PREFIXES` in `blender_server.py`.
