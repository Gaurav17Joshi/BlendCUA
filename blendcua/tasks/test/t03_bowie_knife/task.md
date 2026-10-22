# t03_bowie_knife

**Bowie knife**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the unedited image). reference.png is original.png with the title text, the Blender logo and the player icons removed and re-rendered sharper at 2048x1152 by gpt-image-2; if the two ever differ on the object itself, original.png wins.

Only a few basic instructions (everything else is yours to plan and work out):-

Model the knife in the reference: a clip-point bowie blade with a flat grind and a
bevelled edge, three round thumb notches along the spine, and the etched maker's mark
and engraving on the flat; a brass guard, flared and slightly curved; and a thick
burl-wood handle that swells toward the butt. Brushed, slightly worn steel with the
etching as a material or decal, not geometry; aged brass; figured burl wood with dark
streaks and a satin finish.

**Other views.** Only this one view is given. If you need straight views (front, side,
top) to get depths, thicknesses or the blade's thickness and grind, make them yourself with gpt-image-2
(`blendcua_core.load_api_keys()`; pass the bash tool a longer `timeout`, one image takes
up to about 2 minutes) and turn them into blueprints with the `blueprint` tool -- see
`Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and
blueprints are aids only: **reference.png is the true one, and wherever they disagree
with it, the reference wins.**

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the object and move on. Do not spend actions hunting
an exact match to the reference framing.
