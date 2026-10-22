---
name: tone-calibration-region-means
description: Read this before calibrating material colours of a still (a mug, cream, a table, small props) against the reference photo, or when a patch-by-patch calibration has converged and the render still looks wrong (grey, lavender, washed out). Project the same large 3-D regions into both images, mask out decals, highlights, occluders and clipped pixels, compare means in linear light under soft lighting, and keep exposure and albedo from fighting. Also: check the channel order of every named colour, and a texture's value range before its colour ramp.
evidence: mem/16_chocolate_cup_decor_run_002 (hand rebuild, 2026-09-16) steps/step_005/02_calibrate_tones.py, scripts/tone_calibration.json and tone_calibration_attempt1..3.json, 01_build_wood_set_camera.py; the eye-tuned colours of mem/16_chocolate_cup_decor_run_001 as the counter-example; blends/16_chocolate_cup_decor_run_002/LESSONS.md A9, B9, B11, B12
---

# Calibrate tones on region means, not patches

## Colours tuned by eye were wrong

| | reference | loop render |
|---|---|---|
| mug, G/R and B/R | 0.72 / 0.84 (dusty rose) | 0.52 / 0.56 (too red, too saturated) |
| "pink" marshmallow | sRGB [211,179,215] | violet: linear base (0.58, 0.29, 0.73), blue above red |
| cocoa dust | specks ~0.007 across | noise blobs 0.02-0.04, read as rust |
| table | wood grain | noise blobs, no grain |

Colours come from measured reference windows. **Check the channel order of every named
colour: a "pink" with B > R is violet.**

## Three designs that failed, then one that worked

| attempt | design | what happened |
|---|---|---|
| 1 | same 3-D patches in both images; exposure driven by one "upper cream" patch | in the reference that patch landed on a drizzle strand ([94, 78, 86]); exposure ran to its −2 clamp, every albedo saturated at its cap, the mug went grey |
| 2 | match colour ratios on small patches | mug converged; the cream patch was clipped and two marshmallow patches were occluded, so those albedos ran off |
| 3 | visibility and clipping handled, still single small patches | every patch matched within a few levels, yet the render looked wrong: one brightly lit tier drove the cream albedo to 0.37 and greyed the rest; one patch made the whole mug lavender |
| 4 (works) | soft lighting plus **region means** | below |

The method that works:

1. **Soft lighting**, soft enough that no region you calibrate clips.
2. **Large regions, the same in 3-D:** the whole visible mug body, the whole visible
   cream, a stretch of table, projected into both images through each image's own camera
   (`measure-the-reference-camera.md`).
3. **Masks** drop decals, drizzle and highlights.
4. **Visibility test:** keep only sample points a ray from the camera actually hits on
   the target object. A "green marshmallow" patch measured purple because the pink rim or
   a neighbour was in front of it.
5. **Clipping test:** drop samples with any channel ≥ 250. A cream patch at
   [255, 250, 232] made its colour ratios meaningless.
6. **Means in linear light.** Exposure steps down only if the cream clips; per-channel
   albedo is scaled toward target/measured, with damping, so exposure and albedo do not
   fight.
7. Small objects use hand-measured box colours as targets.

Result, render against reference (sRGB): mug [169, 102, 101] / [169, 100, 97]; cream
[203, 190, 184] / [202, 189, 183]; table [123, 66, 47] / [124, 65, 46].

Keep failed calibration attempts on disk (`tone_calibration_attempt1..3.json`).

## Textures: check the value range before the ramp

- **Small features at measured size.** Cocoa as Voronoi specks sized to the measured
  ~0.007, not noise blobs.
- **Wood grain.** Wave bands gave evenly spaced stripes that read as corduroy. Stretched
  noise with the old ramp gave *flat* brown: noise returns a narrow band around 0.5, and
  adding a second noise pushed every value past the ramp's last stop. What worked: noise
  stretched ~30× along the grain, **Map Range 0.38-0.62 → 0-1**, a small fine-noise
  modulation, then the colour ramp.

See also `material-target-audits.md` (per-role audits on a fresh final-camera render).
