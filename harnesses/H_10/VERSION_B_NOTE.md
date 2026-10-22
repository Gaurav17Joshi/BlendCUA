# MILESTONE: the harness after 10 tasks (2026-09-13)

Store commit 29762d0. Taken before the loop starts on tasks 11-13 (pumpkin_decor, newtons_cradle, black_hole).
Task 10 (low-poly dog) was built by hand by another Claude as mem/10_low_poly_dog_run_002 (Cagent/README.md);
the loop's own run_001 stopped at step 2. Compare against H_00 (start) and the after-20 snapshot.
Contents = H_06 + reference.load_reference reload fix (29762d0).

## Added by hand 2026-09-13 08:14 (task 10, the hand dog run_002)
- Skills/Planner/Objects/low-poly-animal.md (standing low-poly animal from side/front/top plates: one ring loft along the spine, limbs from reserved roots), indexed in Skills/README.md. Part of task 10's contribution, so it belongs to this "after 10 tasks" milestone; store commit follows 01813c9.

## Added by hand 2026-09-13 16:40 (task 09, the hand hammer run_003; store commit 7180a72)
Task 09 is inside the first ten, so these belong to the after-10 milestone and are backfilled here
(same treatment as the animal skill from task 10). Files copied from main; README lines and the
curator rule inserted without bringing later (11-13) additions into this snapshot:
- Skills/Planner/trace-or-type.md (trace when the silhouette is the shape; type measured primitives
  when the outline is straight runs, chamfers and circles; rasterise the mesh back for a residual)
- Skills/Executor/relief-along-world-paths.md (world-space stroke_displace paths for relief that reads
  from every side; native brush strokes are one-view)
- Skills/Scripting/blender-state-gotchas.md (finish replaces same-named objects, matrix_world stale
  until view_layer.update, no MATERIAL shading under Workbench)
- Skills/Curator/human-judgement.md rule 11 (a three-quarter width is not a depth; one-view relief is
  not relief; a lit patch is not a tone)
- Skills/README.md index lines for the three
