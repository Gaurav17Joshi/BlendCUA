<!-- ref-image: reference.png -->

# 05 Energy Can Build Plan

Build a single slim energy-drink can in the supplied studio product view. The
important read is a tall near-black wraparound label, the three irregular neon
green Monster claws with a thin light outline, the white/green word marks below,
and the rolled silver top and bottom rims. Keep the geometry manufactured and
subtle: this is a product can, not a black cylinder with raised letters glued to
it. Use the reference for camera and projected targets, and preview the result
after each major change rather than treating any starting dimension as proof.

All paths below are relative to `plans/Energy_can/`. The measurement scripts,
crops, and the transparent logo artwork are in `scripts/`; the durable landmark
list is `marked_Energy_can.json` and its drawn evidence is
`marked_Energy_can.jpg`.

## What the reference is and how to use it

`reference.png` is a 1024 x 1536 portrait studio photograph/render of one can on
a nearly uniform light-grey background. It is a mildly perspective product view,
not an orthographic blueprint: the top rim is visible from slightly above, and
the shoulder and lower rim taper in projection. Build the rotational form in
world space with Blender Z as the can axis, then fit a perspective camera. Do not
multiply image `u,v` directly into world X/Z; use the matched camera or project a
curved label/decal onto the can.

The axis is near the image centre (`u` about 0.500; the straight-body edge pair
at y=300 is x=267..762). A strict local-background segmentation (`difference
threshold = 12`, saved by `segment_can_bounds.py`) gives the reliable visible
object box x=267..762, y=90..1468: **496 x 1379 px**, width/height **0.359681**
and height/width **2.780242**. A looser threshold sees a grey halo, x=264..764
at threshold 6 and x=232..773 at threshold 4; those are diagnostics, not
permission to fill a larger rectangular crop. The strict mask includes the
metal rims and the black can surface, so use it as a projected silhouette target.

## Measurements taken from the reference

These values come from the saved PIL/OpenCV scripts rather than a coordinate read
from the displayed photograph.

### Silhouette and manufactured profile

| feature | measured reference target |
|---|---:|
| strict visible bbox | x `267..762`, y `90..1468` |
| strict bbox size and aspect | `496 x 1379 px`; width/height **0.359681** |
| image/axis centre | top landmark x `512`; straight-body edge midpoint about `514.5` (`u` about 0.500) |
| broad top-rim span at y=140 | x `284..746`, width `463 px` = **0.933468** of the straight-body width |
| shoulder span at y=180 | `463 px`; at y=200 `478 px`; at y=220 `494 px` |
| straight black body at y=230..300 | about `496 px`; at y=300 x `267..762` |
| lower straight body | about `495 px` through y=1200 and y=1350 |
| lower taper | y=1380 `493 px`, y=1400 `471 px`, y=1410 `449 px`; the silver foot/rim then rolls inward to the bottom at y=1468 |
| outer top and bottom | top y `90`; bottom y `1468`; the silver top band occupies roughly y=90..155 and the silver lower band roughly y=1419..1468 |

Taking the strict bbox bottom as the datum, the derived world-space-friendly
fractions are: body diameter/H **0.359681**, body radius/H **0.179840**; the
straight body runs approximately from z/H `0.064` to `0.847`; the shoulder grows
to full width between z/H `0.905` and `0.847`; the top rim's broad outer width is
0.933 of the body width. The top and bottom silver spans are about 0.0479 H and
0.0363 H respectively. These are starting targets to compare against the
photograph, not a substitute for the camera check.

`measure_can_targets.py` also found about **10** broad local highlight candidates
across the visible front at y=225. This is the useful count for the shallow
longitudinal stamped/fluted reflection pattern; the channels must remain much
shallower than the can diameter.

### Label and artwork placement

The green upper-logo mask, using the channel-ratio threshold in
`analyze_reference.py`, is x `297..719`, y `269..939`: **423 x 671 px**. It is
0.852823 of the straight-body width and 0.486584 of the full visible height.
The padded, transparent cutout made from that exact region is
`scripts/monster_logo_cutout.png`; use it rather than
`monster_logo_crop_raw.png`, whose black cylindrical background is not
transparent. The white edge should remain visible around all three claws.

The other graphic bands, resolved by threshold scans in the interior of the
body, are:

