# 18_tree

**Gnarled tree with leaf-card canopy**

Reference: reference.png

Other plates in `reference/`: original.png (same as reference.png); trunk_only.png,
trunk_thick_branches.png, trunk_branches.png (the bare trunk in three stages);
branch.png (one forked branch); leaf_card.png (a leaf cluster as an alpha image on a
rough cage mesh); leaf_clusters.png (the kind of leaf-cluster images to make).

Only a few basic instructions (everything else is yours to plan and work out):-

Build the tree in the reference: a thick, twisted, dark-barked trunk flaring into root
buttresses, leaning and splitting into heavy limbs, then thinner branches and a full
canopy of pale green leaf clusters. Work in this order:

1. **Trunk and thick limbs** from trunk_thick_branches.png -- trace it (`outline_trace`)
   or use any simpler method, keeping the lean, twist, root flare and limb positions.
2. **Sculpt the trunk jagged** (`sculpt_native` / `sculpt`): add lots of the features
   the plate shows -- twisting ridges, deep grooves, folds, root buttresses, knots --
   not a smooth tube. Bark material with strong bump goes on top of the sculpt, not
   instead of it.
3. **Leaf images from gpt-image-2**, like leaf_clusters.png: one spray per image on a
   plain background, 3-4 images (more for variety). Callable from `bash` in planning or
   build (`blendcua_core.load_api_keys()`; pass a longer `timeout`, one image takes up
   to ~2 min). Cut each to alpha, with no halo. Leaves are not modelled one by one.
4. **Leaf cards**: each spray on a rough cage, as in leaf_card.png
   (`Skills/Planner/Objects/flat-objects.md`, method B); bend and scale the cages so no
   two are alike.
5. **Branches**: duplicate, scale and bend branch.png; get a few more from gpt-image-2
   and trace them if needed.
6. **Leafy branches**: put lots of leaf cards along a branch; make several different
   ones.
7. **Fill the canopy**: attach the leafy branches to the limbs and repeat, many times,
   until the canopy is as full as the reference -- dense pale green masses with only
   small gaps. A sparse canopy is not finished.

No need for fancy lighting -- keep it simple. Same for the camera: pick a sensible
view that shows the object and move on. Do not spend actions hunting an exact match to
the reference framing.
