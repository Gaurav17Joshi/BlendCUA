---
name: acting-on-corrections
description: How to read a correction for its real scope before rebuilding — from three rounds of bat legs and several rounds of bat arm.
---

# Acting on corrections

A correction tells you something is wrong. It does not usually tell you **how big
the fix is**, and picking the expensive interpretation without checking is how
single rounds turn into three.

## Ask when the two readings differ in cost

The bat legs, round 2. The correction was:

> "the legs are not rotated, they are straight, parallel to y axis… they have to be
> longer, look at the reference image below it man!"

That is genuinely ambiguous between two fixes:

- increase the fixed **angle** of a still-straight leg — one direction vector, one
  number; or
- make the leg follow a **curving path** — structurally different, a multi-point
  chain instead of a single extrude.

The expensive reading was picked without checking, the legs were rebuilt with the
chain tool, and it was rejected immediately: "No!! the legs have to be straight!!"

> **When a correction is ambiguous between a cheap fix and an expensive one, ask
> before doing the expensive one.**

Picking the simpler reading and checking in is also fine — a fast wrong attempt
that reverts in one action costs less than a round trip. What is not fine is
picking the reading that means switching tools and rebuilding, silently.

## Re-read the plan before re-deriving from the picture

Bat legs, round 1: the leg was attached at the flank and pointed sideways, because
the attachment point was re-derived by scanning the reference photo for a plausible
dark diagonal — which turned out to be the wing's forearm. The plan had already
defined the attachment point one paragraph earlier, in words.

> A definition the plan already gave is settled. Do not re-derive it from pixels.

## Reach for domain knowledge before pixel-matching

Bats' legs attach near the tail. That single fact settles round 1 without opening
the photo at all — and in that particular gliding pose the real legs are hidden
under the membrane, so the photograph could never have answered it.

When the subject is something with common-knowledge structure — anatomy,
architecture, how a pot is thrown — check the structure first and use the picture
to place it, not to discover it.

## Suspect the most prominent feature

Bat arm: the agent optimised for "the most prominent continuous vein line" rather
than "the plan's stated stopping point", and built a humerus seven times too long.
The perception was accurate; the **scope** was wrong. It never asked "how far
should this go" against the text, only "does this line match a visible vein".

A photograph's most visually dominant line is exactly the kind of thing that reads
as the answer while spanning several things the plan wants built separately.

## Sanity-check scale against something in your own scene

Before committing a traced chain, compare it to a known length already in the
scene: "the seed cube is 0.05; my chain is 7× that — is a single humerus really
seven seed-cubes long?" That question, asked once, catches the error with no
tooling at all.

## What a good round looks like

Round 3 of the legs took one pass: "drop the last extrude segment, bump one scale
factor for a bigger paddle, +20% on the seed's X offset." Small, unambiguous,
numeric. **That is the shape feedback should take once the underlying structure —
attachment point and direction — is actually right.** If you are several rounds in
and the corrections are still structural, stop tuning numbers and re-read the step.
