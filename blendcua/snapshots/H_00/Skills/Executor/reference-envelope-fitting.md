---
name: reference-envelope-fitting
description: Read this when a profile or final camera must match a measured silhouette envelope without changing the model.
evidence: 05_energy_can_run_001 step_001; 07_monstera_pot_run_001 step_001; 08_desk_chair_run_001 step_005; 09_skull_run_001 step_001; 11_umbrella_run_001 step_004; 12_tablecloth_drape_run_001 steps_001 and 003; 14_sneaker_run_001 steps 1 and 5; 16_hourglass_run_001 step_004; 18_thors_hammer_run_001 step_004; 20_low_poly_dog_run_001 step_003
---

# Fit the reference envelope before refining the surface

Keep the authored mesh fixed while calibrating a product camera. Measure the
**evaluated** world-space vertices of every part that contributes to the
silhouette, choose the intended perspective distance/elevation, and fit the
continuous image envelope in one pass with `projection.fit_envelope`. Let the
helper measure Blender's actual lens-shift response; do not hand-derive a
portrait sensor formula or move the model to hide a framing error.

A bbox fit solves scale and frame centre, not the acceptable amount of
perspective distortion. If rims, shoulders, or other parts sit at different
depths, choose a sufficiently far distance first and report the resulting
row/profile residuals. For a composition with several separate parts, keep
named groups and compare each evaluated group envelope; a union bbox can hide
a back that is too far left while the seat or radial base looks correct. Use
`projection.projected_group_bounds` for that read-only per-group report while
sweeping pose, rather than fitting one part and compensating with child moves.
For an orthographic judged camera tied to an image Empty, do not keep refitting
the box: rasterize the evaluated mesh with `reference_audit.audit_projected_mesh`,
keep the reference row probes, and correct the owning part when the profile
disagrees despite a close bbox. Only after the envelope is stable should profile
or material work begin. Finish with a fresh active-camera render, because a
viewport fit is not proof of the camera render.

When adding an attached part to an already-passing profile, the old core's
silhouette is not the new assembly's envelope. Treat the union and each new
part as separate constraints: probe the decisive source rows with interpolated
silhouette edges (not only binned stations or endpoint landmarks), identify
which part owns any excess span, and correct that part before moving on. In
`reference_audit.audit_projected_mesh`, `edge_rows`, `edge_columns`,
`landmarks`, and `groups` keep those measurements in one source frame.

When a component is constrained by both endpoint landmarks and a full
silhouette envelope, treat those as separate measurements. For a station-based
part, measure endpoint ring centroids and the all-vertex evaluated envelope
independently. Do not lengthen the part by moving the endpoint centres: that
can satisfy the span while breaking the landmarks. Put the missing extent into
an explicit cross-section/end-cut parameter that leaves the measured centres
fixed, then remeasure endpoint errors, axial span, and cross span after the
replacement.

A source-space or viewport envelope is still not the final-render envelope. For
a shallow canopy or any subject with parts at different depths, render a cheap
preview from the actual presentation camera at the final aspect and measure the
relevant material-role mask separately from the whole object. A modest yaw or
pitch can compress the canopy's projected depth and turn a correct near-front
ratio into a visibly narrow render; whole-object margins can hide that failure.
If the review names a rendered ratio, treat it as an output target: use the
measured residual to choose a near-front pose or a deliberate depth correction,
then repeat the same mask measurement before the expensive final render. Do not
compensate with camera-object scale or guessed pixel-aspect hacks: use
`fit_envelope(..., fit_width=True)` to solve the measured width and lens shift
for the chosen pose, then verify the same settings with a real render.

For an animated assembly, a margin-only sequence fit is not an exact reference
fit. Evaluate the selected frames as one envelope, fit one declared dimension,
centre the result from the installed camera's measured shift response, and choose
any perspective candidate by its residual on the other dimension. The general
`lighting.fit_camera_to_target_sequence` helper packages that solve; verify its
reported target bbox again at the final render resolution.

The returned fit report's final envelope is `bbox_px`; `final_bbox_px` is not
part of the contract. If an earlier action is rewritten, replay every
dependent camera/render action before trusting its saved image or report.
