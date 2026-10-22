# 20_low_poly_well

**Low-poly wishing well**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the unedited image).

Only a few basic instructions (everything else is yours to plan and work out):-

Model the low-poly well in the reference: the round wall of chunky faceted stones in
stacked courses, the two wooden posts, the curved upswept beam, the roof of overlapping
faceted terracotta shingles, the winch axle with its crank handle and the rope wound
round it, the rope down into the well, the plank leaning on the left post, and the
loose rocks on the ground. Keep it low poly and flat-shaded, with the varied stone and
shingle colours of the reference.

**Other views.** Only this one front three-quarter view is given. If you need straight
views (front, side, top) to get the well's depth, the stone ring or the roof slope, make
them yourself with gpt-image-2 (`blendcua_core.load_api_keys()`; pass the bash tool a
longer `timeout`, one image takes up to about 2 minutes) and turn them into blueprints
with the `blueprint` tool -- see `Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and blueprints
are aids only: **reference.png is the true one, and wherever they disagree with it, the
reference wins.**

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the object and move on. Do not spend actions hunting
an exact match to the reference framing.
