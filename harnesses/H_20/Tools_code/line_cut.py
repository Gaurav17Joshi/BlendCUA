"""line_cut — cut an opening into a body between lines read from the photograph.

A mouth, a slot, a seam, a socket: the reference shows two edges, the model needs the material
between them gone. Used by hand for the shark's mouth (mem/08_shark_run_002 step 2, 2026-09-12):
two straight lines from the photo's gum band, one full-width Boolean, a closed mesh. This module
holds only the parts that are the same for every such cut and that went wrong when done by feel;
the mask, the lines and whatever is planted on the new lips are a few lines each and are written
in the step (Skills/Executor/cut-openings-from-traced-lines.md says how).

Shell side (PIL + numpy):
    fr = load_frame(".../photo_frame.json")                # the photo Empty: W, H, display_size, x0, z0
    x, z = world_from_px(u, v, fr)                         # traced rows -> world XZ through the frame
    draw_lines_on_render(render_png, photo_png, [(pts_a, (255,40,40)), (pts_b, (255,170,0))], fr, out_png)
    silhouette_gap(stations_json, photo_png, fr)           # does the mesh have the mass under the lines?
Blender side:
    cam = frame_camera("FrameCam", fr)                     # ortho through the frame, on the viewing side
    frame_render(cam, fr, out_png, keep=["SharkBody"])     # render px = photo px / 2, registered
    st = stations(ob, -4.05, -2.0)                         # zmin / zmax / half-width per x station
    cutter = slab("MouthCutter", poly_xz, -1.2, 1.2)       # closed solid from an XZ polygon, full width
    boolean(ob, cutter)                                    # EXACT difference, safe after a checkpoint load
    paint_plane_faces(ob, [{"line": (k, b), "x_range": (x0, x1)}], "MouthInterior")
    audit(ob)                                              # boundary_edges 0, non_manifold_edges 0 or not done

Built in because it bit once: the camera sits on the side the image Empty faces (-Y) or the
render is mirrored; a self-crossing profile makes an inside-out solid that the Boolean drops in
silence (slab refuses it); modifier_apply needs a window override right after a file load; the
cut faces are found by their plane, not by a point-in-polygon test on centres (that paints
saw-teeth because the faces lie ON the polygon's edges).
"""
from __future__ import annotations

import json
import math

import numpy as np


# ---- the photo frame -------------------------------------------------------------------------


def load_frame(path):
    """photo_frame.json: W, H (px), display_size (world width of the image Empty), x0, z0 (its centre)."""
    return json.load(open(path, encoding="utf-8"))


def world_from_px(u, v, fr):
    """Photo pixel (u right, v down) -> world (X, Z) through the frame."""
    W, H, s = fr["W"], fr["H"], fr["display_size"]
    return (fr["x0"] + (u / W - 0.5) * s, fr["z0"] + (H / 2 - v) / W * s)


def px_from_world(x, z, fr):
    """World (X, Z) -> photo pixel (u, v)."""
    W, H, s = fr["W"], fr["H"], fr["display_size"]
    return ((x - fr["x0"]) / s * W + W / 2, H / 2 - (z - fr["z0"]) / s * W)


# ---- shell side: look before cutting ---------------------------------------------------------


def draw_lines_on_render(render_png, photo_png, lines, fr, out_png, crop=None, ghost=0.3, scale=2):
    """The preview: polylines in world XZ (`[(points, rgb), ...]`) drawn on the frame render of the body
    with the photo ghosted under it. `crop` = (l, t, r, b) in render px. Look at this before cutting."""
    from PIL import Image, ImageDraw
    photo = Image.open(photo_png).convert("RGBA")
    render = Image.open(render_png).convert("RGBA")
    canvas = Image.new("RGBA", render.size, (70, 70, 70, 255))
    g = photo.resize(render.size)
    g.putalpha(g.split()[3].point(lambda a: int(a * ghost)))
    canvas.alpha_composite(g)
    canvas.alpha_composite(render)
    d = ImageDraw.Draw(canvas)
    f = fr["W"] / render.size[0]
    for pts, col in lines:
        d.line([tuple(c / f for c in px_from_world(x, z, fr)) for x, z in pts], fill=tuple(col) + (255,), width=3)
    if crop:
        canvas = canvas.crop(crop)
        canvas = canvas.resize((canvas.width * scale, canvas.height * scale), Image.LANCZOS)
    canvas.convert("RGB").save(out_png)
    return out_png


