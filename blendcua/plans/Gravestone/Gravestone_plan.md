<!-- ref-image: gravestone.png -->

# Gravestone Build Plan — BlendCuaLoop

Build a stylised low-poly gravestone matching `gravestone.png`: a wide cuboid
base, a two-segment stone **inset and extruded out of the base's own top face** so the
two are one continuous mesh, a peaked top made asymmetric on purpose, and eight
corners individually bevelled into chips. Then unwrap it and hand-paint everything
else into a single 2048 texture — a bottom-to-top gradient, a carved panel border with
an inner highlight, seam and worn-edge passes from four 3/4 views, branching cracks
front and back, and "RIP" lettering. No sculpting, no baking, no lighting: this plan
stops at a painted model in Material Preview.

**This plan is deliberately not prescriptive.** It says what to build,
which tool to use, and which numbers this build converged on — not per-action
parameters.

**Everything this plan refers to sits beside it in this folder** — the reference
image and any data files. Paths below are relative to this file, not to the
repository root.

## The one decision that shapes everything: the detail is PAINTED, not modelled

The geometry here is about ten minutes of box modelling and roughly two hundred faces.
Everything that makes it read as a weathered gravestone — the seam where stone meets
base, the worn light along every arris, the cracks, the carved panel, the lettering —
is strokes composited into one image texture. That is the opposite of the pillar
build, which sculpts the same kinds of damage into 700,000 vertices and bakes them
down. Both are "stone with damage" and the methods share nothing:

> **Sculpt it if the damage has to catch the light; paint it if it only has to be
> seen.** A painted crack is flat and always will be — but it costs one stroke, not a
> subdivision pass, and at this stylised, hand-drawn target that is the correct
> trade.

The consequence that drives step 2: **a stroke is picked in normalised screen
coordinates against one particular view**, exactly like the duck's traced points, and
is only meaningful there. `apply_paint_lines` projects through the *current* view and
skips back-facing triangles, so paint lands only on the side you picked it from. That
is what makes the seam work **four separate passes** — front-right, back-left,
back-right, front-left — rather than one clever pass.

## The one reference, and how to read it

`gravestone.png` is the whole reference and it shows only the **finished** object.
There are no intermediate pictures here, so what "done" looks like for each pass is
written into the steps below and those descriptions are the spec. Three of them are
worth pulling out of the reference before you start, because they are visible in it
and easy to walk past:

- the **carved panel** is not an outline. It is a dark line with a lighter one just
  inside it, and its corners are sharp while its edges are visibly not ruler-straight;
- the **seam** where stone meets base is dark *under* the stone and picks up a light
  rim *on* the base's top arris — two different strokes, not one line doing both jobs;
- the **cracks** branch rather than fork symmetrically, and they are grey hairlines
  rather than black, thin enough that the lettering stays legible where they cross it.

## The numbers that matter

| | value |
|---|---|
| base | 1.44 × 0.60 × 0.18, sitting **on** the ground (z = 0 to 0.18), not straddling it |
| footprint | the base's top face **inset 0.08** — the ring left behind is the visible ledge |
| stone | extrude 0.45, then extrude 0.55 and scale XY by **1.06** — a slight shoulder, not a straight taper |
| peak | ridge cut front-to-back at the X midpoint, lifted **0.16** |
| lean | left top edge −0.05, right top edge +0.05 — a **left-right** shift, so it is visible from the front |
| chips | 8 vertex bevels, 2 segments, offsets **0.09 – 0.235**, all different |
| texture | one 2048 image, mid-grey fill, wired to Base Color; UVs by Smart UV Project at **island margin 0.05** |
| gradient | 0.22 at the base → 0.62 at the peak, screen-projected along a picked line, `subdiv=8` |
| panel | 5 points, sharp corners, wobble amplitude 0.006 — plus the same 5 points nudged ~12% inward as a white `screen` highlight |
| seams | dark: width 0.008, softness 0.007, strength 0.8, colour 0.04, `multiply`. Worn edges: same width, colour 1.0, strength 0.5, `screen` |
| cracks | `waviness="jagged"`, width 0.004, strength ~0.7, colour **0.16 front** and 0.06 back |
| lettering | letter box 0.105 wide, advance 0.086, colour 0.10 — darker than the cracks so it stays legible over them |
| views | FRONT ortho for the panel, the front cracks and the lettering; the four seam passes from `Euler(65°, 0, θ)` in **perspective** at θ = 35, 125, 215, 305 — one per corner, 90° apart; the back cracks from `Euler(80°, 0, 180°)` |

