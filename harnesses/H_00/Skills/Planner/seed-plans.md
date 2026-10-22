---
name: seed-plans
description: What the expert's short seed plan looks like — the input to the plan loop — with two real examples and what each got right and wrong.
---

# Seed plans

Step 1 of the loop is **an expert writing a short plan**: the skeleton, not the
polished document. It is meant to be rough. Its job is to fix the order of work
and the vocabulary, so that a run against it produces a trajectory worth
correcting. Two real ones are reproduced below.

## What a good seed plan does

- **Fixes the order** — which part is built first, and what each part is built
  *from* (a seed cylinder, the base's own top face, a lone edge).
- **Names the parts** in the words the whole project will use afterwards.
- **Says which existing run or tool to copy** where one exists.
- **Points at progress images** for stages a sentence cannot pin down.
- **Leaves the numbers open.** A seed plan that specifies radii is doing the
  agent's job and pre-empting the loop.

Length: one to two pages. Both examples below are under 70 lines.

---

## Example 1 — the gravestone (a good one)

> Base — make a cube and flatten it, to make the cuboid like base shape.
>
> Grave — take the top face of the base, and inset it, then the new face made,
> extrude it up somewhat (40% height), then extrude (50% height) more and this
> time also scale out the top face a bit (as the top part increases in size a bit
> at the top), then make top cuts so that the top face has an edge in its middle,
> scale the edge up a bit to make the pointed top of the grave. Now the top part
> of the grave has two symmetric edges — we pull one of them a bit down to make
> the grave asymmetric (and the other a bit up).
>
> Then we use bevels to make some damage on the edges: pick some vertices
> (corners) of grave and base and make small bevels of different size.
>
> Should look like `grave_partial.png` after this.

**Why it works.** Every sentence is one operation on a named piece of geometry,
in order, with the *reason* attached where it matters ("as the top part increases
in size a bit at the top"). Percentages rather than absolute heights. Damage is
specified as "different size", which is the property that matters, and no sizes
are given. It ends with a picture of done.

Its step 2 goes further and does something worth copying: it **describes a tool
that does not exist yet** and asks for it — "I want a tool by which the agent can
make these lines… by specifying end points, and these lines can be made a bit
wavy by some math… also tools that give coordinates of the edges and vertices
visible in this view." That is how `paint.apply_paint_lines` and
`perceive.edge_map` came to exist. A seed plan is the right place to notice that
the step needs a capability the harness lacks.

---

## Example 2 — the bat (a good plan that leaked two failures)

The bat seed plan is longer and mostly good: it fixes the seed cylinder, the
extrude-and-scale chain, the mirror, the ear-built-in-isolation trick, and the
whole material setup. Two sentences in it cost several rounds each, and both are
worth studying because the flaw is subtle:

> "…extrude, scale it to make **one arm** out of the 5. Next we then put new
> cylinders on the place where the 5 arm extensions meet, and then make those arms
> as well."

Read carefully this says: build one short bone now, then five more later, starting
where they meet. Read quickly it says: build the arm. The agent built the whole
limb to the wingtip. **Fix: number the sub-steps, and state the expected length
as a proportion.**

> "…we extrude and scale it down 3 times such that it makes **the bottom part**
> (not the legs of the bat)… place the cube near the bottom part of the bat."

"Bottom part" is defined in a parenthetical and reused two steps later as though
settled. The agent re-derived it from the photo and attached the legs to the
wing. **Fix: define the term in its own sentence and restate it at the reuse.**

See `wording-that-cannot-be-misread.md` for the full catalogue.

---

## After the run

Do not edit the seed plan into a better seed plan. **Compress the corrected
trajectory into a plan** — the seed's job is finished once a run exists. The five
documents in `plans/*/` are what that looks like: same skeleton, plus the
measurements the run found, the tools it settled on, and a section naming every
trap so the next reader starts past it.

**Write the result forwards.** The corrections came out of a run, but the plan that
carries them is read by someone building the thing for the first time, and it is
also the example the next plan gets modelled on. So the knowledge survives and the
history does not: *"a direction change at a single station tips that ring hard
enough to put it behind the ring before it — split the turn over two"*, never
*"the neck-base ring came out behind the breast ring"*. Same trap, same cause, same
fix, no phantom previous attempt. There is one kind of document here, not a seed
kind and a finished kind.
