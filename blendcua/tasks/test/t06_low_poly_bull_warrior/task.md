# t06_low_poly_bull_warrior

**Low-poly bull warrior, swinging his axe**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the unedited image);
front_plate.png (the same character straight from the front, on white, made with
gpt-image-2 -- use it as the front guide). reference.png is original.png with the white
arrow and the checkerboard background removed by gpt-image-2; if the two ever differ on
the character itself, original.png wins.

Only a few basic instructions (everything else is yours to plan and work out):-

Step 1: model the low-poly character in the reference: a muscular red bull-headed
warrior (minotaur) with two cream horns, a flat-shaded faceted body, black boots and a
row of dark blue spikes down his back; a wooden-handled axe with a grey faceted blade
in his right hand; and a large shield on his left arm, a brown wooden face inside a
thick white faceted rim. Keep it low-poly: visible flat facets, flat shading, no smooth
subdivision. The body, head and limbs are one character mesh; axe and shield are
separate objects.

Step 2: rig him with a simple armature (spine, neck/head, both arms with elbows and
hands, both legs), the axe parented to the right hand and the shield to the left
forearm.

Step 3: animate him **swinging the axe** on a loop: a wind-up that raises the axe back
over the right shoulder, a hard diagonal swing down and across the body, a short
follow-through, and a return to the guard pose. The torso twists and the weight shifts
with the swing, the shield arm stays up in guard, and the feet stay planted. The
deliverable is the animation: render a few frames of the loop and a short clip.

**Other views.** If you need more straight views (side, top, back) to get depths or
the shield's thickness and the spike row, make them yourself with gpt-image-2 (`blendcua_core.load_api_keys()`; pass the
bash tool a longer `timeout`, one image takes up to about 2 minutes) and turn them into
blueprints with the `blueprint` tool -- see `Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and
blueprints are aids only: **reference.png is the true one, and wherever they disagree
with it, the reference wins.**

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the whole figure and the full arc of the swing and move on. Do not spend actions hunting an exact
match to the reference framing.
