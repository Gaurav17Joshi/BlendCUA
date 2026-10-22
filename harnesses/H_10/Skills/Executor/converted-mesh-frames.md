---
name: converted-mesh-frames
description: Read this when converted text or curve geometry is remapped between local axes, a physical face, and a named viewport side.
evidence: 04_datestone_1934_run_001 step_001
---

# Re-measure converted geometry after remapping

A curve's `extrude` value and a viewport name are not reliable descriptions of
the delivered mesh. Conversion can put bevel/extrusion geometry on both sides of
the source axis, and a named `FRONT`/`BACK` view may be opposite to the plan's
physical-front wording.

After conversion, read the actual mesh bounds on every axis, then map
`min..max` to the intended world interval. In particular, normalize the
converted depth interval to the requested relief instead of mapping the source
`extrude` setting directly. Verify the result from the real camera on the
physical face and check the rendered reading left-to-right; an isolated outline
can look correct while the camera sees mirrored text or the back.

Keep the convention as scene data: state the physical face normal and the camera
location, and test the named viewport side rather than assuming its label. This
is a frame-conversion check, not a reason to rotate the finished mesh after the
camera has proved it correct.
