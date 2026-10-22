# t02_black_office_chair

**Black leather office chair**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the unedited image);
front_plate.png (the same chair straight from the front, on white, made with
gpt-image-2 -- use it as the front guide).

Only a few basic instructions (everything else is yours to plan and work out):-

Model the office chair in the reference: a tall upholstered backrest in black leather
with horizontal stitched channels; a seat cushion with its own finer channels and a
rounded front edge; two flat-sided black arms, each an open loop that runs from under
the seat up to a padded armrest cap; a height-adjust lever under the seat; a chrome gas
lift in a black cylinder; a five-spoke black base; and five twin-wheel castors on
chrome stems. Soft black leather with visible stitch lines, satin black plastic,
chrome.

**Other views.** Only this one view is given. If you need straight views (front, side,
top) to get depths, thicknesses or the arm loop and backrest curve, make them yourself with gpt-image-2
(`blendcua_core.load_api_keys()`; pass the bash tool a longer `timeout`, one image takes
up to about 2 minutes) and turn them into blueprints with the `blueprint` tool -- see
`Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and
blueprints are aids only: **reference.png is the true one, and wherever they disagree
with it, the reference wins.**

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the object and move on. Do not spend actions hunting
an exact match to the reference framing.
