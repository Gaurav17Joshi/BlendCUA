<!-- moved out of prompt_files/current_tools.md — read on demand, not in any prompt -->

# Part 5 — Wear & Tear Textures (surface damage)

Part 4's brushes carve **events** — a chipped corner, a crease along an arris,
a knock. This part covers surface **quality**: a face that is rough, pitted,
scratched or flaking everywhere, with no single place you could point at.

## ⚠️ Read this first: brush textures do not work from a script

Blender brushes can carry a texture. **You cannot use that from here.** Three
independent walls, all silent:

1. The sculpt brush is *linked* from Blender's Essentials asset library, and a
   linked datablock silently discards `brush.texture = tex` — no error, reads
   back `None`.
2. `make_local()` would fix that, but it is a no-op both when a local copy
   already exists and when the datablock has no users. The asset brush has no
   users.
3. Even with a genuine local brush, `bpy.ops.sculpt.brush_stroke` ignores it
   and resolves the asset brush anyway.

**Do not try to make brush textures work, and do not localize the brush** —
localizing costs you all brush control (measured: size 15 px and 60 px then
cut the same depth *and* width, strength 0.05 and 1.00 became
indistinguishable). `sculpt_native.LOCALIZE` is `False` and must stay that
way. Evidence: `mem/texture_test_001/steps/step_002`, reports 01-03.

Surface texture comes from **displacement** instead. It is not a downgrade:
strength is in metres and lands on the number you ask for.

## The two rules that decide whether it will look right

**FEATURE SIZE vs MESH.** Displacement cannot express detail finer than about
**eight mesh cells**. Feature size in metres is `plane_size / tile / cells`
where `tile` is the texture's `repeat_x`/`repeat_y`. Too fine does not come
out subtle, it comes out as aliased noise, and no amount of strength tuning
fixes it. Widen the feature or coarsen the tiling — subdividing the model is
the expensive answer.

**POLARITY.** `mid_level` is the map value that does *not* move. Damage that
is DARK in the map (pits, flakes, scratches) needs a HIGH mid_level so the
dark parts cut in and the intact surface stays put. Damage that is BRIGHT
(pebbles) needs a LOW one so only the bright parts lift. Get it backwards and
pits become warts.

Layers only read as separate scales when they are more than about **4x**
apart. Closer than that and the finer one simply replaces the coarser.

## S6 — `wear_textures` — the map library

Seven generators, all returning a tileable float array in 0..1, all
deterministic given `seed`. `wear_textures.LIBRARY` carries the same table as
data: `name -> (function, mid_level, strength, min_feature_mm, description)`.

| name | what it is | mid_level | strength | min feature |
|---|---|---|---|---|
| `cracked_plates` | broken slabs with crack lines between them | 0.5 | 8–20 mm | 20 mm |
| `pebbles` | rounded stones proud of a floor (**adds** material) | 0.05 | 8–20 mm | 20 mm |
| `pits` | scattered pockmarks eaten in | 1.0 | 4–12 mm | 20 mm |
| `flakes` | spalled terraces where a layer broke away | 1.0 | 4–14 mm | 25 mm |
| `scratches` | directional gouges — has an `angle` | 1.0 | 3–10 mm | width*tile |
| `erosion` | water-worn channels, rounded | 0.7 | 6–18 mm | none |
| `granular` | even coarse roughness; a finishing layer | 0.5 | 1–4 mm | 20 mm |

`erosion` has no characteristic size, so it is the safe choice on a coarse
mesh — it degrades into gentle undulation rather than into noise. `granular`
is the opposite: all high frequency, and the one most likely to alias.

```python
import wear_textures as wt
import sculpt_native as sn

fn, mid, strength, minf, desc = wt.LIBRARY["flakes"]
arr  = fn(size=1024, cells=7, seed=13)      # every param has a docstring
path = wt.write_png(step_dir + r"\assets\flakes.png", arr)
tex  = sn.image_texture("flakes", path)
tex.repeat_x = tex.repeat_y = 6             # -> feature = size/6/7
```

## S7 — `displace` — texture a whole surface

```python
sn.displace(obj_name, texture, strength, mid_level=0.5,
            direction='NORMAL', texture_coords='LOCAL',
            coords_object=None, vertex_group=None, label=None)
```

Applies immediately, so **stacking is just calling it again**. Layer coarse
then fine, each with its own seed and tiling.

`texture_coords='LOCAL'` samples an image on the object's local **XY**, which
is right for a surface lying in XY and **wrong for a vertical face** — there
the image is constant along the normal and smears into vertical stripes. For
a vertical face either use `'OBJECT'` with `coords_object` set to an Empty
whose XY plane lies parallel to the face, or use a procedural Blender texture
(`CLOUDS`, `VORONOI`, `DISTORTED_NOISE`, `STUCCI`), which are 3D fields and
have no projection problem at all.

`vertex_group` restricts the effect and **the group's weights are the
falloff** — this is how one face gets textured and its neighbours do not. Give
the weight a smoothstep ramp over a margin: a hard 0/1 mask leaves a step at
the boundary that reads as resurfacing, not weathering.

## S8 — `stroke_displace` — a textured brush stroke

The replacement for a textured brush: the texture supplies the detail, the
stroke's own falloff footprint supplies the where.

```python
sn.stroke_displace(obj_name, texture, path_world, radius, strength,
                   mid_level=0.5, hardness=0.0, tail=0.0, label=None)
```