| graphic | reference extent / placement |
|---|---|
| upper Chinese/plus band | glyphs y about `145..191`, inside the black collar below the silver rim |
| three-claw logo | green x `297..719`, y `269..939`; top/bottom z/H from the lower datum about `0.8695`/`0.3836` |
| `MONSTER` word | bright band y `1007..1124`, approximately x `280..750` |
| `ENERGY` word | green/white band x `325..716`, y `1140..1183` |
| lower white Chinese blocks | y `1249..1365`, one block on the lower left and one on the lower right |

The exact typeface is less reliable than these band positions, so use a close
condensed/display font or a flat image/decal; the letters must read as printed
ink, not solid extruded objects. The upper band contains white Chinese glyphs
with green plus signs. The lower left reads as a white quantity block including
`330` and the lower right is a white flavour/energy block. Keep their visible
parts following the cylinder toward the sides so the label is genuinely
wraparound rather than a front-only rectangular plate.

### Colour evidence

Robust samples from `sample_reference_colors.py` are sRGB starting targets, with
the usual allowance for the final light transport: far background medians are
about `[210, 209, 209]`, clean black label pixels `[4, 5, 7]`, green claws
`[112, 189, 6]`, green `ENERGY` `[137, 192, 8]`, white label pixels
`[219, 222, 223]`, top silver `[192, 192, 192]`, and lower silver
`[190, 188, 187]`. Preserve the relationships (near-black body, luminous green,
light printed ink, neutral metallic rims); do not make the black material an
unlit absolute black that loses all reflections.

## World-space starting proportions

Use a convenient total visible height `H = 4.0` world units with the underside of
the lower rim at Z=0. Set the maximum straight-body diameter to about
`0.359681 * H = 1.439` (radius about 0.720), and centre the rotational axis in
X/Y. A uniformly rescaled model is fine if it preserves the ratios above.

Make the exterior as a closed manufactured can. A useful outer profile is: a
small rounded lower roll rising from z/H=0 to about 0.036; the black body at
near-constant radius 0.1798 H from about z/H=0.064 through 0.847; a lower/upper
shoulder transition that visibly narrows to roughly 0.165 H radius around
z/H=0.934; and a top rolled rim whose outer radius is about 0.1679 H. Add extra
stations around both rolled rims and the shoulder so it does not become a
straight cone. The top is a shallow dark lid/recess under the silver lip, not an
open hole; do not add a prominent pull tab that is absent from this view.

## Toolkit

The builder's current manual covers ordinary viewport work and the `perceive`
helpers. The following calls are outside its detailed prompt or need their
specific contracts made explicit here.

**`meshgen.py` -- rotational can body and smoothing**

```python
import meshgen as mg

body = mg.spin_profile(profile, sides=64, name='CanBody',
                       location=(0, 0, 0), smooth=False)
mg.smooth_by_angle(body, degrees=...)
```

`spin_profile` takes ordered `(radius, z)` pairs, with radius in world units. It
does not close a profile for you: for a solid can the path should start at the
bottom axis, travel out and up the outer wall, and return to the top axis so the
ends are capped. It revolves about Z. `sides` is circumferential resolution;
choose enough that no polygon bands are visible at 1024 px. Use the same helper
for a separate lathed ring only if its profile is a complete annular/solid
section; otherwise standard Blender torus/mesh construction is fine. Apply
`smooth_by_angle` only after the profile is final so the body shades continuously
while the rolled lip and lid edges remain crisp.

**`reference.py` and `perceive.py` -- matched-view evidence**

```python
from reference import load_reference
from perceive import silhouette_vs_reference

load_reference('.../plans/Energy_can/reference.png',
               axis='FRONT', name='CanRef', display_size=...)
fit = silhouette_vs_reference(['CanBody', 'TopRim', 'BottomRim'],
                              ref_name='CanRef', label='can_silhouette',
                              axis='Z', samples=64, margin=0.04)
```

`load_reference` creates a temporary image empty and sets the viewport to the
requested orthographic direction. `silhouette_vs_reference` draws the evaluated
mesh outline onto the reference itself and returns stations in image-normalized
coordinates; for this vertical can pass `axis='Z'`. Use it for diagnosis, then
remove `CanRef` before the final scene. Always read the reference's own
1024 x 1536 dimensions when converting normalized output to pixels.

