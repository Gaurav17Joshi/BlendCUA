---
name: seating-by-contact
description: Read this before placing props that rest on, lean against or float in something (marshmallows on cream, a candy cane in a mug, fruit in a bowl, a spoon in a cup) and before writing the gate that says they "sit on" it. Seat by a vertical drop with ray casts against everything below, float objects in liquids, solve a leaning object's two contacts from geometry, and gate on contact plus bounded overlap measured by point-in-solid - never "above the floor", never a hand-pinned support point.
evidence: mem/16_chocolate_cup_decor_run_002 (hand rebuild, 2026-09-16) steps/step_004/01_build_candy_cane.py, 02_build_marshmallows.py, 03_audit_props.py, scripts/props_audit.json; mem/16_chocolate_cup_decor_run_001 step_004 as the counter-example (min z > 0 gate, cane pinned by hand outside the drink); blends/16_chocolate_cup_decor_run_002/LESSONS.md A5, A6, B5, B8, B10
---

# Seat props by contact, and gate on contact

## What went wrong

The loop's cup passed a step-4 "commit" check that was `min z > 0`: "above the floor".
Anything in a mug passes that. Its seating reviews compared projected boxes, not
physical contact. The result: marshmallows 34-73% inside the cream, and a candy cane
whose foot was hand-pinned at r 0.863, outside the drink disc (r 0.845), resting on
nothing.

## Resting objects: drop straight down

- Seat with a **vertical drop**: ray-cast down from each underside vertex against every
  surface below and move the object by the smallest gap. Dropping along the surface
  normal at a steep cream edge threw two marshmallows sideways into the wall.
- **A resting body does not touch at its lowest vertex.** A marshmallow on a slope
  touches at its uphill side. Measure the smallest gap across the whole underside.
- **Never start a ray inside a solid.** The first gap test cast from 0.002 above each
  vertex; for a vertex already embedded that ray starts inside the support and returns
  the far wall as a positive "gap". Cast from well above (0.3 on the cup) and take the
  first surface.

## Objects in a liquid: float them

The drink ring between the cream and the wall (0.184) was narrower than a marshmallow
(0.191); dropped, they perched on the cream's edge with 0.02-0.10 of air underneath.
Marshmallows float on hot chocolate. Modelled 25% submerged and nestled against the
cream (≤ 12% overlap), they matched both physics and the reference.

## Leaning objects: two computed contacts

A leaning object needs two contacts, and both are solved from geometry, never pinned.
For the cane:

1. Solve it in its own radial plane, at the measured lean (42.8°) and tube radius
   (0.052; the loop's was 0.033 at 25.8°).
2. Lift it along the shaft normal until the tube **touches** the rim: the contact
   distance equals the tube radius (0.0524).
3. Walk down the shaft to its first contact with the inside wall: that is the foot
   (0.88 below the drink).
4. **Include the mirrored half of the section.** The first search used the lathe section
   for ρ ≥ 0 only; the shaft crosses the axis, so it walked the whole shaft without
   finding the far wall and had no foot.

## Gates that test the defect they name

| claim | gate |
|---|---|
| sits on X | smallest underside gap to X ≤ 0.005, and % of vertices inside X (ray-parity point-in-solid) ≤ 15% |
| floats in X | bottom below the liquid surface, no more than half its diameter under |
| leans on a rim | closest distance to the rim = tube radius (contact, not overlap) |
| stands in a vessel | foot below the liquid and touching the inside wall; ≤ 1% of vertices inside the ceramic |

Rebuild result: marshmallows 0-12% inside the cream, all supported; cane 0% inside the
ceramic.

See also `projected-overlap-is-not-clearance.md` (image overlap is not physical
clearance) and `Reviewer/writing-review-checklists.md` ("A gate tests the defect it
names").
