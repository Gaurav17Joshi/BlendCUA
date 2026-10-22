---
name: verifying-your-own-work
description: The eight ways to answer a question with a computation instead of a glance — cropping, pixel scans, bmesh reads, state dumps, minimal repros.
---

# Verifying your own work

The built-in pipeline (overlay → pick → apply) is how you *act*. This is the layer
above it: throwaway Python run via `Bash` or `run.py` whenever the pipeline does
not answer the specific question in front of you, or a stated assumption turns out
to be untested.

> **Reach for code that computes a definite answer whenever the question has one.**
> Save visual review for the genuinely holistic judgements that do not reduce to a
> number — is the framing good, does the palette work, does the motion read as
> natural.

Mixing these up costs time in both directions: trusting a "looks plausible" render
over a computed check, and second-guessing a correct render because a theory about
what was wrong had not been checked numerically yet.

## A — Crop and zoom before reading

Cheapest, most general, and the one to try first. `fit_objects_ortho_view` frames a
compromise across everything in shot, so a claw, an eye or a 40-pixel boundary is
past what can be judged by eye.

```python
from PIL import Image
img = Image.open("path/to/action_NN.png")
w, h = img.size
crop = img.crop((int(w*x0), int(h*y0), int(w*x1), int(h*y1)))   # normalized box
crop = crop.resize((crop.width * 2, crop.height * 2))
crop.save(".../scratchpad/detail.png")
```

Then `Read` the crop. Crop *before* upscaling — a full-image upscale just blurs.

## B — Pixel classification on a screenshot

"Does the mesh actually reach this point, or does it only look like it does?"
Load the **unannotated** render (plan-preview actions save a marker-free
`_planbase.png` for exactly this) and classify by a channel comparison that
separates subject from background in this scene's palette:

```python
r, g, b = im.getpixel((int(0.82 * w), int(0.565 * h)))
is_sky = b > r + 8        # cool background vs. warm membrane
```

Two things built on it: **boundary scans** (walk a column, find the last non-sky
pixel — this caught a "known" 3D landmark sitting 0.07 of frame *inside* the
membrane's real edge, because an exact coordinate means precise, not *on the
boundary*), and **feature tracing** (scan a strip, take the local brightness
minimum, repeat across x to trace a curve).

Classify by **ratios**, not absolute values, when the light varies across the
subject — the chilli plant's key varies about fourfold, so absolute thresholds
misclassify a whole side.

## C — Project invisible data onto something visual

For data a render cannot show — UVs, weights, vertex groups. Dump it, redraw it
with PIL on top of the *source image*, and read that. Full technique in
`checking-invisible-data.md`.

## D — Measure the mesh directly, no render at all

`bmesh` already holds the ground truth. For structural questions this is strictly
more precise than any screenshot proxy, and faster:

- **Planarity / twist**: split each quad into two triangles and compare their
  normals. A large angle means a warped face. This found the finger-twist bug —
  33–130° on the segment right off the seed face against under 11° everywhere else
  — which pinned the cause exactly: a coincident-duplicate seed face inherits its
  *parent's* normal.
- **Bend angle**: walk a tube's rings and measure the angle between consecutive
  segment directions.
- **Displacement**: world coords before and after, then max/mean/count. Every
  damage pass in the pillar build reports these, and a pass that reports nothing
  has failed whatever the render looks like.

## E — Dump state to text instead of screenshotting

For transforms, constraints and depsgraph state, where the render has nothing
visibly wrong to react to — or, worse, looks *identical* across a change, which is
itself the clue.

```python
lines = []
for f in (1, 60, 120, 180, 240):
    scene.frame_set(f)
    lines.append("frame %d: offset=%.4f pos=%s"
                 % (f, con.offset_factor, tuple(rig.matrix_world.translation)))
open(".../diag.txt", "w").write("\n".join(lines))
```

This found two bugs no render would have caught quickly: a Follow Path constraint
that was silently a no-op (keyframes animating, `matrix_world.translation` frozen
— constraints added across separate script executions on a long-running Blender
session do not always trigger a relations rebuild; fix with `obj.update_tag()` +
`view_layer.update()`), and a `matrix_parent_inverse` that baked in a stale pose
because the parent was mid-animation when the inverse was captured.

**Blender-side scripts must write to a file.** Blender's stdout goes to the
console it was launched from; `run.py` returns only status JSON. A diagnostic that
prints is one nobody can read.

## F — Minimal isolated reproduction, in the live session

"Is this a bug in my object, or in the tool?" When the constraint above looked
broken, the next move was not to keep tweaking the real rig — it was a brand-new
empty and a brand-new 2-point curve, created and constrained in one script. That
worked, which isolated the bug to the *existing* object rather than to Follow Path
constraints in general, and stopped the fix going somewhere completely wrong.

Change one variable at a time until the one variant that differs tells you what is
responsible.

## G — Tag geometry so a later script can find it

Indices are not stable across extrude/subdivide/bevel. Two ways to keep a
reference:

- `landmarks.py` — vertex-group backed, named, JSON-registered. Reach for it when
  you need several independently-named references that must survive many edits.
- A raw custom layer — `bm.faces.layers.int.new("finger_id")` — when you need a
  small, fixed, known-in-advance set of tags within one part's build sequence.

The wrist's five fingers used the second: duplicate the tip face in place
(zero-offset), tag each copy 1–5, and each later action looks up its own start
face by ID. Coincident duplicates mean no seam, which five separately-authored
cylinders could never give.

## H — Sweep an undocumented parameter

When the API does not say what a value means, three bands at three values on a
face the build is not using will tell you in one action. This is how the pillar's
texture scale, mapping mode and brush-radius-to-cut ratio were all settled.

---

## Which to reach for

| Question | Use |
|---|---|
| "Does this look roughly right?" | just `Read` the screenshot |
| "Is this specific small detail right?" | A — crop and zoom |
| "Does the geometry reach exactly this point?" | B — pixel scan |
| "Is this non-visual data correct?" | C — project it onto an image |
| "Is the mesh structurally sound?" | D — bmesh measurement |
| "Did this operator/constraint actually do anything?" | E — state dump to text |
| "Is this my object or the tool?" | F — minimal repro |
| "How do I find this geometry again later?" | G — tag it |
| "What does this parameter do?" | H — sweep it |

## Before handoff: prove the run replays

Iterating with partial replays and checkpoint reloads leaves a scene that the recorded
actions may no longer produce. Before handoff:

1. Run a **full ordered replay** of every action from an empty scene.
2. Load **every checkpoint** and verify it contains only its own step's objects.

The chocolate cup rebuild (task 16, run_002, 2026-09-16) did both: 15/15 actions OK,
checkpoints holding 2 → 10 → 21 → 28 → 34 objects
(`blends/16_chocolate_cup_decor_run_002/LESSONS.md` B13).
