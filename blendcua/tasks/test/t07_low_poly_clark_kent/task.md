# t07_low_poly_clark_kent

**Low-poly Clark Kent, walking**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the unedited image);
front_plate.png (the same character straight from the front, on white, made with
gpt-image-2 -- use it as the front guide).

Only a few basic instructions (everything else is yours to plan and work out):-

Step 1: model the low-poly character in the reference: a big-chested man with a
faceted bald head, two small black dot eyes and no other facial features; a white
shirt with the collar up and the sleeves rolled to the elbows; a red tie; a black belt;
dark blue trousers; black shoes; and bare forearms and hands. Visible flat facets and
flat shading, no smooth subdivision. Build the body as one mesh with the limbs grown
from it; tie, belt and shoes can be separate.

Step 2: rig him with a simple armature (hips, spine, neck/head, both arms with elbows
and hands, both legs with knees and feet).

Step 3: animate a **walk cycle with the arms swinging**, on a loop: contact, down,
passing and up poses for each leg; each arm swings forward with the opposite leg; the
hips rise and fall and turn a little, the shoulders counter-rotate, and the feet do not
slide while they are planted. He can walk in place or along a straight line. The
deliverable is the animation: render a few frames of the cycle and a short clip.

**Other views.** If you need more straight views (side, top, back) to get depths or
the chest's depth, make them yourself with gpt-image-2 (`blendcua_core.load_api_keys()`; pass the
bash tool a longer `timeout`, one image takes up to about 2 minutes) and turn them into
blueprints with the `blueprint` tool -- see `Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and
blueprints are aids only: **reference.png is the true one, and wherever they disagree
with it, the reference wins.**

Warm yellow backdrop as in the reference. No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the whole figure from the side or three-quarters and move on. Do not spend actions hunting an exact
match to the reference framing.
