---
name: build-from-traced-outline
description: Read this when a step hands you an outline polygon read from the reference (plans/<task>/scripts/*.json from trace-the-reference), or when you are about to build a curved part "by feel" from a photo. The mesh is the polygon extruded, placed by measured angles and scale; the check is the render's outline aligned on landmarks over the photo, with a residual per row; the material is scaled onto the photo's medians.
evidence: mem/06_tablecloth_drape_run_003 steps/step_001/05_build_legs.py + 08_collar.py, steps/step_002/02..04 (2026-09-12): traced legs at 8/11 px mean edge residual, wood median 93/54/39 -> 76/45/41 against the photo's 67/36/27
---

# Build from the polygon, check on the photo

Scope: a flat part whose silhouette in one view is its shape (a pedestal leg, a bracket, a
plate). A body or a limb with a round, changing cross-section is not built by extruding
its outline; see `blueprint-traced-loft` for a one-axis mass and the plan's per-part
decision for the rest.

## If there is no polygon, make one before building

An empty `scripts/` folder in a construction step is the failure, not a detail. Run
`outline_trace` yourself (mask, row table, landmarks, `boundary_polygon`, `image_to_plane`,
`draw_polygon`) and save the JSON and the overlay picture in this step's `scripts/`. Twenty
minutes of image reading beats five redos of a typed path. Say in the handover which
landmarks you chose and why.

## Building

- `outline_trace.extrude_profile(name, [(r*L, z*L) ...], thickness)`: the closed outline as
  one n-gon face, extruded to the measured thickness, bevelled, smooth-shaded with sharp
  marks above 60 deg. Use the evenly resampled polygon (~5 px spacing), not the
  Douglas-Peucker one: long straight runs between corners shade in visible bands.
- **Scale once.** L in scene units comes from something already fixed in the scene (the old
  feet's radial reach, the tabletop, a datum the checker accepted), not from a fresh guess.
- **Bury the root.** The straight cut at the neck is pushed inward (`root_x`) so the part
  overlaps the member it grows from; no boolean, no visible seam. If the neighbour is fatter
  than the photo's neck (run_001's column ended in an onion of radius 0.6 where the photo has
  a neck of 0.09 L), compress the neighbour there so the traced roots own that mass — the
  photo says whose mass it is.
- **Place by measured angles**: `place_radial(ob, angle)` at the spacing the photo forced on
  the trace (three legs: -90 toward the camera, +30, +150).
- Toes on the floor: z = 0 of the profile is the floor row you traced from; add the scene's
  floor offset, do not leave a hover for the reviewer to find.

## Checking — the outline back on the photo

Render through the scene camera (EEVEE is enough for a mask), make the same material mask
of the render, `align_by_landmarks` on the axis, the floor row and the toe span, then
`mask_residuals` over the rows of the part. Report mean and worst per row and say where the
worst is. Expected: the traced members land within ~10 px on 1024 px; what is left is the
camera (run_001's camera is closer and steeper than the photo's, so the near leg draws
longer) and merged-root regions the trace could not separate. Never align on bounding boxes:
a cloth or a shadow changes the box without changing the part.

## Tone — the same mask, both pictures

`tone_stats(photo, mask)` and `tone_stats(render, mask)`: median RGB, value, highlight
fraction, p95 luminance. Move the Principled base colour by `base_colour_scale` (per
channel `(photo/render)^2.2`), roughness by the highlight fraction and p95 (a lacquer: sharp
highlights, 5% of pixels far above the median). Re-render with Cycles (EEVEE reads coat and
specular differently) and measure again. A clear coat of 0.6 turned the wood grey by
mirroring the grey backdrop; 0.3 kept the red-brown. Two passes are normal; log both.

## Harness note

Inside the Blender server, after `checkpoint.load_step` (`wm.open_mainfile`) the big UI area
can be an IMAGE_EDITOR (a final-render step left it there) and `bpy.context.screen` is None
for that tick. `mem/06_tablecloth_drape_run_003/scripts/tryout_view.py` shows the fix: find the window
through the window manager, turn the area back into a VIEW_3D under a window override, and
render viewport shots with that override. Camera renders (`bpy.ops.render.render`) need
none of that.
