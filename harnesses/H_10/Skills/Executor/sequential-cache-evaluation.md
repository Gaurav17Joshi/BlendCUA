---
name: sequential-cache-evaluation
description: Read this before judging a cloth, particle, or modifier cache at a late frame or deciding whether a native particle API is functional.
evidence: 12_tablecloth_drape_run_001 step_002; 16_hourglass_run_001 step_003
---

# Warm a history-dependent result from its start frame

A late `scene.frame_set(target)` is not evidence that a history-dependent
modifier has produced the intended target pose. After creating or changing a
simulation, set the scene to the cache start and advance one frame at a time to
the target, updating the dependency graph on every frame. Repeat that traversal
after collision or solver edits; otherwise a checkpoint can show a valid-looking
pose while later frames are frozen or the point cache is stale.

Use `simulation.evaluate_sequence` for this traversal and record at least the
start/end bounds, changed-vertex count, and cache flags. Leave the scene at the
measured target frame so the following render and audit describe that same live
state. A render-only comparison must not replace this mechanical provenance
check.

An operator or settings type being present is not evidence that a particle or
emitter path is usable. After setup, scrub the actual evaluated output at the
start, middle, and end and inspect its record/instance count and bounds. If the
cache remains empty or stale, treat that native path as functionally unavailable
and switch to a deterministic keyed mesh or Geometry Nodes fallback before
building dependent audits; record the functional failure rather than probing only
API availability.

