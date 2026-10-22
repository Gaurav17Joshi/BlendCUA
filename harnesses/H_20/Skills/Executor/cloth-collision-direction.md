---
name: cloth-collision-direction
description: Read this before a cloth or other sheet simulation falls onto a closed collision mesh.
evidence: 12_tablecloth_drape_run_001 step_002
---

# Make closed collision supports two-sided before the first fall

A closed support can still be one-sided to Blender's collision solver. Before
starting a sheet above a tabletop, pedestal, or other closed support, explicitly
set every intended collision object's `use_culling = False` and
`use_normal = True`; do not treat the presence of a `COLLISION` modifier as
proof that the incoming side will collide. Keep the inner and outer thicknesses
explicit and close to the surface when the support is thin. This belongs in the
source setup before frame 1, not in a late repair after a pass-through.

The cloth can be unpinned and physically valid while still crossing a support if
this direction setting is omitted. Audit the RNA values before the first
checkpoint, and keep feet or decorative meshes out of the collision set unless
the drape is meant to contact them.
