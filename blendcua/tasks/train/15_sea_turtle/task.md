# 15_sea_turtle

**Green sea turtle**

Reference: reference.png

Other plates for this task are in `reference/`: original.jpg (the unedited
photo), and three gpt-image-2 plates: top_plate.png (from directly above),
bottom_plate.png (from directly below) and side_plate.png (left profile). Each
plate has a blueprint beside it (top_blueprint.png, side_blueprint.png,
bottom_blueprint.png, from the `blueprint` tool) with the contour polygon in the
.json next to it.

Only a few basic instructions (everything else is yours to plan and work out):-

Model the green sea turtle in the reference. This one is not low poly -- keep
enough geometry for the shell dome and the flipper shapes to read properly. Use the plates themselves for the surface: make the body
follow the top plate so that the plate image can be used directly as the carapace
texture (look at step 5 of the bat plan, plans/Bat/Bat_plan.md: put the image in
Blender, fit the model to it, and UV-project it on), the bottom plate the same way
for the plastron, and the side plate for the flanks, head and neck. The scutes and
the scale pattern come from the images, not from modelling.

Then make the four flippers (the front pair are the fore-flippers, the back pair
the hind flippers) as their own pieces: trace each one from the top blueprint,
build it as a thin mesh pushed out from the body at its root, and texture it with
its own region cut out of the top and bottom plates.

Then rig it -- a bone chain per flipper plus head and tail -- and animate it
swimming: the fore-flippers stroke down and up like wings, the hind flippers
trail and steer, over a short loop. (Note get the animation in viewport shading to
speed it up)

The plates and blueprints are already made -- use them rather than generating your
own.

No need for fancy lighting -- keep it simple. Same for the camera: pick a
sensible view that shows the object and move on. Do not spend actions hunting
an exact match to the reference framing.
