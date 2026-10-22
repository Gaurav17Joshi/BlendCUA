---
name: blueprints-from-plates
description: Read this when a task should be built from straight views and only a photo exists — how to make the plates (gpt-image-2, front / side / top, on pure white), turn each plate into a BLUEPRINT drawing (pale silhouette fill, one dark contour, light construction strokes, measured landmarks) with the blueprint tool, verify it against the photo, and hand both plate and blueprint to the build. The blueprint is a measurement with a picture attached, not clip-art.
evidence: plans/04_skull front/side_blueprint.png (the hand skull built from them at 1.5 / 2.0 px residual); tasks/train/10_low_poly_dog and 09_thors_hammer reference/ (plates and blueprints made 2026-09-12 with Tool_scripts/make_task_plates.py and Tools_code/blueprint.py)
---

# What a blueprint is here

`plans/04_skull/side_blueprint.png` is the model: the subject's silhouette filled pale
blue on a near-white page, its outline drawn once as a dark contour, and inside it thin
light strokes for the construction the builder needs — orbit circles, the brow band, the
nasal bridge, the tooth arcs, the ramus. Nothing else: no shading, no texture, no
background, no shadow. It exists because a plate *photograph* is hard to trace (shading
and highlights confuse a threshold, a cast shadow becomes part of the mask) and a drawing
is easy: the fill *is* the mask, the contour *is* the polygon, and the same script that
drew it wrote those numbers to a JSON beside it.

## 1. Make the plates

`python Tool_scripts/make_task_plates.py <task>` (add the task's job list in `JOBS`; prompts
come from `generate_views_gpt_image.py`, rules in `Gpt_images/prompting-reference-plates.md`).
Ask for pure white background, no ground, no shadow (`BG_WHITE`), the same pose and markings
as the photo, and say which view the photo already is. Plates land in
`tasks/train/<task>/reference/{front,side,top}_plate.png` with a contact sheet.

Then **verify identity** before anything else: same object, same pose, same proportions
between plates (the dog's height in the side and front plates must agree, the hammer head's
width in front and top must agree). A plate that invents a different object is thrown away
and re-prompted; a plate you keep is a plate you measure from.

## 2. Draw the blueprint

```
python Tool_scripts/Tools_code/blueprint.py reference/side_plate.png reference/side_blueprint.png --marking tan
```

`blueprint.make_blueprint` masks the subject against the plate's own border colour (or its
alpha), keeps the largest piece, fills its holes, traces the outline (`outline_trace`), and
draws: the pale fill, the contour, the **inner strokes** (strong edges of the smoothed
luminance well inside the outline, pieces of at least 60 px), the **marking strokes** (the
boundary of a named colour — `tan`, `dark`, `light`, `red`, `gold` — so a dog's tan legs, a
gold band or a red wrap become lines), and any **landmarks** you pass (`circles`, `lines` in
plate px). It writes `<out>.json`: size, background, bbox, the contour polygon, stroke
counts, landmarks. That JSON is the build input; the PNG is what the builder looks at in
Blender next to the plate.

- Plates on pure white trace at the default tolerance. A grey plate with a cast shadow
  (the skull's) does not: the shadow joins the mask at the default and a higher tolerance
  eats the bone, which is nearly the background's grey. Make plates on pure white with no
  shadow (`BG_WHITE`); for an old grey plate mask it by the subject's colour instead and
  pass that mask through `fill_holes` / `boundary`. Look at the contour before you trust it.
- Inner strokes are honest but noisy on a uniformly coloured subject (a black dog's coat);
  marking strokes and landmarks are the reliable construction lines there. On a subject
  with parts (the hammer) the inner strokes alone give the bands, collar, ridges and pommel.
- Landmarks come from measurement, not by eye: the eye centre, the ear root, the joint
  heights, the mouth line as pixel rows/columns found with a script, drawn as circles and
  lines. The skull's orbit circles and tooth arcs were exactly this.

## 3. Use it

The plan says: put `side_blueprint.png` (and the front / top) in Blender as the guides,
the plates beside them hidden; build the main mass by reading the blueprint's contour JSON
(`plate_loft` across two plates, `outline_trace`/`extrude_profile` for a flat part), place
features on the landmark strokes, and review with the built outline drawn back on the
blueprint (`reference_outline`, residual per row). The photograph is for colour, markings,
and the final camera — never for the shape once the blueprints exist.
