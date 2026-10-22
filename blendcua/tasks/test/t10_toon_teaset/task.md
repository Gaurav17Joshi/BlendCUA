# t10_toon_teaset

**Toon-style tea set**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the unedited image).

Only a few basic instructions (everything else is yours to plan and work out):-

Model the still in the reference, in a toon (anime-style, cel-shaded) look: the teapot
(round body, domed lid with a knob, curved spout, loop handle), two tea cups with their
saucers, each cup filled with milky tea with a swirl and small bubbles on the surface;
two spoons (one resting on the near saucer's edge in the cup, one on the far saucer),
one more spoon lying on the table in front, and a crumpled cloth napkin lying on the
table beside the near cup. The napkin is **cloth**: a subdivided plane dropped and
crumpled onto the table with a cloth simulation (then applied), not a sculpted lump. It
all stands on a wooden table. Cups, saucers and teapot are closed solids of revolution
with thickness; the spoons are thin metal with a shallow bowl.

For the toon look, read the **toon material guide** at the end of this file before
planning the materials and lighting.

**Other views.** Only this one view is given. If you need straight views (front, side,
top) to get the profiles of the teapot, cup and saucer, make them yourself with
gpt-image-2 (`blendcua_core.load_api_keys()`; pass the bash tool a longer `timeout`, one
image takes up to about 2 minutes) and turn them into blueprints with the `blueprint`
tool -- see `Skills/Planner/blueprints-from-plates.md` and
`Skills/Planner/Gpt_images/prompting-reference-plates.md`. Generated plates and
blueprints are aids only: **reference.png is the true one, and wherever they disagree
with it, the reference wins.**

No need for fancy lighting beyond what the guide below describes. Same for the camera: pick a
sensible view that shows the whole set and move on. Do not spend actions hunting an
exact match to the reference framing.

## Toon material guide

**The toon material (from the tutorial).** Render in **EEVEE** -- the key node, *Shader
to RGB*, only works there. Every toon material is Principled BSDF -> Shader to RGB ->
Color Ramp set to **Constant** interpolation -> Material Output, so the real lighting is
cut into flat bands. Ceramic (teapot, cups, saucers): Principled white, roughness 0,
four ramp stops from light to dark: white, a pale grey-blue, a mid
blue and a dark blue for the shadow; slide the stops until the bands sit like the
reference. Lighting: an HDRI in the world (the tutorial used a Poly Haven interior HDRI
at 1K, rotated 180 degrees with a Mapping node -- the `polyhaven` tool can fetch one),
plus one Sun with angle 0.5 (sharp but slightly soft shadows) shining from behind so
the shadows fall toward the camera; the reference's big soft shadow bands come from a
window-frame shape blocking that sun. EEVEE: ambient occlusion, screen-space
reflections, bloom on; colour management Filmic (or AgX) with a High Contrast look.

**Textured toon materials use a shadow mask.** For wood, spoon, napkin and tea the
colour comes from a texture, so build it as its own node group, and separately a
**shadow mask**: a white Principled BSDF -> Shader to RGB -> Constant Color Ramp (black
where the object is in shadow, white where lit). Feed the mask into the Factor of a
**Mix Color**: B = the lit colour, A = the same colour through a Hue/Saturation/Value
node with Value lowered (the shadowed colour). Wood table: Noise texture (Object
coordinates, scale 0.5, detail 5.5, roughness 0.8, distortion 0.05) stretched by the
Mapping scale (X 0.45, Y 3.4, raise the overall scale to fit the table) into a Constant
ramp of dark brown, mid brown and light brown; shadow Value 0.3. Spoon: Principled metallic 1,
roughness 0.05 -> Shader to RGB -> Constant ramp of white, light grey and mid grey; lit
side through HSV Value 1.3, shadow side Value 0.2 for contrast. Napkin: a fabric image
texture on UVs (scale 1.5) as the base colour, roughness 1, shadow mask with a dark
grey base and a ramp of white / mid grey / very dark grey so the folds get a deep crease
shadow; shadow Value 0.4. Tea: Noise (scale 5, detail 15, distortion 2) whose vector is
a Mix Color in *Linear Light* (factor 0.65) of the Mapping vector and a **Spherical**
Gradient texture, which swirls the noise in circles like stirred tea, into a Constant
ramp of tea brown, a lighter pinkish brown and a milky peach; shadow Value 0.3. The
finishing touches from the tutorial's last part: the small bubbles on the tea surface,
and the hand-drawn dark outline round every object (Line Art or Freestyle, or an
inverted-hull outline) -- the outline is part of the look.
