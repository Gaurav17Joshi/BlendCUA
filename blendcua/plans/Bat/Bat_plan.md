<!-- ref-image: Bat.jpg -->

# Bat Build Plan — BlendCuaLoop

Build a static fruit-bat model matching `Bat.jpg` (top-down photo, wings
spread, head at top): a tapered body/head/mouth, mirror symmetry, one eye
(mirrored), thin straight legs with paddle feet, curved teardrop ears, a short
humerus arm with 5 finger bones fanning from the wrist, a wing membrane between
them, and a photo-projected skin material with subtle bump/SSS. No rig, animation,
or camera — this plan stops at a complete, textured, static bat.

**This plan is deliberately not prescriptive.** It says what shape
to build and which tool to use — not exact coordinates, angles, or scale factors.
Use the `*_preview` tools below to look before you commit, judge proportions
against the photo by eye, and iterate. Finding the right numbers yourself is part
of this build.

**Everything this plan refers to sits beside it in this folder** — the reference
image and any data files. Paths below are relative to this file, not to the
repository root.

## Visual context shipped with this plan

`marked_bat3.jpg` is `Bat.jpg` with every landmark drawn and named, colour-coded by
group, and `marked_bat.json` is the same thing as data: 19 landmarks and 4 region
boxes, each with `uv` (0–1 fractions of the source photo, origin top-left, v growing
down), `px` for this image's 2081 × 2601 pixels, a `group`, and a note recording how
it was measured and what it was corrected from.

Read the JSON rather than re-reading the picture — it is exact, and several of its
notes record a landmark that was moved because the first reading was wrong.
**All wing landmarks describe the LONG (upper) wing only**, the one the build traces
before mirroring.

**The four boxes are loose crops, not targets.** `head`, `torso`, `leg` and
`wing_long` bound roughly where each region sits in the frame; they are not the
dimensions of anything. A previous run built the head to *fill* its box and produced
a skull at twice its correct width, then carried on without noticing. Follow the
animal in the photograph; use the box only to know where to look.

## Review system

Same as always: after your geometry work, output your JSON result block
(`"pass": false`). The reviewer's feedback comes back as your next message — read
it, fix only what it names, then output JSON with `"pass": true` once satisfied.

## Toolkit — specialized tools this build needs

Your `current_tools.md` covers basic viewport/selection/single-operator tools.
These come from the same `Tool_scripts/Tools_code/` package but aren't documented
there — import and use them directly.

**Tapered profile chain** (`perceive.py` / `handle.py`) — for a body/limb tapering
from a seed cylinder's end cap, one segment at a time:
```python
from perceive import body_profile_preview   # PREVIEW — read-only
from handle import apply_body_profile        # APPLY
```
`body_profile_preview(steps, direction=1, label="profile", pre_scale=1.0)` /
`apply_body_profile(...)` — same signature, one previews, one commits. Requires the
end-cap FACE selected. `steps`: list of `(dist, scale)` pairs, `dist` = local-Z
length of that segment, `scale` = XY factor on the *current* ring radius, chained
multiplicatively. `direction`: `+1`/`-1` along local Z. `pre_scale`: scales the
selected face in place before the first extrusion (default `1.0` = no-op). Both
leave the newest ring selected, so you can chain straight into another call.

**Bent chain through screen-picked points** (`handle.py`) — for a curved tube (arm,
finger) that bends at 1+ points, traced by eye in normalized `(x_norm, y_norm)`
screen coordinates:
```python
from handle import chain_preview, chain_plan_preview, apply_chain, align_seed_face
```
- `chain_preview(label=...)` — shows the selected face's current screen position on
  a 0–1 grid, to read a starting point before inventing the rest by eye.
- `chain_plan_preview(points, label=...)` — preview only; draws the path apply_chain
  would produce over the reference image. Re-run with adjusted points freely.
- `apply_chain(points, label=..., auto_face=True, face_mode="average")` — extrudes
  through the whole chain, auto-rotating each face so the cross-section stays
  smooth through bends. Leaves the final face selected.