**`bake.py` -- stable UV/material/image proof**

```python
from bake import (unwrap, uv_stats, uv_layout_png, new_image, load_image,
                  save_image, image_stats, ensure_material)

mat = ensure_material('CanBody', 'CanLabel_Material')
# Use a rear vertical seam and a cylindrical projection/unwrap for the label;
# then use these helpers for evidence and image lifecycle.
stats = uv_stats('CanBody')
uv_layout_png('CanBody', '.../scripts/can_uv_layout.png', size=1024)
label_img = new_image('CanLabel_Color', size=2048,
                      colorspace='sRGB', fill=(0.004, 0.006, 0.009, 1))
logo_img = load_image('.../scripts/monster_logo_cutout.png',
                      colorspace='sRGB')
```

`ensure_material` clears stale material slots and leaves exactly one named
node-based material. `new_image` replaces a same-named image; `sRGB` is required
for this base-colour map. `load_image` reuses an external artwork image, and
`save_image` writes the intended datablock to PNG. `uv_stats` returns
`(islands, coverage, faces)` and `uv_layout_png` saves a human-inspectable map.
For this cylinder, a deliberate rear seam plus Blender's cylindrical projection
is preferable to SMART UV if SMART would split the front into many islands;
still record `uv_stats` and inspect the layout. `image_stats` returns RGB
mean/min/max and is the quick check that the active image is not still uniform
black. Connect the final image or the artwork/decal image explicitly to the
Principled Base Color/Alpha nodes rather than relying on a stale `.001` image.

**`paint.py` -- optional fine printed strokes**

```python
from paint import stroke_lines_preview, apply_paint_lines
stroke_lines_preview(strokes, label='can_print_preview')
# In the following action, after inspecting the preview:
apply_paint_lines('CanBody', 'CanLabel_Color', strokes,
                  label='can_print_apply', face_normal=..., normal_tolerance=0.9)
```

Each stroke has normalized `(u,v)` points with origin at the top left plus
`width`, `softness`, `strength`, `color`, and `blend` (`multiply` for dark ink or
`screen` for light/green ink). Preview is read-only and must happen in the exact
view used for apply; reuse the same stroke dictionaries in the next action.
Back-facing triangles are skipped, so a whole circumference cannot be painted
from one front view. Use this only for small separators/accents if text objects
or a composited UV image are not more suitable; do not try to redraw the
irregular Monster claws as a handful of guessed lines.

**`lighting.py` -- plain product presentation**

```python
import lighting as lt
lt.world_colour((...), strength=...)
lt.backdrop((...), width=..., height=..., distance=..., z=...)
lt.camera(target=(0, 0, 2.0), distance=..., azimuth=...,
          elevation=..., lens=...)
lt.key_light(target=(0, 0, 2.0), distance=..., azimuth=...,
             elevation=..., energy=..., colour=(1, 1, 1), size=...)
lt.render('.../scripts/final_Energy_can.png', 1024, 1536,
          samples=..., engine=...)
```

`world_colour`, `backdrop`, `camera`, `key_light`, and `render` create the simple
neutral studio setup and a real saved render. Keep the backdrop in the measured
grey family, use one broad soft key (a restrained fill is fine), and tune the
perspective camera from the projected silhouette rather than from a guessed lens.

## What goes wrong here

- **The visible bounding box is not a rectangular modelling target.** The
  `496 x 1379` box contains a narrow top rim, shoulder, straight body, and lower
  roll. Match the profile rows and camera; do not make a cuboid or a flat image
  plane fill the box.
- **`spin_profile` takes radius, not diameter, and does not close the path.** A
  radius/diameter mix-up makes every ring twice too wide. A profile that omits
  its axis endpoints leaves an open or oddly capped can.
- **The camera is part of the silhouette.** An orthographic camera or a guessed
  front view loses the visible top rim and changes the shoulder and lower-roll
  proportions. Fit the perspective view before moving graphics to compensate.
- **The silver rims are rolled lips, not silver discs.** Keep the top outer span
  about 0.933 of the body width, preserve the black recessed lid, and keep the
  lower roll shallow. A wide flat silver cap or a large pull tab becomes the
  dominant wrong feature.
