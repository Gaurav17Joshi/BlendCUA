# Plate-by-plate review — gpt-image-2 view re-projection

Every plate in [baseline/](baseline/) judged against its reference, plus a second
attempt at the ten that were worst. **No original was overwritten** — each retry
is a new file with a `_v2` suffix sitting next to the plate it replaces, and both
appear on the task's `contact_sheet.png` so they can be compared directly.

66 plates over 20 tasks. `gpt-image-2`, `images.edit`, `quality=medium`. Prompts
for every plate are in the per-task `manifest.json`.

---

## 1. The two prompt fixes that did the work

Everything below is a variation on two failure modes, and both have the same
one-line fix.

**A — The model will not give up the object's recognisable face.** Ask for a
view in which the hero surface disappears and you get the hero surface anyway.
Four plates failed this way on the first pass and were re-prompted before the
first write-up: `04_datestone_1934/02_top` and `06_iron_gate/02_top` both came
back as the carved face and the gate face again rather than a top edge;
`11_umbrella/02_side` furled the umbrella into a closed cone rather than spinning
it; `12_tablecloth_drape/02_side` returned a near-duplicate of the front. (Those
four were fixed with `--force`, so only the corrected versions are on disk — they
predate the `_v2` convention used everywhere else in this document.)

> **Fix: say what must NOT be in frame.** "The carved 1934 face points away from
> the camera and must NOT be visible — do not show the numerals." Naming the
> camera's physical position helps too: "the camera is mounted on the ceiling
> directly above, pointing straight down."

**B — Scale and identity are not conserved across a re-projection.** The model
re-draws the object rather than re-photographing it, and the redraw drifts:
proportions change, ornament vanishes, a plant regrows.

> **Fix: state the invariant as a ratio or a named part list.** "The can is a
> right circular cylinder, so its silhouette is identical from every horizontal
> direction — same height, same width, about five times taller than wide."
> "Every piece of ornament survives the rotation: the scrollwork cartouche keeps
> its full width and volutes, then the spiral twist, then the diamond lattice
> band, then the stepped base."

Vague geometric language ("rotate 90 degrees", "show the side") is what fails.
Concrete language — a ratio, a part inventory, an explicit exclusion — is what
works. Every one of the ten retries below used one of those three devices.

---

## 2. The retries

Ten plates were re-prompted. Eight are clearly better, one is a wash, one traded
one defect for another.

| plate | what was wrong | what changed in the prompt | verdict |
| --- | --- | --- | --- |
| [05_energy_can/01_side](baseline/05_energy_can/01_side.png) → [_v2](baseline/05_energy_can/01_side_v2.png) | can reduced to a thin black rod, label almost entirely gone | told it the can is a **right circular cylinder** whose silhouette is identical from every horizontal direction, gave the ratio (~5:1), forbade narrowing | **much better** — correct width, full wrap of label with the claw split across the seam |
| [13_domino_cascade/02_top](baseline/13_domino_cascade/02_top.png) → [_v2](baseline/13_domino_cascade/02_top_v2.png) | dominoes laid **flat, face-up** with pips showing and even spacing | "they are STANDING ON EDGE… each reads as a narrow bar ~8 mm × 40 mm, the pip faces point sideways and are NOT visible, do not draw pips" | **much better** — eight bars, spacing readable, lean angles preserved and widening down the line |
| [15_street_lantern/02_side](baseline/15_street_lantern/02_side.png) → [_v2](baseline/15_street_lantern/02_side_v2.png) | post slimmed to a bare pole, the scrollwork cartouche deleted | listed the ornament top to bottom and required each to survive; forbade slimming the post | **much better** — cartouche back at full width, post thickness held |
| [16_hourglass/01_side](baseline/16_hourglass/01_side.png) → [_v2](baseline/16_hourglass/01_side_v2.png) | barely rotated (still only two columns) and the sand restarted running | "spin 45° so ALL FOUR columns are visible"; "keep the sand exactly as the reference has it, do NOT add a falling stream" | **much better** — four columns correctly staggered, sand state frozen |
| [01_cardboard_box/02_side](baseline/01_cardboard_box/02_side.png) → [_v2](baseline/01_cardboard_box/02_side_v2.png) | box came back as a tall portrait carton, taller than in its own front view | "the box HEIGHT is exactly the same as in the front view… a broad, almost square rectangle. It must NOT come out as a tall portrait box" | **better** — now square and consistent with `01_front` |
| [07_monstera_pot/01_side](baseline/07_monstera_pot/01_side.png) → [_v2](baseline/07_monstera_pot/01_side_v2.png) | plant regrown: stems stretched, leaves thinned, aerial roots fused into one trunk | "the SAME specimen, not another plant of the same species" + a part list (seven leaves, short stubby stems, curtain of roots, pot = ⅓ of height) | **better** — root curtain and pot ratio restored; leaf arrangement still not identical |
| [08_desk_chair/03_desk_side](baseline/08_desk_chair/03_desk_side.png) → [_v2](baseline/08_desk_chair/03_desk_side_v2.png) | read as a standalone chest of drawers, no desk top spanning above | asked for the whole desk in profile with the top overhanging | **marginal** — v2 adds the overhanging top cap, otherwise the same. On reflection **both are geometrically correct**: in a true side elevation the near pedestal's side panel is flush with the desk depth and occludes everything behind it, so a desk really does look like this end-on. My original criticism was wrong. |
| [08_desk_chair/04_desk_top](baseline/08_desk_chair/04_desk_top.png) → [_v2](baseline/08_desk_chair/04_desk_top_v2.png) | correct but zero information — a bare wooden board | asked for floor shadows to reveal the pedestals' footprint | **traded one fault for another** — v2 is far more informative (both pedestals, all six drawers) but it is no longer a top-down view; it slid to a high oblique. Asking for shadow cues broke the orthographic projection. |
| [08_desk_chair/00_isolate_desk](baseline/08_desk_chair/00_isolate_desk.png) → [_v2](baseline/08_desk_chair/00_isolate_desk_v2.png) | *(background complaint was wrong — see below)*; real fault is the **bowed front edge** on the desk top, which the reference does not have | "a STRAIGHT rectangular desk top — do not bow or curve the front edge, do not restyle it into an executive desk" | **no change** — came back bowed again. A reproducible failure: this is the one instruction in the whole set that was refused twice. |
| [08_desk_chair/01_isolate_chair](baseline/08_desk_chair/01_isolate_chair.png) → [_v2](baseline/08_desk_chair/01_isolate_chair_v2.png) | *(background complaint was wrong — see below)* | forbade the backdrop/glow | **no change needed** — v1 was already fine |