- `align_seed_face(points, label=...)` — call once, immediately before
  `apply_chain`, **only** on a genuinely fresh seed face (e.g. a just-separated
  branch, Step 3). Pre-rotates the seed's normal to match the first segment's real
  direction. **Skip this and a fresh branch's first segment comes out twisted** —
  the seed inherits its parent mesh's unrelated normal. Never call it on a face
  already connected to prior rings.

**One seed branching into several limbs** (technique, Step 3): tag the wrist tip
face with a custom int face layer (`bm.faces.layers.int.new("finger_id")`), one
value per finger. Duplicate that face **in place** (zero-offset
`duplicate_move`) once per extra finger, tagging each copy its own id — every copy
is then exactly coincident with the wrist ring, no seam. One finger stays fused
(extrude directly off its tagged face, same object). The rest each get
`bpy.ops.mesh.separate(type='SELECTED')` into their own object + own Mirror
modifier, then `align_seed_face` + `apply_chain` as usual.

**4-corner patch placement with surface pinning** (`handle.py`) — for the wing
membrane's 4 initial corners, 2 of which must land exactly on the body's surface:
```python
from handle import quad_plan_preview   # preview only — no dedicated apply
```
`quad_plan_preview(corners, label=...)` — `corners`: list of `{"label", "color",
"current", "target"}`. No `apply_quad` — after confirming, move the matching verts
yourself (`v.co = mw_inv @ target_world`). For corners that must sit ON the body:
don't just unproject the screen point — unproject to a world Y, then raycast to
find the real surface there:
```python
from lib.view import unproject_norm
approx = unproject_norm(x_norm, y_norm, region, rv3d)   # 0-1 top-left coords
ok, loc, _, _, hit_obj, _ = bpy.context.scene.ray_cast(
    depsgraph, Vector((0.0, approx.y, 0.0)), Vector((1.0, 0.0, 0.0)))
```
Use `unproject_norm` — never `region_2d_to_location_3d` with pixels read off a
screenshot. The delivered PNG is 1024×768 while the live region is a different
size with an inverted Y axis; passing image pixels straight in unprojects to the
wrong world point (see the screen-coordinates warning in `current_tools.md`).

## Ad-hoc diagnostic Python

Some parts (especially the wing membrane boundary) are only solved correctly by
writing small, throwaway Python outside the normal preview/apply loop — not a
persisted action, use `Bash`/a scratch script with PIL/bmesh/numpy:

| Question | What to do |
|---|---|
| "Is this small detail right?" | Crop-and-zoom the screenshot with PIL, look at the crop instead of the whole frame. Cheapest — try first. |
| "Where does a boundary really run?" | Pixel classification (`im.getpixel`, a simple channel comparison) then walk a row/column to find the true edge. An exact 3D coordinate isn't automatically a boundary point — a bone landmark sits *inside* a membrane, not necessarily at its edge; verify with a scan before trusting one as an edge target. |
| "Is invisible data (UV, weights) correct?" | Dump it and redraw with PIL on top of the *source photo*, not the render. |
| "Is the mesh structurally sound?" | Read `bmesh` directly — e.g. compare a quad's 2 triangle face normals to catch a warped/non-planar face. |

## What goes wrong here

- **"The arm" means the humerus only** — a short bone close to the body. The most
  visually prominent line in the photo is a vein running the whole way to the
  wingtip; tracing that in full skips straight past the 5-finger step. The humerus
  should be a small fraction of the shoulder-to-wingtip span, not most of it.
