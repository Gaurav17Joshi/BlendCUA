# Terminal & Blender Interaction

## Setup (done by human before you start)

- Blender is open with a clean scene and viewport.
- `Tool_scripts/win_blender_server.py` has been run in Blender's Script Editor
  — it listens on `localhost:6666`.
- Working directory: the `BlendCuavb_run/` project root (Windows).

## Your tools

You have the ordinary coding tools, plus one that drives Blender:

- **`read(path, offset?, limit?)`** — read a file. Text comes back with line
  numbers; **images come back as pixels you can look at**.
- **`write(path, content)`** — write a file. For helper modules, scratch
  scripts, notes. Not for this step's `NN_*.py` build actions.
- **`edit(path, old_string, new_string, replace_all?)`** — change part of a
  file. **This is how you fix a value.** Never re-send a whole file to change
  one number.
- **`glob(pattern, path?)`** — find files by name, e.g. `'**/*.py'`.
- **`grep(pattern, path?, glob?, output_mode?)`** — search file contents.
  `mem/` is skipped unless you point at it explicitly.
- **`bash(command, timeout?, cwd?)`** — run a shell command. PIL crops, pixel
  scans, anything slow. `bpy` does **not** exist here; that's `write_and_run`.
- **`write_and_run(filename, content, show_screenshot?)`** — the Blender one.
  Writes the action file *and* runs it in one call.

**Other runs under `mem/` are off limits, and the tools enforce it.** `mem/`
holds every run this project has ever done. They are not reference material:
several failed review, and where one of them got something wrong the plan
already tells you so directly. Copying an earlier run's numbers reproduces its
mistakes, and their screenshots show you geometry you are trying not to build.
Your own run's directory is readable as normal — that is how you inspect your
earlier actions. Build this step from the plan, the reference photo, and your
own measurements.

**Anything that is not a change to the Blender scene does not belong in an
action file.** Not because it is wasteful, but because an action runs *inside
Blender*: anything slow in there freezes the whole session instead of just
failing, and a crash takes the scene with it. Inspection belongs in `bash`,
where it is safe and where a mistake costs you nothing but a re-run.

| Job | Use |
|---|---|
| Read a plan, a note, or one of your own earlier actions | `read` — never a Blender action that just `open()`s a file |
| Look at an image | `read` — the reference photo, an earlier crop, a previous step's render |
| Find a helper's signature before calling it | `read` on `Tool_scripts/Tools_code/handle.py`, or `grep` |
| See what files exist | `glob`, e.g. `mem/<run>/steps/step_001/*.py` |
| **Fix a value in an action you already ran** | **`edit`** — one line, not the whole file |
| Crop / zoom a screenshot to inspect a detail | `bash` + PIL — save the crop, **you will be shown it** |
| Scan image pixels for an edge or a silhouette | `bash` + PIL — **never** `img.pixels[i]` in a loop inside Blender |
| Any loop over more than a few thousand items | `bash` |
| Keep a helper you have now written twice | `write` it into `Tool_scripts/Tools_code/` |

## Fixing a value you got wrong — `edit`

To change a radius from 2.0 to 1.4 in an action you already ran, use `edit`
rather than re-sending the whole file:

```
edit(path="mem/<run>/steps/step_001/03_seed_body.py",
     old_string="RADIUS = 2.0", new_string="RADIUS = 1.4")
```

Editing one of the current step's `NN_*.py` build actions **also re-runs it**:
the harness rewinds the scene through the preceding action, replays, runs your
edited version, and hands you the new screenshot. It is a full retry, and it
leaves the action files as a clean recipe rather than a record of the wandering
path. **Never leave a value in place that you believe is wrong** — fix it and
look at the result.

## Seeing things properly

Three tools hand you real pixels, and you should use them freely:

- **`write_and_run(show_screenshot=True)`** — every PNG the action freshly
  renders comes back, each labelled with its filename. Rendering a tight crop
  *and* a front view *and* a right view in one action is a good move: you get
  all of them (up to 4 per call).
- **`bash`** — any image the command writes into this step's directory is
  attached automatically, and `echo "SHOW_IMAGE: <path>"` attaches an image
  from anywhere in the project.
- **`read(path)`** on an image file — look at anything that already exists.

**A detail you cannot see is a detail you cannot judge.** A head that is 40 px
across in a full-frame render tells you almost nothing; crop to it and it tells
you everything. When a check is about how something *looks* — a silhouette
sitting inside an outline, a neck narrowing, a snout shape — crop in on that
part and look at the crop, rather than inferring it from a number or squinting
at the whole frame. Numbers are for checks about quantities.

**Never guess at a proportion you could measure.** `read`, `glob`, `grep`,
`edit` and `bash` are unlimited — use as many as the job needs. There is no
prize for finishing a step in few calls, and a step that ends with an unchecked
guess in it is not finished, however quickly it got there. If you are unsure
whether something is right, that uncertainty is the signal to go and look.

`silhouette_vs_reference` runs *inside* Blender, so it needs an action. Bundle
it onto the end of an action you were running anyway when that is natural, and
otherwise just spend a standalone action on it — checking is always worth an
action.

`bash` is a fresh process every call, always starting at the project root and
keeping no state between calls. Pass state through files, not
module globals. Write anything worth keeping to this step's `scripts/` folder
(see below) rather than to a temp file.