### A correction on the two isolates

I first recorded both isolate plates as having ignored `background="transparent"`
and returned a dark backdrop with a rim-light halo. That was wrong — it was my
image viewer compositing the PNG onto black. The alpha channels are clean:

```
00_isolate_desk_v2.png   a=0: 35.8%   a=1..245: 1.5%   a=246..254: 62.6%
01_isolate_chair_v2.png  a=0: 84.0%   a=1..245: 1.4%   a=246..254: 14.6%
```

A two-level matte with only ~1.5 % soft edge — a genuinely good cut-out. One
quirk worth knowing: **the subject tops out at alpha 254, never 255.** A
downstream check for "fully opaque" will report zero opaque pixels on every
`background="transparent"` plate gpt-image-2 returns.

---

## 3. Plate-by-plate

### Very good — usable as modelling guides unchanged

| plate | note |
| --- | --- |
| [09_skull](baseline/09_skull/) `01_front` `02_side` `03_top` | The strongest set in the run. Anterior view has symmetrical orbits, midline nasal aperture and teeth in occlusion; lateral view has the vault, brow, zygomatic arch, jaw hinge and ramus; superior view carries the sagittal and coronal sutures through correctly. Only nit: the superior view is a touch too egg-like — the zygomatic bulge should show at the edges. |
| [18_thors_hammer](baseline/18_thors_hammer/) `00_upright_front` `01_side` `02_top` | The de-tilt is the single most impressive result. A diagonal three-quarter hero shot becomes a square-on upright plate with the handle truly vertical and both gold bands level. `01_side` then correctly narrows the head to its square striking face, and `02_top` reads as the gold-framed cracked rectangle. |
| [14_sneaker](baseline/14_sneaker/) `01_front` `02_top` `03_bottom` | Front is symmetrical with laces on the centre line; top shows lacing, tongue and collar cleanly; the outsole is a plausible, well-organised Nike Free tread. |
| [11_umbrella](baseline/11_umbrella/) `01_front` `02_side` `03_top` | `03_top` is the valuable plate — a clean circle divided into exactly eight panels by the rib seams with the fringe as a ring. |
| [12_tablecloth_drape](baseline/12_tablecloth_drape/) `01_front` `02_side` `03_top` | `03_top` nails it: square cloth with rounded corners, diagonal fold creases radiating from the round table beneath, feet peeking out. `02_side` (after re-prompt) correctly points a hanging corner at the camera. |
| [02_chess_staunton](baseline/02_chess_staunton/) `02_top` | Pawn as concentric circles with the ball finial centred, rook as a ring with four square crenellation gaps — exactly what the task needs to cut the crenellations. |
| [03_wine_glass](baseline/03_wine_glass/) `01_side` `02_top` | Side silhouette correctly identical to the front (it is a lathed solid); the top view resolves rim, wall, bowl, stem and foot as distinct concentric circles. |
| [13_domino_cascade](baseline/13_domino_cascade/) `00_clean_side` | Motion blur removed convincingly, eight tiles resolved, lean angles and spacing preserved. |
| [17_shark](baseline/17_shark/) `01_front` `02_top` | Both reconstructed from a pure side profile. Head-on is bilaterally symmetrical with pectorals spread and dorsal on the centre line; the dorsal plan view has the right torpedo outline, both fin pairs and the countershading break. Pectorals sweep back slightly more than life. |
| [19_human_thinker](baseline/19_human_thinker/) `00_clean_front` `01_side` `02_top` | Viewport grid, axis lines and mouse cursor all removed; the faceted flat-shaded look survives all three views, T-pose held, no facial detail added. |
| [15_street_lantern](baseline/15_street_lantern/) `01_front` `03_top` | Front elevation is square-on with the glow intact; the top view resolves finial, pyramidal roof and the square base plinth beyond. |
| [08_desk_chair](baseline/08_desk_chair/) `05_chair_front` `06_chair_side` `07_chair_top` | Consistent with each other and with the isolate — five castors in the front and top views, correct backrest rake and seat depth in profile. |
| [01_cardboard_box](baseline/01_cardboard_box/) `01_front` `03_top` | Front puts both printed labels flat-on and legible; top shows the closed flaps and the centre tape run. |
| [10_anglepoise_repose](baseline/10_anglepoise_repose/) `01_front` `02_side` `03_top` | Arm pose preserved across all three. `01_front` looks correctly into the mouth of the shade; `03_top` resolves base circle, arm bars, springs and shade ellipse. |
| [04_datestone_1934](baseline/04_datestone_1934/) `01_side` | Correct thin slab in profile with the stepped bottom moulding projecting. |
| [06_iron_gate](baseline/06_iron_gate/) `01_side` `02_top` | Both correct after the re-prompt: a tall narrow slab edge-on, and a single thin bar from above. |
| [16_hourglass](baseline/16_hourglass/) `02_top` | Round top disc with the four ball finials evenly spaced and the glass neck at centre. |
| [05_energy_can](baseline/05_energy_can/) `02_top` | Clean lid: stay-tab, rivet and rolled rim as concentric circles. |
| [07_monstera_pot](baseline/07_monstera_pot/) `02_top` | Leaf rosette radiating around the pot rim — useful for the geometry-nodes leaf distribution the task asks for. |
| [20_low_poly_dog](baseline/20_low_poly_dog/) `01_front` | Symmetrical head-on Rottweiler with the tan chest and muzzle markings correctly mirrored, moved off the grass to a studio background as asked. |

