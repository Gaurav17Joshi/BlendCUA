<!-- ref-image: Duck_image.jpeg -->

# Mallard Duck Build Plan — BlendCuaLoop

Build a low-poly standing mallard drake matching `Duck_image.jpeg`: one
12-sided tube run from a seed ring in the middle of the body forward through breast,
neck and head and backward to the tail, a flat paddle bill extruded off the head, two
raycast eyes, a folded wing plate on each flank, mirrored legs on webbed feet, and
eight flat colours. Flat shaded throughout, around 450 verts, no rig, no lighting —
this plan stops at a coloured model that can be laid beside the photograph.

**This plan is deliberately not prescriptive.** It says what to
build, which tool to use, and which numbers this build converged on — not per-action
parameters. Trace, preview, look, correct: finding the rest is the build.

**Everything this plan refers to sits beside it in this folder** — the reference
image and any data files. Paths below are relative to this file, not to the
repository root.

## The one decision that shapes everything: the render IS the coordinate system

Unlike the pillar (invented) or the chilli plant (measured), **this one is traced**,
and `handle.apply_chain` extrudes a face through *screen-space* points, unprojecting
each against the depth of the one before. So every point in this build is
`(x_norm, y_norm)` — a fraction across and down a render of the photograph, origin
top-left — and those points mean nothing except in one particular view.

That view is therefore pinned in action 1 and re-established at the top of **every
later action**:

```python
setup_axis_ortho_view(area, region, rv3d, axis='RIGHT')
rv3d.view_location = (0.0, 0.023, 0.033);  rv3d.view_distance = 0.42
```

RIGHT ortho: screen right is world **+Y**, screen up is **+Z**, depth is **X**. The
duck faces left in the photograph, so its head is at −Y and its tail at +Y, and the
whole body chain stays in the X = 0 plane — where a mirror-symmetric bird's spine
belongs anyway. An action that reads a traced point without first restoring this view
is reading it in the wrong coordinate system.

**Frame on the bird, not on the picture.** At the default framing the duck spans
about 700 px of a 1432 px render and every point carries the reading error of a
coarse image. Centred and zoomed to fill three quarters of the frame is the
difference between placing a neck ring to 3 mm and to 10 mm.

## One reference, and a style that is not in it

**`Duck_image.jpeg`** is the only image in this folder, and it answers exactly one
question: **what shape is a duck**. It is a side-on photograph on white, which is why
a silhouette can be thresholded out of it in one line and compared against the model
in world metres. Every proportion, every radius and every traced point comes from it.

It does **not** answer what the model should look like when finished, because it is a
photograph and the target is not. The style target is stated here instead, and it is
short: **12-sided rings, flat shading everywhere, no Subsurf, eight flat colours, every
facet visible.** Around 450 verts in the scene. A surface is one value across a whole
region — where the photograph has a gradient, the model has a boundary.

So when the photograph and this paragraph disagree, they are answering different
questions: the photograph wins on shape, this paragraph wins on polygon count, shading
and how many colours there are.

## The numbers that matter

**Scale.** The reference is loaded at `IMAGE_WIDTH_M = 0.60`, so 0.60 m of world spans
the photograph's width. **The result is not life size and is not meant to be.** The
bird occupies 74% of the photograph's width, so at 0.60 m it comes out about **44 cm**
bill to tail against a real drake's ~58 cm — roughly three-quarters scale. That is
fine: every number in this table lives in the same 0.60 m frame, so the proportions
are right and the millimetres below are self-consistent. Do not "correct" the scale to
life size unless you also rescale the entire table, and do not quote the model's
dimensions as a mallard's.

At the pinned framing, **2353 px per metre** — a 0.068 m circle drew as a 160 px
radius. Every millimetre quoted below depends on that one line.

