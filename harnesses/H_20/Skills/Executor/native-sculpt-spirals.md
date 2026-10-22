---
name: native-sculpt-spirals
description: Read this when a task asks for a sculpted form (piped cream, soft-serve, a coiled mound, rolled tiers) and you are about to fake it with a lathe of lobes or a cluster of spheres, or when a sculpt_native pass leaves lips, lumps, blobs or a bald cap. Lathe the fitted mound, voxel-remesh it, and sculpt along a world-space spiral split into overlapping, cross-faded sectors with brushes scaled to the local radius; invert CREASE for grooves and read the signed max_in/max_out report after every stroke.
evidence: mem/16_chocolate_cup_decor_run_002 (hand rebuild, 2026-09-16) steps/step_003/01_build_cream_mound.py, 02_sculpt_cream.py, scripts/cream_sculpt.json and cream_sculpt_attempt1.json / attempt2.json; the lobe-lathe-plus-six-spheres cream of mem/16_chocolate_cup_decor_run_001 as the counter-example; blends/16_chocolate_cup_decor_run_002/LESSONS.md A7, B6
---

# Sculpting a spiral mound with native brushes

## When the task names a method, use it

The loop's cup built its whipped cream as a lathed lobe field plus six UV spheres. It
read as a cluster of balls, and its apex was 18% too tall (0.635 above the rim against a
measured 0.538). The task asked for a conical mound shaped by sculpting. **When the task
names a method (sculpting, cutting, curves), use it, and record the measured
displacement.**

## The recipe

1. Lathe the measured dome profile into a cone.
2. **Voxel-remesh first** (0.008 on the cup) so a groove spans several vertices.
3. Sculpt with Blender's own brushes (`sculpt_native.apply_world_strokes`) along a
   world-space spiral (4 turns on the cup):
   - DRAW rolls the tiers outward;
   - CREASE, **inverted**, cuts the grooves between tiers;
   - a light SMOOTH filter softens the brush dabs.

## Traps, each of which broke a first attempt

- **CREASE pushed outward.** On a retyped brush the first pass reported `max_out +0.020`
  and `max_in ≈ 0`: a knife-thin lip on every tier instead of a groove. `invert=True`
  gave `max_in −0.026` as intended. **Read the signed `max_in` / `max_out` report after
  every stroke**; the render is not where you find out the sign.
- **A spiral wraps behind the object.** Split it into azimuth sectors and stroke each
  sector from its own side.
- **Sector joins show as lumps.** Overlap neighbouring sectors (±8°) and fade pressure to
  zero across the overlap with `profile=` and `profile_size=False`.
- **An abrupt end leaves a blob.** Fade the ends of the whole spiral; a hard stop left a
  blob near the peak.
- **Small upper turns get smothered, or left bald.** Scale brush radius and strength with
  the local surface radius; a spiral stopped early leaves a bald "helmet" cap.

Keep each attempt's report (`cream_sculpt_attempt1.json`, `…attempt2.json`) beside the
final one so the next reader sees what the numbers were when it looked wrong.

See also `relief-along-world-paths.md` for relief that must read from every side as an
auditable depth in metres.