### Decent with caveats

| plate | caveat |
| --- | --- |
| [20_low_poly_dog/02_top](baseline/20_low_poly_dog/02_top.png) | Correct plan view with the legs hidden under the body, but the torso is over-smoothed into a sausage — shoulder and hip masses do not read, and the ears are ambiguous. Fine for footprint, weak for form. |
| [08_desk_chair/02_desk_front](baseline/08_desk_chair/02_desk_front.png) | Good: drawers correctly closed as instructed, 3 + 3 drawers, knee-hole with back panel, sensible proportions. Inherits the invented bowed top edge from the isolate. |
| [09_skull/03_top](baseline/09_skull/03_top.png) | Sutures right, outline slightly too ovoid. |
| [08_desk_chair/03_desk_side_v2](baseline/08_desk_chair/03_desk_side_v2.png) | Geometrically correct but visually uninformative — a true side elevation of a pedestal desk really is a blank panel. Not a model failure. |

### Bad — and now superseded by a `_v2`

All five are described in §2: `05_energy_can/01_side`,
`13_domino_cascade/02_top`, `15_street_lantern/02_side`,
`16_hourglass/01_side`, `01_cardboard_box/02_side`.

### Bad and still unfixed

| plate | problem |
| --- | --- |
| [08_desk_chair/00_isolate_desk](baseline/08_desk_chair/00_isolate_desk.png) (and `_v2`) | The desk top's front edge is **bowed into a curve**. The reference top is a plain rectangle. An explicit "do not bow or curve the front edge" was ignored on the retry, so both isolates and every desk view downstream carry the invented curve. This is the one hard failure in the run. |
| [08_desk_chair/04_desk_top_v2](baseline/08_desk_chair/04_desk_top_v2.png) | More informative than v1 but no longer orthographic — asking for shadow cues tipped it into a high oblique. Keep `04_desk_top` for the projection and `_v2` for the drawer layout. |

---

## 4. What this says about gpt-image-2 for this pipeline

**It is good at the hard cases and sloppy about the easy ones.** Reconstructing
a head-on shark from a pure profile, a superior skull view from a three-quarter
photo, or a de-tilted Mjolnir from a diagonal hero shot all worked first time.
What it gets wrong is bookkeeping: a can's width, a box's height relative to its
own front view, whether a piece of ornament is still there.

**Practical rules that came out of this run:**

1. Say what must not be visible, not just what must.
2. Pin scale with a ratio or a cross-reference to another plate ("the same
   height as in the front view"), never leave it implied.
3. For a rotation, name the parts that must survive it.
4. For a rotationally symmetric object, say so — "right circular cylinder",
   "lathed solid of revolution" — and the silhouette locks.
5. Do not ask for lighting or shadow effects in an orthographic plate; it
   trades the projection for the effect.
6. Treat every plate as a guide to form and feature placement, never to
   measurement. Cross-view scale is not conserved, and surfaces the reference
   never showed (`14_sneaker/03_bottom`, `18_thors_hammer/02_top`) are invented
   plausibly rather than derived.