| | value |
|---|---|
| seed ring | at `(0.489, 0.641)`, **r 88 mm**, 12 verts, normal along −Y towards the head |
| forward chain | 10 stations — body, **shoulder fillet**, upper breast, neck base, three neck rings, three head rings — radii 88 → 84, 74, 60, 44, 34, 30, 32, 42, 46, 30 mm |
| backward chain | 6 stations, radii 88 → 88, 79, 61, 36, 17, 8 mm — full depth a long way back, then a collapse into the tail |
| neck | the thinnest ring on the bird at **30 mm**, roughly a third of the body, leaning **back** over the breast as it rises (centre x drifts 0.372 → 0.383) |
| bill | 4 stations from a 34 mm root down to 7 mm, then flattened to **0.55 in Z** and widened to **1.15 in X** |
| eye | `(0.312, 0.288)`, r 7.5 mm, placed by raycast — above the *back of the bill*, not mid-head |
| wing | a 46 × 216 × 98 mm plate, tilted 9° nose-down, tapered to a point at the rear, standing 68 mm off the mid-plane |
| legs | ±26 mm either side of centre, r 11 → 8 mm, chain stopping at the ankle; the foot is a 6 mm-thick **outline** of three webbed toes plus a hind toe |
| colour | 8 flat materials, assigned by world position; ~240 body faces, ~450 verts in the scene |

## Review system

Same as always: after your geometry work, output your JSON result block
(`"pass": false`). The reviewer's feedback comes back as your next message — read
it, fix only what it names, then output JSON with `"pass": true` once satisfied.

## Toolkit

**`handle.py`** — the whole body and its limbs come out of one family of calls:

```python
from handle import (chain_preview, chain_plan_preview, chain_profile_preview,
                    apply_chain, align_seed_face, face_radius_world)
```

- `chain_preview(label=...)` draws the selected face's centre on a 0–1 grid — how you
  read a starting point before inventing the rest by eye.
- **`chain_plan_preview(points, scales=...)` and `chain_profile_preview(points,
  scales=...)` are both required, because they answer different questions.** The plan
  draws a *circle* at every station and catches a neck that is not actually thin; the
  profile draws the same radii as bars with rails joining their ends, and catches a
  neck that is the right thickness everywhere and still meets the breast in a step.
  A chain can pass one and fail the other.
- `apply_chain(points, scales=...)` takes **ratios between consecutive rings**, not
  radii. Keep the absolute millimetres as the single source of truth and convert in
  one helper — stating the same shape twice, once as sizes and once as ratios, is how
  a preview and an apply drift apart.
- `face_mode="average"` mitres each joint between its incoming and outgoing
  directions, which is what keeps the neck a bend rather than a stack of sheared
  cylinders — and is also why a hard turn needs its own fillet station (see *What goes wrong here*).
- `align_seed_face(points)` pre-rotates the selected face so its normal already points
  at `points[0]`. Call it **once, immediately before `apply_chain`, and only on a fresh
  seed face with no extruded geometry attached to it yet** — so: on the seed ring
  before the forward chain, and on the bill's and the legs' starting faces. Never on a
  face that is already the tip of a chain, where rotating in place warps the rings
  behind it.
- `face_radius_world(face, mw)` returns a BMFace's mean centroid-to-vertex distance in
  **world** units. This is how you check a ring came out the radius you asked for, and
  the `mw` argument is the point — see the `matrix_world` lesson below.

**`perceive.outline_preview(obj_names, label=...)`** traces the built silhouette in red
over the reference. `obj_names` is a **name string or a list of names**, not an object
— pass `"DuckBody"`, or the list once there is more than one object, so the wing and
legs are in the outline too. This is the check that matters: a plan can be right in
every number and still make the wrong shape, because the outline is the radii, the
path, the mitring and the 12-sided cross-section all at once. It hides and restores the
named objects for you, so the base render underneath is the bare photograph — do not
add your own hide/unhide around it.

**`reference.load_reference(path, axis=..., display_size=...)`** puts the photograph in
the scene at a known world width, and `lib.view.unproject_norm(x, y, region, rv3d)`
turns a traced point into a world position. Never `region_2d_to_location_3d` with
pixels read off a screenshot — the PNG and the live region are different sizes with
opposite Y.

**What lives in the run, not the toolkit** — `steps/step_001/duck_body.py` (the seed,
the two chains, the radii, and the face-picking helpers) and
`steps/step_002/duck_parts.py` (bill, eye, wing, legs, and the `view()` that
re-establishes the traced frame). These are tables of traced numbers for one bird; the
test for `Tool_scripts/Tools_code/` is not "could someone else call this?" but **"would
it be the right shape for them if they did?"**

## Ad-hoc diagnostic Python

