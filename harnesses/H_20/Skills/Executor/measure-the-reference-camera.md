---
name: measure-the-reference-camera
description: Read this before placing anything by matching a pixel of the reference photo, or before reading heights off a perspective photo of a round object. Measure the reference camera once from geometry (a many-point ellipse on the sharpest circular edge, cross-checked), convert every reference feature into the object's own frame (azimuth, height, radius on the part), build there with no camera involved, and set the camera last. Covers why a pixel solve through the run's own camera puts things in the wrong place, why the lowest pixel of a round base is not the base, square pixels, hole-filled centroids, and registering renders on projected known points.
evidence: mem/16_chocolate_cup_decor_run_001 (loop run, 5/5 steps PASS, every placement solved through its own 18° camera with pixel aspect 1.06) against mem/16_chocolate_cup_decor_run_002 (hand rebuild, 2026-09-16; steps/step_001/scripts/measure_reference_frame.py, reference_frame.json, steps/step_002/scripts/measure_face.py, face_handle_audit.json); write-up in blends/16_chocolate_cup_decor_run_002/LESSONS.md A1-A3, B1, B2, B4
---

# Measure the reference camera, build in the object's frame, camera last

## The failure this prevents

The loop's chocolate cup placed the face marks, the drizzle paths, the marshmallows and
the candy cane by Newton-solving or ray-casting each one until it landed on the right
pixel of `reference.png` **through the run's own camera**. Every step passed its own
review, and the model was wrong from every other angle:

- A pixel fixes two of three coordinates. Depth was left free and picked by hand
  (`y = 0.02`, `y = 0.58`), so marshmallows sat 34-73% inside the cream.
- The run's camera was not the reference camera (18° elevation against 15.54°, and a
  1.06 pixel aspect). Matching a pixel through the wrong projection puts the feature in
  the wrong place *on the model*: the face came out 27° round from where it belongs
  (119° from the handle against 92°) and too high (eye height 0.893 of the rim against
  0.849).

**Rule: never solve an object's 3-D position through a camera to match a pixel.**

## The order that works

1. **Measure the reference camera once, from geometry** (below). Write it to one file
   (`reference_frame.json`) that every later action reads.
2. **Convert each reference feature into the object's frame**: azimuth, height and
   radius on the part. On a surface of revolution the depth comes from the known surface,
   so a feature is two equations in two unknowns, e.g. `x = axis + R·r(z)·sin ψ` and
   `row = base − R·(z·cosθ − r·cosψ·sinθ)`.
3. **Build in that frame with no camera involved.**
4. **Place the camera last**, at the measured elevation, for presentation only.

Result on the cup: face→handle 92.00°, eye separation 34.66° (target 34.7°), eye height
0.849, every prop target within tolerance.

## Measuring the elevation

- **Fit an ellipse to the sharpest in-focus circular edge, with many points.** The cup's
  rim inner lip, 18 hand-read points, 0.92 px residual → 15.54°.
- **Cross-check with every other circular feature**, and record the ones that disagree
  instead of dropping them. On the cup: foot ellipse 15.73° (agrees but blurry, ±2-3°),
  back rim 15.48° (agrees, assumes the roll height), eye pair 13.91° (disagrees; the most
  sensitive method, 1 px = 0.77°, and it assumes both eyes were drawn at one height).
- **Look for an independent check on the fit itself.** The lip ellipse's fitted radius
  (0.927 R) matched the known inner edge of the rim roll (0.93).
- **If an automatic edge scan picks up clutter, hand-read the points on a gridded 4×
  crop.** White sprinkles on the dark drink made stronger edges than the lip.
- **Be suspicious of agreement that is too perfect.** Unfilled eye blobs (a black disc
  with a white highlight cut out) shifted each centroid ~3 px and gave 15.61°, which
  looked like perfect agreement. With holes filled it is 13.91°. Fill holes before a
  centroid (`binary_fill_holes`), and pick features as the N *largest* blobs, not by an
  area threshold: after filling, the smile crossed the threshold and was taken as an eye.

## Heights from a photo looking down

On a camera looking down, the **lowest pixel of a round base is the front of the base
ellipse**, R·sin(elevation) below the base plane. Mapping it to z = 0 made the cup 7% too
tall (height/diameter 0.755 against 0.705; reproducing the mistake gives 0.758).

**Only silhouette points at zero depth map straight to heights.** Put a plane's height on
the row of its ellipse's left and right tips, never on its lowest or highest pixel.

## Square pixels

The Blender server's default scene has `render.pixel_aspect_y = 1.06`, and nothing in
`Tool_scripts` resets it. Every render comes out 6% short, and `world_to_camera_view`
honours it, so any projection-based solve or audit is fitted to a squashed image. On the
cup it first showed as a silhouette audit reading the lower belly 30-60 px too narrow
while the profile fit itself was at 0.6 px.

- Set `scene.render.pixel_aspect_x = pixel_aspect_y = 1.0` in the **first build action**,
  so every checkpoint carries it.
- Assert it again in any audit that renders or projects.

## Registering a render against the reference

Do not register on an extreme of a shallow curve. The audit first found the model's rim
equator as "the widest row"; the wall runs from r 0.995 to 1.0 over ~40 rows, and a few
rows of slip showed as 30 px errors on the sloped belly. **Project known world points**
(the equator, the axis) through the audit camera with `world_to_camera_view` and
register on those.

## Related

- `camera-landmark-fitting.md`: fitting a camera from image corners, and the
  `to_track_quat` and RMS traps.
- `lathe-profile-from-silhouette.md`: the profile of a round object read through this
  camera.
- `seating-by-contact.md`: placing things *on* the model once they are in its frame.
