---
name: ik-landmark-calibration
description: Read this when a rigid IK chain must match measured joint landmarks or a pole search keeps returning a different bend.
evidence: 10_anglepoise_repose_run_001 step_002 and step_003
---

# Calibrate measured IK from a feasible seed

A measured target can be kinematically reachable while Blender's iterative IK
solver keeps returning the wrong elbow branch. Before broadening a pole grid,
prove the request is feasible: mute IK, reset the pose, author the chain directly
through the measured landmarks, and record the endpoint errors. Then evaluate
every pole/angle candidate from that same seed. An in-place sweep is not a fair
comparison because the solver may retain the previous branch; signed angle ranges
also matter because a nominal `0..360` sweep can repeat a clamped endpoint rather
than test the opposite bend.

Keep the mechanical objectives separate: score the measured joint positions first,
apply front-side or other pole-side rules explicitly, and use carried-part
orientation as a secondary selection or a later bone-frame audit. If the joints
fit but a rigid child is tilted, inspect and correct the owning non-IK bone's roll;
do not rotate the child mesh to conceal a rig-frame error.
