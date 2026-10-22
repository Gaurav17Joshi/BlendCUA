---
name: checking-invisible-data
description: How to see UVs, weights and other per-vertex data a render does not show — and the analytical UV unwrap that removes viewport dependence.
evidence: 08_desk_chair_run_001 step_003; 14_sneaker_run_001 step_003
---

# Checking invisible data

Some correctness questions have no visual representation in a normal render. UV
coordinates are the clearest case: a wrong unwrap still produces a render that
looks plausible at a glance, especially with a densely patterned texture. The move
is to **make the invisible thing visible on something familiar**, then look at
that.

## Dump it, draw it on the source image

```python
import bmesh, json

def dump_uvs(obj_name, out_path):
    obj = bpy.data.objects[obj_name]
    bm = bmesh.new(); bm.from_mesh(obj.data)
    uv = bm.loops.layers.uv.active
    faces = [[tuple(l[uv].uv) for l in f.loops] for f in bm.faces]
    bm.free()
    json.dump({"faces": faces}, open(out_path, "w"))
```

```python
from PIL import Image, ImageDraw
im = Image.open("Bat.jpg").convert("RGB"); w, h = im.size
draw = ImageDraw.Draw(im)
for face in faces:
    pts = [(u * w, (1 - v) * h) for u, v in face]      # V is bottom-up
    draw.line(pts + [pts[0]], fill=(255, 140, 0), width=3)
```

Reading that image immediately showed the UV wireframe sitting off the wing's real
vein pattern — obvious once drawn, invisible in the material-preview render.

Draw on a blank grid instead of the photo when you want the UV *layout* rather
than its alignment. Either way this replaces the UV Editor entirely; no GUI
needed.

## The bug it usually finds: `project_from_view` drifts

`bpy.ops.uv.project_from_view` maps each vertex's on-screen position to a UV
coordinate, which only works if the viewport is framed **exactly** to the image's
bounds at the moment you call it. `fit_objects_ortho_view`'s ratio fit only
guarantees a tight fit in the *limiting* dimension — a portrait reference in a
landscape region leaves a margin on the other axis, and the UVs land in the wrong
sub-region of 0–1 space.

## The fix: compute UV analytically

Do not fight the framing — remove the dependency. A reference Empty has a fixed,
known transform, which is a complete description of where the image sits in 3D. So
inverse-transform each vertex through it:

```python
ref = bpy.data.objects["BatRef"]
img_w, img_h = ref.data.size
size = ref.empty_display_size
if img_w >= img_h:
    rect_w, rect_h = size, size * img_h / img_w
else:
    rect_w, rect_h = size * img_w / img_h, size
ox, oy = ref.empty_image_offset            # default (-0.5, -0.5) = centred
ref_inv = ref.matrix_world.inverted()

def world_to_uv(world_pt):
    local = ref_inv @ world_pt
    return (local.x / rect_w - ox, local.y / rect_h - oy)
```

then write it straight into each loop via bmesh. No viewport state involved, so it
cannot drift. **Keeping a fixed, known-transform reference Empty is what makes
this available** — it is worth doing for that reason alone.

## Which to use

- **Project from view** — fine for a rough unwrap, or when object and reference
  share an aspect ratio.
- **Analytical inverse-transform** — whenever the UV must line up precisely with a
  placed reference. Same effort, no drift.
- **Neither** solves a genuinely round surface: both are top-down projections, so
  front and back points land on the same UV. That is a limitation of the
  projection, not of the technique.

## Perspective renders need the camera's frame

For a textured surface judged by an elevated or perspective product camera,
`project_from_view` or a cylindrical unwrap can produce a plausible layout while
putting the painted pixels on the wrong rendered faces. Project the visible
faces through the active camera at the exact render resolution and pixel aspect,
put the hidden side on a deliberate separate island, and set both `active` and
`active_render` to the layer that was painted. A valid UV-layout PNG is not
render proof: finish with a fresh active-camera image and crop the feature.

## Generalising

The pattern is: *dump the data layer, redraw it on something you can already read,
`Read` the picture.* It applies to vertex groups (colour verts by weight), normals
(draw them as short segments from each face centre), selection state, and anything
else that lives in the mesh and not in the shading.
