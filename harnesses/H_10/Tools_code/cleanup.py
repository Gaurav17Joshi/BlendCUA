"""Return Blender to an empty scene between tasks, without touching the window.

    from cleanup import reset_scene
    reset_scene()

Why not `bpy.ops.wm.read_homefile()`: that reloads the startup file, which
resets the window layout — the viewport size, the shading mode, the editor
split. Those are set up by hand once at the start of a session and are a
nuisance to redo, so this deletes the *data* and leaves the *window* alone.

What accumulates across a task, and why it matters: every run leaves meshes,
materials, images (a full-resolution reference photo plus any generated
texture), node groups and orphaned datablocks behind. Blender does not free
them while anything still references them, so a session that builds four
objects back to back carries all four. Since scripts execute on the main
thread via `bpy.app.timers`, a heavy scene slows every subsequent dispatch and
eventually pushes ordinary actions past the client's 30 s timeout — at which
point the agent retries an action that is still running.
"""
import bpy


def _purge_orphans(passes: int = 4) -> int:
    """Delete unreferenced datablocks. Repeated: freeing one orphans the next.

    A material holds an image, an image holds nothing — deleting the mesh
    orphans the material, and only the pass *after* that orphans the image.
    Four passes settles every chain we have in practice.
    """
    removed = 0
    for _ in range(passes):
        before = sum(len(getattr(bpy.data, c)) for c in
                     ("meshes", "materials", "images", "node_groups",
                      "textures", "curves", "armatures", "actions"))
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True,
                                       do_recursive=True)
        after = sum(len(getattr(bpy.data, c)) for c in
                    ("meshes", "materials", "images", "node_groups",
                     "textures", "curves", "armatures", "actions"))
        removed += before - after
        if before == after:
            break
    return removed


def reset_scene(*, keep_camera: bool = False) -> dict:
    """Empty the scene and free its data. Returns what was removed."""
    if bpy.context.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass

    before = {c: len(getattr(bpy.data, c)) for c in
              ("objects", "meshes", "materials", "images", "node_groups")}

    for obj in list(bpy.data.objects):
        if keep_camera and obj.type == "CAMERA":
            continue
        bpy.data.objects.remove(obj, do_unlink=True)

    # Images are the expensive ones — a reference photo is tens of megabytes in
    # memory. They survive orphan purging while a fake user is set, which
    # `load_reference` and the bake tools both do.
    for img in list(bpy.data.images):
        if img.name in ("Render Result", "Viewer Node"):
            continue
        img.use_fake_user = False
        try:
            bpy.data.images.remove(img, do_unlink=True)
        except RuntimeError:
            pass

    for coll in list(bpy.data.collections):
        if not coll.objects and not coll.children:
            bpy.data.collections.remove(coll)

    purged = _purge_orphans()

    after = {c: len(getattr(bpy.data, c)) for c in
             ("objects", "meshes", "materials", "images", "node_groups")}
    result = {"before": before, "after": after, "orphans_purged": purged}
    print(f"[cleanup] {before} -> {after}  (+{purged} orphans purged)")
    return result
