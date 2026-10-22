---
name: material-target-audits
description: Read this before tuning rendered materials against sampled reference colours.
evidence: 05_energy_can_run_001 step_002; 07_monstera_pot_run_001 step_004; 08_desk_chair_run_001 step_002 and step_005; 09_skull_run_001 step_005; 14_sneaker_run_001 steps 3, 4, and 5; 16_hourglass_run_001 step_004
---

# Audit material roles on a fresh render before handoff

When the reference gives numeric colour targets, tune against a fresh
active-camera render and sample each material role separately. Use clean
interior pixels for the dark label, and independent patches for the top and
bottom metal; a broad band median can hide an overbright highlight on one part
and an underexposed shadow on another. Compare built medians and channel deltas
to the same reference patches after every material correction, while checking
that the lighting cue and background remain readable.

Do not infer the rendered result from Principled defaults, node colours, or a
previous render. Save one repeatable report with the crop coordinates, target
medians, built medians, and deltas, then hand off only after the report explains
any remaining tolerance. This catches material-only review failures before they
consume a correction round.

When roles have a required ordering, record that ordering as a separate invariant
beside the per-patch deltas. Test every related patch on the same final render and
assert the intended pairwise relations—such as crown brighter than jaw, jaw
brighter than teeth, and a far recess brighter than a near recess—rather than
treating individually plausible medians as sufficient. A reversed relation is a
material failure even when every swatch is warm.

An isolated material preview is not final proof: placement changes alter which
parts fall into key-light and desk shadows. After the combined presentation
camera, light, or object placement changes, repeat the same role patches on a
fresh combined render before handoff; do not carry isolated medians forward.

For a multicolour subject, use `reference_audit.audit_render` with explicit
role specs (HSV/channel ratios), per-role patches or ROIs, and same-coordinate
comparison crops. `compare_image_masks` is luminance-only; it is useful for a
dark occupancy check but cannot reliably separate a bright leaf, terracotta,
trunk, soil, and backdrop into material roles.

## 5. Calibrate shared body and pip roles in the final camera

When a reference supplies body/pip colour targets, sample role-masked pixels from
the same final-camera render after the key, world, exposure, and camera are in
their actual presentation state. For a domino-like subject, mask the central body
face and the pip interiors independently, excluding bevels, highlights, shadows,
floor, and neighbouring roles.

Record the reference median, built median, and per-channel delta for every role in
a repeatable audit; node/base colours are inputs, not proof. Repeat the audit after
any presentation-light or exposure change, and do not pass clipped pips or lifted
dark faces as a merely qualitative match. The fresh calibrated render must be the
one handed to the reviewer.

Evidence: `mem/13_domino_cascade_run_001/steps/step_001/01_floor_materials.py`,
which shows the hand-picked body and pip base values that were treated as if they
were rendered results.

## 6. Calibrate multi-role desk wood on the combined hero

For a multi-role desk, an isolated material preview is provisional. After the
final presentation light, camera, or placement is in its actual state, sample
the top, drawer fronts, side panel, and rear panel on the combined hero. Adjust
the linear ramps from those rendered deltas, preserve the intended light-to-dark
role ordering, and hand off only the render whose per-role medians and ordering
are recorded in the audit.

Evidence: `mem/05_desk_chair_run_001/steps/step_005/17_final_handover_dump.py`.

## When single patches keep disagreeing, use region means

Per-role patches are the audit; they are a poor calibration target when a patch can land
on a decal, a highlight, an occluding neighbour or a clipped pixel. The chocolate cup's
three patch-driven calibrations all converged and still rendered grey or lavender. For
calibrating, use `tone-calibration-region-means.md`: the same large 3-D regions in both
images, visibility and clipping masks, means in linear light under soft lighting.
