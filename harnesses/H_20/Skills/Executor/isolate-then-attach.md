---
name: isolate-then-attach
description: Build a part away from the model, shape it in its own space, and place it last — when to do it and when not to.
---

# Isolate then attach

When a new part needs shaping work that does not depend on exactly where it ends
up, build it as a **separate object in open space**, shape it there, and compute
its real placement only in the last action.

## The shape of it

The bat's ear, in four actions:

1. `09_ear_seed_line.py` — a new object `BatEar`: two vertices and an edge, at
   world `(0.6, 0, 0.3)`. That location has nothing to do with where the ear ends
   up; it is chosen purely so the part renders in open space, alone in frame, from
   FRONT.
2. `10_ear_teardrop.py`, `11_ear_thicken_curve.py` — extrude, scale, solidify,
   bend, entirely in the object's own local space with its origin at `(0,0,0)`.
   None of this knows the body exists.
3. `12_ear_place.py` — only now does it get a `.location` and
   `.rotation_quaternion` computed **from** the body: a point on the skull's
   surface, and a direction to point along.

## Why it is worth the extra object

- **Every intermediate screenshot is just the part, filling the frame**, with
  nothing else competing for pixels or confusing `fit_objects_ortho_view` about
  what it is framing. Shaping decisions get made at a size you can actually judge.
- **A mistake mid-shaping is free to undo** — re-run the seed action and start
  over, without touching the body at all.
- **The two concerns separate**: "what shape is this" and "where does it go" are
  different questions, and answering them together is how a part ends up the right
  shape in the wrong place, or vice versa.

Same underlying idea as a seed cylinder: build the blank, shape it independently,
attach last.

## Placement by attachment, not by coordinate

When you do place it, derive the position **from the thing it sits on** — raycast
onto the surface, or ask the branch for its own point and direction:

```python
hit, loc, nrm, _ = duck.ray_cast(origin_local, direction_local)   # eye on the head
p, d = mg.point_on(branch_points, t)                              # leaf on a branch
```

A screen pick says where a feature sits *when seen from one side*; it says nothing
about how far out the surface is there. Raycasting puts the part on the surface
whatever the surface turned out to be.

This also matters when the thing underneath moves later:

> **Anything positioned by a coordinate rather than by attachment has to be
> re-read when the thing it sits on moves.**

Correcting the duck's head placement left the collar band cutting across the jaw
and the eye's raycast landing on the crown — both were stated in the old
geometry's terms. A leaf placed by asking its branch moves with the branch for
free.

## When not to isolate

- **When the part is a continuation of the surface.** The duck's bill is extruded
  off the head's own front face, because a separate bill object leaves a visible
  seam where two closed surfaces interpenetrate. Same for the gravestone's stone,
  inset from the base's own top face.
- **When several parts must share a start point exactly.** Duplicate the face in
  place and tag the copies instead — separately authored cross-sections never
  match, and the seam shows.

## The join, either way

Two closed surfaces that touch exactly leave a visible ring under a hard key.
Start the attached part **inside** the parent — a centimetre into the belly, one
anchor inside the stem — and the join buries itself.

## Organic petioles: continue into the receiving blade

For a petiole, shape the path in isolation, but derive its leaf-side terminal from
the real lamina-root or midrib anchor. Begin inside the trunk/core and continue
through the receiving blade or far enough under it to bury the cap; a terminal
stopped at a projected card root is not an attachment. Verify the assembled join
has no background gap before accepting the support.

Evidence: `Curator/reports/03_monstera_pot/round_02/curation.json` and the reverted
Step 3 in `vb/state/03_monstera_pot/round_02/store_after/plans/03_monstera_pot/03_monstera_pot_plan.md`;
`Checker/reports/03_monstera_pot_run_003/verdict.json` measured the resolved top
join at a 0 px background gap with a continuous green run at x=495..500, y=280..430
(previously approximately 20–30 px).
