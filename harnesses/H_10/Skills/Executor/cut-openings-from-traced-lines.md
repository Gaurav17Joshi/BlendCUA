---
name: cut-openings-from-traced-lines
description: Read this when a step needs an opening in a body that the photograph shows as edges — a mouth, a slot, a seam, a socket, a notch — or when you notice you are about to build such a feature as separate parts stuck on the outside. The edges are read from the photo as lines, previewed on the mesh through the photo's own frame, straightened, cut with ONE Boolean across the body, and whatever sits in the opening is planted on the mesh's own new lips. Says how to decide whether the mesh even has the mass to cut, what to script, and what to keep simple.
evidence: mem/08_shark_run_002 steps/step_002 (2026-09-12): the loop's executor spent its step on external jaw shells, gum tubes and a crashed Boolean; by hand it was two straight lines from the pink-gum mask, one full-width cut, cone teeth on the mesh's lips, boundary_edges 0, and a mouth that reads from every side. Tool: Tool_scripts/Tools_code/line_cut.py
---

# The opening is a cut in the body, not a part on the body

The checker's first shark defect read: *"the jaw is an external stack of rectangular and
cylindrical blocks instead of an integrated shark mouth"*. That is what happens when an opening
is built as objects: shells, tubes and plugs placed against the skin. A mouth, a slot or a seam
is the absence of material, so it is made by removing material — one Boolean, owned by the body —
and only what lives *inside* it is added afterwards.

## 1. Decide before you cut: three questions, each answered by a script

1. **Where are the edges in the photo?** Not "about here": a mask of the band that marks them
   (the pink gums; a shadow line; a colour seam — a 5-line predicate on the RGB array, cleaned
   with `outline_trace`'s mask helpers) and its per-column top and bottom rows. Map the rows
   through the photo frame (`line_cut.world_from_px`) — the same frame the body was traced with —
   so the lines land on the body where the photo has them.
2. **Does the mesh have the mass the lines assume?** Measure the body per station
   (`line_cut.stations`) and compare with the photo's silhouette (`line_cut.silhouette_gap`). The
   shark's underside ran exactly along the photo's lower gum line: there was no lower jaw to cut
   a mouth into. Knowing that first is what lets you choose the simple cut (below) instead of
   discovering it after three tries.
3. **What does the opening look like from the other sides?** A cut across the full width opens
   both sides and the front — right for a mouth, wrong for a socket. Decide the extent (full
   width, one side, a depth) from a front or top view of the reference or a plate, not from the
   side view alone.

## 2. Preview the lines on the mesh through the photo's frame

Render the body through `line_cut.frame_camera` + `frame_render`: an orthographic camera on the
side the image Empty faces, `ortho_scale` = the Empty's size, so every render pixel is one photo
pixel. Draw the traced lines on that render with the photo ghosted under it
(`draw_lines_on_render`) and LOOK. The shark's first preview came out mirrored because the camera
was on the wrong side of the plane; the second showed the missing jaw at a glance. Two lines and
a corner is what the preview should show — if you cannot say in one sentence what will be cut,
you are not ready to cut.

## 3. Straighten, then cut once

- **Straight lines beat traced ones for a cut.** Rows traced at 1 px steps change slope every
  segment and corrugate the cut faces (stripes in every render). Take the line from the mean of
  the first eight traced samples to the traced corner (three lines of numpy): it keeps the photo's
  position and slope and gives flat cut faces. Resample only when the edge is truly curved.
- **Carry the upper line forward until it leaves the body** (the shark: to x = -3.60) so the front
  of the opening is open, then close the profile below the lowest point of interest — one polygon,
  one `line_cut.slab`, one `line_cut.boolean`. Write the polygon to a JSON next to the action.
- **Paint the new faces by the plane they lie on** (`line_cut.paint_plane_faces`), flat-shaded, in
  the interior colour. A point-in-polygon test on face centres paints saw-teeth: the cut faces
  lie ON the polygon's edges and flip on float noise.
- **Audit or it did not happen**: `line_cut.audit` must say `boundary_edges 0,
  non_manifold_edges 0` after the cut. Write the numbers into the action's note.

## 4. Plant what goes inside on the mesh's own lips

The lips are the boundary between the cut faces (the interior material) and the skin — read them
off the cut mesh with a short bmesh loop (edges whose two faces differ in material), order the
points by angle about a point behind the opening, resample every ~0.075. Teeth, pins, hinges then
sit on the edge that was actually cut, inset a little, largest at the front and smallest at the
corners for a mouth (a cone is eight verts and a tip; write it). Never place them from the plan's
numbers: those describe the photo, the loop describes the cut.

## 5. What not to build (tried, dropped)

- A **throat block** kept inside the cut so the mouth is not see-through: its inset exceeded the
  gap at the front, the block went inside-out and the Boolean dropped it in silence — the mouth
  became a tunnel and nobody noticed until the render. `slab` now refuses a self-crossing profile;
  if you need a back wall, check its minimum thickness in a script first, or leave the interior
  dark and move on.
- A **jaw bulge** pushed down to the photo's chin before the cut: correct in principle, three
  more parameters to tune, and the reviewer preferred the plain cut. Do the plain cut first,
  show it, and add mass only if the review asks for it.
- **Tapered cores, resampled lenses, expanded polygons**: every one of them was a fix for a
  problem the straight-line cut does not have.

## Budget

Trace and preview: 2 actions. Cut and audit: 1. Details on the lips: 1. Review render: 1. The
shark's step 2 is exactly those five files; the executor's version had eight actions and no mouth.