## Review system

Same as always: after your geometry work, output your JSON result block
(`"pass": false`). The reviewer's feedback comes back as your next message — read it,
fix only what it names, then output JSON with `"pass": true` once satisfied.

## Toolkit

**`paint.py`** — the whole of step 2:

```python
from paint import (gradient_line_preview, gradient_line_plan_preview,
                   apply_screen_gradient, stroke_lines_preview, apply_paint_lines)
```

- `gradient_line_preview()` renders a numbered 0–1 grid over the current view; you read
  two points off it, `gradient_line_plan_preview(p0, p1)` draws the candidate line, and
  `apply_screen_gradient(obj, image, p0, p1, value0, value1, subdiv=...)` bakes it.
  **`subdiv` is not cosmetic** — each quad is subdivided into a grid before
  rasterising, and without it every face takes one flat value and the "gradient" comes
  out as a staircase.
- `apply_paint_lines(obj, image, strokes)` composites N strokes into the texture in
  list order, each over the last. A stroke is a dict: `points`, `smooth`, `waviness` /
  `amplitude` / `frequency` / `roughness` / `seed` for the wobble, then `width`,
  `softness`, `strength`, `color`, `blend`.
- **`blend` is the whole vocabulary of this build**: `multiply` darkens (carved seams,
  grime, cracks, lettering), `screen` lightens (worn arrises, polished edges). Every
  carved feature in the reference is a dark line with a light one beside it.
- `stroke_lines_preview(strokes)` draws exactly those paths over a render of the
  current view. Preview with the same dicts you are about to apply, never a
  hand-copied set.

A stroke, in full — this is the shape every one of step 2's twenty-odd strokes takes,
and the only things that really change between a seam, a crack and a letter are the
last five fields:

```python
{"points": [(0.38, 0.27), (0.35, 0.38), (0.37, 0.46), (0.32, 0.58)],
 "smooth": True,          # Catmull-Rom through the anchors; False = straight segments
 "waviness": "jagged",    # "straight" | "subtle" | "wavy" | "bumpy" | "jagged"
 "roughness": 1.0, "amplitude": 0.008, "seed": 5,
 "width": 0.004,          # normalized image space — a hairline
 "softness": 0.004,       # feather either side
 "strength": 0.7,         # peak opacity at the centre
 "color": 0.16,           # grey, or (r, g, b)
 "blend": "multiply",     # darken; "screen" to lighten
 "label": "crackPA_"}
```

**`perceive.edge_map(tl_norm, br_norm, max_edges=...)`** renders every visible mesh
edge, labelled, and writes the payload to the step's `overlay_json/`. This is how a
seam gets painted **on** the seam instead of near it: run the edge map as its own
read-only action first, then have the paint action read that JSON. `edge_at_label` is
the convenience path — but read *What goes wrong here* before relying on a label.

**`lib.mesh.enter_edit(name, select_all=)`** and **`GeoHistory`** — snapshot before a
bmesh op and ask for `new_verts_since`, which is how the ridge cut finds the two
vertices it just made instead of guessing at indices. **`lib.view`** supplies
`get_viewport` and `fit_objects_ortho_view`.

**Nothing here needs a run-local module**, and that is a fact about this build rather
than a rule: there is no table of traced geometry to share, only a stroke list per
action, each one belonging to the view it was picked in. If you do find yourself
copying the same coordinates into two actions, move them into a module in the step
folder — the test for `Tool_scripts/Tools_code/` is not "could someone else call
this?" but **"would it be the right shape for them if they did?"**

