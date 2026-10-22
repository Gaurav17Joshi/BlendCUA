---
name: verify-live-scene
description: Read this when a step inherits a long-running Blender session and a saved render already looks correct.
evidence: 04_chess_staunton_run_001 step_001
---

# Verify the live scene before reusing a render

A saved render proves what existed when it was written, not what Blender's live
session contains now. Before editing an inherited object or treating a cached
render as the current state, run a lightweight scene inventory and assert the
exact names and types the next action needs.

If the inventory is an unrelated scene, do not tune the cached render or add a
second copy beside it. Re-establish the build from a deterministic clean action
(`clear_scene()`/`cleanup.reset_scene()` followed by the required construction
actions), then verify the live names again. Keep the saved render as a reference
for comparison only.
