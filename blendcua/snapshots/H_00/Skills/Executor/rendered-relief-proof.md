---
name: rendered-relief-proof
description: Read this after applying fine sculpt relief or surface weathering whose numerical displacement must also be visible in the final render.
evidence: 09_skull_run_001 step_004
---

# Numerical relief is not visible relief

A native sculpt report proves which vertices moved and by how many millimetres;
it does not prove that the active material and light make a 1–4 px groove readable.
After each fine relief pass, render the actual judged camera at the target
resolution and inspect a 2x crop of the path. Record a pixel-level difference or
projected line width as well as the post-stack world displacement.

If the depth is inside its budget but the line disappears, do not blindly deepen
the cut. First check the render/material cue and the path raycast; use a restrained
same-path shadow or contrast layer when the visual cue needs support, while keeping
the native relief as the geometric source of truth. Recheck broad weathering after
that layer because overlapping masks can change the final depth.