The eye is good enough to place a bill and bad enough to shift a whole taper, and the
only thing that tells the two apart is a measurement. Two scripts do the work, and
they are only comparable because **both report world metres**:

| script | runs | answers |
|---|---|---|
| `measure_silhouette.py` | system python | what the *photograph* measures — threshold the white background away, take each column's longest run, convert to metres |
| `dump_rings.py` | inside Blender | what the *model* measures — cluster vertices along the body axis to recover each ring's position and radius |
| `check_reference_aspect.py` | inside Blender | is the reference plate drawn undistorted (project its own corners; do not measure it on screen) |

Save each under the step's `scripts/` folder with the images and JSON it produced.
And **measure the right thing, not the easy thing** — both false alarms in this build
came from measuring the extent of what was visible instead of the thing in question.

## What goes wrong here

- **Trace a centreline BETWEEN the two outlines, not along the visible one.** The eye
  follows the edge it can see, and the neck's far edge is hidden against the breast —
  so every neck ring came out hanging over the chest. Corrected, the neck's centre
  runs *back* as it rises, which is the posture; a vertical neck reads as a goose.
- **Preview the rings, not the path.** The very first ring preview showed three errors
  at once — body 68 mm against a silhouette measuring 79, the neck on its front edge,
  head stations sitting on the crown — none of them visible from a line of dots.
- **The eye is consistent-but-wrong on the biggest, smoothest form.** Measured against
  the photograph, the neck and head were within a few millimetres but the body's taper
  started too early everywhere: thin where the bird is still full, fat where it has
  already closed into the tail. That is *one* error across five stations, and only
  laying model against photo in the same units shows it.
- **Measure the right thing.** A body scan reported 104 mm against a model built at 79
  — because **the legs are attached**, so the scan measured back-to-*foot*. Compare
  behind the legs. And a reference plate measured on screen gave aspect 1.71 against
  the file's 1.33, because the plate is **cropped by the frame** at that zoom.
- **A hard turn needs a fillet station of its own.** `apply_chain` mitres a joint
  between its two edges, so a direction change made at a single station tips that ring
  hard — hard enough here that the neck-base ring came out *behind* the breast ring and
  the silhouette doubled back on itself. Split the turn over two smaller ones.
  - **This is the weakest point of this plan, and one fillet station is not always
    enough.** The shoulder is where this build most often ends up with a visible notch
    or angular wedge. Judge it explicitly rather than assuming the fillet handled it: **check the turn on the profile preview before applying**, and measure the
    angle between the incoming and outgoing segments at the shoulder. If it exceeds
    about **35°** at any single station, split it again — a third station costs 12
    verts and is always cheaper than discovering the notch in the outline afterwards.
- **Anything positioned by a coordinate rather than by attachment must be re-read when
  the thing it sits on moves.** Fixing the head's placement left the white collar
  cutting across the jaw and the eye's raycast landing on the crown; both were stated
  in the old geometry's terms.
- **Use `matrix_world` for anything that compares positions.** The seed circle is
  created with a 90° object rotation, so the mesh's local axes are not the scene's —
  asking for the face with the largest local Y picked a side quad off the flank. Three
  separate things in this build broke for that one reason.
- **Three bmesh traps, all silent.** `face.select = True` does not survive the
  selection flush (use `BMFace.select_set`); in edit mode `obj.data` still holds the
  pre-edit mesh, so counts must come off the BMesh; and a BMFace is only valid while
  its BMesh is alive, so measure it inside that scope and return plain floats.
- **`extrude_region_move` keeps the original face**, so the seed cap survives the
  forward chain and the back of the mesh has zero boundary edges. The first version
  hunted for an open loop to fill, got `CANCELLED`, and handed `None` to the next line.
- **A mirror about an object's own origin puts the copy back on top of the original.**
  Put the origin on the mid-plane and offset the geometry in local X.
- **Assign colour by world position, never by face index.** Index order is an accident
  of the order the chains extruded in, and every attempt here that trusted it picked
  the wrong faces.

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

## Step 1 — the body, from one seed ring

- **1.1 Reference first, then pin the view.** Clear the scene, load the photograph at
  its real-world width, set RIGHT ortho and frame on the *bird*. Write the framing
  down: every number after this is meaningless without it.
