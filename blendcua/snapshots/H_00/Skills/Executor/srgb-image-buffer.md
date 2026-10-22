---
name: srgb-image-buffer
description: Read this before writing target colours into a Blender image or tuning a textured material against rendered samples.
evidence: 02_cardboard_box_run_001 step_002
---

# sRGB image buffers

In this Blender image workflow, an image marked `sRGB` expects the encoded
sRGB channel values in `Image.pixels`. If a measured target is `[175, 130, 85]`,
write `[175, 130, 85] / 255` to the buffer; do not linearize it first. The
Image Texture node performs the shader-side colour conversion. Linearizing
before assignment made the saved cardboard PNG read about `[111, 58, 24]`.

Prove the result in two places: sample the saved PNG/image buffer, then sample
the corresponding region of a fresh real camera render. The texture values
may intentionally compensate for directional light, so matching the rendered
face medians is not a reason to replace a varied map with a uniform fill.
