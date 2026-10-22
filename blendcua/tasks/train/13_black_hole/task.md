# 13_black_hole

**Black hole with accretion disc (animated)**

Reference: reference.png

Other plates for this task (the unedited original) are in
`reference/`: original.png. `dump.txt` is the transcript of the tutorial the
reference render comes from.

Only a few basic instructions (everything else is yours to plan and work out):-

Build and animate the black hole in the reference. Render in Cycles (EEVEE will not
show the materials correctly); it stays fast because everything is emission.

How the reference was made, in short: two objects and a world. The rings are a
cylinder scaled ~3x, squashed very thin, inset top and bottom and subdivided; the
centre is a smooth icosphere. The rings material is a 4D noise (scale ~50, detail ~12)
on object coordinates, warped into circles by mixing a spherical gradient into the
mapping vector (linear-light, factor ~0.1), multiplied by a second spherical gradient
so the disc fades out at its rim; that drives a colour ramp of orange-red, yellow,
black and orange into an emission shader (strength ~5), mixed with a transparent
shader so the black parts are see-through. The centre is a refraction BSDF with IOR =
1 / layer-weight facing, through a colour ramp (blend ~0.9) that makes the dark core
and the thin bright ring; turn off the object's transmission visibility. The world is
a Voronoi (scale ~600) through a colour ramp for stars. Camera far back with a long
lens (~180 mm). Animate by keying the noise W from 0 to ~0.3 and the mapping Z
rotation from 0 to ~100 over 250 frames, linear, plus a slow camera move. Cycles at
~10 samples with denoising.

(Get the animation in viewport shading to speed it up.)

The disc glow is the lighting here, so it does need to read as the light source --
but nothing beyond that. For the camera, pick a sensible view that shows the object
and move on. Do not spend actions hunting an exact match to the reference framing.
