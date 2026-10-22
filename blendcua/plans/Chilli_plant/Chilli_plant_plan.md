<!-- ref-image: Chilli_plant.png -->

# Chilli Plant Build Plan — BlendCuaLoop

Build a stylised potted chilli plant matching `Chilli_plant.png`: a chamfered
white plinth, a terracotta bowl pot lathed from the reference's own silhouette, one
stem carrying twelve branches, about sixty folded lanceolate leaves, ten hanging
chillies with faces (seven ripe red, two pale, one green and unhappy about it), a
flat palette, and finally a warm key light **cut by a flag** so the picture has the
same hard light/dark division the reference does. No rig, no animation — this plan
stops at a lit still that can be laid beside the reference.

**This plan is deliberately not prescriptive.** It says what to
build, which tool to use, and which numbers were already measured off the reference
so you do not have to re-derive them. It does not give you per-action parameters.
Preview, look, measure, iterate — finding the rest of the numbers is the build.

**Everything this plan refers to sits beside it in this folder** — the reference
image and any data files. Paths below are relative to this file, not to the
repository root.

## The one decision that shapes everything: this reference is a RENDER

`Chilli_plant.png` is 660 × 1110 and it is a **perspective render**, not a
flat-on photograph. That changes the method completely from the bat and duck builds:

- **Do not trace in normalised screen coordinates.** `handle.apply_chain` extrudes a
  face through screen points — right for tracing a silhouette, wrong here. A point on
  a perspective render corresponds to no single plane in the scene, so a traced path
  is correct at one depth and skewed everywhere else.
- **A plant is not a silhouette anyway.** It is a dozen branches leaving one stem at
  a dozen azimuths, and the whole shape depends on some coming towards the camera and
  some going away. Traced in screen space every branch lands in one plane and you get
  a pressed flower.

So the reference is used the other way round: **measured**, in fractions of its own
width and height, converted to metres once, and everything built in world space.

## The measurements that matter

**Scale.** The pot's widest silhouette is 0.654 image-widths; a bowl planter of that
shape is about 26 cm across, which fixes everything:

```
0.654 image-widths = 0.260 m   ->   1 image-width  = 0.3976 m
                                    1 image-height = 0.6687 m
```

Two different factors, because the image is not square, and using the wrong one is a
68% error. Expose them as two *named* functions, one per axis, so the mistake cannot
be made silently.

**Camera.** The pot's rim ellipse is 0.089 as tall as it is wide, and a circle seen
from elevation *e* projects at ratio sin(*e*) — so the reference's camera sits **5.1°
above the rim**. Its frame spans z = −0.166 to +0.482 with the plinth's top face at
z = 0. The plinth's near-parallel vertical edges and that very shallow ellipse mean a
long lens far back, not a wide one close: **85 mm at 1.60 m**.

| | measured |
|---|---|
| pot | R 0.130, H 0.157, belly at 64% of its height, rim wall 0.235 R. **Check the ratio, not just the two numbers**: 0.260 wide against 0.157 tall is **1.66 : 1**, and that ratio is what makes it a bowl. Anything near 2 : 1 is a dish. |
| plinth | 0.238 m across the face, yawed ~10°, **centred under the pot** |
| plant | 371 mm tall, 376 mm wide, stem base 11 mm left of the pot's axis |
| stem | 4.2 mm radius at the soil, tapering to a point |
| leaves | 60–145 mm long, widest at 38% of their length |
| fruit | 10 — seven red, two pale, one green — 46–70 mm long |
| key light | azimuth 318°, elevation 13°, warm, small, **flagged** |
| the cut | crosses the plinth at x = 0.4106 of the frame, the pot at 0.4621 |

## Review system

Same as always: after your geometry work, output your JSON result block
(`"pass": false`). The reviewer's feedback comes back as your next message — read it,
fix only what it names, then output JSON with `"pass": true` once satisfied.

## Toolkit — specialized tools this build needs

**`meshgen.py`** (`Tool_scripts/Tools_code/`) — general procedural primitives, built
from 3D control points rather than screen picks:

