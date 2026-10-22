---
name: projected-overlap-is-not-clearance
description: Read this when separate objects must overlap in the camera view but remain physically separate.
evidence: 08_desk_chair_run_001 step_005; 16_hourglass_run_001 step_003
---

# Projected overlap is not physical clearance

A 2-D camera overlap says where two objects appear in the image; it does not
say that their evaluated 3-D surfaces are allowed to intersect. When a reference
needs one object visibly in front of another, keep two checks separate:

1. Project evaluated vertices through the final camera to verify the requested
   image anchors, occlusion, and silhouette overlap.
2. At the same transforms, build an evaluated world-space clearance/intersection
   check for the intended object pairs (a BVH for surface overlap is the useful
   test), and reject a pose that fails it.

Run both checks before saving a placement and again after any root, camera, or
child correction. Do not use a successful 2-D overlap to justify a hidden
collision, and do not move the camera or hide geometry just to make the collision
unreadable in the render.

The same split applies to contents inside a closed vessel: a raw reference mask
can be wider than the physically available inner cavity. Measure the interpolated
inner wall and find the widest contained profile before widening a mass; if the
raw target is infeasible, preserve positive clearance and report the residual
instead of repeating wall-crossing edits. If a centered detail is hidden by an
opaque foreground object, isolate-render it to prove the geometry and use a
controlled presentation cue rather than moving it toward the wall.

## Final-camera candidate search after a handover change

When a final handover changes the camera or resolves a collision, recompute the
projected seat, back, and base anchors under that actual final camera before
choosing the pose. For each root/yaw candidate, measure the required image
overlap and run the evaluated BVH clearance test against every intended
obstacle; accept only a candidate that satisfies both the projected target and
positive physical clearance. Persist the accepted root, any child correction,
camera, hero render, and audit as one state. Never restore a pose selected under
an earlier camera when its final seat bounding box misses the overlap target.

Evidence: `mem/05_desk_chair_run_001/steps/step_005/16_pose_clearance_matrix.py`.
