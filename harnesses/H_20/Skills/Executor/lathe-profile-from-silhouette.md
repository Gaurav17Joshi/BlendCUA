---
name: lathe-profile-from-silhouette
description: Read this before building a round object (mug, vase, bottle, bowl) whose profile must come from a perspective photo taken from above or below, or before a glossy lathe goes to render. Forward-fit one smooth monotone B-spline profile through the measured camera against the tracked silhouette (never un-project row by row), leave out the heel, validate by re-rendering the built mesh at that camera, and space the rings at no more than 2-3% of the height so a glossy body does not band.
evidence: mem/16_chocolate_cup_decor_run_002 (hand rebuild, 2026-09-16) steps/step_001/01_build_mug.py, 02_audit_mug.py, scripts/mug_lathe.json, scripts/mug_audit.json; the banded 11-station body of mem/16_chocolate_cup_decor_run_001 as the counter-example; blends/16_chocolate_cup_decor_run_002/LESSONS.md A4, B3
---

# A lathe profile from a photo: forward-fit, validate by re-render

## Why the silhouette is not the profile

Seen from above, the occluding contour of an inward-curving belly rotates toward the
camera: `cos ψ = (dr/dz)·tanθ`. A silhouette pixel therefore reads too low and too narrow,
by up to ~21 px on the cup. Reading rows straight off as (r, z) gives the wrong shape, and
trying to undo it row by row is worse.

Four attempts on the cup, in order:

| attempt | method | result |
|---|---|---|
| 1 | raw rows mapped straight to heights | kinked, flat dish at the bottom |
| 2 | un-project each row separately | noise amplified into ripple bands; the global-gradient version diverged to r → 22 |
| 3 | forward fit including the heel rows | flared "pedestal skirt" at the bottom |
| 4 (works) | forward fit, heel rows excluded | smooth, 0.60 px mean residual |

## The method that works

1. Measure the camera first (`measure-the-reference-camera.md`); take the base plane from
   the side tips of the base ellipse, not its lowest pixel.
2. Model the wall as **one cubic B-spline in (r, z) with a monotone control polygon**:
   build the control points from non-negative increments, so the profile cannot fold back.
3. **Forward-project** the profile's occluding contour at the measured elevation and
   least-squares it against the tracked silhouette.
4. **Exclude the heel**, where the track mixes the turning-under contour with the base
   ellipse. Including it gave the pedestal skirt.
5. **Validate by re-rendering the built mesh** at the measured camera and comparing its
   silhouette row by row. The fit's own residual is circular; the render is not. Cup:
   0.51 px mean, 2.0 px p95, 6.0 px worst.

## Ring spacing on a glossy body

The loop's cup had 11 outside stations, with vertical gaps up to 20% of the height, and
its handover called that "low-poly in the vertical direction… intentional". On a smooth
glossy surface that spacing shows as horizontal bands and terracing.

- Sample the fitted curve **uniformly by arc length**. The rebuild used 78 outside
  stations; the largest gap is 2.0% of the height.
- **Gate it:** the largest vertical gap between rings ≤ ~2-3% of the height for a glossy
  lathe. Say "low-poly" only when the task asks for facets.