```python
import meshgen as mg
mg.catmull3(anchors, n)               # 3D Catmull-Rom (lib.pathgen's is 2D only)
mg.tube(points, radii, sides=...)     # sweep a ring along a 3D polyline
mg.spin_profile(profile, sides=...)   # lathe from (radius, z) pairs
mg.bevel_box(size, bevel, ...)        # chamfered cube
mg.smooth_by_angle(obj, degrees)      # smooth shading, sharp edges kept sharp
mg.place(obj, loc, azimuth, pitch, roll);  mg.join(objects, name)
mg.point_on(points, t)                # point + direction along a polyline, BY ARC
                                      #   LENGTH
```

- `tube` uses **parallel-transport framing** — "up × tangent" flips when a tangent
  passes vertical, which a drooping branch does. A radius of exactly `0` collapses that
  end to a point, so a stem tapers to a tip and not to a 1 mm disc catching the key.
- `spin_profile` does not close the section for you. For a vessel, give one open path
  from the outer base, up the outside, **over the rim at full wall thickness** and back
  down the inside — the reference plainly shows the rim's thickness, and a
  zero-thickness lathe shows a paper edge exactly where the light is brightest.
- `point_on` measures by arc length. Indexing into the sample array instead bunches
  attachments wherever the curve is tightly sampled — on a Catmull-Rom, exactly where
  it bends, so every leaf crowds into the corners.

**The leaf and the fruit are NOT in the toolkit**, and should not end up there. They
live in the run, next to the actions that use them:

```
steps/step_003/leaf_shape.py     LEAF_OUTLINE + leaf(...)
steps/step_004/chilli_shape.py   CHILLI_PROFILE + chilli(...) + the face
```

Both are built out of `meshgen`'s primitives, but a lanceolate blade folded down its
midrib, or a fruit with a calyx and a smile, is not a general anything — it is this
plant, tuned against this reference. The test for what belongs in
`Tool_scripts/Tools_code/` is not "could someone else call this?" but **"would it be
the right shape for them if they did?"**. Put a subject in the shared toolkit and the
next build inherits a "leaf" that only ever suited a chilli.

**`lighting.py`** (`Tool_scripts/Tools_code/`) — camera, lights, flags, and a real
render. Everything else in the toolkit renders the *viewport* via
`bpy.ops.render.opengl`, which ignores the scene's lights and uses a fixed studio
matcap: right for judging a shape, useless for judging a light.

```python
import lighting as lt
lt.camera(target, distance, azimuth, elevation, lens=..., shift=...)
lt.key_light(target, distance, azimuth, elevation, energy, colour, size)
lt.world_colour(rgb, strength);  lt.backdrop(rgb, ..., distance, z, roughness)
lt.point_at_screen(camera, u, v)      # ray-cast: world point under a screen pick
lt.cutter_plane(light, boundary, shadow_point, frac, width, height, tilt)
lt.dust(count, centre, extent, ...);  lt.render(path, w, h, samples, engine, ...)
```

Azimuth is degrees about Z with 0 at +X and **270 towards the camera** — the same
convention the branch skeleton uses, so a light is described in the same terms as the
branch it is lighting.

## Ad-hoc diagnostic Python

This build is measured far more than it is eyeballed, and the scripts are part of the
build. Save every one under the step's `scripts/` folder **with the images it
produced** — the same crop gets wanted again after every fix.

