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
