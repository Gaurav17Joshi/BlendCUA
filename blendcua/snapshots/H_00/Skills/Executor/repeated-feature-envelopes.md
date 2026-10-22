---
name: repeated-feature-envelopes
description: Read this before building repeated crowns, slats, stones, or other arrays from a reference image.
evidence: 09_skull_run_001 step_003; 11_umbrella_run_001 steps 2 and 3
---

# Measure repeated features as an envelope

A correct count and vertical band do not make a repeated row correct. Before
building the array, measure its external span and the per-item size trend in the
reference crop; then verify the rendered group against those measurements. Keep
central pieces fuller and let the posterior pieces shrink or become occluded when
the source does. Do not let a convenient world-X interval silently become the
row's screen-space width.

The useful report has three separate answers: total group left/right extent,
individual projected crown/element widths, and the gap/overlap between neighbors.
A row can pass count and separation while extending far beyond the source, as the
skull's first dental pass did. Correct the center positions and taper together,
then rerender the unannotated close crop before moving on.

For radial arrays, keep the root azimuths and member count as structural
constraints, but measure the source-facing tip sequence independently. A
marked front tip may require an individual radius, height, or terminal path
adjustment; do not globally rotate an otherwise correct eight-way fan or add a
ninth member to repair one projected landmark. Record the per-sector targets
and verify that each attachment still lands on real stock.

A raw evaluated-vertex AABB is not automatically the visible envelope. Sparse
polygon chords, a low-resolution hem, and a simulated surface can put the
vertex extrema outside the traced edge or leave the traced edge short of them.
At the settled frame, use an evaluated polygon/mask or edge-aware trace at a
resolution supported by the outer topology, and compare the continuous side
and low-hem profile before handing off. If it disagrees, fix the owning ring,
pin, or path; do not add a free overhang or change the presentation camera
until the source-facing geometry has been checked.
