---
name: relief-along-world-paths
description: Read this when relief must read from every side of a part (grooves round a grip, seams round a barrel, a helix, a ring of dents) or when a sculpt pass is judged only from the view it was made in. Native brush strokes are screen-space from one view and stop where that view ends; a world-space path through sculpt_native.stroke_displace with a constant texture cuts the relief all the way round, in metres you can audit from the mesh. Record every depth/footprint pass in the action's constants and judge the look on a render, not the report.
evidence: mem/09_thors_hammer_run_003 steps/step_003/02_sculpt_wrap.py (12-turn helix, groove 0.009 with a 0.17-pitch footprint, four recorded passes; audit in scripts/wrap_sculpt.json) against mem/09_thors_hammer_run_002 step 4 (native strokes from the front view, ridges on one side, "underbuilt relief" from the checker) (2026-09-13)
---

# Relief that must read from every side is sculpted along world paths

## Why the one-view pass fails

A native brush stroke is a list of screen points raycast onto the surface from the
current view. Whatever the view cannot see, the stroke cannot touch: a groove round a grip
made from the front is a groove on the front. The report says "12 ridges, 1.5 mm" and is
true; the three-quarter render shows a plain back. That is run_002's wrap.

## The world-path pass

1. **Build the path in world space** on the surface: a helix `(r cos a, r sin a, z)` for a
   wrap, a circle for a ring, a polyline for a seam. Twelve turns at the pitch you measured
   off the plate's seam rows.
2. **Displace along it**: `sculpt_native.stroke_displace(obj, texture, path, radius, strength,
   mid_level=0.5, hardness, tail)`. The footprint is a 3D distance to the path, so it wraps
   round corners and the back alike. With a constant black 8x8 PNG as the texture (`image_texture`)
   the displacement is `-strength/2` everywhere in the footprint: a clean groove of a known
   depth with the footprint's smoothstep shoulder. Constant white gives a crest.
3. **Audit from the mesh**, not the report: min/max radius per ring along the axis
   (`wrap_sculpt.json`: 0.153..0.163), 0 boundary / 0 non-manifold, and the width audit
   against the plate still passing.
4. **Judge the look on a render** and write each pass into the action's constants with what
   it looked like: 0.014 deep with a 0.30-pitch footprint read as a coiled rope; 0.013 and
   0.010 still too round; 0.009 with a 0.17-pitch footprint and hardness 0.45 is a strap.
   The next reader sees four passes and their reasons, not one number.

## Notes

- The dense tube must exist before the pass (240 rings x 96 sides for a grip); the
  displacement moves vertices, it does not add them.
- Overlapping paths go into one `strokes_footprint` and one displace; stacking passes doubles
  relief where they cross.
- `rendered-relief-proof` still applies: a millimetre groove that the material and light do
  not show is not there for the reviewer.