| Question | What to do |
|---|---|
| "What does this part look like?" | Crop and enlarge with PIL. Cheapest — always first. |
| "Where exactly is that in the frame?" | Draw a labelled 0–1 grid over the reference and read the value between two ruled lines, instead of judging "about a third across" on an unmarked picture. |
| "What is the pot's profile?" | A pot is a solid of revolution and **the silhouette of a solid of revolution IS its profile** — the half-width at each height is the radius of the ring there. Threshold against a *modelled backdrop* (interpolate between each row's two margins), not against brightness: the key is hard enough that the pot's shaded half is darker than the wall behind it. |
| "How many chillies, where, how big?" | Classify by colour **ratios**, not absolute values — the key varies about fourfold across the plant — then connected components. |
| "Is the model the right size / does it cover the frame right?" | Compare **in world metres**, and project every vertex through the camera with `world_to_camera_view`. Never by comparing two pictures: that is exact, needs no render, and cannot be thrown by framing or resolution. |
| "Where does the light/dark cut fall?" | Find where brightness crosses **half way between each row's own dark and light plateaus** — not the largest derivative (see *What goes wrong here*). |

Blender-side scripts must write their report to a **file**: Blender's stdout goes to
the console it was launched from and `run.py` only returns the status JSON, so a
diagnostic that prints is one nobody can read. `run.py` will time out on these; that
is expected.

## What goes wrong here

- **A right bounding box can hide a wrong plant** — it cannot see leaf *area*. The
  reference's branches are short and its leaves are long (the biggest is 126 mm,
  nearly as long as the branch carrying it). Measure individual leaves too.
- **Leaves bend; a bent tip is not a bent leaf.** Curve the midrib, then lay the blade
  *across* it — a fixed ±Y offset narrows the blade by the cosine of every turn. Keep
  the sweep gentle, or the point turns across the blade and reads as a hook.
- **Leaf shape, twice wrong:** aspect measured off the picture is narrower than the
  leaf is (most are tilted, so foreshortened), and a blade peaking at mid-length is an
  oval however many stations it has.
- **Spread the branch azimuths round the whole circle.** The first twelve sat within
  25° of the left–right axis: fine from the reference's angle, a bald-backed fan from
  every other. Depth is a choice here — make it deliberately, check it from TOP ortho.
- **A fruit hanging below the rim must clear the pot SIDEWAYS.** Two ended up inside
  it. The constraint is radius, not height, and no preview caught it because the thing
  they hit was a different object.
- **Anything that rebuilds must clear its target name.** Deleting every `Leaf_*` left
  the previous run's joined `Leaves` alive; the new join became `Leaves.001`, every
  lookup returned the old mesh, and changing every leaf length appeared to do nothing.
- **Two ways the scene lies to a script.** `matrix_world` is still the identity inside
  the script that created the object (use `rotation_euler`); and a ray-cast hits what
  the camera cannot see — an aim-ray struck *last run's* flag and returned mid-air.
- **Vertical bands on a lathe are a shading problem** — more sides only makes them
  narrower. `smooth_by_angle` fixes it. And facet counts set by counting facets in the
  tightest place run low: the pot got 16 sides from its edge-on rim. Count the widest.
- **A landmark that does not move is worse than none, because it looks like a
  measurement.** A step detector found the plinth's own corner and reported it through
  four lighting setups, including one with the subject entirely in shadow. Check what
  a mask contains, too — the pot's box held the chilli hanging off its left edge.
- **Hues can be measured, values cannot.** Sample lit *and* shadowed, divide out the
  ambient tint, convert to linear; the reference's lit pot samples (254, 255, 105),
  which is no pot's colour. Values are then chosen, and the render is the check.

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

## Step 1 — plinth and pot

- **1.1 Datum first.** Clear the scene and build the plinth, because its top face is
  z = 0 and every height afterwards is measured up from it. Two stacked chamfered
  blocks — the reference shows a seam and a second chamfer about four fifths of the
  way down the visible part. Yaw it around 10°: enough to show a narrow left face,
  not so much that a corner points at the camera.
- **1.2 Do NOT load the reference into the scene.** Unlike the bat and duck builds
  there is nothing to trace on; it is measured externally and compared against at the
  end.
- **1.3 Measure the pot**, then lathe it as a vessel section. Use only the **right**
  edge — the key is hard and from the right, the pot's left falls into shadow deep
  enough to lose a few rows, and a solid of revolution needs one side.
- **1.4 Subdivide the profile before lathing.** The measured rings alone leave
  flat-shaded bands about 12 mm tall that read as stripes. Then `smooth_by_angle`.
- **1.5 Soil** as a separate shallow disc just below the rim, so it can take its own
  colour — not the pot's inner floor raised up.
