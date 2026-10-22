# 14_robot

**TV-head robot on a wheel**

Reference: reference.png

Other plates for this task are in `reference/`: front_plate.png (reference.png on a
plain grey ground) and side_plate.png (the same robot in left profile); front_blueprint.png
and side_blueprint.png (the silhouettes of those two plates as filled outlines, contour
polygon in the matching .json) -- use them as the front and side guide images.

Only a few basic instructions (everything else is yours to plan and work out):-

Model the character in the reference: a retro TV set for a head (rounded red-brown
shell, cream front bezel, dark curved screen with a face of two glowing rectangles and a
short bar for a mouth, a channel strip and two knobs on the right, two thin antennae
with balls on top); an orange puffy zip-up jacket for the body with a front zip and two
zipped pockets; short thin dark blue rods out of the sleeve cuffs, each ending in a
polished chrome ball with three simple curved chrome fingers, so the hands hang just
below the cuffs; and, instead of legs, a short grey metal box chassis under the jacket
hem with a single large black ribbed tyre half hidden inside it, its lower half showing
below the chassis and resting on the ground, axle running left-to-right so the tread
faces the front.

Do not use tracing for the TV head use simple mesh methods, can use some tracing for jacket
and fingers but be careful with it.

Build each part as its own object and keep the proportions -- the head is nearly as
wide as the body and the arms are short and thin. The screen face is emissive; ball,
fingers and antennae are chrome. Blue backdrop as in the reference.

Deliverable besides the scene: write a short `robot_notes.md` next to the .blend that gives
helping info to another agent rigging the character and making animation,. -- the object
names and what each is (head, screen, antennae, jacket, each arm rod, ball, fingers,
chassis, tyre), where the natural pivots are (head on the neck, ball hands at the cuff,
fingers at the ball, tyre axle), which objects should move together, and how the face
works (the screen material, the emissive eye rectangles and mouth bar and how to change
their shape or brightness for an expression). Keep it to one page.

No need for fancy lighting -- keep it simple. Same for the camera: pick a sensible
view that shows the object and move on. Do not spend actions hunting an exact match to
the reference framing.
