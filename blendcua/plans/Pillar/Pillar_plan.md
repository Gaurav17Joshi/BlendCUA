<!-- ref-image: Pillar.png -->

# Stone Pillar Build Plan — BlendCuaLoop

Build a weathered square stone gate post from the shape in `Pillar.png`: a
4 m stack — stepped footing, flare, three shaft blocks separated by two grooves,
capital flare, neck, top slab — sculpted at ~700,000 vertices with knocked corners,
worn arrises, a broad smudge, four differently weathered faces and five cracks, then
baked down to a 62-face cage carrying 2048 px normal, colour and roughness maps. No
rig, no scene, no lighting: this plan stops at a game-ready asset and the pair of
screenshots proving the bake worked.

**This plan is deliberately not prescriptive.** It says what to build,
which tool to use, and which numbers this build converged on — not per-action
parameters.

**Everything this plan refers to sits beside it in this folder** — the reference
image and any data files. Paths below are relative to this file, not to the
repository root.

## The one decision that shapes everything: nothing here is measured

The bat was traced against a photograph and the chilli plant measured off a render. This
is neither. It is an **invented architectural object**, and the reference is a picture
of somebody else's. Do not load it into the scene, place landmarks, unproject screen
picks or run `silhouette_vs_reference` — there is no correspondence to recover, because
your pillar is not that pillar. Decide the proportions yourself.

That removes the verification method the other two builds leaned on, and it is why
this plan is four steps long instead of one: **the shape is the cheap part.** Step 1
is a single action; steps 2–4 are the build, and each is judged by whether the
surface reads as *stone* rather than as a mesh somebody ran a filter over. That has
no measurement, so it is attacked from the other side: every damage pass reports the
millimetres it moved and the vertices it touched, and a pass that reports nothing
has failed whatever it looks like.

## The one reference, and what it does not show

`Pillar.png` is the whole reference: the clean stacked silhouette, untextured, from a
3/4 view. It is step 1's target and nothing else's. **Every pass after step 1 is
specified in words here, not pictured** — what a smudge, a crease, a fracture and a
weathered face are supposed to look like is written into the steps below, and those
descriptions are the spec. Do not go looking for a picture of the finished thing;
there isn't one, and inventing what it "must" look like from the clean stack is how a
build ends up with uniform machine damage.

The deliverable's poly budget is stated rather than shown: the finished low-poly
should land in the region of **386 verts / 768 tris**.

## The numbers that matter

Choices, not measurements — but they came out of a run corrected until it was accepted,
and the ratios are what make it read as a pillar rather than a box.

| | value |
|---|---|
| height, datum | 4.00 m; bottom face at **z = 0**, centred on Z, symmetric in X and Y |
| section, profile | a **plain square**, 4 verts a ring; 16 rings, slab half-width 0.620 against the shaft's 0.375 — a **1.65×** overhang — and a base group 0.78 m tall against the capital's 0.70 |
| the chamfer | **dropped.** The short plan cut every vertical edge at 45° and the reference's base and capital do look that way, but it costs 8 verts a ring and a wedge face down each corner, and step 2's damage makes a better arris anyway. Keep the cut small if you keep it. |
| grooves | V-section: one ring 50 mm narrower, 70 mm tall — a shadow line, not a channel |
| sculpt / cage | ~700k verts; the cage is 64 verts / 62 faces, kept **before** densifying |
| edges | corner wear ~2 mm, chips 8–10 mm, 3–4 per block edge; six creases at **11–33 mm, not in ascending order**; one smudge, a 130 mm brush over a 70 mm stroke, ~30 mm deep |
| what the damage MEASURES | the radii above are brush sizes, not results. What the report has to come back saying: creases cut **15–21 mm**, corner chips **8–10 mm**, the smudge **~30 mm**. A crease reporting 3 mm is a scratch, and no radius in range makes it a crease. |
| brush strengths | inverted `CREASE` at **0.85**; the corner `PLANE` scrape and `DRAW_SHARP` chips per 2.2. Half strength halves the cut: at 0.42 a crease comes out around 3 mm, which is a scratch, not a crease. |
| stroke shape | every damage path is **wavy, `amplitude` ≈ 6 mm** — a corner arris projected straight off the geometry and stroked straight reads as a machined groove, not a broken edge. Never pass a raw geometric path through as `resolved`. |
| weathering | erosion 4.5–7.0 mm, pebbles 3.0–6.0 mm, features 62–125 mm across |
| cracks | cores 18–34 mm wide, deepest cut 34 mm; shoulders 95–125 mm at ~8% strength |
| bake | 2048 px; cage extrusion 90 mm, max ray 140 mm, island margin 32 px |