- **Legs attach at the TAIL end, straight back**, parallel to the body's own axis —
  not at the flank like the arms, and not curved to follow a vein line (that photo
  angle doesn't map directly onto this top-down build). Basic anatomy beats
  pixel-matching here; a gliding photo may not even show the legs.
- **Use an 8-vertex cylinder for the arm/finger seed, not a cube** — a 4-sided
  cross-section visibly facets at bends once separated into its own object. Skip
  Subdivision Surface on this seed specifically (unlike leg/body) — it shifts
  vertices away from the exact points you place.
- **A coincident-duplicate seed face inherits its parent's normal**, unrelated to
  the new branch — always `align_seed_face` before the first `apply_chain` on a
  freshly-separated finger.
- **Switch to Material Preview shading (`space.shading.type = 'MATERIAL'`) before
  screenshotting anything material-related** — Solid shading ignores materials and
  textures entirely.
- **Skip `bpy.ops.uv.project_from_view`** — it depends on the viewport being framed
  to exactly the reference image's bounds, which drifts UVs off. Compute UV
  analytically instead, inverse-transforming each vertex through the reference
  Empty's own `matrix_world`:
  ```python
  ref_inv = ref.matrix_world.inverted()
  local = ref_inv @ (obj.matrix_world @ vert.co)
  u, v = local.x / rect_w - offset_x, local.y / rect_h - offset_y
  ```
  (`rect_w`/`rect_h` = the ref Empty's aspect-corrected display rect,
  `offset_x/y = ref.empty_image_offset`, default `(-0.5, -0.5)`.)
- **`vert.select` set directly via bmesh does not select the connecting edge.**
  Before an edge-extrude meant to use 2 verts you just selected in code, call
  `bm.select_flush(True)` — otherwise it silently no-ops. Assert the vertex count
  grew to catch this.
- **`bpy.ops.mesh.subdivide()` cascades to adjacent faces.** To split only one edge,
  use `bmesh.ops.subdivide_edges(bm, edges=[edge], cuts=1)`.

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

## Step 1 — body, head, mouth (seed cylinder + tapered profile chain)

- **1.1 Reference image.** Clear the scene. Load `Bat.jpg` as an Image Empty
  `BatRef` (`empty_display_type='IMAGE'`), kept visible as a backdrop for the whole
  build. Reorient so the bat reads head-down (toward -Y) in top ortho, longer wing
  on the left. Fit view to `BatRef`, ortho TOP.
- **1.2 Center the body.** Render a labelled grid over the viewport, identify the
  torso by eye, unproject that point to world XY, shift `BatRef.location` so it
  lands on the origin.
- **1.3 Seed cylinder.** Add a cylinder (modest vertex count) at the origin, named
  `BatBody`, local Z along world Y (head-tail axis). Radius/depth are a visual
  guess — render over the photo, eyeball torso width (not wings). Don't
  pixel-measure first; the taper chain below is where you actually converge.
- **1.4 Rear/hip taper (-Z).** Select the rear cap face. Preview + apply a short
  multi-segment taper narrowing toward the tail — the rump stub, not the legs.
- **1.5 Chest/neck/skull taper (+Z).** Select the original head cap face. Preview +
  apply a longer taper: chest widens FIRST, then neck narrows, then skull widens
  again — match that rhythm, not a target number.
- **1.6 Snout.** Select the tip face. Preview + apply a short taper into a small
  rounded snout — a disk, not a point.
- **1.7 Shade smooth** `BatBody`.

**Review:**

**Important**

- **Check the torso and the head separately, zoomed in on each.** A full-frame look
  cannot answer this: the torso can be correct while the head is two or three times too
  fat, and at full frame both still look fine. Crop to each, judge it alone, and say
  what you saw.
- **There is a measurable neck narrowing** — one ring narrower than both the chest
  before it and the skull after it. Quote the three widths. A profile that widens
  monotonically from chest to skull is a fail, and it is the failure this build is most
  prone to.
- **The muzzle is thin.** Compare it against the photo's own snout, zoomed, and say
  what each measures. A blunt cap is correct; a blunt cap several times too wide is
  what this check exists to catch.
- **The silhouette follows the bat in the photo** — nothing sticks out past the animal
  into the sky, nothing falls short of it.

**Other**

- One continuous mesh: torso tapering to a short rump stub at one end, chest → neck →
  skull → blunt snout at the other.
- The snout ends in a flat disk, not a sharp point.
- `BatBody` centred on z = 0, so the reference plane passes through its mid-depth.
- No gaps or inverted-normal patches.

---

## Step 2 — mirror symmetry, eye, legs, ears

- **2.1 Mirror.** Edit mode on `BatBody`, delete one side of the centerline mesh.
  Add Mirror modifier, X axis, `use_clip=True`.
- **2.2 Cap fill + Subsurf.** The mouth/rear rings each have an open boundary arc
  from 2.1 (not the centerline seam — mirror handles that). Select each cap's
  boundary edges (same constant local-Z), `bpy.ops.mesh.edge_face_add()`. Add
  Subdivision Surface AFTER the Mirror modifier.
- **2.3 Eye.** Small icosphere on the skull bulge, mostly lateral with a slight
  upward lean, gently embedded (raycast or estimated surface radius). Name `Eye`,
  Mirror modifier (`mirror_object=BatBody`) — build only the one side.
- **2.4 Leg seed.** Small cube near the TAIL TIP, close to centerline — not the
  flank (legs ≠ arms). Local Z straight rearward, no lateral angle. Name `BatLeg`,
  add Subdivision Surface + Mirror (`mirror_object=BatBody`).
- **2.5 Leg extension.** Select the seed's outer face. Preview + apply a straight
  `body_profile` taper (not a bent `chain` — the leg is straight).
- **2.6 Paddle paw.** Select the tip face. Preview + apply: widen into a paddle,
  hold, taper to a rounded tip. `shade_smooth` `BatLeg`.
- **2.7 Ear seed (isolated).** New object `BatEar`: 2 verts, 1 edge, roughly half
  the head's diameter wide, placed well clear of the body so it fills the frame
  alone while you shape it — final placement comes last (2.9). Fit view FRONT.
- **2.8 Shape the ear.** FRONT view, select all, `MEDIAN_POINT` pivot. Repeated
  extrude-up + narrow (widen to a "shoulder" first, then narrow) to build a flat
  teardrop, then a final extrude + `bpy.ops.mesh.merge(type='CENTER')` to close the
  tip. Add Solidify (small symmetric thickness). In edit mode, bend the upper
  portion (Z-filtered) around an X-axis rotation to curl the tip. Add Subsurf
  (after Solidify) + `shade_smooth`. Check from RIGHT view.
- **2.9 Place the ear.** Behind/above the eye, embedded slightly into the skull
  (not glued on top). Point mostly straight up (dorsal), not splayed sideways — an
  overhead view should read it as small/foreshortened. Mirror
  (`mirror_object=BatBody`) — place only the one ear.

**Review:**

**Important**

- **Bilateral symmetry with no centreline gap.** A mirror about the object's own origin
  puts the copy back on top of the original; check the seam closed rather than assuming
  the modifier did it.
- **The ears grow out of the skull rather than sitting on it.** Crop to one ear: a
  visible join ring where ear meets head is the failure, and it is invisible at full
  frame.
- **The eyes are visibly embedded, not floating or sunk.** Lateral and slightly
  forward/up. Check from a 3/4 view, not from the side.

**Other**

- One mirrored eye per side.
- Thin straight legs from the tail, with paddle feet.
- Ears are curved teardrops behind the eyes, pointing mostly up.

---

## Step 3 — arm and 5 finger bones

Most likely step to go wrong if rushed — re-read the humerus-vs-full-arm lesson
above first.

- **3.1 Arm seed.** Small 8-vertex cylinder (not a cube) at the shoulder (the
  chest-to-skull transition on `BatBody`). Name `BatArm`. Local Z along the wing's
  leading edge (mostly lateral, slightly forward/down — read off the photo). Mirror
  (`mirror_object=BatBody`). **No Subsurf** on this object.
- **3.2 Humerus.** Render a fine grid over the shoulder-to-wingtip region to trace
  by eye. Select the seed's outer face, `chain_preview` for the start point, then
  preview + apply a SHORT bent chain (elbow, then wrist) — stays close to the body,
  nowhere near the wingtip.
- **3.3 Reserve 5 finger points.** Tag the wrist tip face with a `finger_id` int
  layer. Duplicate it in place 4 more times, tagging each its own id (see toolkit
  section above).
- **3.4 Finger 1 (fused).** Select its tagged face on `BatArm` itself. Trace,
  preview, apply a chain following the most prominent vein to the wingtip corner.
  Scale the new tip face down slightly to taper. `shade_smooth`.
- **3.5 Fingers 2–5 (separate objects).** For each: select its tagged face,
  `separate(type='SELECTED')`, rename, own Mirror modifier
  (`mirror_object=BatBody`). Trace + `chain_plan_preview`, then
  **`align_seed_face` before applying** (mandatory — fresh branch seed),
  `apply_chain(auto_face=True, face_mode="average")`, taper the tip, `shade_smooth`.

  Trace each against the photo's own vein pattern and silhouette — don't reuse
  another build's points:

  | Finger | What it traces | Notes |
  |---|---|---|
  | 2 (thumb claw) | Short digit dropping from the wrist into open sky, past the membrane edge. | Free-hanging, not attached to the wing patch — short, fine-tapered. |
  | 3 | Vein to the middle scalloped peak. | One of the longer fingers. |
  | 4 | Vein to the next peak over. | Nearly vertical from the wrist; may need 3+ points. |
  | 5 (short strut) | Short digit into the membrane between thumb and finger 4. | Easy to miss — look for a short flat stretch in the trailing edge right after the wrist, not a steep line. |

**Review:**

**Important**

- **No seam at the bifurcation where the fingers leave the wrist.** Each finger must be
  a fused continuation, not a separate tube parked against the wrist. Crop to the wrist
  and say what you see — this is the join most likely to be faked.
- **No twisted or non-planar faces at any separated finger's base.** A seed face rotated
  in place while already attached warps the geometry behind it; check each base.
- **The humerus is short and does not reach toward the wingtip.** Quote its length
  against the finger that does. A long humerus turns the whole wing into one straight
  spar.

**Other**

- One humerus per side.
- Five fingers fanning from the wrist: fused straight extension to the wingtip (1),
  short claw (2), two reaching further peaks (3, 4), short strut (5).

---

## Step 4 — wing membrane

- **4.1 Seed plane.** Flat plane roughly over the wing area (+X side), named
  `BatWing`, Mirror (`mirror_object=BatBody`). Exact size/position doesn't matter —
  every vertex moves to an exact target next.
- **4.2 Place 4 corners.** `quad_plan_preview`, then move the matching verts
  directly (sort by world X: 2 smallest = body-side, 2 largest = wingtip-side; sort
  each pair by Y). Body-side corners: raycast onto `BatBody`'s real surface near
  the shoulder and near the leg. Wingtip-side corners: plain unprojected points, a
  modest distance out.
- **4.3 Push the outer edge out in stages.** Each stage: `quad_plan_preview` (the 2
  wingtip verts moving further out) → extrude the outer edge (`bm.select_flush(True)`
  first) → move the new verts to the previewed targets.
  1. First push — a rough guess, a little further out from 4.2.
  2. Second push — further still.
  3. Once the arm/fingers exist, converge exactly onto their real tips — the arm's
     wrist and finger 3's tip, queried directly off the built meshes, not
     re-estimated from the photo.
  4. Converge the near-leg side onto finger 4's real tip. On the shoulder side,
     don't reuse a bone landmark (an interior point, not a boundary point — see
     *What goes wrong here*) — column-scan a screenshot for the true membrane/sky
     edge instead,
     with a small safety margin inward.
  5. Final edge: both sides converge on finger 1's real tip (the wingtip corner).
     Extrude, snap both new verts to that one point, then
     `bpy.ops.mesh.remove_doubles(threshold=0.0001)` to merge them cleanly.

  If a small sky triangle remains between two finger tips (check by pixel-scanning,
  not eyeballing), fix it with one targeted `bmesh.ops.subdivide_edges` on just
  that edge (not `bpy.ops.mesh.subdivide`, which cascades) and push the new
  midpoint out to the true boundary.