def silhouette_gap(stations, photo_png, fr):
    """Does the mesh have the mass the lines assume? Per station: the mesh's lowest z against the photo's
    silhouette bottom at that x, in px. The shark's underside ran 10-37 px above the photo's chin under
    the mouth: there was no lower jaw to cut a mouth into, so the cut had to be the simple one."""
    from PIL import Image
    al = np.asarray(Image.open(photo_png).convert("RGBA"))[..., 3] > 128
    out = []
    for s in stations:
        u = int(round(px_from_world(s["x"], 0, fr)[0]))
        col = np.nonzero(al[:, u])[0] if 0 <= u < al.shape[1] else []
        if len(col):
            pz = world_from_px(u, col.max(), fr)[1]
            out.append({"x": s["x"], "mesh_zmin": s["zmin"], "photo_zmin": pz,
                        "gap_px": (s["zmin"] - pz) / fr["display_size"] * fr["W"]})
    return out


# ---- Blender side ----------------------------------------------------------------------------


def frame_camera(name, fr, distance=12.0):
    """Orthographic camera through the photo frame from the side the image Empty faces (-Y), +X to the
    right like the photo, ortho_scale = the Empty's size. At (W/2, H/2) every render px is one photo px."""
    import bpy
    sc = bpy.context.scene
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = fr["display_size"]
    cam.data.clip_end = 1000
    cam.location = (fr["x0"], -abs(distance), fr["z0"])
    cam.rotation_euler = (math.pi / 2, 0.0, 0.0)
    return cam


def frame_render(cam, fr, path, keep=None, colour_by="MATERIAL"):
    """Workbench render through `cam` at half photo size, transparent film. `keep` = object names to show
    (their children too); everything else is hidden for the shot and restored after."""
    import bpy
    sc = bpy.context.scene
    keep = set(keep or [])
    prev_hide = {o.name: o.hide_render for o in bpy.data.objects if o.type == "MESH"}
    if keep:
        for o in bpy.data.objects:
            if o.type == "MESH":
                o.hide_render = not (o.name in keep or (o.parent is not None and o.parent.name in keep))
    prev = (sc.camera, sc.render.resolution_x, sc.render.resolution_y, sc.render.filepath,
            sc.render.film_transparent, sc.render.engine, sc.render.resolution_percentage)
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = colour_by
    sc.render.film_transparent = True
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = fr["W"] // 2, fr["H"] // 2
    sc.render.filepath = path
    # No render window: the GUI's default (render_display_type WINDOW) opens a window from inside
    # the server's timer callback, and one dog run (2026-09-12, step 3) blocked there for the whole
    # 2000 s dispatch timeout after two hours of scripts. NONE renders straight to the file.
    prefs = bpy.context.preferences.view
    prev_display = prefs.render_display_type
    prefs.render_display_type = "NONE"
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        prefs.render_display_type = prev_display
    (sc.camera, sc.render.resolution_x, sc.render.resolution_y, sc.render.filepath,
     sc.render.film_transparent, sc.render.engine, sc.render.resolution_percentage) = prev
    for n, h in prev_hide.items():
        if bpy.data.objects.get(n):
            bpy.data.objects[n].hide_render = h
    return path


def stations(ob, x0, x1, step=0.02, centre_hw=0.06):
    """Evaluated mesh per x station: zmin, zmax, ymax (half-width), z_bottom_centre (underside on the
    centre line). The table the cut is decided on."""
    import bpy
    dg = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(dg).to_mesh()
    co = np.array([ob.matrix_world @ v.co for v in me.vertices])
    out = []
    for x in np.arange(x0, x1, step):
        m = (co[:, 0] >= x) & (co[:, 0] < x + step)
        if m.sum() < 3:
            continue
        s = co[m]
        near = s[np.abs(s[:, 1]) < centre_hw]
        out.append({"x": round(float(x + step / 2), 4), "zmin": float(s[:, 2].min()), "zmax": float(s[:, 2].max()),
                    "ymax": float(np.abs(s[:, 1]).max()),
                    "z_bottom_centre": float(near[:, 2].min()) if len(near) else float(s[:, 2].min())})
    return out


def _dedupe(poly):
    out = []
    for p in poly:
        if not out or abs(p[0] - out[-1][0]) + abs(p[1] - out[-1][1]) > 1e-5:
            out.append(tuple(p))
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) + abs(out[0][1] - out[-1][1]) < 1e-5:
        out.pop()
    return out


def _self_crossing(P):
    n = len(P)

    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        for j in range(i + 2, n):
            if (j + 1) % n == i:
                continue
            c, d = P[j], P[(j + 1) % n]
            if ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d):
                return True
    return False


