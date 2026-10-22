---
name: fenestrated-blade-construction
description: Read this when a broad folded leaf must be made procedurally and a shared prototype will be instanced.
evidence: 07_monstera_pot_run_001 step_003
---

# Build the blade before instancing it

For a broad fenestrated blade, make the lamina continuous around each real
slot (or cut the openings from one continuous surface), then add the raised
midrib and fold. Do not build the visible silhouette out of many overlapping
radial ribbons: a correct `Instance on Points` graph only repeats the
prototype's strip/fan artifact eight times. Inspect the hidden prototype alone
in a top view and compare a close crop before wiring it into GN; it should read
as one broad connected blade with separated curved lobes, irregular open slots,
and controlled overlap.

## Solid-safe leaf carrier

When a broad fenestrated blade is judged in Solid shading, keep the verified image for fine colour and fenestration detail, but do not let a rectangular alpha card be the only evaluated geometry. Build the blade carrier as a faceted, curved, non-rectangular form with real fold/depth, inspect it alone in Solid shading before instancing, and reject any exposed rectangular backing or carrier skirt.

Evidence: `Curator/reports/03_monstera_pot/round_01/03_monstera_pot_remedy.md#1` and `Curator/reports/03_monstera_pot/round_01/apply/applied.json#remedies[0]`; `Checker/reports/03_monstera_pot_run_002/verdict.json` resolved `leaves.geometry.flat_card_planes` after the eight rebuilt leaves measured 30 vertices/20 faces and showed curved solid volumes with no rectangular backing.
