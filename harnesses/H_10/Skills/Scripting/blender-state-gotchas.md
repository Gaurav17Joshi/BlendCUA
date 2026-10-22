---
name: blender-state-gotchas
description: Read this when a Blender-side build script produces objects that are missing, all sitting at the origin, or a viewport call that raises on an enum - three state facts about the 5.x server that each cost an hour and produce no error until much later: same-name replacement in meshgen.finish, a stale matrix_world before view_layer.update(), and no MATERIAL viewport shading while the render engine is Workbench.
evidence: mem/09_thors_hammer_run_003 steps/step_002 (rivets vanished, then all at the origin; fixes in scripts/th_head.py) and steps/step_004-005 (material_shading raising after a Workbench experiment; the engine guard in 01_materials.py and the checkpoint actions) (2026-09-13)
---

# Three Blender state facts that fail silently

1. **`meshgen.finish(bm, name)` replaces any object of that name.** Building twenty rivets
   with `finish(bm, "rivet")` leaves one rivet and a `ReferenceError` on the next access
   to the removed ones. Give temporaries unique names (`"rv_%02d" % i`) and join them; the
   replace-by-name behaviour is right for replayed actions, wrong for parts made in a loop.

2. **A just-created object's `matrix_world` is identity until `bpy.context.view_layer.update()`.**
   Setting `obj.location` does not update the matrix inside the same script. Any code that
   reads `matrix_world` to bake or join new objects (a join helper, a dump for a shell-side
   audit) puts every one of them at the origin unless the view layer is updated first. The
   audit that caught it: min/max of the dumped vertices, all within +-0.034 of zero.

3. **With `scene.render.engine == "BLENDER_WORKBENCH"` the viewport has no `MATERIAL` shading**,
   so `lib.view.material_shading` raises `enum "MATERIAL" not found`. Any experiment that
   switches the engine to Workbench for fast flat renders leaves it there for the next action;
   set the engine to EEVEE (or Cycles) before a material-shaded screenshot, or restore it at the
   end of the experiment.
