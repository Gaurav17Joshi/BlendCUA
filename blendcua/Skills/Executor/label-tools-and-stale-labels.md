---
name: label-tools-and-stale-labels
description: How the edge_map / face_grid label workflow is meant to be used, the one way it bites, and the known gaps in the tool.
---

# Label tools, and stale labels

`perceive.edge_map()` and `perceive.face_grid()` follow the harness's usual shape:
a perception action renders a labelled overlay and writes a JSON sidecar, then the
*next* action reads a label out of that JSON and acts on it.

## The intended workflow

1. Action N calls `edge_map()`. It renders the current view, draws every visible
   edge labelled `E_1`, `E_2`, … and writes the payload to `overlay_json/`.
2. **You look at the labelled image** and pick, by eye, which labels are the
   feature you want — "the seam is `E_8`, the left corner is `E_16`".
3. Action N+1 reads those labels' coordinates out of that JSON via
   `edge_at_label("E_8", prior_action=N)` and builds its stroke from them.

That is it. No re-deriving projections, no bmesh in the paint action.

## The one way it bites

**`bm.edges` iteration order is not guaranteed identical across separate
invocations.** Calling `edge_map()` twice on an unchanged mesh in an unchanged
view can hand out different `E_N` labels to the same edges.

This does **not** break the workflow above, as long as the image you looked at and
the JSON you read come from **the same call** — which is what
`prior_action=<the action that rendered the image>` enforces, and what the
action-N / action-N+1 pairing does naturally.

What actually went wrong on the gravestone: labels were looked up with *throwaway
verification scripts* that called `edge_map()` fresh, and those observed strings
were hardcoded into the real paint action. When the real edge-map action later
re-ran during a full replay it produced a different mapping, and the hardcoded
strings silently pointed at the wrong edges.

> A label learned from a debug call is not a label. Only ever read labels off the
> image the persisted action saved.

## What that cost, and why not to copy it

The fix applied at the time was to stop trusting labels altogether and instead
search the JSON **by geometric criteria** computed fresh in every paint action —
"both endpoints at z ≈ 0.18, front side, x-span > 1.0", plus a chain-walk to follow
a corner upward. It works and it is defensible, but it is far heavier than
intended: ~50 lines duplicated near-verbatim across four paint actions, and it
needs bmesh access in each one, which is exactly the boilerplate the tool exists to
remove.

If you are writing a new label-based action, **use the simple workflow.** Reach for
geometric resolution only if you actually need it — for instance when the same
action must run against meshes that differ.

## Known gaps in `edge_map()` (worth fixing before the next texture build)

1. **The JSON has screen coordinates only.** Each entry is
   `{"edge_idx", "v0", "v1", "mid"}` in viewport pixels. The function computes
   world positions internally to project them, then throws them away — so any
   caller wanting 3D has to reopen the mesh, look up `bm.edges[edge_idx]` and
   recompute `matrix_world @ vert.co` itself.
   **Fix:** add `"w0"`, `"w1"`, `"wmid"` to each entry, and have
   `edge_at_label()` return them.
2. **Label numbering is not deterministic.** Number the edges by a stable key —
   `edge_idx`, or rounded world midpoint — instead of raw iteration order. Cheap,
   and it makes `E_N` mean the same edge across separate calls, removing the
   footgun entirely.

With both done, the whole geometric-criteria block disappears and the workflow is
back to: render once per view, eyeball the labels, hardcode the handful of strings.

## The same rule for other pickers

`face_at_grid(row, col)` raycasts the pixel under a grid dot from the **current**
view, so the grid you looked at and the pick you make must come from the same
framing. Any picker that turns a picture into an index has this property: the
picture and the index are one unit, and separating them across actions or across
runs is where it goes wrong.