## Review system

Same as always: after your geometry work, output your JSON result block
(`"pass": false`). The reviewer's feedback comes back as your next message — read
it, fix only what it names, then output JSON with `"pass": true` once satisfied.

## Toolkit

**`sculpt_native.py`** — Blender's own sculpt brushes over the socket, and the main
tool of steps 2 and 3: `frame_ortho` (returns pixels per metre), `apply_stroke`,
`world_arrays`/`movement`, `displace`, `face_axis`, `drape_line`, `strokes_footprint`.
Three things it will not let you forget:

- **Brush size is in SCREEN PIXELS** and does not scale with the object: a 50 mm
  brush is 7 px with the whole pillar in frame and 35 px with one block in frame.
- **A native brush is not predictable, so every call returns what it measured** —
  write those to a report file and read them; `strength=0.9` means nothing alone.
- **How much of its radius a brush cuts depends on the brush** — `DRAW_SHARP` about
  90%, `PLANE` about 17%. A 30 mm chip brush tore 73 mm gouges out of a 375 mm block.

**`paint.stroke_lines_preview`** draws candidate paths over a render of the current
view. **The preview and the apply must call the same function to get their paths** —
not merely agree on the numbers.

**Preview every damage pass, and preview all the paths of one kind together.** Not
the first corner and then five blind ones; not six crease rings with no preview at
all. One image showing all six crease bands at once is how you see that the spacing
is uneven or that one band sits off its edge — six separate cuts cannot show you
that, and by then they are cut. This step is *more* worth previewing than a scripted
step, not less: every number below is in millimetres and every brush is in screen
pixels, so the preview is where you find out the two agree.

**Leave `show_anchors` ON.** The anchors are what make a path readable — the reference
build's crease preview labels every station (`b1_bot_0…6`) so a misplaced one is
obvious. Do not replace them with brush-scale circles: at the framing this step uses a
12 mm brush projects to about 7 pixels, which is a dot that tells you nothing.

**`fracture.py`** — cracks that read as split stone rather than an engraved line: a
profiled **core** whose width varies and whose tips feather to nothing, a wide weak
one-sided **shoulder** dropping the stone on one side, optional **lobes** where a
flake spalled off. `plan()` is pure geometry and `cut()` calls it.

**`weathering.py` + `wear_textures.py`** — draped face strokes, a preview drawing
brush and feature sizes as circles, and `weather()` to lay texture layers in. All
paths become **one** footprint: displacing per stroke doubles the texture wherever
two bands overlap, which shows as a bright seam down every face.
**`bake.py` + `polyhaven.py`** — cage stashing, unwrap, UV layout PNG, the bake, image
maths, seamless tiling from a crop, and CC0 asset fetch with credit written out.

**What lives in the run, not the toolkit** — `pillar_geom.py` (where the edges are),
`edge_pass.py`, `smudge_pass.py`, `sides.py` (which weathering goes on which face),
`cracks.py`, `texture_pass.py`. The test for `Tool_scripts/Tools_code/` is not "could
someone else call this?" but **"would it be the right shape for them if they did?"**:
`fracture` splits any mesh from any view, while `cracks.py` knows this pillar's
blocks are 0.77 m tall and that the one on the back-left falls to its left. Define
each fact **once** — `pillar_geom.py` exists because the preview and the apply
drifted apart twice, each time because both carried their own copy of the z values.