- **1.6 Look at it** from front, quarter, above and side before anything is planted.

**Review:**

**Important**

- **Measure the pot against the REFERENCE, not against this plan.** Every other check
  here is self-referential — a fraction of the pot's own height, a fraction of its own
  radius — so a wrong number in the table above passes all of them cleanly. Threshold
  the pot out of the reference photograph, take its width and height in pixels, convert
  with the two named scale functions, and state both against the built pot's. **The
  width-to-height ratio is the one that matters: about 1.66 : 1.** A pot near 2 : 1 is
  a shallow dish however good its profile.
- **The pot's widest point sits above its mid-height, not at it.** Say where the
  maximum falls as a fraction of the pot's height. A barrel widest at the middle is the
  usual failure and it is hard to see without measuring.
- **The profile is a flared foot with a waist above it** — three changes of direction,
  not a smooth taper.
- **No vertical facet bands anywhere on the pot's lit half.** Banding means too few
  sides or shading left flat; it is invisible in wireframe and obvious under light.

**Other**

- The rim shows a wall of real thickness seen from above.
- The pot overhangs the plinth on both sides and is centred on it.

---

## Step 2 — stem and branches

- **2.1 Stem.** Trace its centre line off a grid overlay as (x, v) fractions and
  convert; give it a little depth in Y too, which the reference cannot show you and a
  perfectly planar stem reads as a diagram. Sweep with `tube`, few sides — at 8 mm
  across it is ~13 px in the final render, and the sides are better spent on the
  leaves and the pot. Taper front-loaded: a stem loses most of its thickness in its
  lower third.
- **2.2 Branches as parameters, not points.** Twelve of the same curve — state each as
  height on the stem, azimuth, rise, droop, sway and length and generate them. A dozen
  hand-traced point lists are a dozen chances to get one subtly wrong.
  - **Heights and lengths are measured; azimuths are chosen.** Spread them round the
    whole circle, roughly a third carrying towards the camera and a third away.
  - Start each branch's first anchor **inside** the stem. Two closed surfaces that
    touch exactly leave a visible ring under a hard key.
  - Vary the droop hard. A dozen arcs with the same droop read as a mechanism.
- **2.3 Join** the branches into the stem — same colour, same material, same shape
  family, and thirteen objects always treated as one thing are twelve too many.
- **2.4 Check from TOP ortho.** This is the view that matters and the one the
  reference cannot provide.

**Review:**

**Important**

- **From directly above, branches reach into all four quadrants**, with no bald front
  or back sector and no two within about 15° of each other. This is the check that
  decides whether the plant is a bush or a fan, and it can only be answered from the
  TOP view — from the front a fan looks full.
- **The plant's depth is at least two thirds of its width.** Quote both.
- **Measured plant height within 5% of 371 mm** — say the measured value.

**Other**

- Every branch leaves the stem going up, and most end lower than their node.
- No branch visibly separates from the stem at its base.

---

## Step 3 — leaves

- **3.1 Place them by asking the branch**, not from stored positions: regenerate the
  skeleton, use `point_on` for the point and the branch's own direction there, and
  orient relative to that. Then a change to a branch's droop moves its leaves with it,
  and there is no second copy of the plant's shape to keep in step.
- **3.2 Pitch is an offset from the branch's own slope, at about half weight.** Added
  in full the terminal leaves hang at nearly seventy degrees — a branch tip already
  points steeply down, and a leaf drooping another thirty from there points at the
  floor.
- **3.3 Infill near the stem.** A traced table will put every leaf at t ≥ 0.28,
  leaving the inner third of every branch bare — and twelve bare inner thirds all
  overlap in the middle of the plant, where the eye goes first. One extra blade per
  branch, low down, opposite the first.
- **3.4 Leaves off the growing tip too**, straight off the leader with no branch under
  them, or the stem ends in a bare spike.
- **3.5 Fold, don't flatten.** A flat plane is a paper cutout; the crease down the
  midrib is what gives each leaf a bright half and a dark half, which the reference
  plainly has. Keep the fold gentle — creased hard, a blade is edge-on from half the
  angles it gets placed at and contributes nothing to the plant's mass.