## Ad-hoc diagnostic Python

Less measurement than the other builds, because there is no photograph to measure
against — the reference is a painting. Two habits carry the weight instead:

- **Every paint action previews first, in the same view, from the same stroke dicts.**
  A stroke's `width`, `softness` and `blend` are invisible until they land, so the
  preview is checking the path and the *apply* is the only check on the brush. Budget
  a second pass for every paint action.
- **The edge map is ground truth, and it is data, not a picture.** Read the JSON,
  resolve the edges you need by geometric predicate, and print what you matched. An
  action that says "seam: z ≈ 0.18, y ≈ −0.22, x-span > 1.0, matched 1 edge" can be
  argued with; one that says "E_16" cannot.

## What goes wrong here

- **Edge-map labels are not stable across runs.** `E_16` is an index into a bmesh
  iteration order that is not guaranteed reproducible even on an unchanged mesh.
  Hardcoding a label verified in a one-off pass silently pointed at a different edge
  the next time action 7 was re-run. Load the full JSON and **re-resolve each edge by
  geometric criteria every run** — same ground truth, no cached name to drift.
- **The object's origin is not at world z = 0** (the base was lifted by half its
  height to stand on the ground), so `v.co.z` is not world Z. Anything comparing
  against a world threshold must use `matrix_world @ v.co`, or a filter like "the
  base's top ring" quietly matches nothing.
- **"Any unused edge touching this point" is not "the corner continuing upward".**
  Many edges meet at a vertex, and the naive chain-walk grabbed one running sideways
  across the shoulder ring to the opposite corner. Require the next edge to go *up*,
  to stay near the same X and Y, and prefer the **shortest** hop.
- **If a feature is not visible from this view, skip it — do not fabricate it.** No
  front-facing base-right edge exists in the front-right view; the action checks, finds
  none, and omits that stroke rather than inventing a plausible coordinate.
- **`smooth=False` for points that are already a real edge chain.** Catmull-Rom across
  segments of very different length and direction overshoots into a little curl at the
  join, and straight segments between real mesh points need no smoothing anyway.
- **Branching needs no new machinery.** `apply_paint_lines` composites arbitrarily many
  strokes, so a branch is just another stroke whose first anchor is copied from the
  **middle** of the trunk's own anchor list. The two then meet exactly.
- **A crack is not a wavy line.** `waviness="jagged"` sums three incommensurate sine
  frequencies, so it never repeats and mixes a broad wander with fine jitter. One sine
  reads as a wave, and a wave reads as decoration.
- **`bpy.data.materials.new()` and `images.new()` silently suffix `.001`** instead of
  replacing. Remove the old datablocks first or a re-run stacks orphans and the
  material you edit is not the one on the object.
- **Re-derive bmesh references after every operator.** The asymmetry pass reads the top
  corners, moves one pair, then re-sorts the vertices from a fresh bmesh for the second
  pair rather than trusting the BMVerts it was holding.
- **A front-back nudge on the peak is invisible from the front** — the front and back
  vertices project to the same screen position. Break the symmetry **left-right** or
  the whole action shows nothing.
- **Two colours that both look right can still collide.** The cracks were first painted
  at 0.06, and the "RIP" lettering at a similar value disappeared into them wherever
  the two crossed. Lightening the cracks to 0.16 fixed a legibility problem, not a
  colour one.
- **The edge map and the paint action must set the same view, to the degree.** Both are
  written out longhand — fit, then an explicit rotation, then `view_all`, then
  perspective — because a point read in one framing and painted in another lands
  somewhere plausible and wrong, and nothing about the result says so.
- **Straight-line wobble is the difference between carved and printed.** The panel's
  first pass used amplitude 0.003 at frequency 1.6 and came out looking ruled. The
  values that read as hand-cut are roughly twice that, and the inner highlight needs a
  **different seed** or it tracks the outer line exactly and the pair reads as one
  thick line.

---

## Scripting — read the reference with a script before you build