**Ad-hoc diagnostics.** These steps drive an operator whose behaviour is undocumented
in half the places that matter, and the fastest way through is a throwaway script
sweeping one parameter across three bands on a face the build does not need. Ask three
things of every damage pass: **did it move anything** (`world_arrays` before and
after, `movement` between — a render can be argued with, 552 verts moved by 31.3 mm
cannot); **did it make the right shape** (sample a *profile*, not a total — how far
the corner apex sits along its bisector every 10 mm of height is what separates a
patch from a stripe); **did it touch anything it shouldn't** (report movement outside
the footprint and assert it is zero). Save each script under the step's `scripts/`
folder with the images it produced, and write reports to a **file** — Blender's stdout
goes to the console it was launched from, so a diagnostic that prints is unreadable.

## What goes wrong here

- **A brush texture cannot be driven from a script at all.** `brush.texture = tex` on
  the linked Essentials brush silently does nothing, `make_local()` is a no-op when
  the datablock has no users, and with both solved `brush_stroke` still resolves its
  brush from the paint mode's asset reference. Surface texture comes from
  `sn.displace()` instead — a brush texture panel is not a route a script can take.
- **Two traps in `displace`:** under LOCAL coordinates an image on a **vertical** face
  is constant along one axis and comes out striped (use `face_axis()` and
  `texture_coords='OBJECT'`), and it cannot express detail finer than about eight mesh
  cells — too fine is not subtle, it is aliased noise.
- **A symmetric groove can never read as a split**, however deep: both banks are the
  same height, and what the eye reads in a real fracture is that one side sits
  *lower*. Author the anchors as corners too — a spline through big swings gives you a
  river, and stone kinks.
- **Damage must cover the whole edge and must not clump.** Strokes have to run *past*
  both ends: creases stopping at the corners left a crisp arris where the block meets
  its groove, the least plausible place on a pillar for undamaged stone. And give each
  chip its own slot — drawn from one uniform over the block, two landed within 5% of
  each other and the corner came out one mangled patch and two thirds untouched.
- **Uniformity is the tell.** Six identical creases read as manufacturing; three cracks
  that all drop their left side read as three cracks made by the same script.
- **Work at 45°, down the corner's own bisector** — square onto a face a vertical corner
  projects to a line on the silhouette, and you cannot see how far the brush reaches
  onto either side of it.
- **The low poly is not a decimation** but the cage the sculpt was built from, kept
  before densifying — decimate the sculpt instead and every millimetre its silhouette
  wanders bakes as black speckle.
- **Cavity shading flatters everything and tells you nothing** — a flat smudge and a
  mottled blotch look alike under it. Off, for the whole build.

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

## Step 1 — the clean stack

One action. This is a flat, simple object and it does not need the overlay-and-pick
machinery.

- **1.1 Declare the silhouette as data** — a list of `(z, half_width)` rings bridged
  into quads. A repeated `z` is a hard step (a slab edge); a change in both is a taper
  (the flares). The silhouette is then one list to read and adjust, instead of fifteen
  extrudes where changing one segment means redoing everything above it.
- **1.2 Three ratios make it read as a pillar** rather than a box: the slabs
  **overhang the shaft** by half as much again; the **base group is visibly heavier**
  than the capital; the grooves are **shadow lines, not gaps**.
- **1.3 Flat shading, no Subsurf** — stone has hard edges, and Catmull-Clark would round
  off the crisp slab edges the silhouette rests on. A couple of hundred verts, no more.
