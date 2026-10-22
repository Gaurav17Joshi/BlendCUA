---
name: measure-or-eyeball
description: When to measure the reference and when to judge by eye — and the order to do them in, which is the part that matters.
---

# Measure or eyeball

Both work. The order is what decides how long the step takes.

> **Eye first, then measure.** The eye gets you a shape in ten minutes that a
> measurement would take an hour to specify; the measurement then catches the
> errors the eye cannot see in its own work.

## Why not measure first

Starting the bat's body, the tempting plan was: render a fine grid cropped to the
torso, read off shoulder width, waist width, head width and length by eye, unproject
each pick to world coordinates, and arrive at exact target dimensions before
touching the mesh.

It was abandoned for three reasons, all still true:

- **Slow.** A tapering profile needs many picks, and each is a round trip.
- **False precision.** The source photo has perspective and foreshortening, so
  "exact" pixel measurements do not correspond to true orthographic proportions
  anyway.
- **Nothing to sanity-check against.** All the measuring happens before any
  geometry exists, so a systematic error has nothing to contradict it.

What replaced it: build the seed, then use the ordinary overlay loop for each
extrude and scale — render a ruler of candidate values, look at it next to the
reference, pick one that looks right, apply, screenshot, compare, adjust. Expect a
few rounds per segment.

## Why not eyeball only

The duck's body was traced entirely by eye and looked plausible at every single
station. Measured against the photograph's own cross-sections in world metres, the
taper was starting too early **everywhere** — the body thin where the bird is still
full, fat where it has already closed into the tail:

| ring | model had | photo measures |
|---|---|---|
| 0.059 | 79 mm | 95 mm |
| 0.153 | 68 | 58 |
| 0.194 | 52 | 35 |
| 0.227 | 32 | 10 |

That is *one* error across five stations, not five errors, and no amount of
station-by-station looking finds it — only laying model against photograph in the
same units does.

Meanwhile the neck and head, checked the same way, came back within a few
millimetres of what the eye had put there.

> **Expect the eye to be fine on small parts and consistently wrong on the largest,
> smoothest form** — which is roughly the opposite of what you would guess.

## So: measure the big smooth thing, eyeball the rest

A practical split:

- **Eyeball** — anything small, anything with a distinctive shape, anything where
  a preview overlay gives you candidate values to choose between.
- **Measure** — the one or two largest, smoothest, least-featured forms in the
  build. Those are where a consistent bias hides.

## Measure in world metres, both sides

A model measurement and a reference measurement are only comparable in the same
units. The pair that works:

- a script outside Blender that thresholds the reference and reports each
  cross-section in **metres**, using the scale you loaded the reference at;
- a script inside Blender that clusters the mesh's vertices along its axis and
  reports each ring's position and radius in **metres**.

Never compare two pictures. Projection through the camera (`world_to_camera_view`)
or a direct world measurement is exact, needs no render, and cannot be thrown by
framing or resolution.

## Measure the right thing

Both false alarms in the duck build came from measuring the easy thing rather than
the thing in question:

- A body scan reported 104 mm against a model built at 79 — a 25% error apparently
  everywhere. **The legs are attached**, so over the columns they occupy they are
  part of the same connected run, and the scan measured back-to-*foot*. Taking the
  longest run and comparing behind the legs put the real error at about a sixth.
- The reference plate measured 1.71 aspect against the file's 1.33, which looked
  exactly like the aspect being applied twice. It was not: **the plate is cropped
  by the frame** at that zoom, so its measured width is not its real width.
  Projecting the Empty's own corners settled it.

Before trusting a measurement, ask what is inside the region you measured, and
whether the thing you measured is the thing you named.

## Finish with the outline

A plan of numbers can be right at every station and still make the wrong shape,
because a silhouette is the radii, the path, the joint mitring and the
cross-section all at once. End the step by drawing the built outline over the
reference — with the model itself **hidden** for the base render, or you are
comparing the outline against a shaded object standing in front of the photo
rather than against the photo.