- **4.4 Finish.** `shade_smooth` `BatWing`.

**Review:**

**Important**

- **The membrane reads as one continuous scalloped surface from body to wingtip**, not
  a flat rectangle or triangle. The scallops between fingers are the whole shape; a
  straight trailing edge is the failure.
- **No large sky gaps between fingers, and no clipping past the silhouette.** Check the
  trailing edge against the photograph's own membrane edge, column by column rather
  than by eye — a gap and a slight overshoot look alike at full frame.

**Other**

- The membrane is symmetric between the two wings.
- It attaches along the body, not floating clear of it.

---

## Step 5 — materials, UV, skin texture

- **5.1 Skin material + UV.** `BatSkin`: `Bat.jpg` Image Texture → Principled
  BSDF Base Color. Assign to `BatBody` + `BatWing`. UV-unwrap both **analytically**
  (skip `project_from_view` — see *What goes wrong here*): for every face loop,
  `world_to_uv(mw @ loop.vert.co)` where
  ```python
  ref_inv = BatRef.matrix_world.inverted()
  img_w, img_h = BatRef.data.size
  size = BatRef.empty_display_size
  rect_w, rect_h = (size, size*img_h/img_w) if img_w >= img_h else (size*img_w/img_h, size)
  ox, oy = BatRef.empty_image_offset
  def world_to_uv(world_pt):
      local = ref_inv @ world_pt
      return (local.x / rect_w - ox, local.y / rect_h - oy)
  ```