- **1.4 Then look**: FRONT ortho for the stack, TOP for the section, one 3/4
  perspective against `Pillar.png`. Expect the first pass to be off: the usual
  failure is a base flare so gradual that footing, step and flare merge into one
  taper. Then
  rewrite the action under the same filename with `# REDO N: "<what was off and what
  you changed>"` added **above** the existing header. Required, not optional — and
  keep every comment already in the file: the redo replaces the geometry, never the
  record of why the previous values were rejected.

**Review:**

**Important**

- **The stack reads in order, top to bottom: stepped footing → flare → three-block
  shaft with two grooves → flare → neck → top slab.** None missing, none doubled. This
  is the whole point of the step; everything below is a detail by comparison.
- **The slabs overhang the shaft and the base reads heavier than the capital.** Say
  what the widths and heights came out as, in metres. "It looks right" does not answer
  this — the overhang is a ratio and the base/capital comparison is two numbers.
- **The two grooves are shadow lines, not channels.** One ring narrower and about
  70 mm tall. A groove deep enough to read as a gap between blocks is wrong at this
  stage; step 2's creases do that job.

**Other**

- Bottom face at z = 0, centred in X and Y.
- TOP view is identical rotated 90° — the section is a true square.
- One object, flat-shaded, no Subsurf, no materials.
- No doubled vertices.
- Nothing loaded into the scene as a reference Empty.

---

## Step 2 — density, and the edges

- **2.1 Densify in two stages**, because either alone gives bad topology. First cut
  loop rings until **every** edge is under a target length: step 1's quads are wildly
  non-square, and a carve stroke crossing a ribbon steps along the ribbon's long axis
  instead of following the stroke. Then **SIMPLE** subdivision, not Catmull-Clark,
  which keeps the silhouette exactly and only adds density. Halve iteratively,
  re-collecting the edge list each pass — grouping edges by cut-count invalidates the
  `BMEdge` references the later groups hold. **Stash the cage first**, hidden: that is
  the mesh that ships, and everything after this is about to become an image.
- **2.2 Chip the vertical corners**, one corner per action, framed down its own
  bisector. Two brushes on one path per block: a full-length `PLANE` scrape to wear
  the arris, then `DRAW_SHARP` inverted for the chips. **The chips come from the
  brush, not from extra strokes** — wide dab spacing plus heavy jitter scatters one path
  into discrete bites, where default spacing lays a fine continuous sawtooth that reads
  as render noise. Two opposite corners is enough.
  - **One path per block is three paths, and it is not a tidiness rule.** A single
    stroke down all 4 m forces the whole pillar into frame to author it, and brush size
    is in screen pixels — so the same physical 20 mm brush lands as 9 px instead of 14,
    and cuts a third as deep. Frame each block on its own bisector, author that block's
    path, stroke it, move on. Expect **~700 px/m**; if the report says ~470 you have the
    whole pillar in shot and every size below is wrong.
  - **The path must be wavy before it is stroked** — `waviness="wavy"`, `amplitude`
    ≈ 0.006. `screen_corner_path` gives you the arris as projected geometry, which is
    exactly straight; stroking that produces a machined groove down a perfect line, the
    single most obvious way this step comes out looking wrong. **Do not pass it through
    as `resolved`** — that flag means "already wobbled, leave it alone", and on a raw
    projection it silently throws the irregularity away.
- **2.3 Crease the horizontal edges on all four sides.** A horizontal edge runs the
  whole way round the block, and creasing only the camera's face leaves the other
  three pristine — visible the moment anything orbits. Frame each side from its own
  normal and size in metres, so the crease is the same physical width on the wide base
  as on the narrow shaft. Use the native `CREASE` brush inverted **at strength 0.85**:
  it pinches vertices *toward* the stroke as well as down it, where a sharpened draw
  plus a weakened relax pass comes out as a rounded groove. Each crease must report
  **15–21 mm** of cut; if it comes back at a few millimetres the strength is too low or
  the brush is too few pixels, and the fix is to raise one and re-frame for the other
  — not to accept the number and move on.
