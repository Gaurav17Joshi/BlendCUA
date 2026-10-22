---
name: wording-that-cannot-be-misread
description: The specific plan ambiguities that have failed runs in this project, and how to word around them.
---

# Wording that cannot be misread

Everything in a plan is read literally and in full, and **anything left ambiguous
gets resolved by the agent in whichever direction seems reasonable at the time.**
It will not flag it; it will pick and continue. Each item below cost real rounds.

## A bounding box is not a target

The bat plan shipped four boxes over the reference — head, torso, leg, wing — as
loose crop windows saying roughly where each part sits. The plan never said
"loose crop". The agent built the head to **fill** its box and produced a skull at
twice its correct width, then carried on without noticing.

> Between a visual signal and a textual signal, **the agent follows the textual
> one.** A box drawn on a photo, unqualified, reads as a specification.

Say what the annotation is *for*: "these bound roughly where each region sits;
they are not the dimensions of anything — follow the animal, use the box only to
know where to look."

## Several sentences means several steps

The bat seed plan's step 3 read: "make the thin arms… extrude, scale it to make
**one arm** out of the 5", then separately, "put new cylinders where the 5 arm
extensions meet, and then make those arms as well." Two sentences, two distinct
sub-steps, meeting at the wrist.

The agent fused them, built humerus + forearm + wrist as one chain reaching almost
to the wingtip, and then spent several rounds trying to make *that* long chain
track a vein line — when the fix was to stop much sooner. Note that the same plan's
steps 1 and 2 had the same many-sentences-many-actions shape and were read
correctly; the pattern was established and still missed here.

**Number the sub-steps rather than relying on sentence breaks**, especially where
one sub-step's endpoint is the next one's start.

## Define a term once, then rely on it — and say you are

The same plan established "bottom part" to mean the rear/tail end, in a
parenthetical one paragraph earlier ("makes the bottom part (not the legs)"). Step
2 reused the phrase. The agent re-derived the attachment point from scratch off the
photo, found a plausible dark diagonal near the body, and built the legs onto the
**wing's forearm**.

If a term is doing load-bearing work, define it in its own sentence, and where it
recurs, restate it in three words.

## Name the anatomy, not the pixels

"Legs attach at the tail end, straight back, parallel to the body's own axis" is
unambiguous. "Legs like in the photo" is not — and in that particular gliding pose
the legs are hidden under the membrane, so the photo cannot answer it at all.

Where common domain knowledge settles a question, put the knowledge in the plan.
It costs one clause and removes an entire class of pixel-matching error.

## Warn about the prominent wrong thing

A wing photo has one long, visually dominant vein running shoulder to wingtip. It
is exactly the kind of feature that reads as "the answer" while spanning several
segments the plan wants built separately. If your reference contains such a
feature, name it and say what it is not:

> "The most prominent line in the photo is a vein running the whole way to the
> wingtip; tracing it in full skips straight past the 5-finger step."

## State expected proportions before any tracing

A single sanity number — "the humerus should be a small fraction of the
shoulder-to-wingtip span" — catches a 7×-too-long chain immediately, with no grid,
no overlay and no round trip. Proportions are cheap to state and expensive for the
agent to discover after it has already built the wrong thing.

## Say when a reference does not apply

If a progress screenshot was shot from a different camera angle than the build's
working view, say so. A line's apparent angle in that photo does not transfer, and
an agent told to "look at the reference" will assume it does.