- **The vertical can reflections are subtle.** The roughly ten front highlight
  bands at the shoulder are shallow stamped/fluted cues, not deep grooves or
  evenly spaced black ribs running over the whole label. Use lighting and gentle
  radial relief together.
- **A raw crop is not a wraparound label.** `monster_logo_crop_raw.png` contains
  black can pixels and vertical reflections. Use the transparent
  `monster_logo_cutout.png`, curve/project it onto the front of the label, and
  put the UV seam at the rear. Do not leave a rectangular black decal or a flat
  front card intersecting the cylinder.
- **Raw `u,v` pixels are not world X/Z.** Match the final camera and compare
  projected extents. The logo target is x `297..719`, y `269..939` in the
  reference image, not a world-space rectangle with those numbers as coordinates.
- **Printed artwork must stay flat.** `MONSTER`, `ENERGY`, Chinese lines, and the
  logo are ink/decal/image detail. Raised text, thick white extrusions, and
  opaque black label plaques destroy the reference's continuous curved surface.
- **Painting is view-dependent.** `apply_paint_lines` only affects front-facing
  triangles in its current view. Preview first, apply from the same camera, and
  use a separate side view for any detail that truly has to continue around the
  wrap.
- **Near-black is not invisible black.** Preserve soft vertical reflections and
  a faint readable edge on the label. Pure emissionless black under a flat
  light loses the can; glossy plastic or a silver body loses the label hierarchy.
- **Temporary evidence must not ship.** Remove `CanRef`, grid overlays, crop
  planes, cutters, duplicate bodies, and stale material/image datablocks before
  the final save.

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

## Step 1 -- closed can body, rolled silhouette, and matched camera

1. Clear stale build objects and establish a single Z-up can datum: underside of
   the lower rim at Z=0, axis centred in X/Y, and total starting height H=4.0.
   Keep stable names such as `CanBody`, `TopRim`, `BottomRim`, `TopLid`, and
   `CanRef` for diagnosis.
2. Build the closed outer can body in world space from a revolved profile. Include
   the nearly constant straight body, the short lower taper, the narrowing upper
   shoulder/collar, and enough profile stations around each transition that the
   silhouette is curved rather than a stack of cones. It is acceptable for the
   first clay blockout to use simple provisional rims, but it must already read
   as one tall slim can.
3. Add shallow separate rolled top and bottom rim geometry and a recessed dark
   lid only far enough to make the top/bottom contour visible. Fit the perspective
   camera from a slightly elevated, nearly frontal product angle. Load `reference.png`
   as `CanRef`, use the outline comparison, and tune aim, distance, lens, and
   elevation until the object occupies the same portrait framing.
4. Preview a neutral clay render and correct the world profile/camera now. Do not
   begin the artwork while the shoulder or lower roll is still being compensated
   by camera placement.

**Review:**

**Important**

- **Measure this blockout against the REFERENCE first, not against H=4.0 or the
  profile table.** Project the combined `CanBody`/rim silhouette onto the saved
  reference and report the actual bbox; target strict x `267..762`, y `90..1468`,
  width/height **0.359681**, and axis near `u=0.500`. A correctly scaled can with
  the wrong camera must fail this check.
- **The projected width changes at the measured transitions.** In the matched
  1024 x 1536 view, quote widths near y=140 (about **463 px**), y=180 (**463**),
  y=200 (**478**), y=220 (**494**), y=300 (**496**), and y=1380 (**493**).
  The top must narrow before the shoulder, the middle must be almost straight,
  and the lower body must begin its roll rather than ending as a square tube.
- **The full can is vertically framed like the REFERENCE.** The top outer rim
  reaches about y=`90`, the bottom outer rim about y=`1468`, and the visible top
  surface is only a shallow elevated ellipse. Compare this against the photo,
  not only against the model's own Z endpoints.

**Other**

- The body/rims are closed meshes with no visible open end, floating duplicate, or
  geometry below the Z=0 datum.
- The working camera is perspective and shows a little top rim without a strong
  three-quarter yaw; the axis is vertical in the image.
- `CanRef` and any clay guides are clearly temporary and are not part of the final
  presentation collection.

## Step 2 -- rolled metal, black label surface, and restrained can relief

