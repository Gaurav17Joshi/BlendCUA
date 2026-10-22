---
name: continuous-strap-networks
description: Use this when a reference shows a connected branch/scroll network or flat forged strap rather than independent rods.
evidence: mem/02_iron_gate_run_001/steps/step_002/05_lower_side_bays.py; mem/02_iron_gate_run_001/steps/step_003/review/round_01/review.txt
---

# Continuous strap networks

Use this when the visible member is a broad forged strap or a connected branch/
scroll network. Build the shared path graph first: give every branch-to-branch,
branch-to-collar, and branch-to-rail transition one shared node in the caller's
coordinate frame. Do not begin with independent capped rods and hope that an
object join repairs the construction.

Call `flat_strap_network.build_flat_strap_network` with the ordered paths and
shared node ids. Use its broad, shallow chamfered section so the front face carries
the projected line weight while the edge depth stays narrow. Taper and cap only
true degree-one terminal curls; a branch transition remains uncapped and shares
its junction ring. If a collar or rail is a separate owner, make the attachment a
shared/welded transition in the network data instead of placing a cap behind it.

Before handoff, inspect both proofs:

1. **Front continuity.** Render an unshaded close crop. At every non-terminal
   junction, require one continuous occupied run with zero background gap. Compare
   the clean mask to the reference with `reference_curve_mapping.audit_curve_masks`
   and use row/column runs at the branch rhythm.
2. **Oblique section.** From TOP or a modest orbit, report the actual front width,
   edge depth, and depth/width ratio for a representative large curl and lower
   curl. Confirm the shallow chamfered face, closed sides, and absence of capped
   object-joined overlaps. The returned section and junction-gap audit is evidence,
   not a substitute for looking at the crop.

Keep path geometry, section dimensions, material, terminal names, and mirror choice
caller-owned. Re-run the front mask after mirroring; do not mirror a graph whose
source-side branch order has not passed its ROI evidence.

Evidence: `mem/02_iron_gate_run_001/steps/step_002/05_lower_side_bays.py` taught
that separate parts were object-joined, and the Step 3 review passed numeric widths
without checking front flatness or junction continuity.