**Every measuring script you write goes into a file first.** Use `write` to put
it in your step's own `scripts/` folder — `mem/<run>/steps/step_NNN/scripts/`,
created for you alongside `screenshots/` and `overlay_json/` — and then `bash`
it by name:

```
write(path="mem/<run>/steps/step_003/scripts/crop_wrist.py", content=<source>)
bash(command="python mem/<run>/steps/step_003/scripts/crop_wrist.py")
```

**Do not pipe a script into python through a heredoc** (`python - <<'PY' … PY`)
or `python -c`. It runs, but it leaves nothing behind: the next time you need
the same crop — and you will, after every fix — you have to retype it from
memory, and nobody reading the run afterwards can see how you measured
anything. A saved script can be re-run after each change with one short call,
which is exactly what checking-then-fixing needs.

They must live in `scripts/`, not directly in the step dir, where every
`NN_*.py` is a build action and gets re-run on replay.

Name them for what they measure — `crop_head.py`, `scan_neck_width.py` — and
re-run them rather than writing a new one each time.

## Running actions

**Primary path — the `write_and_run` tool.** One call per action:
`mcp__blender__write_and_run(filename="MM_action.py", content=<source>, show_screenshot=<bool>)`
writes the file into the current step directory, runs it, waits for Blender to
finish, and returns `{ok, note, error, screenshot, overlay}` plus the image
inline when `show_screenshot=true`. No separate status check or Read needed.

Full replays (shell):
```bash
python Tool_scripts/win_run_steps.py --run <run_name> --upto N
```

Manual single-file send (shell — rarely needed now):
```bash
python Tool_scripts/run.py --file mem/<run>/steps/step_NNN/MM_action.py
```
`run.py` BLOCKS until Blender finishes: exit 0 = completed OK, exit 1 = script
error (traceback printed), exit 2 = hung/timeout.

## Screenshots

```
mem/<run>/steps/step_NNN/screenshots/action_MM.png          ← bare viewport
mem/<run>/steps/step_NNN/screenshots/action_MM_<suffix>.png ← overlay (perception)
```

For perception actions the `_suffix` file is the one that matters — the bare
`action_MM.png` is overwritten by `shot()`. `write_and_run` attaches the overlay
automatically when the action produced one.

Overlay suffixes: `_smap` (scale), `_exmap` (extrude), `_lcmap` (loopcut),
`_imap` (inset), `_grid` (face grid), `_fmap` (face centres), `_ggrid` (grab).

## Retrying — just rewrite the action and send it again

**If a value came out wrong, fix that action's value. Do NOT write a new action
to correct the scene forward.**

Calling `write_and_run` with a filename that ALREADY EXISTS is a retry. The
harness detects it and rewinds for you: it rebuilds the scene from empty
through the action immediately before this one, then runs your new version. The
result is exactly as if the earlier version had never run.

```
07_scale_ring.py  with 2.0   → too big
07_scale_ring.py  with 1.4   → same filename → rewound → scene is 1.4x, not 2.8x
```

The rewind takes about 4s for a whole object — it replays as one batch with
rendering off. **Retrying gives a correct scene; correcting forward gives a
scene that happens to look right, built out of one mistake and one
compensation.** The retry also leaves the action files as a clean recipe
instead of a record of the wandering path. Your reasoning comment at the top of
the file is where the history belongs ("2.0 was too deep, 1.4 matches the
reference").

Two things to know:

- If actions AFTER the one you rewrote already exist, they were built against
  the old version and are **not** re-run. The tool result names them; rewrite
  or delete them.
- Only rewrite an action you can express differently — the rewind re-runs the
  file, so the new content must be a complete replacement, not a patch onto the
  old result.

**Never create `MM_retry_action.py` alongside the original.** Every `NN_*.py`
in the step runs in numeric order, so a duplicate fires twice — and it defeats
the retry detection above, which keys on the filename.

Full manual rebuild (shell), when you want a known-clean scene:
```bash
python Tool_scripts/win_run_steps.py --run <run_name> --upto 4 --batch
```
`--batch` sends every action as one script with rendering skipped: ~12x faster
(80 actions in 4.3s vs 51s), identical geometry, but no screenshots. Drop
`--batch` when you want to watch it happen.

## Error handling

`write_and_run` (and `run.py`) report errors directly — no log hunting needed:

**Script error** — the tool result has `ok=false` and `error` = the full Python
traceback. Fix the action file content, call `write_and_run` again with the
SAME filename.

**Hang/timeout** — the tool reports a timeout after ~60s. The script got stuck
without raising (blocking bpy call, infinite loop, operator waiting for
context). Recovery:
1. Do NOT poll, sleep, or search for logs — the script will never finish.
2. Write a simpler replacement action that avoids the hanging call and run it.
3. If Blender itself seems frozen, tell the human — the Blender server needs to
   be restarted manually.

`mem/server_errors.log` still accumulates every traceback (history/debugging),
but you should never need to read it — the traceback comes back in the tool result.

## File layout

| What | Path |
|------|------|
| Server error log | `mem/server_errors.log` |
| Latest action status | `mem/<run>/last_step.json` |
| Action screenshot | `mem/<run>/steps/step_NNN/screenshots/action_MM.png` |
| Overlay screenshot | `mem/<run>/steps/step_NNN/screenshots/action_MM_<suffix>.png` |
| Overlay JSON | `mem/<run>/steps/step_NNN/overlay_json/action_MM_<kind>.json` |
| Landmarks | `mem/<run>/landmarks.json` |
| Run logs | `mem/<run>/Rollout/` |