- **2.4 One smudge, and only one.** A broad soft patch as wide as it is tall, fading
  into both faces — so a **short** stroke under a **wide** brush, the dabs stacking
  into one depression. The depth control is the flatten plane's offset: at offset 0
  the brush levels to the surface it measures and, on a corner 2.2 has already worn,
  finds nothing proud and takes 6 mm. Preview it with **dots scattered over the
  vertices the brush will reach**, not a line. Commit one and look before deciding
  about the rest — the previous version committed three and got three with the same
  problem.

**Review:**

**Important**

- **Every cut is the depth it was supposed to be — quote the measured numbers.**
  Creases 15–21 mm, corner chips 8–10 mm, corner scrape ~2 mm, the smudge ~30 mm. A
  crease reporting 3 mm is a scratch and fails this check however good the layout is.
  This is the check the step exists for: the shapes can all be in the right places and
  the pillar still read as undamaged.
- **The damage paths wander; nothing is a straight line.** A corner worn along a
  mathematically straight arris reads as a machined groove, not a broken edge. Look at
  a corner close up and say whether the line meanders.
- **Every horizontal block edge is creased on all four sides**, the six visibly
  different widths. Orbit and check the faces that were away from the camera — creasing
  only the near face is invisible from the authoring view and obvious from anywhere
  else.
- **Damaged corners are worn along their whole length**, with no untouched stretch at
  either end, and the chips are spread down the edge rather than piled in one patch.

**Other**

- The sculpt is near the density target and the silhouette is unchanged from step 1 —
  check a groove is still sharp.
- The hidden cage exists with step 1's vertex count.
- The smudge is one patch, not a stripe, and not repeated elsewhere.
- Every damage report shows zero movement outside its own footprint.
- Cavity shading off throughout — it flatters damage and makes a shallow depression
  look like a deep one.

---

## Step 3 — the faces, and the cracks

- **3.1 Weather all four faces, each differently.** Vertical strokes draped down the
  real surface, two texture layers laid into their combined footprint: a broad
  **erosion** wash and a finer **pebble** relief, masked by face normal and fading out
  at the arris. Preview the paths *with the brush circle and one circle per feature* —
  a path says where a stroke goes and nothing about how wide it is or how big the
  texture will be, and both are invisible until after it has run. **Same kind of
  weathering, different intensities**: vary the number and spacing of lines, the
  radius, the depth, the feature size and every seed. Giving each side its own *pair
  of maps* was tried first and made them look like four different materials.
- **3.2 Then the cracks — one per corner**, so the four corner views cover all of
  them. Author each path in screen coordinates from the view that judges it;
  `sculpt_native` raycasts every sample onto whatever surface is under it, which is
  what lets one path cross a face, an arris and a groove without anyone working out
  where those are. **A crack that stays on one face is not a crack** — a real one runs
  over the arris and through the groove into the block below, because the stone split
  and the fracture does not care where the faces are. Keep the wander *smaller*
  than the cut or it comes out shredded rather than jagged: the mesh cannot render a
  wobble finer than the groove it is in. And a branch should start at an anchor **of**
  the trunk, so the two meet exactly rather than nearly, and carry no shoulder of its
  own — a branch with its own displaced plate reads as a second crack.
- **3.3 Four corner views at the end**, so every adjacent pair of sides is seen together
  and every crack appears at least once.

**Review:**

**Important**

- **Each crack has a visible level difference between its two sides.** This is what
  separates a split from an engraved line, and it is the single thing most likely to be
  missing. A symmetric groove — same height either side — is a fail no matter how
  jagged its path.
- **The fractures do not all drop the same side.** Check the shoulder direction of each
  and say which way it goes; five cracks all shouldered the same way read as a pattern,
  not as damage.
- **Nothing reads as a machined channel or as a river.** A crack whose width is
  constant along its length is machined; one that meanders smoothly without jitter is a
  river. Both tips must feather to nothing.
