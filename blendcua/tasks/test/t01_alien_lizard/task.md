# t01_alien_lizard

**Alien lizard bust**

Reference: reference.png

Other plates for this task are in `reference/`: original.png (the same as
reference.png); front_plate.png and side_plate.png (the same creature re-projected
straight on and in left profile, on a plain grey ground); front_blueprint.png and
side_blueprint.png (the silhouettes of those two plates as filled outlines, with the
contour polygon in the matching .json).

Only a few basic instructions (everything else is yours to plan and work out):-

Sculpt the creature bust in the reference: a green reptilian alien, head, neck and
upper chest only, cut off flat below the shoulders like a portrait bust. Bald domed
head; two glossy eyes on each side (a large one forward, a smaller one behind it) set
in wrinkled sockets; two nostril pits on the snout; a wide lipless mouth with small
pointed teeth and the flat red tongue hanging out; a small ear pit on the cheek; and
the long, thin skin flap that hangs from the back of the head down past the neck.

**This is a not just sculpting task (tho sculpting is an imp part of it). Work in this order:**

1. **Base mesh, made by you.** Build the rough shape of the bust as one simple mesh
   from the reference and the plates: the domed skull, the long snout, the jaw, the neck
   and the shoulder mass, with the right proportions from the front and the side. You may
   trace the blueprints for the outline, but do not rely on tracing alone. A traced
   outline gives the silhouette, not the volume, so shape the cross-sections yourself
   from what the reference shows. Keep this mesh low in vertices and clean.
2. **Subdivide.** Add a Subdivision Surface modifier to the base mesh, and apply it, to
   get enough vertices and a rounder, smooth form to sculpt on (remesh if the density
   is uneven).
3. **Sculpt the features** into that mesh (`sculpt_native` / `sculpt`): the eye sockets
   with their wrinkles, the brow ridges, the nostril pits, the mouth opening and its
   corners, the ear pit, the jaw line, the throat folds and the shoulder mass. The skin
   flap at the back of the head is sculpted or built as part of the same body.
4. **Separate parts:** the eyes, the teeth and the tongue are separate objects, seated
   in the sculpted sockets and mouth.
5. **Skin:** the fine scaly, leathery texture is a material (procedural bump/noise),
   not sculpted.

Dark green backdrop as in the reference. No need for fancy lighting -- keep it simple.
Same for the camera: pick a sensible view that shows the object and move on. Do not
spend actions hunting an exact match to the reference framing.
