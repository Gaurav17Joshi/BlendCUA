---
name: candle-flame
description: Read this when a scene has a candle, lamp or small fire that must read as lit in the render. A flame is a small teardrop mesh with an emission material graded from a white core to an orange rim that fades to transparent at the silhouette, a point light inside it, and a bloom in the compositor for the glow. A flat painted shape, or a light with no flame, is the mistake.
evidence: mem/11_pumpkin_decor_run_003 steps/step_003/02_candles.py and step_005/02_scene_setup.py (2026-09-13); mem/11_pumpkin_decor_run_001 as the counter-example (orange leaf-shaped card with a white blob)
---

# A flame is a graded emitter with a light inside and a glow outside

- **Mesh:** a closed teardrop by revolution, widest a third of the way up, pointed at
  the top, its height and width read from the photo's white core box; standing on the
  wick's tip. No shadow casting.
- **Material:** emission, colour and opacity driven by how much the surface faces the
  camera (Layer Weight, Facing: zero facing the viewer, one at the silhouette). Core
  warm white, rim orange, opacity full over the core and fading to nothing at the
  silhouette, blended render method. The flame then looks soft from every angle without
  volumetrics.
- **Light:** a small warm point light inside the flame, so the wax top and whatever
  stands beside the candle catch its colour. Wax is translucent (a little subsurface) so
  the top rim glows.
- **Glow:** a compositor Glare node of the Bloom kind on the render layer; that is the
  halo the photo shows around each flame, and it is where the wax gets bright, so keep
  the flame light modest.
- **Check:** a crop of each candle in the render shows a white core, an orange edge, a
  halo, and a lit wax top; two candles means two of each.
