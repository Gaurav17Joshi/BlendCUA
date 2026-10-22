<!-- moved out of prompt_files/current_tools.md — read on demand, not in any prompt -->

# Part 4 — Sculpting Tools

`sculpt_native` drives Blender's OWN sculpt brushes. It is not a
reimplementation: the vertices are moved by Blender's sculpt engine, so every
brush, the boolean trim gestures and the mesh filters are available.

Sculpting needs a DENSE mesh. Subdivide first (SIMPLE subsurf keeps the
silhouette; Catmull-Clark rounds it) — a few thousand verts will give you a
polygonal notch instead of a chip.

```python
import sculpt_native as sn
```

## Summary table

| # | Call | Does |
|---|------|------|
| S1 | `apply_stroke(obj, brush, stroke, **settings)` | drag one brush along one screen path |
| S2 | `apply_strokes(obj, brush, [stroke, ...])` | same brush, several paths |
| S3 | `trim_box(obj, x0,y0,x1,y1)` | boolean-cut a rectangle through the model |
| S4 | `trim_lasso(obj, [(x,y), ...])` | boolean-cut an arbitrary drawn outline |
| S5 | `mesh_filter(obj, kind, strength, iterations)` | whole-mesh SMOOTH / RELAX / RANDOM / SHARPEN / … |

## S1 — Brush stroke

`stroke` is the SAME dict `paint.stroke_lines_preview()` takes, so a path can
be previewed with the painting overlay and then sculpted with it unchanged.
Coordinates are normalised screen, y DOWN.

```python
rep = sn.apply_stroke(
    "Pillar", 'CREASE',
    {"points": [(0.42, 0.20), (0.42, 0.60)], "waviness": "subtle", "seed": 7},
    size=32,           # SCREEN PIXELS, not world units
    strength=0.6,
    invert=False,      # True = carve instead of build
)
print(rep["max_in"], rep["max_out"])   # signed, in metres
```

Useful brushes: `DRAW`, `DRAW_SHARP`, `CLAY`, `CLAY_STRIPS`, `CREASE`, `BLOB`,
`INFLATE`, `PINCH`, `PLANE`, `MULTIPLANE_SCRAPE`, `SMOOTH`, `LAYER`, `NUDGE`,
`SNAKE_HOOK`. `DEFAULTS` in the module has a sane starting point for each.

## S3/S4 — Trim gestures

Real booleans. **They rebuild topology** (measured 659,458 → 610,648 verts), so
nothing holding vertex indices survives across one. `trim_lasso` is the useful
one for damage: the outline you draw IS the silhouette of the missing chunk,
so a break can be drawn to look broken instead of being derived from a falloff.

```python
sn.trim_lasso("Pillar", [(0.50,0.30), (0.56,0.28), (0.58,0.35), ...])
```

## ⚠️ Six things that will waste your time

1. **Size is in SCREEN PIXELS.** A brush is as big as it looks in the
   viewport. Sculpt from a square-on ortho view or the far end of a stroke
   covers more world space than the near end.
2. **Author strokes inside the object's screen rect.** Project the object's
   `bound_box` and lay paths out inside it. A path that misses raycasts to
   nothing and `apply_stroke` raises. Do not write screen positions by eye:
   the viewport is not square, so an object fitted to 92% of the height may
   only span x 0.15–0.85.
3. **`PLANE` does nothing until you set `plane_height`/`plane_depth`.** Both
   are 0.0 on a bare brush datablock, which is zero range — it will run at
   strength 0.9 and move exactly 0 vertices without complaint. They name the
   side of the plane the brush REACHES INTO, not the direction it pushes:
   `height 1 / depth 1` = flatten, `height 1 / depth 0` = scrape (cuts in),
   `height 0 / depth 1` = fill (builds out).
4. **The clay brushes need `plane_offset`.** With offset 0 on an already-flat
   surface the target plane is the surface, so they move nothing.
5. **Symmetry is OFF here by default** (Blender's default is X ON, which
   mirrors every stroke). Pass `symmetry=(True, False, False)` if you want it.
6. **Nothing is predictable — measure.** Every call returns signed
   displacement along the original normals (`max_out`, `max_in`,
   `mean_signed`). Set size/strength, read the number, adjust. Do not assume
   a strength value means a depth.

---

