# 10_low_poly_dog

**Low-poly dog**

Reference: reference.jpg (a side photo on grass)
Plates: reference/side_plate.png, reference/front_plate.png, reference/top_plate.png —
straight side, front and top views of the same dog in the same pose on a white background
(made from the photo with gpt-image-2).
Blueprints: reference/side_blueprint.png, front_blueprint.png, top_blueprint.png — the same
views as drawings (silhouette fill and one contour, nothing else), each with a .json beside
it holding the contour polygon and bbox.

Only a few basic instructions (everything else is yours to plan and work out):-

Model the Rottweiler in the reference as a low-poly model -- flat-shaded and
faceted, no fur or fine detail. Build it from the blueprints with scripts (in planner and execution), not by eye: put
the side and front blueprints in Blender as guides, read the outline and station widths
from their contour JSON and mark head, legs and tail as points, build one main mesh from
those numbers, and check the built outline back on the blueprints. The photo is for colour
and the tan markings; the duck plan (plans/Duck/Duck_plan.md) shows the way of working.
Make the mouth as a cut in the head, and cut with the `line_cut` tool
(Tool_scripts/Tools_code/line_cut.py) the way Skills/Executor/cut-openings-from-traced-lines.md
describes.

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the object and move on. Do not spend actions hunting
an exact match to the reference framing.