- **1.2 The seed circle**, on the body's centre — halfway between the back line and
  the belly at that station, not on the back. 12 vertices: low-poly is the brief, and
  12 is where a ring still reads as round in silhouette while every facet stays
  visible. It is born lying in the XY plane facing +Z, so **stand it up across the
  body** (90° about X) or the first extrude travels sideways out of the duck.
- **1.3 Forward chain: body → breast → neck → head.** Preview it **both ways** (plan
  and profile), fix what the circles show, then apply the identical points and scales.
  Three neck rings, not one — a single segment between shoulder and head is a cone.
  Include a **shoulder fillet** station where the path turns from forward-and-up into
  straight-up.
- **1.4 Backward chain: body → flank → rump → tail**, extruded from the seed cap,
  which the forward extrude left in place. Shorter and simpler: a duck carries its
  depth a long way back and then collapses over the last two rings, so the tail is a
  spike off a full body, not a long taper.
- **1.5 Then measure, then look.** Compare model rings against the photograph's
  cross-sections in world metres at columns **behind the legs**; correct; and finish
  with the outline traced in red over the photograph with the model hidden.

**Review:**

**Important**

- **There is no notch, step or doubling-back where the neck meets the shoulder**, and
  no self-crossing loop under the jaw. This is the defect this build is most prone to:
  the shoulder turn tips one ring hard enough to put it behind the ring before it.
  Crop to the shoulder and judge it on its own — at full frame it is invisible.
- **Say what the measured ring radii came out as against the photograph's, in
  millimetres.** Measure at columns **behind the legs**: the legs are attached, so a
  column scan through them measures back-to-foot, not body thickness, and reports the
  body several centimetres too deep.
- **The red outline follows the photograph's bird** — the belly does not sit inside it,
  and the tail neither overshoots nor points up where the bird's points down.
- **The neck leans back over the breast** and is roughly a third of the body's
  thickness at its thinnest. A vertical neck reads as a goose.

**Other**

- One object, 12-sided rings throughout.
- Flat shaded, no Subsurf.
- The mesh is closed — zero boundary edges, zero non-manifold edges.

---

## Step 2 — bill, eyes, wings, legs

Four parts, attached three different ways, and **which way each uses is a decision,
not a detail**: the bill is extruded off the head's own front face so it shares the
mesh and the shading; the eyes, wings and legs are separate objects because each wants
its own material and two of them want a Mirror modifier.

- **2.1 Bill.** A chain off the head's front face that pulls in hard at the root, then
  barely tapers along its length and drops to a point only at the tip. Then **flatten
  it**: a round bill reads as a beak — squashed in Z and widened in X it reads as a
  duck's. `apply_chain`'s scales are uniform, so this is a separate per-axis scale of
  the selected verts.
- **2.2 Eyes, placed by raycast.** The traced point says where the eye is *seen from
  the side* and nothing about how far out the head's surface is there — and the head
  is a 12-sided tube whose radius changes ring to ring. Fire a ray in along X and take
  the hit. On the photograph the eye sits directly above the back of the bill, not in
  the middle of the head.
- **2.3 Wings — its own solid, not the body's faces.** The obvious build is "a wing is
  a raised panel": inset a band of flank faces and lift it. It tears, twice over. A box
  test does not select a contiguous patch, so `inset` builds several separate panels
  with hard borders; and extruding along the normals of faces that curve around the
  flank pushes neighbours *into* each other — on a 12-sided tube 4 mm is enough for the
  corners to cross. Build a flattened solid lying against the flank instead: it reads
  the same from outside and cannot damage the body's topology.
  - The shape to aim for is a long flat **plate** starting high at the shoulder,
    running most of the length of the body and ending in a **point** past the rump —
    not a lens in the middle of the flank. The photograph shows where the folded wing
    sits and where its trailing point ends; take those two positions off it. Taper each
    vertex in proportion to how far back it sits; a single scale on the back half gives
    a blunt teardrop instead of a point.
  - How far out it stands is what makes the intersection with the body a closed loop,
    which is what a folded wing's outline *is*. Too far in and it vanishes; too far out
    with too short a shape and only the rear emerges, as an angular notch.
