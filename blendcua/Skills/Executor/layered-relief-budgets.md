---
name: layered-relief-budgets
description: Read this before stacking broad or fine surface wear on a sculpt that already contains measured event relief.
evidence: 04_datestone_1934_run_001 step_002
---

# Budget relief after the layers interact

A groove or chip report measured immediately after its brush pass is not the
final depth. Any broad weathering footprint applied later can overlap the same
vertices and push an event outside its target, even when each individual layer
looks restrained. Keep explicit event paths and broad surface wear as separate
masks where possible; otherwise audit the final high mesh at every event path
before baking and correct only the known bands.

Use a local scale check for fine wear as well. A grain field that reads as
irregular on a wide panel can alias into repeated stripes on a narrow ledge or
foot. Compare a close base-band crop, and switch to a world/3-D field or reduce
the image layer when its feature size is not supported by that face's cells.

The authoritative numbers are post-stack depth, width, and movement. Write
those values into the final report and use them for the bake envelope; do not
carry forward a pre-weathering brush report just because its label says
"groove" or "chip".
