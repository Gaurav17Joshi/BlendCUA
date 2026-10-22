---
name: reference-mask-audits
description: Read this when traced or branched reference linework matches its bbox but its internal occupied shape may still be wrong.
evidence: 06_iron_gate_run_001 step_002 and step_004; 07_monstera_pot_run_001 step_003 and step_004
---

# Reference mask audits

A landmark, bbox, or projected outline can pass while a branched ornament still
has the wrong branch order, loop size, or bottom return. Before handing off a
traced linework pass, compare the unannotated built occupancy against the source
in the same reference pixel frame, split into feature ROIs. Use IoU together
with a few row/column run queries: IoU says how much of the shape agrees, while
runs show exactly where a branch is too wide, missing, or merged. Keep the
threshold explicit and inspect precision versus recall; a low score is evidence
to fix the owning path, not permission to globally thicken or shift every
stroke.

`perceive.silhouette_vs_reference` remains useful for envelope stations. It is
not a substitute for this check when the criterion is the internal rhythm of
open or branching strokes.

When foreground roles have different hues or overlap a neutral backdrop, define
those roles with HSV and channel-ratio predicates and audit them separately;
the luminance-only mask can answer occupancy but not leaf/pot/trunk/soil role
membership. `reference_audit.audit_render` packages those role masks, row runs,
patch medians, and same-coordinate crops in one repeatable report.