- **2.4 Legs and webbed feet.** Build one at +X and mirror — tracing the second by eye
  would put it somewhere almost the same, which is worse than either matching or
  clearly differing. Start the chain **inside the belly**: a leg starting exactly at
  the skin leaves a visible ring where two closed surfaces meet.
  - **The foot is an outline, not an extrude.** As a link in the chain it arrives as a
    near-vertical ring and flattening it in Z squashes its *length*; extruded forward
    and flattened it is the right size with no shape at all, because an 8-gon pushed
    forward can only ever be an 8-gon pushed forward. Draw it from above: three forward
    toes with the web pulled back between them, plus a small hind toe. **The notches
    are the whole point** — they are what says toes-with-skin rather than paddle.
- **2.5 Look from somewhere other than the reference view.** Dead side-on is the one
  angle where a wing lying flat on the flank and a foot pointing forward are both
  nearly invisible. Front, top and both quarters, plus a close-up of one foot.

**Review:**

**Important**

- **Look from somewhere other than the reference view.** Dead side-on is the one angle
  where a wing lying flat on the flank and a foot pointing forward are both nearly
  invisible. Front, top and both quarters, plus a close-up of one foot — a step judged
  only from the traced view has not been judged.
- **No torn faces or crossed corners anywhere on the flank.** The wing sits against the
  body as its own solid; if it was built by insetting and lifting body faces instead,
  the corners cross and the flank tears. Crop to the flank and check.
- **Each foot has three toes with notches between them**, visible from above and from
  the front. The notches are the whole point — without them it is a paddle, not a
  webbed foot.
- **The bill is visibly wider than it is deep and blunt at the tip**, not a cone. A
  round bill reads as a beak.

**Other**

- The eyes sit on the head's surface — not floating, not sunk — and above the back of
  the bill.
- Each wing reads as one closed teardrop with an unbroken body outline above it, and a
  rear point that does not overhang the tail.
- Two legs, symmetric, emerging from the belly with no visible join ring.

---

## Step 3 — colour

- **3.1 Assign by where each face is**, in the same traced coordinates as the geometry,
  converted to world once. Two different splits, because the bird is two shapes: the
  **head and neck split by height** (green cap, white collar, brown breast are
  horizontal bands stacked up a vertical neck), and the **body splits by depth** (back
  and flanks against a pale belly), applied only behind the shoulder.
- **3.2 The collar is the hard one.** It is a thin band, so it needs two bounds rather
  than one — and it must sit **below the jaw**. The head hangs directly over the neck,
  so at collar height the jaw is at the same height *and* nearly the same depth, and no
  combination of tests separates them: bands tried higher up painted six jaw faces
  white and lost the collar. Below the jaw there is only neck and the question does not
  arise; a mallard's green runs down to the collar anyway.
- **3.3 Sample the photograph, then flatten what you sampled.** Eight regions, eight
  materials: green head, white collar, brown breast, grey-brown back, pale grey belly,
  darker wing, yellow bill, orange legs and feet. Take each one's hue from the middle
  of that region in the photograph — a `read` of the image and a crop is enough — but
  take **one** value per region, not the range. The photograph will offer you a
  gradient across every one of them; picking the mid-tone and discarding the rest is
  the whole job, because a flat-shaded model has no gradient to put it in.
  - Then check them **under the light you will show them in**. Colours that are
    clearly distinct as numbers come out flatter on screen, and the two pairs that
    collapse are body-against-belly and body-against-wing. Push those pairs apart
    beyond what the photograph justifies. A wing you cannot find is not a wing.
- **3.4 Final views**, including a hero angle, and a face count per material — a
  material with two faces is a boundary in the wrong place.

**Review:**

**Important**

- **Each region is legible on its own under the light you will show it in**, not just
  as numbers. The two pairs that collapse are body-against-belly and
  body-against-wing — check those two specifically. A wing you cannot find is not a
  wing, however correct its material assignment.
- **The white collar is a clean band on the neck**, with none of it on the jaw or
  behind the bill, and the green runs down to meet it. The collar is the hard one: at
  collar height the jaw sits at nearly the same height and depth, so a band placed too
  high paints jaw faces white and loses the collar entirely.
- **Face counts per material are reported and none is implausibly small.** A material
  with two faces is a boundary in the wrong place, and it is invisible in a render.

**Other**

- All eight colours are present.
- The bill is yellow, the legs and feet orange, with no colour bleeding onto the body.
- Colours assigned by world position, not by face index.
