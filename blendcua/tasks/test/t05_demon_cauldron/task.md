# t05_demon_cauldron

**Demon cauldron**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the unedited image).
reference.png is original.png with the background and the floor reflections replaced by
a plain grey backdrop (gpt-image-2); if the two ever differ on the object itself,
original.png wins.

Only a few basic instructions (everything else is yours to plan and work out):-

Model the stylised cauldron in the reference: a dark blue-black pot with a thick rim, a
wide gold band round its belly with small gold studs, two angular loop handles, and
short curled feet; glowing green liquid inside; three purple tentacles rising out of it
and curling, with pale round suckers along their inner sides; and under it a round
base of cracked, light grey stone slabs laid in a ring. Stylised and chunky; the
tentacles are smooth. The liquid glows (emission).

**Other views.** Only this one view is given. If you need straight views (front, side,
top) to get depths, thicknesses or the handle and foot shapes, make them yourself with gpt-image-2
(`blendcua_core.load_api_keys()`; pass the bash tool a longer `timeout`, one image takes
up to about 2 minutes) and turn them into blueprints with the `blueprint` tool -- see
`Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and
blueprints are aids only: **reference.png is the true one, and wherever they disagree
with it, the reference wins.**

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the object and move on. Do not spend actions hunting
an exact match to the reference framing.