**Review:**

**Important**

- **Every leaf curves along its whole length**, rather than being straight with a bent
  tip. Crop to a single leaf to judge this — at full frame a bent tip and a curve look
  the same.
- **Each leaf is widest in its lower third and draws out to a long point**, not an
  oval. Quote where the maximum width falls.
- **The middle of the plant is not a bare patch of crossing sticks.** Leaves must fill
  the interior, not only the outline.
- **Measured plant width within 5% of 376 mm** — say the measured value.

**Other**

- A clear light half and dark half meeting at the midrib.
- No leaf intersects the stem or another leaf's midrib.

---

## Step 4 — the chillies

- **4.1 Ten fruit**, at the centres the colour classifier found, positioned along the
  branches: seven ripe red, two pale, one green.
- **4.2 Shape.** Broad domed shoulder, widest about a third down, then a long run to a
  blunt point — a cone is wrong at both ends. Pack the profile stations where the
  curvature is. About 2:1 length to width; the connected-component box that says
  otherwise includes the stalk and calyx, which are all length and no width.
- **4.3 Hang them on a stalk**, so the top of the stalk meets the branch rather than
  the fruit's shoulder — a chilli attached straight to a branch reads as growing
  sideways out of it. The calyx is a **small green cap**, its points reaching a bit
  over half the fruit's width and turning down, not a brim wider than the shoulder.
- **4.4 Faces, all turned to the camera.** `bo.chilli` builds them on the fruit's
  local −Y; place every fruit with only a small azimuth offset so all ten look forward
  whichever way their branch points. That is what the reference does and it is not an
  accident of its camera — a fruit whose face is turned away is just a chilli. The
  green one frowns; that is the joke.
  - **Sink the eyes, do not stick them on** — solve the surface circle at the eye's
    own offset rather than using the fruit's radius, or the outer eye floats, and a
    sphere left proud of the skin reads as a rivet under flat shading. The mouth
    follows the surface too: a curve drawn flat and pushed to the average depth pops
    through the skin at the corners.
- **4.5 Group by colour as you build** — the three fruit colours, one green object for
  all calyxes and stalks, one black object for all faces. Those four groups are
  exactly the four materials Step 5 needs.
- **4.6 Frame one fruit on its own** and look at it. At the scale the plant renders a
  chilli is ~90 px tall and its eyes are four pixels across; any two dots and any
  curve at all will look like a face.

**Review:**

**Important**

- **In the close-up: two sunken eyes and a mouth that follows the surface, not three
  bumps.** Judge this cropped to one fruit. Features that sit proud of the surface read
  as warts; they must cut into it.
- **Every fruit reads as a chilli, not an egg or a pod** — tapering, curved, with a
  shoulder.
- **All ten faces point at the camera.** A face on a fruit turned away is invisible and
  the effort is wasted.

**Other**

- The calyx is narrower than the fruit's shoulder.
- No fruit is buried inside the pot or clipping a leaf.
- Exactly one green fruit, and it is frowning.

---

## Step 5 — colour

- **5.1 Assign by object, not by face position.** Every colour is already its own
  object because Steps 2–4 grouped them that way as they built. That was the point.
- **5.2 Nine materials**: terracotta pot, white plinth, dark compost, a dark green for
  foliage and a lighter yellow-green for stem/calyx/stalk, three for the fruit, and
  near-black for the faces.
- **5.3 Roughness does as much work as colour.** The reference has a small hard
  specular dot on every ripe chilli and none at all on the soil, and that difference is
  most of what says "waxy fruit" and "dry compost" — two materials otherwise both dark
  and warm. Real leaves are **matt**: a broad sheen on a leaf turns pale and yellow the
  moment a warm key hits it, and that looks like a colour problem when it is a
  reflectance problem.
- **5.4 Judge this step under the studio matcap**, with no scene lights yet — judged
  together with the lighting, every time the plant looks too dark there are two knobs
  to reach for and no way to tell which is wrong. Use MATERIAL shading; Solid ignores
  materials entirely, so a step that did nothing but colour the model would show no
  change at all.

