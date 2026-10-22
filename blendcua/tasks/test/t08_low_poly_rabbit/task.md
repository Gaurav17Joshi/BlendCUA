# t08_low_poly_rabbit

**Low-poly rabbit**

Reference: reference.png -- a photo of a real rabbit in left-side profile, sitting (made
with gpt-image-2). This is the rabbit to build: measure from it.

Also: reference/low_poly_style.png -- a finished low-poly rabbit. It is **only an
inspiration** for what the result should look like once it is made low-poly (the facet
size, the flat shading, the colours), not a plate to measure or trace.

Only a few basic instructions (everything else is yours to plan and work out):-

Model the rabbit in reference.png as a low-poly model -- flat-shaded and faceted, no
fur or fine detail -- the way the low-poly dog was built from its photo: put the rabbit
photo in Blender as the side guide and build one faceted mesh from it (see
`Skills/Planner/Objects/low-poly-animal.md`). Tall ears with pale inner faces, the
short muzzle and a dark eye, the rounded body and haunch, the front legs, the long hind
feet flat on the ground and the small pale tail. Tan body, cream belly, chest and inner
ears, as in the style image.

**Other views.** If you need more straight views (side, top, back) to get depths or
the body's width from the front and top, make them yourself with gpt-image-2 (`blendcua_core.load_api_keys()`; pass the
bash tool a longer `timeout`, one image takes up to about 2 minutes) and turn them into
blueprints with the `blueprint` tool -- see `Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and
blueprints are aids only: **reference.png is the true one, and wherever they disagree
with it, the reference wins.**

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the rabbit and move on. Do not spend actions hunting an exact
match to the reference framing.
