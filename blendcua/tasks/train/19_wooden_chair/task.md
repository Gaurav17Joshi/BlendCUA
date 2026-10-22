# 19_wooden_chair

**Oak dining chair**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the unedited image).

Only a few basic instructions (everything else is yours to plan and work out):-

Model the wooden dining chair in the reference: the curved plywood backrest with its
four screw dots, the thin bent seat, the four splayed square-section legs, the side
rails joining each front leg to the back leg with their cut-out notch, and the curved
stretcher across the middle. Oak material.

**Other views.** Only this one three-quarter view is given. If you need straight views
(front, side, top) to get depths, splay angles or the backrest curve, make them yourself
with gpt-image-2 (`blendcua_core.load_api_keys()`; pass the bash tool a longer `timeout`,
one image takes up to about 2 minutes) and turn them into blueprints with the `blueprint`
tool -- see `Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and blueprints
are aids only: **reference.png is the true one, and wherever they disagree with it, the
reference wins.**

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the object and move on. Do not spend actions hunting
an exact match to the reference framing.