**Review:**

**Important**

- **Every region is legible as its own colour under the light you will show it in.**
  The two pairs that collapse are leaf green against stem green, and the pale fruit
  against the plinth — check those two specifically rather than judging the palette as
  a whole.
- **The faces read as black marks, not dark green.** A face that merges into its fruit
  is invisible at any distance and is the point of step 4 lost.

**Other**

- Nothing left grey.

---

## Step 6 — the light, and the flag that cuts it

This step is the picture. Everything before it is a grey model.

- **6.1 Camera** from the measured numbers above, then **verify by projection, not by
  eye**: project every vertex and compare the plant's, pot's and plinth's boxes against
  the reference's, to a couple of percent. A camera offset moves the subject the
  **opposite** way, and the reference clips its topmost leaf, so anchor on the pot.
- **6.2 Key light**, warm, aimed at the **pot** and not the plant — which is why the
  plant is dimmer at the top than the middle. Small, about 12 mm: an area light's
  energy is total watts, so small costs nothing in brightness and is what makes the
  flag possible.
- **6.3 THE FLAG — what makes the reference look like the reference, and the thing most
  likely to be missed.** A flat face lit by one light takes one value all over, so the
  hard vertical line splitting the plinth cannot come from lighting — and it carries on
  across the pot above, which a terminator cannot do. Something stands in the beam.
  - **Do not derive the key's azimuth from that boundary.** It is not a terminator, so
    R·sin(a) does not apply; it puts the key round far enough to hit the plinth at 80°
    incidence while the reference's front face is the brightest thing in frame. Derive
    it from the plinth's two faces: front lit hard, left face dark.
  - **Aim the cut on screen** — give `point_at_screen` the measured screen position and
    let it ray-cast. The plinth is yawed, so its front face is not where a first glance
    puts it. Give the cutter **a point that must be dark**, not a left/right flag: that
    sign inverts easily and the render comes back crisp, confident and wrong.
  - **Penumbra** = light size × `(subject − blocker) / blocker`. A 0.10 m light 0.22 m
    ahead of a subject 0.95 m away smears a third of a metre — no edge at all.
  - **The cut is not plumb:** 0.4621 of frame at the pot against 0.4106 at the plinth.
    A vertical edge has one screen x at every depth and can only match one. Lean it.
- **6.4 Ambient is a light the size of the sky.** Unlit surfaces in the reference are
  near black; "a bit of ambience" raises the empty shadows first and most. Keep it very
  low; make the background with a **backdrop plane**, not the world colour.
- **6.5 The fill goes in FRONT**, on the shadow side — behind the subject it washes out
  the backdrop and leaves the pot's shaded half black. Set it by measurement: the
  reference's shaded plinth face reads **82 of 255**.
- **6.6 EEVEE**, with raytracing, soft shadows and 2048 shadow maps — without them a
  2 mm stalk casts nothing, and on a plant that is most of the geometry.
- **6.7 Lay them side by side** at matched height with measured coverage under each,
  then three more angles under the same **fixed** key: move the camera, not the lights.

**Review:**

**Important**

- **A hard-edged light/dark boundary runs continuously from the plinth up across the
  pot.** Measure its half-brightness crossing in both pictures: 0.41 of frame at the
  plinth, 0.46 at the pot. A boundary that stops at the pot, or is plumb, is the flag
  done wrong — and this feature is most of what makes the reference look like itself.
- **The plinth's shaded face is a legible warm grey, not black.** Quote its value
  against the reference's 82 of 255.
- **Plant and pot each cover the same fraction of frame as the reference**, within a
  couple of percent — say both numbers, anchored on the pot, since the reference's
  plant is clipped at the top edge.
- **The plant reads as a bush, not a fan, from all four angles.** A build that only
  holds up from the camera it was authored against is a flat arrangement.

**Other**

- The flag itself is nowhere in frame.
- The background is near-black in the corners, with a soft warm pool behind and right
  of the pot.
- The four angles differ by camera, not by light.