1. Refine the top and bottom rings as thin rolled aluminium lips with a slight
   rounded cross-section and a narrow highlight. The top ring should span about
   463 px where broad in the reference, while the body below reaches about 496 px;
   retain the dark recessed top just inside it. The lower silver ring should occupy
   only the bottom ~50 px of the reference-height equivalent.
2. Give the main body a continuous near-black wraparound label/surface and the
   rims a neutral metallic material. Use high enough roughness to keep the label
   from becoming a mirror, but leave broad soft reflections that reveal the
   cylinder. Use the sampled sRGB relationships as starting colour targets, not
   as an excuse to ignore the final light.
3. Add the can's shallow longitudinal manufactured relief. Aim for roughly ten
   broad highlight bands across the visible front at the shoulder region (the
   diagnostic scan at y=225 found ten candidates), with only a small radial
   amplitude and soft transitions. Let the lower label remain visually clean;
   the relief must not slice the green logo into deep grooves.
4. Smooth the body without melting the rolled lips. Inspect a close clay/material
   crop of the shoulder, rim, and lower roll before proceeding to the label
   graphics.

**Review:**

**Important**

- **Compare the rims and shoulder to the REFERENCE crop first.** Measure the
  rendered top-rim width at the broad y=140-equivalent level and the straight-body
  width; target about **463 px**, **496 px**, and a rim/body ratio near **0.933**.
  Check the top silver band is about 0.048 H and the lower silver band about
  0.036 H, rather than accepting a self-consistent torus size.
- **Compare material patches against the external photo.** Sample clean render
  pixels and report them beside the reference targets: black near `[4,5,7]`,
  top/lower silver near `[192,192,192]` / `[190,188,187]`, and grey background
  near `[210,209,209]`. The can should retain readable soft highlights; an
  unlit black void, chrome-black plastic, or all-silver body fails.
- **The relief is shallow and countable in a close shoulder crop.** Count about
  ten broad front highlight lanes around the shoulder and compare their depth to
  the can diameter: they should be 1--3 px highlight cues at reference scale,
  not deep channels, hard polygon facets, or a repeated rib texture covering the
  label graphics.

**Other**

- The top is a dark recessed lid under the silver lip; no large pull tab or bright
  interior hole dominates this camera view.
- The metal rings have smooth/controlled shading and no obvious faceted stepping,
  z-fighting, or seam where they meet the black body.
- The main body remains one continuous cylindrical label surface with a stable
  material name; no temporary profile, light card, or clay object is visible.

## Step 3 -- cylindrical UV label and printed Monster artwork

1. Prepare a deliberate rear vertical UV seam and a cylindrical unwrap for the
   full wraparound body. Create one explicit sRGB `CanLabel_Color` image with a
   near-black base, or use explicitly named curved image decals while preserving
   the same UV/image proof. Save `can_uv_layout.png`, record `uv_stats`, and keep
   sufficient empty margin that the artwork cannot bleed across the seam or rim.
2. Load `scripts/monster_logo_cutout.png` as sRGB and place it on the curved front
   label. Use the final camera to scale/position it so the projected green mask is
   x `297..719`, y `269..939` in the 1024 x 1536 reference; this is 0.853 of the
   body width and 0.487 of the full visible height. Keep the thin light outline,
   all three irregular claw shapes, and the narrow pointed ends. Composite it into
   the UV image or use a gently curved alpha decal, never a flat rectangular card.
3. Add the lower printed word marks as flat image/text treatment: the white
   stylized `MONSTER` band at y `1007..1124`, the green/white `ENERGY` band at
   x about `325..716`, y `1140..1183`, and the two small white Chinese blocks at
   y `1249..1365`. Use a condensed/display treatment with a light outline where
   visible. Keep the black label visible between the logo, word marks, and lower
   blocks; do not fill any of these bands with raised solid geometry.
4. Add the upper white Chinese/green-plus band inside y about `145..191`, below
   the silver lip, and continue the lower side text around the cylinder enough
   that an oblique orbit reads as a wraparound label. Put any label seam at the
   rear. If screen-space strokes are used for separators, follow the preview then
   apply contract in the Toolkit and use a separate view for side-facing details.
5. Preview the exact product camera and a close 2x crop of the logo/word bands.
   Correct alpha halos, texture stretching, z-fighting, line weight, and any
   perspective drift before moving to the final lighting.

**Review:**

**Important**