`path_world` is a list of 3D points, `radius` is in metres. Unlike a real
brush it does not accumulate along the stroke, so the band is even end to end
rather than deepening where dabs overlap — for surface texture that is an
improvement. Returns the usual displacement report plus `footprint_verts`.

Supporting calls: `sn.stroke_footprint(obj, path, radius, hardness, tail)`
returns the per-vertex weights on their own, and `sn.make_vertex_group(obj,
name, weights)` writes any weight array as a group (bucketed — adding 600k
vertices one at a time takes minutes).

## S9 — Previews must show BOTH sizes

A path line says where a stroke goes and nothing about how wide it is or how
big the texture on it will be. Those are the two numbers most often wrong, and
both are invisible until after the stroke has run. Draw them:

```python
c = path_world[0]
strokes.append({"points": to_screen(sn.brush_circle(c, radius, n=64)),
                "smooth": False, "show_anchors": False,
                "color_hint": (60, 200, 255), "label": "brush 200mm"})
strokes.append({"points": to_screen(sn.brush_circle(c, feature_m / 2, n=40)),
                "smooth": False, "show_anchors": False,
                "color_hint": (255, 90, 90), "label": "45mm"})
```

`show_anchors: False` draws the outline with one label instead of a numbered
dot per vertex — without it a 64-point circle buries the image under its own
annotation.

Read the result like this: if the **feature circle is a large fraction of the
brush circle**, only a couple of features fit across the band and it will read
as lumps rather than as texture — raise `tile`. If the feature circle is tiny
against the mesh, it will alias — lower `tile`.

## S10 — `weathering` — the level an action should work at

`sculpt_native` has the primitives; `weathering` assembles them so a
weathering action is a dozen lines of decisions rather than 300 lines of
plumbing. Nothing in either module knows what it is weathering.

```python
import weathering as we

paths = we.vertical_face_lines(obj, normal=(0, -1, 0),
                               offsets=(-0.30, -0.10, 0.10, 0.30),
                               z0=0.06, z1=3.94, n=46)

we.preview_paths(paths, radius=0.16, face_normal=(0, -1, 0),
                 features=[("pebbles", 0.083)], label="front", note="...")

res = we.weather("Pillar", paths, radius=0.16, assets_dir=...,
                 face_normal=(0, -1, 0), group="weather_front",
                 layers=[{"texture": "erosion", "tile": 2, "strength": 0.006},
                         {"texture": "pebbles", "tile": 3, "strength": 0.004,
                          "cells": 8, "seed": 3}])
```

A layer spec can be as short as `{"texture": "pits"}` — mid_level and
strength fall back to the library's recommendation. Any other key is passed
to the generator, so `seed`, `cells`, `occupancy`, `angle` and the rest are
all available without a second call.

**`weather()` combines ALL the paths into ONE footprint and displaces each
layer through it once.** Do not loop over paths calling `displace` yourself:
that applies the texture twice wherever two bands overlap and leaves a bright
seam down the middle of every face.

It returns `before` / `after` world-coordinate arrays for the same vertices,
the per-layer reports, the footprint `weights`, and a ready `text` summary.

### Proving it stayed where it was told

```python
outside = res["weights"] <= 1e-6
mx, mean, n = sn.movement(res["before"], res["after"], mask=outside)
# mx must be 0.0000
```

Better than masking each face by hand, because the footprint IS the
definition of what was meant to change. Displacement never alters topology,
so before and after are directly comparable.

## S11 — Supporting primitives in `sculpt_native`

| call | what it is for |
|---|---|
| `face_axis(name, normal)` | Empty whose local XY lies on a face. Required for image textures on any non-XY surface — without it the map collapses into stripes running down the face, silently. |
| `drape_line(obj, a, b, dir, n)` | a straight line raycast onto the surface, so a stroke follows steps, tapers and grooves instead of leaving the model at the first profile change |
| `movement(before, after, mask)` | how far vertices actually moved, in mm — compares the same vertices rather than measuring a region against a nominal plane, which reports the model's own shape as damage |
| `brush_circle(centre, radius, normal)` | the outline for a preview's size circles |
| `strokes_footprint(obj, paths, radius, face_normal=...)` | one weight field from several paths, gated on the vertex normal so a stroke stops at an arris instead of wrapping around it |
| `make_vertex_group(obj, name, weights)` | weights as a group, bucketed — adding 600k vertices one at a time takes minutes |

`lib.view.solid_shading()` replaces the twelve-line shading block that was
copy-pasted at the top of nearly every action.

### What stays in the action

Which face, where the lines go, the brush radius, which maps at what tile,
strength and mid_level, the height range, the view angle. Those are the
decisions. As a worked example,
`mem/pillar_run_001/steps/step_003` weathers all four sides of a pillar with
one data table (`sides.py`, 96 lines, mostly the table and its reasoning) and
eight actions of about forty lines each — down from a single 299-line module
that did everything.

## Worked reference

`mem/texture_test_001` is the reference run, and is the fastest way to re-tune
any of this without touching a model:

- `steps/step_001` — why brush textures do not work (six lanes of evidence)
- `steps/step_002` — every surface-detail method compared, layered
  displacement, and vertex-group masking
- `steps/step_003` — one pebble stroke, tuned over four rounds
- `steps/step_004` — all seven maps, one stroke each, with size circles

