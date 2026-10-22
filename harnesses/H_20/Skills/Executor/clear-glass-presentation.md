---
name: clear-glass-presentation
description: Read this before tuning transparent material and lighting against a neutral product reference.
evidence: 05_wine_glass_run_001 step_003; 16_hourglass_run_001 step_004
---

# Clear-glass presentation

Start clear-transmission tuning with a **dark neutral world, a neutral
render-visible backdrop for the transmitted field, and small side/rim sources**;
keep broad camera-side/front lights at zero or very low energy until a bowl crop
proves that they add edge information rather than pale panels. Measure the
background side patches and inspect the bowl/rim crop after each lighting change.

In the wine-glass run, broad front and backdrop sources made the bowl read as
milky and produced a wide glossy foot strip through four review rounds. Lowering
those sources and raising only the neutral backdrop emission restored the
reference-grey field while preserving the thin side reflections. Do not reshape
accepted geometry to compensate for a transparent-render contrast problem.

A realtime engine may expose a valid Transmission Weight socket while still
rendering a closed shell as a dark opaque body under its current settings. Record
the engine readback and inspect a fresh judged-camera render before trusting the
socket or a viewport preview. If face-on transmission swallows the contents, a
restrained Transparent/Fresnel mix can supply the face-on pass and grazing rim
without changing the shell or its physical clearance.
