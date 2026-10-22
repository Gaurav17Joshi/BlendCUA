# Action File Conventions

## Step vs Action

- A **Step** is a logical build unit (e.g. "add seat disc"). Directory: `mem/<run>/steps/step_NNN/`.
- An **Action** is one `.py` file that runs in Blender without an LLM decision in the middle.
  Numbered `01_`, `02_`, … within a step.
- Closed-loop perception needs ≥ 2 actions: one renders the overlay, one applies the picked value.

## Running actions — the `write_and_run` tool

Use `mcp__blender__write_and_run(filename, content, show_screenshot)` for every
action. ONE call writes the file into the current step directory, runs it in
Blender, **waits for completion**, and returns:

- `ok` — whether the script completed without an exception
- `note` — the `shot(...)` message
- `screenshot` / `overlay` — paths of the images this action produced
- the image itself attached inline when `show_screenshot=true` (the overlay
  PNG when the action rendered one, else the bare viewport shot)

Set `show_screenshot=true` for perception/verification actions — you get the
image in the tool result, no separate Read needed. Set `show_screenshot=false`
for blind setup actions (add object, add modifier, mode set, join) to save tokens.

**Do NOT write separate `*_check` / `*_view` verification actions.** Every
action already ends with `shot()` — set the viewport
(`fit_objects_ortho_view`) INSIDE the geometry action right before `shot()`,
pass `show_screenshot=true`, and judge from the returned image. A separate
check action doubles your turns and adds an extra image for zero information.
One check-style action is acceptable only at the very end of a step if the
last geometry action's screenshot angle genuinely cannot show what you need.

On error, `ok=false` and `error` holds the full Python traceback — fix the
content and call `write_and_run` again with the SAME filename (edit in place,
never a new file alongside).

If the tool reports a timeout, the script hung inside Blender (blocking op /
infinite loop). Do NOT sleep or poll — write a simpler replacement action.

Do NOT hand-write a file and then run it separately to perform one action —
that is several turns for what `write_and_run` does in 1. For a full replay of
a whole step range, shell out from `bash`:

```python
import subprocess, sys
print(subprocess.run([sys.executable, "Tool_scripts/win_run_steps.py",
                      "--run", "<run>", "--upto", "N", "--batch"],
                     capture_output=True, text=True).stdout)
```

## Action file boilerplate

Every action file starts with:

```python
import sys
TOOLS_CODE = r"C:\Users\render\Joshi\Blenduse\BlendCuavb_run\Tool_scripts\Tools_code"
if TOOLS_CODE not in sys.path:
    sys.path.insert(0, TOOLS_CODE)

from runtime import use, shot
use("<run_name>", step=N, action=M)

import bpy
# ... your work here ...

shot("<one-line observation>")
```

`use()` creates `screenshots/` and `overlay_json/` directories for the step.
`shot()` renders the viewport screenshot and writes `last_step.json`.

Note: `use()` does NOT save `.blend` checkpoints (removed from BlendCuagent2).

## Every action file starts with a reasoning comment — mandatory, not optional

Before the `import sys` line, write 1–7 comment lines explaining what THIS
action does and — more importantly — WHY you're doing it this way right now:
what value you picked and where it came from (a plan default, a prior
action's overlay reading, a computed measurement), what alternative you
considered and rejected, or what an earlier attempt got wrong that this one
fixes. Skip it only for truly self-explanatory one-liners (a bare viewport
snap with no parameters to justify).

```python
# Step 1, Action 1 — Add ONE leg cylinder + Mirror(X,Y) modifier + splay verts.
#
# One cylinder + Mirror(X,Y) becomes 4 legs once we shift verts off-centre
# in EDIT mode. SPLAY=0.165 gives generous outward spread so that after the
# -6deg inward tilt in action 2 pulls the tops back toward the axis, the
# leg tops still land close to the base rim.

import sys
...
```

This is not decoration — it's the only record of your reasoning that
survives into the saved action file (`mem/<run>/steps/step_NNN/*.py`) for
later inspection, review, or reuse across runs. `prompt_files/examples.md`
is full of these; match that style exactly, don't just describe the code in
different words — say why you chose what you chose.

## First action of a Step

```python
# Step N — <step name>
# Plan:
#   01_<action> — <one line>
#   02_<action> — <one line>
#   03_<action> — written after seeing 02's overlay

import sys
TOOLS_CODE = r"C:\Users\render\Joshi\Blenduse\BlendCuavb_run\Tool_scripts\Tools_code"
if TOOLS_CODE not in sys.path:
    sys.path.insert(0, TOOLS_CODE)

from runtime import use, shot
use("<run_name>", step=N, action=1)
```

## Entering edit mode

Use `enter_edit(obj_name)` from `lib.mesh` instead of the 6-line manual setup:

```python
from lib.mesh import enter_edit
obj = enter_edit("Cushion")   # exits any mode, deselects all, enters EDIT, selects all
bm = bmesh.from_edit_mesh(obj.data)
```

## Review flow — how the reviewer works

After you finish geometry for a step and output your initial JSON, `dispatch_step`
automatically renders the two review images and sends them to a visual reviewer LLM.
The reviewer's full analysis is then injected back into your session as a continuation
message.

**Your job after receiving the reviewer text:**
- If the reviewer is satisfied (says PASS or equivalent) → output your JSON with `"pass": true`
  immediately. Do not re-render, re-check, or investigate.
- If there are issues → fix ONLY what the reviewer named, using at most TWO more
  `write_and_run` calls, then output your JSON with `"pass": true`.

**What NOT to do:**
- Do not write `review_*` action files to render review images.
  `dispatch_step` calls `render_review_shots()` from `review.py` for you.
- Do not `Read` `review_front.png` or `review_persp.png`. Those go to the reviewer LLM,
  not to you. Reading them wastes tool calls and invites second-guessing the reviewer.

**Return JSON format (both initial and final responses):**
```json
{
  "notes": "<what was built and what values were chosen>",
  "actions_taken": <int>,
  "anomalies": [],
  "pass": false
}
```
Set `"pass": true` only when the reviewer is satisfied. Nothing may follow the JSON block.

## Key gotchas

**`bpy.ops.transform.*` hangs without a fresh VIEW_3D context.** Call
`bpy.ops.object.mode_set(mode='EDIT')` immediately before any `transform.translate`,
`transform.resize`, `transform.rotate`, `mesh.bevel`, `mesh.extrude_*`, etc. — even
when already in EDIT mode. The `mode_set` re-establishes the window context.
Skipping this has hung runs before.

**BMesh invalidation**: `bpy.ops.*` and mode toggles invalidate all BMVert/BMFace
references. Save integer indices before any op, re-fetch from a fresh bmesh after.

```python
face_idx = some_face.index
bpy.ops.mesh.select_all(action='DESELECT')
bm = bmesh.from_edit_mesh(obj.data)   # fresh bmesh after the op
bm.faces.ensure_lookup_table()
bm.faces[face_idx].select = True
bmesh.update_edit_mesh(obj.data)
```

**`landmarks.tag()` toggles modes** — extract any values from BMesh elements
BEFORE calling `tag()`.

**Overlay vs bare screenshot**: perception actions produce TWO images. The one you
need for the pick is the `_suffix` file (e.g. `action_02_smap.png`) — the bare
`action_02.png` is overwritten by `shot()`. `write_and_run` already prefers the
overlay when attaching the inline image, so with `show_screenshot=true` you get
the right one automatically.

**New tool modules**: if you add a `.py` under `Tools_code/`, add its module name
to `_TOOL_PREFIXES` in `blender_server.py` so Blender reloads it on each run.