**Scripting** means writing a small Python program, saved as a `.py` file in the step's
`scripts/` folder (`mem/<run>/steps/step_NNN/scripts/`), that reads the reference image
or the Blender scene and **prints numbers or draws an overlay**: a material mask and its
row table, the axis and floor rows, a part's outline traced into a polygon, a thickness,
colour medians, the built outline drawn back on the reference with a residual. Shell-side
with PIL/numpy for pictures (`Tool_scripts/Tools_code/outline_trace.py` has the pieces),
Blender-side for the scene (`perceive.reference_outline`, bounds per row). It is not the
action that builds the part and it is not reasoning in prose about what the picture shows.

Every step that builds a shape does this **before its first build action** and saves what
it found (`scripts/<part>.json` and the trace drawn on the reference as a PNG); the build
action reads that file instead of retyping numbers; the check at the end of the step is the
same kind of script (outline on the reference, residual per row). A construction step
whose `scripts/` folder is empty has built its shape from memory, not from this reference,
and fails review on that alone. See `Skills/Scripting/measure-before-you-build.md`.

## Step 1 — the stone

Seven actions, all box modelling. Judge each from a 3/4 view; the final check is
easiest to read in **edit mode**, because the chipped-corner bevels are nearly
invisible under solid shading.

- **1.1 The base**: a cube flattened into a wide, low slab, sitting on the ground.
- **1.2 Inset, then extrude.** Inset the base's **own top face** and extrude the inner
  face up — that one decision is why base and stone end up as a single continuous
  mesh instead of two objects meeting at an interpenetration, and the flat ring left
  behind by the inset is the base's visible ledge.
- **1.3 A second extrude, scaled out slightly** in the same action. The reference's
  stone is a little wider at the top than at the join, so it reads as having a
  shoulder; a dead-straight prism does not.
- **1.4 The peak.** Cut a ridge across the top face and lift it. The two edges to
  subdivide are the ones whose endpoints **share a Y** — front and back — so
  subdividing them together with grid fill puts a new vertex at the X midpoint of
  each, which is exactly the ridge line. Assert you got two new vertices; a top face
  with unexpected topology should stop the action, not guess.
- **1.5 Make it lean.** The four original top corners now sit below the ridge. Drop the
  left pair and raise the right pair. **Left-right, not front-back** — see *What goes wrong here*.
  Identify them by sorting on Z then X, not by remembering an index.
- **1.6 Chip the corners.** Bevel a handful of individual vertices, each with its own
  offset, rather than running one uniform bevel pass — the point is irregularity.
  Corners are found by maximising a signed combination of world X, Y and Z; the base's
  **top** ring needs a Z-band restriction as well, because a plain max-Z search jumps
  straight to the stone's peak. Spread the damage across all four base corners rather
  than stacking two above two.
- **1.7 Look at it** in edit mode from a 3/4 perspective.

**Review:**

**Important**

- **The stone leans, seen from the front.** A gravestone standing perfectly upright
  reads as new. Say how much it leans and which way — quote the two corner heights.
- **Eight corners carry bevels of clearly different sizes**, spread across the base's
  top ring, the base's bottom ring and all four stone-top corners. Not two large ones
  and six untouched, and not eight of the same size — quote the range. Uniform bevels
  read as a chamfer the modeller applied, not as damage the weather did.
- **The top is a peak with a ridge running front to back**, not a flat or a dome.
- **The stone is slightly wider at the top than at the segment join** — a subtle
  outward expansion, not a straight prism. Quote both widths.

**Other**

- Base and stone are one object.
- The ledge is visible all the way round, including the back.
- Nothing floats below z = 0.
- All quads and n-gons, with no stray loose geometry left by the bevel passes.

---

## Step 2 — the painted texture

Nineteen actions, and the order matters: **broad to fine, and every pass composites
over the last.** Gradient, then panel, then seams and edges, then cracks, then
lettering. Painting the lettering before the cracks would put hairlines over the
letters instead of under them.

