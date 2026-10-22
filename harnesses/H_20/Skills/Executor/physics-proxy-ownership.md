---
name: physics-proxy-ownership
description: Read this when visible geometry must follow a rigid-body constraint whose physical length or collision role differs from the visible endpoint span.
evidence: 12_newtons_cradle_run_001 step_003; step_004
---

# Keep visible endpoints and physics ownership separate

When a visible string, tendon, or strap is defined by two measured attachment
points but a solver requirement demands a different physical rod length, do not
stretch the visible endpoints or give the visible mesh a competing rigid body.
Build a hidden proxy centred on the same pivot span and extend it into the
anchor/attachment bodies to meet the physical length; connect that proxy to the
native constraints and parent the visible child to it. Give the proxy the only
dynamic ownership and make its collision policy explicit.

Audit the visible endpoint span and the proxy's outer-ring length as separate
quantities at rest and at the required posed frames. This preserves the measured
visual attachment while making the constrained body satisfy the solver or rubric
length, and prevents a later bake from leaving a static visible thread behind a
moving body.

Evidence: `mem/12_newtons_cradle_run_001/steps/step_003/handover.md` and
`mem/12_newtons_cradle_run_001/steps/step_003/review/round_01/review.txt`.