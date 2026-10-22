---
name: review-checklist-format
description: The shape a step's Review block must take — bullets, Important/Other grouping, and the reference-anchored check that goes first.
---

# Review checklist format

`Reviewer/writing-review-checklists.md` covers *what* to check. This covers the
shape, which is not a matter of taste: get it wrong and the checks silently do not
exist.

## Bullets, or nothing

`parse_plan` extracts a step's checks with `_bullets()`, which collects lines
starting with `- `. **A Review written as a paragraph parses to an empty list.**

When that happens nothing errors. The reviewer is handed:

```
(no explicit checks — evaluate overall visual fit vs. reference)
```

and grades the step on a general impression plus the plan text, reconstructing
criteria for itself. Every one of the five plans in `plans/` was written this way
at first, so every review for months ran with no checklist at all — and it is
invisible from the outside, because the reviews still come back detailed and
confident.

It also explains a symptom worth recognising: two reviewers, the same unmodified
texture, opposite verdicts. They were not disagreeing about a criterion. Neither
had one.

## The shape

```markdown
**Review:**

**Important**

- **The bolded claim, stated as a fact to be confirmed.** Then how to check it,
  and what the failure looks like when it happens.
- **The next one.** …

**Other**

- A terse, verifiable fact.
- Another.
```

`**Important**` and `**Other**` are read by the parser and tag each check, so the
reviewer is told which ones decide the step. Untagged checks default to Important.

## What goes in which

**Important** — the checks a build actually fails on. Each one earns a crop, a
measurement, or a number quoted back. Three to five per step; if everything is
important, nothing is.

**Other** — bookkeeping. Object counts, shading flags, modifier lists, nothing
loaded that should not be. Real, worth confirming, not worth a paragraph. The
reviewer is told not to fail a step on one of these alone.

The split exists because reviewer effort is finite and was being spent badly: three
paragraphs on "no doubled vertices" and one sentence on whether the silhouette
matched.

## Write Important checks so they cannot be answered from a full frame

The best ones name the crop and the number in the same sentence:

> **Check the torso and the head separately, zoomed in on each.** A full-frame look
> cannot answer this: the torso can be correct while the head is two or three times
> too fat, and at full frame both still look fine. Crop to each, judge it alone, and
> say what you saw.

> **There is a measurable neck narrowing** — one ring narrower than both the chest
> before it and the skull after it. Quote the three widths.

Compare with what those replaced — *"head chest-widens then neck-narrows then
skull-widens"* — which is true, unfalsifiable at a glance, and passes a head twice
its correct width.

## The first Important check anchors to the reference

Put it first and say why it is there. Without it, a wrong number in the plan passes
every other check, because the rest compare the build against the plan rather than
against the thing the plan was measured from. See `numbers-that-hold-up.md` §2 —
this is the single highest-value line in a checklist.

## Prefer a measurement to an adjective

Criteria stay stable across reviewers in proportion to how numeric they are.
Measured on the same builds:

| stable | unstable |
|---|---|
| "creases 15–21 mm" | "no per-face stepping" |
| "zero movement outside footprint" | "visibly not ruler-straight" |
| "64 verts / 62 faces" | "reads as painted by hand" |

If you cannot avoid an adjective, give it a procedure — *"sample a vertical column
of texels and check the brightness rises monotonically; a staircase in the numbers
is banding"* — rather than leaving the reviewer to decide what the word means.