- **2.1 Unwrap and set up.** Smart UV Project with an island margin big enough that
  painting cannot bleed across a seam. One new material with one 2048 image filled mid
  grey, wired to Base Color, assigned to the object. Remove any same-named datablocks
  first (see *What goes wrong here*).
- **2.2 The gradient.** Preview the grid, read two points off it, preview the candidate
  line, then bake: dark at the base, light towards the peak. Two thirds of the
  reference's "weathered stone" read comes from this one pass, and it is picked off a
  view rather than hardcoded to a world axis so the direction is a decision you can
  see before committing.
- **2.3 The carved panel, front view.** A five-point pointed-arch border with **sharp**
  corners and enough wobble to read as hand-carved rather than ruled — then the same
  five points nudged inward as a thin white `screen` line just inside it. Dark on the
  outer edge, light on the inner edge **is** what carved relief looks like; either line
  alone reads as a drawn outline.
- **2.4 Seams and worn edges — four passes, one per corner.** Each is a pair of
  actions: **an edge map first, as its own read-only action**, then a paint action that
  reads that JSON. Per view: the base/body seam as a dark `multiply` stroke, and the
  stone's vertical corners and the base's rim as light `screen` strokes.
  - Walk each corner **upward through the real edge chain** rather than drawing a
    straight line from bottom to top: the stone's corners kink at the shoulder and at
    the peak, and a straight stroke crosses off the silhouette there.
  - The four views are 90° apart and cover the object between them, but they are not
    interchangeable — each shows a different subset of edges, and a stroke that was
    right in one is somewhere else in the next. Set the view longhand in **both** the
    edge-map action and the paint action, identically.
  - Check each pass for both halves of the effect: a dark seam *under* the stone and
    a light rim *on* the base's top arris, not one line doing both jobs.
- **2.5 Cracks, front and back.** Trunk plus branch, the branch starting from a point
  in the middle of the trunk's anchor list. Thin, low-opacity, `multiply` — hairline
  fractures and grime, not bold black lines. Two clusters on the front (one running
  down through the panel, one small Y-fork at a roof corner) and one on the back.
  Leave open space where the lettering goes: the crack layout has to be planned around
  a feature that does not exist yet, which is the one place in this step where an
  action has to think a step ahead.
- **2.6 "RIP", from the same stroke tool.** Each letter is one to three short strokes —
  a straight spine, a four-point bowl that Catmull-Rom rounds into an arc, a diagonal
  leg. Smoothing on for the bowls, off for the spines. A little jitter so it reads as
  hand-painted rather than as a vector font.
- **2.7 Final check** in Material Preview from a clean 3/4 perspective, with everything
  composited.

**Review:**

**Important**

- **The strokes have a weight hierarchy: panel heaviest, lettering lighter, cracks
  lightest.** Cracks must read as thin grey hairlines, not as black grooves. Crop in
  and compare a crack against the panel border in the same image — if they look like
  the same pen, the cracks are too heavy and the stone reads as drawn on rather than
  cracked.
- **Every pass reaches all four sides.** The seam runs the whole way round, and worn
  light runs up the stone's vertical corners and along the base's rim on **all four
  sides**. Orbit and check: each was painted from one view only, so a side that was
  never faced is simply blank and invisible from the authoring angle.
- **No stroke has bled onto a face that was pointing away from the view it was picked
  in.** Painting composites through the current view, so a stroke picked on the front
  can land on the back of a thin feature. Check the rear faces for front-face marks.
- **"RIP" sits on the panel and stays legible where a crack crosses it**, and reads as
  painted by hand rather than as a font.

**Other**

- The gradient runs dark at the base to light at the peak. To settle whether it steps
  per face, sample a vertical column of texels and check the brightness rises
  monotonically — a staircase in the numbers is banding. Judging this by eye off a
  render is not reliable; two people looking at the same texture will disagree.
- The panel is a pointed arch with a dark outer line and a light inner line, its
  corners sharp.
- Cracks branch rather than fork symmetrically, and appear on both front and back.
- One UV layer, one painted material, the image packed.
