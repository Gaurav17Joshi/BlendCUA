---
name: verify-built-feature-values
description: Read this when a review checklist gives a colour, width or placement target for a feature that exists in the built render.
evidence: 02_cardboard_box_run_001 step_002
---

# Verify the built feature, not only the reference

A reference crop proves what the target feature should measure; it does not
prove that the built feature has that value. For every Important rendered
feature with a numeric target, obtain a fresh real camera render, construct a
mask from the built geometry (or a projective face mapping), and sample a
central region that excludes softened edges and neighboring materials.

Report the built median, reference median, channel delta, and the crop used.
For a tape or paint band, also check its orientation and bounds separately.
The first cardboard-box review measured the reference tape but not the built
tape, so a visually plausible result had to be sent back once before it could
pass.

## 2. Qualitative material roles still need rendered medians

For a qualitative material requirement such as near-black or muted gold, require a
fresh built-render sample as well as the reference sample. Use independent masks
for the central body face and pip interiors, excluding bevels, highlights, shadows,
and floor contamination, and report the built median and channel delta for each
important role before PASS.

A reviewer may not pass from material names, Principled node values, or an
unmasked visual impression. Reject clipped pips and lifted dark faces even when
the hierarchy is qualitatively plausible; repeat the measurement after any
presentation-light or exposure change.

Evidence: `mem/13_domino_cascade_run_001/steps/step_004/review/round_01/review.txt`,
whose material PASS reported roles and node/base values but no built/reference
RGB or HSV medians.

## 3. Repeated thin surfaces need a Solid construction proof

For repeated thin parts, obtain a fresh Solid or alpha-disabled inspection of
the evaluated meshes in addition to the textured render. Report the outer
boundary as non-rectangular, the measured fold depth, the number of genuine
cut-through openings, and projected aspect/profile families for representative
copies. A clean alpha render cannot pass a rectangular carrier, a grey backing
outside the boundary, painted openings, or eight copies that share one silhouette
family; inspect the attachment/root coverage in the same proof.

Evidence: `mem/03_monstera_pot_run_001/steps/step_004/review/round_01/review.txt`.

## 4. Review every wood role on the final combined render

A warm-wood mask or top swatch does not prove the drawer-front role. The final
material review must quote built/reference RGB medians for the top, drawer,
side, and rear roles from the final combined render, including the crop or mask
and channel deltas. Repeat those measurements after any presentation-light,
camera, or placement change before PASS; a plausible warm colour without the
role-specific final samples is insufficient.

Evidence: `mem/05_desk_chair_run_001/steps/step_005/review/round_02/review.txt`.
