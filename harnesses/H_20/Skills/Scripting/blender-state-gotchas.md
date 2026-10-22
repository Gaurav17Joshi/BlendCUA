---
name: blender-state-gotchas
description: Read this when a Blender-side build script produces objects that are missing, all sitting at the origin, or a viewport call that raises on an enum - state facts about the 5.x server that each cost an hour and produce no error until much later: same-name replacement in meshgen.finish, a stale matrix_world before view_layer.update(), no MATERIAL viewport shading while the render engine is Workbench, the default 1.06 pixel aspect, ShaderNodeMix's same-named float/colour sockets, render windows that hang the server, and helper modules that need importlib.reload.
evidence: mem/09_thors_hammer_run_003 steps/step_002 (rivets vanished, then all at the origin; fixes in scripts/th_head.py) and steps/step_004-005 (material_shading raising after a Workbench experiment; the engine guard in 01_materials.py and the checkpoint actions) (2026-09-13); mem/16_chocolate_cup_decor_run_002 and blends/16_chocolate_cup_decor_run_002/LESSONS.md A3, B7, B13 (facts 4-7, 2026-09-16)
---

# Blender state facts that fail silently

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

## Four more, from the chocolate cup (task 16, hand run_002, 2026-09-16)

Evidence: `mem/16_chocolate_cup_decor_run_002` and `blends/16_chocolate_cup_decor_run_002/LESSONS.md`
A3, B7, B13.

4. **The server's default scene has `render.pixel_aspect_y = 1.06`.** Every render comes out 6%
   short, and `world_to_camera_view` honours it, so a projection solve or audit is fitted to a
   squashed image. Nothing in `Tool_scripts` resets it. Set `pixel_aspect_x = pixel_aspect_y = 1.0`
   in the first build action (so every checkpoint carries it) and assert it in any audit that
   renders or projects. See `Executor/measure-the-reference-camera.md`.

5. **`ShaderNodeMix` has float, vector and colour sockets that share the names `A`, `B` and
   `Result`**, and `node.inputs["A"]` returns the *float* one. Linking a colour into it does
   nothing visible. Select the socket by name **and** `socket.type == 'RGBA'`.

6. **`bpy.ops.render.render` and `render.opengl` (used by `runtime.shot`) can open a render window
   from the server process and hang or kill it.** Wrap every render in
   `preferences.view.render_display_type = 'NONE'` and restore it afterwards.

7. **The server is one long-lived process, so an edited helper module is ignored** until it is
   `importlib.reload`-ed. After editing a helper, reload it in the action that uses it, or the
   action runs yesterday's code.
