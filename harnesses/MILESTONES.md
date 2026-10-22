# Harness milestones for the comparison

The experiment compares the harness at three points: at the start, after 10 tasks, after 20 tasks.
Snapshots are numbered per loop merge (H_NN), so the milestones are named here, not by number.

| milestone | snapshot | store commit | state |
|---|---|---|---|
| start (before any task) | H_00 | ee62f14 | taken 2026-09-11, the harness before the first remedy of task 02 |
| after 10 tasks | H_07 | 29762d0 | taken 2026-09-13 before the loop started on 11-13; task 10 built by hand as run_002 (Cagent/README.md), the loop's run_001 stopped at step 2 |
| after 20 tasks | (to take) | | same, when task 20 closes |

Notes
- H_06 (89accbc, 2026-09-12 evening) is the harness the dog (10) and human (11) runs start from; it is NOT the
  after-10 milestone, since task 10 has not run on it yet.
- 2026-09-13: 11_human_fire_juggling was taken out of tasks/train (to Tasks/Intial_Set); tasks 11-13 are now
  pumpkin_decor, newtons_cradle, black_hole. The human's H_06 run is in mem_old/2026-09-13_human_run_on_H06.
- Tasks 06-09 were closed by hand without loop merges, so their hand additions live in main and were appended into
  H_05's note rather than getting their own snapshots.
- 2026-09-13: the hammer's hand skills (task 09, run_003: Planner/trace-or-type, Executor/relief-along-world-paths,
  Scripting/blender-state-gotchas, human-judgement rule 11) arrived late; committed to main as 7180a72 (snapshot H_11)
  and backfilled into H_07..H_10 with a dated note, so the after-10 milestone (H_07) includes them.
