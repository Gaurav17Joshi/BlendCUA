# t09_stylised_hammer

**Stylised painted hammer**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the unedited image). reference.png is original.png with the viewport grid, the small grey hammer and the cursors removed by gpt-image-2; if the two ever differ on the object itself, original.png wins.

Only a few basic instructions (everything else is yours to plan and work out):-

Model the hammer in the reference, standing upright: a big chamfered block head of grey
stone-like metal with cracks and chips, a dark steel collar under the head, a wooden
handle, and a steel pommel cap at the bottom. It is hand-painted and stylised: the
cracks, chips and wood grain are painted-looking materials with a little bump, and the
chips and dents on the head may be sculpted. Keep the chamfers on the head and the
proportions of head, collar, handle and cap.

**The main thing in this task is the texture painting -- do it well.** The modelling is
simple; what makes or breaks the result is the hand-painted look. UV-unwrap every part
cleanly, then paint real image textures for each one (`paint` tool: painted lines and
screen gradients into an image, plus your own painting scripts): on the head, the pale
highlight strokes along every chamfered edge, the darker recesses, the long crack lines
and the chips with their light rims, as in the reference; on the handle, the wood grain
lines, the knots and the light-to-dark shading along its length; on the collar and the
cap, the bright edge highlights and dark worn bands. The paint carries the lighting and
the detail, the way a hand-painted game asset does -- not a procedural noise material,
and not plain flat colours. Compare the painted parts with the reference close up.

**Other views.** Only this one view is given. If you need straight views (front, side,
top) to get depths, thicknesses or the head's depth, make them yourself with gpt-image-2
(`blendcua_core.load_api_keys()`; pass the bash tool a longer `timeout`, one image takes
up to about 2 minutes) and turn them into blueprints with the `blueprint` tool -- see
`Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and
blueprints are aids only: **reference.png is the true one, and wherever they disagree
with it, the reference wins.**

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the object and move on. Do not spend actions hunting
an exact match to the reference framing.