- **5.2 Bone material.** `BatBone`: flat black, fairly matte, no texture. Assign to
  `BatArm`, all 4 separated fingers, `BatLeg`, `BatEar`.
- **5.3 Eye material.** `BatEyeShiny`: black, noticeably glossier than the bone
  material (low roughness), plausible IOR if that input exists on this Blender
  version (check with `hasattr`/`in bsdf.inputs`, don't assume). Assign to `Eye`.
- **5.4 Verify.** `space.shading.type = 'MATERIAL'` (Solid hides all of this),
  render a full-bat check.
- **5.5 Ear gets photo colors.** UV-unwrap `BatEar` the same analytical way, assign
  `BatSkin` (overriding `BatBone`) so it samples real photo colors, not flat black.
- **5.6 SSS + bump.** On `BatSkin`'s Principled BSDF: subsurface method Random Walk
  Skin (try `bsdf.subsurface_method`, fall back to `mat.subsurface_method`; try
  `'RANDOM_WALK_SKIN'`, fall back to `'RANDOM_WALK'` on `TypeError`), a modest
  subtle Subsurface Weight (input name varies by version). Add a Bump node:
  `Bat.jpg` Color → Bump Height → Principled Normal, small bump distance. No
  "Filter Width" socket exists on this node in current Blender — that's not a
  missing step.
- **5.7 Wing translucency.** Duplicate `BatSkin` as `Bat_wing`. Add a Translucent
  BSDF (same texture as Color), mix roughly evenly with the Principled BSDF via a
  Mix Shader before Material Output. Assign `Bat_wing` to `BatWing` (replacing
  `BatSkin`).

**Review:**

**Important**

- **The photo texture is correctly oriented — not stretched, mirrored or offset.**
  Verify in Material Preview, and say which feature you used to confirm the
  orientation. A mirrored texture looks plausible until something asymmetric in it is
  found.
- **The wing membrane reads as subtly different from the body** — thinner or more
  translucent — despite sharing a base texture. If membrane and body read as the same
  material the wing disappears into the animal.

**Other**

- Body, wings and ears carry real fur/skin colour from the photograph.
- Arms, fingers and legs are flat black.
- The eye is small and glossy, distinct from the matte bones.