def slab(name, poly_xz, y0, y1, y_step=0.04):
    """A closed solid: the XZ polygon extruded from y0 to y1, side faces subdivided every y_step along Y
    (a Boolean leaves them as the cut faces; long thin faces shade in stripes). Raises on a self-crossing
    profile: that solid is inside-out and a Boolean drops it without a word."""
    import bpy, bmesh
    poly = _dedupe(poly_xz)
    if len(poly) < 3 or _self_crossing(poly):
        raise ValueError(f"{name}: the XZ profile is degenerate or crosses itself ({len(poly)} points)")
    bm = bmesh.new()
    v0 = [bm.verts.new((x, y0, z)) for x, z in poly]
    v1 = [bm.verts.new((x, y1, z)) for x, z in poly]
    caps = [bm.faces.new(v0[::-1]), bm.faces.new(v1)]
    n = len(poly)
    for i in range(n):
        bm.faces.new((v0[i], v0[(i + 1) % n], v1[(i + 1) % n], v1[i]))
    bmesh.ops.triangulate(bm, faces=caps)
    if y_step > 0:
        long_edges = [e for e in bm.edges if abs(e.verts[0].co.y - e.verts[1].co.y) > y_step * 1.5]
        cuts = max(1, int(round(abs(y1 - y0) / y_step)) - 1)
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=cuts, use_grid_fill=True)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def boolean(target, cutter, op="DIFFERENCE", delete_cutter=True, fill=True):
    """One EXACT Boolean of `cutter` on `target`, cutter removed after. Works right after a checkpoint
    load inside the server (explicit window override) and keeps the Boolean first in the stack so it
    acts on the raw mesh when an armature modifier is present. fill=True closes any sliver the cut opened
    and recalculates normals. Returns audit(target)."""
    import bpy, bmesh
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    target.hide_set(False)
    target.hide_viewport = False
    mod = target.modifiers.new("LineCut", "BOOLEAN")
    mod.operation = op
    mod.solver = "EXACT"
    mod.object = cutter
    target.modifiers.move(len(target.modifiers) - 1, 0)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    wm = bpy.context.window_manager or bpy.data.window_managers[0]
    win = wm.windows[0]
    area = next((a for a in win.screen.areas if a.type == "VIEW_3D"), win.screen.areas[0])
    region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region, active_object=target,
                                   object=target, selected_objects=[target], selected_editable_objects=[target]):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    if delete_cutter:
        bpy.data.objects.remove(cutter, do_unlink=True)
    if fill:
        bm = bmesh.new()
        bm.from_mesh(target.data)
        open_edges = [e for e in bm.edges if len(e.link_faces) == 1]
        if open_edges:
            bmesh.ops.holes_fill(bm, edges=open_edges, sides=8)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(target.data)
        bm.free()
    return audit(target)


def audit(ob):
    """verts, polys, boundary_edges, non_manifold_edges of the raw mesh: 0 and 0, or the cut is not done."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    b = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    nm = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    bm.free()
    return {"verts": len(ob.data.vertices), "polys": len(ob.data.polygons), "boundary_edges": b, "non_manifold_edges": nm}


def paint_plane_faces(ob, planes, mat_name="CutInterior", colour=(0.16, 0.035, 0.03), tol=0.004, flat=True):
    """Give the faces a cutter made their own material, found by the plane they lie on:
    {"line": (k, b), "x_range": (x0, x1)} -> faces on z = k*x + b (normal along Z) between x0 and x1;
    {"x": x0, "z_max": z}                 -> a vertical wall at x0 below z.
    Not a point-in-polygon test on centres: the cut faces lie ON the polygon's edges and flip on float
    noise, which paints saw-teeth along the lips. Returns the face count."""
    import bpy
    mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
    mat.diffuse_color = (*colour, 1.0)
    mat.use_nodes = True
    bs = mat.node_tree.nodes.get("Principled BSDF")
    if bs:
        bs.inputs["Base Color"].default_value = (*colour, 1.0)
        bs.inputs["Roughness"].default_value = 0.7
    if ob.data.materials.get(mat_name) is None:
        ob.data.materials.append(mat)
    idx = list(ob.data.materials).index(mat)
    n = 0
    for p in ob.data.polygons:
        c = ob.matrix_world @ p.center
        hit = False
        for pl in planes:
            if "line" in pl:
                k, b = pl["line"]
                x0, x1 = pl["x_range"]
                hit |= x0 - tol <= c.x <= x1 + tol and abs(c.z - (k * c.x + b)) < tol and abs(p.normal.z) > 0.8
            else:
                hit |= abs(c.x - pl["x"]) < tol and c.z < pl["z_max"] + tol and abs(p.normal.x) > 0.8
        if hit:
            p.material_index = idx
            n += 1
        p.use_smooth = not (hit and flat)
    return n