- **All four faces carry relief and no two look alike — say what differs.** Weathering
  applied identically to every face reads as a filter over the model rather than as
  weather on a specific stone.

**Other**

- Five cracks, each crossing at least one arris or groove rather than sitting flat on
  one face.
- Each crack's width varies along its length.
- No bright seam down the middle of any face — that is the double-displacement bug.
- Each weathering report shows zero movement outside its footprint.

---

## Step 4 — bake down to the deliverable

- **4.1 Fetch a quiet stone** (CC0, credit written out). **A texture for a model that
  already has features must be quiet** — a stone photograph carrying its own dark
  craquelure runs that pattern over the whole pillar and reduces the cracks steps 2
  and 3 spent their entire effort cutting to one line among hundreds. Check what it is a photograph *of*: a
  tiled floor's grout lines are the floor's layout, not the stone's. Crop one tile's
  interior and mirror it into a seamless tile — and **a mirror doubles whatever is at
  the crop edge**, so the first crop's 3 px of grout came back as a dark line ruled
  across the pillar every 55 cm in both directions.
- **4.2 Unwrap the cage** with Smart UV Project, not hand-placed seams: on a model whose
  faces are flat and meet at hard angles, cutting on angle *is* the correct seam set.
- **4.3 Bake normal, then AO.** Every chip, crease, smudge, pebble and crack stops
  being geometry here and becomes a direction per texel. Baking needs **Cycles**; in
  EEVEE the operator errors or silently produces nothing. Non-Color on normals,
  roughness and AO, sRGB on colour — a normal map read as sRGB is not obviously
  broken, it just lights slightly wrong, everywhere, forever. **Cage extrusion must
  clear the deepest cut**, or a 35 mm crack bakes as a flat patch where the ray
  stopped short. A bake that did nothing is uniform blue, so **the spread is the
  proof, not the mean.**
- **4.4 Colour: project onto the sculpt, bake through the cage's UVs.** Box projection
  in object space needs no UVs, has no seams, and follows the sculpted surface rather
  than sliding over it — but it cannot ship, being evaluated per-pixel from a 2K
  source and attached to the low poly not at all. Use the diffuse bake with only the
  colour pass, or you photograph this scene's lighting. Scale it so the grain sits
  **between** the pebbling and the block. Fold AO in and floor it: nothing on a real
  pillar is unlit, and a black-floored AO reads as dirt rather than as shadow. What
  ships is **three files and a UV layer** — no procedural nodes, no object
  coordinates, nothing that would not survive an export.
- **4.5 The comparison that matters:** the same close-up of the sculpt and of the cage
  wearing its baked maps. If the bake worked they are hard to tell apart at pillar
  scale and differ only in the silhouette — a normal map fakes lighting, not shape.

**Review:**

**Important**

- **The same block, viewed on the cage and on the sculpt, shows the same cracks and
  weathering.** This is the only check that tells you the bake worked. No black
  speckle, and no flat patches where a crack floor should be — a flat crack floor means
  the ray missed and the map is carrying nothing there.
- **The maps have real spread, not a plausible mean.** Quote the spread of each. A
  normal map averaging a believable value while varying by almost nothing is a failed
  bake that looks fine as a number — spread is the proof, not the mean.
- **The delivered cage meets the stated budget of ~386 verts / 768 tris.** It is the
  step-1 cage subdivided to reach that budget, not a decimation of the sculpt and not
  the 64-vert cage shipped as-is.
- **The stone's grain does not compete with the sculpted cracks.** If the texture's own
  dark lines read as loudly as the cracks, the source was too busy and the whole of
  steps 2 and 3 is lost under it.

**Other**

- Unwrapped into roughly one island per face.
- Three 2048 maps on disk, with the right colour space on each — sRGB for colour,
  Non-Color for normal and roughness.
- No ruled lines or repeating features anywhere in the texture.
- The material references only saved image files and one UV layer — no procedural or
  object-coordinate inputs.
