---
name: camera-landmark-fitting
description: Read this before fitting a perspective camera from measured image corners or trusting a projection residual.
evidence: 02_cardboard_box_run_001 step_001; 19_human_thinker_run_001 step_002
---

# Camera landmark fitting

When a perspective camera is fit from measured image landmarks, the input to
`to_track_quat('-Z', 'Y')` is the **forward direction**, never the camera
location plus that direction. Passing an absolute point makes a plausible
quaternion that aims somewhere else.

Use this order:

1. Keep the model dimensions fixed and express landmarks as world points plus
   top-left-origin image pixels.
2. Set the pose from a normalized world direction, then verify the evaluated
   camera local `-Z` axis agrees with it.
3. Zero the lens shifts and measure each axis' pixel response through
   `world_to_camera_view`; solve the offset from that measured sign and scale.
   Do not import a generic sensor-shift formula.
4. Report both coordinate RMS (`sum(dx²+dy²)/(2N)`) and corner Euclidean RMS
   (`sum(dx²+dy²)/N`). They differ by √2; calling the first one “corner RMS”
   hid the cardboard box's 14.5 px failure.

The direct camera projection report and a real active-camera render are the
proof. A viewport screenshot can remain in an old framing even when the
camera data is correct.

## When the landmarks belong to a posed assembly

A 2-D pose landmark is not a world-space joint. Choose the comparison camera,
render resolution, lens, and image crop once before fitting the bones, then
project every correction through that same camera. Do not alternate a pose edit
with a new azimuth/zoom/framing sweep: the residuals are no longer comparable,
and a camera change can make a generic squat look closer without moving the
pose toward the reference.

Keep the objectives separate: use the fixed-camera projection residual to place
joints in the image, and use world-space distances/bounds to prove elbow, hand,
foot, and support contacts. A projected overlap is evidence of image placement,
not physical contact.

## Freeze the comparison camera while correcting a model landmark

A geometry landmark and the camera target are separate unknowns. Once azimuth,
elevation, lens, shift, and target are chosen for a reference projection, freeze
them while moving the model to a measured landmark; report the rail/frame and
base transition separately. A coupled expression such as `target_z = rail_z * k`
can make a wrong rail appear to pass because the camera moves with it. Finish
with a fresh active-camera projection/render, not only a viewport.

Evidence: `mem/12_newtons_cradle_run_001/steps/step_001/handover.md` and
`mem/12_newtons_cradle_run_001/steps/step_001/review/round_01/review.txt`.