- **Measure the final artwork against the REFERENCE first, not against a UV
  rectangle.** At 1024 x 1536, threshold the render's green logo and report its
  bbox; target x `297..719`, y `269..939`, width/body about **0.853**, height/full
  height about **0.487**. Also report the `MONSTER` band near y `1007..1124` and
  the `ENERGY` band near y `1140..1183`. A neatly aligned but wrongly scaled
  logo fails this external check.
- **The logo is the exact three-claw silhouette with a transparent surround.** In
  a 2x crop compare the rendered graphic with `monster_logo_cutout.png`: green
  areas should be near the sampled `[112,189,6]`, the narrow white edge must remain,
  and no black rectangular crop, opaque alpha box, or missing claw may be visible.
- **The artwork reads as ink on a continuous curved black label.** Inspect front
  and oblique crops: the white/green marks stay flat, the black gaps remain open,
  the top band is below the rim, and the lower text follows the circumference
  without a front-card edge. Raised plaques, floating text, or a front-only decal
  fail even if the full frame looks close.

**Other**

- `uv_stats` reports all mesh faces accounted for, nonzero coverage, and a saved
  inspectable UV layout; the cylindrical front is not split into unusable random
  islands.
- `CanLabel_Color`/artwork nodes are the intended active sRGB images, and
  `image_stats` is not the initial uniform fill. There are no accidental `.001`
  images or materials receiving the logo pass.
- No graphic bleeds onto the silver rims, no alpha fringe reveals the crop's
  original ribbed background, and no decal visibly z-fights with the can.

## Step 4 -- simple studio render, external comparison, and cleanup

1. Keep the matched perspective camera from Step 1. Use a plain matte grey
   backdrop in the reference's `[210,209,209]` family, one broad soft key, and a
   restrained fill/world level that reveals the black label and silver rolls
   without adding a room or fancy lighting setup.
2. Render a clean **1024 x 1536** product image to
   `scripts/final_Energy_can.png`. Save the active label image, UV layout, and
   any reports beside the diagnostic scripts. Do not render grids, landmarks, or
   the reference empty into this final file.
3. Re-run the saved segmentation and graphic-band measurements on the final
   render, comparing its bbox, profile widths, logo bbox, text bands, and sampled
   colours against the reference targets above. If the silhouette misses, adjust
   camera/profile; do not move the logo away from its measured label placement to
   disguise a framing error.
4. Orbit once to a modest rear/side view to check that the label wraps, the rim
   geometry is closed, and no hidden duplicate, open lid, crop plane, or ground
   intersection is present. Restore the product camera, remove `CanRef` and all
   diagnostics, and save the clean scene if the harness expects a blend file.

**Review:**

**Important**

- **Measure the saved final render against `reference.png` before judging polish.**
  Report the strict subject bbox and ratio; target x `267..762`, y `90..1468`,
  496 x 1379 px, width/height **0.359681**, plus the shoulder/body row widths
  (**463** at the broad rim, **478** at y=200, **496** through the middle). This
  reference-anchored check catches a wrong camera that all self-referential
  object dimensions would miss.
- **Re-measure the final graphics in the reference frame.** The green claw bbox
  should remain near x `297..719`, y `269..939`; `MONSTER` should occupy about
  y `1007..1124`; `ENERGY` about y `1140..1183`; lower white blocks about
  y `1249..1365`. Quote the measured render values and explain any deliberate
  tolerance rather than saying only that the can is recognizable.
- **The final product shot preserves the reference's material hierarchy.** Compare
  clean pixels against near-black `[4,5,7]`, green `[112,189,6]`, light print
  `[219,222,223]`, neutral silver `[192,192,192]`, and background `[210,209,209]`.
  The can must read as a tall glossy/matte black label with controlled reflections,
  luminous green printed art, and thin rolled aluminium edges—not as a silhouette
  cutout, mirror, or grey unlabelled tube.

**Other**

- Final resolution is exactly 1024 x 1536; `final_Energy_can.png`, the active
  label PNG, and `can_uv_layout.png` are saved and inspectable.
- The clean render contains one can, one neutral studio presentation, and no
  reference image, grid, landmark, crop plane, duplicate, or helper geometry.
- The rear/side orbit shows no open boundary, inverted rim, floating decal,
  z-fighting, ground penetration, or visible UV seam on the judged front.
