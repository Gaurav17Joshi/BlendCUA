"""Checker — looks at a finished model and finds what is wrong with it.

    python Checker/checker_agent.py --task 08_desk_chair

Reads  blends/<Task>/task/    the brief and the reference photograph
       blends/<Task>/views/   twelve renders of the finished model
       blends/<Task>/manifest.json, render_plan_camera.png, render_three_quarter.png

Writes Checker/reports/<Task>/
       defects.json           the deliverable: a structured, matchable defect set
       <Task>_defects.md      the same thing to read
       scripts/               its own measurement scripts, crops and overlays
       checker_summary.md     what it said when it finished
       checker_check.json     the mechanical validation of defects.json
       usage.json             what the call cost

This is the CHECKER block of method b (see md_files/method_variants_handoff.md).
Everything downstream — ATTRIBUTE, then the cheapest-remedy ladder, then
REWIND + REPLAY, then FIXED? — consumes `defects.json`, so the value of this
agent is entirely in that file being specific, measured and stable.

Built as a near-copy of planner_agent.py because it is the same shape of job:
one long image-heavy conversation, a shell and a scratch folder, measure first
and write second. The differences that matter are all in the prompt.

IT DOES NOT READ THE PLAN
-------------------------
`blends/<Task>/plan/` is off limits, and the run is audited afterwards to
confirm it stayed that way. The point of an independent checker is that it does
not inherit the plan's blind spots: a plan that never considered whether the
chair castors touch the floor produces a build that ignores it AND a review
checklist that does not mention it, and only a judge who never saw the plan will
notice. The reference photograph and the brief are the ground truth here, not
anybody's intentions about them.

For the same reason the checker must stay outside whatever the remedy step is
allowed to edit — otherwise the cheapest way to make FIXED? say yes is to
weaken the check. See section 4 of the handoff note.
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[1])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Windows console defaults to cp1252 and these reports are full of arrows and
# em-dashes; an unguarded print() of that text raises UnicodeEncodeError and
# kills the process. Same guard planner_agent.py uses.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHECKER_DIR = Path(__file__).resolve().parent
ROOT = CHECKER_DIR.parent
sys.path.insert(0, str(ROOT))

import agent_env                                    # noqa: E402
import blendcua_core as core                        # noqa: E402
from models import MODELS, OPENAI_REASONING_EFFORT  # noqa: E402

BLENDS_DIR = ROOT / "blends"
REPORTS_DIR = CHECKER_DIR / "reports"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# The eight compass views plus top and bottom are rendered at one shared camera
# distance so they are directly comparable; front_solid is the mesh in viewport
# Solid shading with no materials; final_render is the hero the build produced.
RING_VIEWS = [f"az_{a:03d}" for a in (0, 45, 90, 135, 180, 225, 270, 315)]
EXPECTED_VIEWS = RING_VIEWS + ["top", "bottom", "front_solid", "final_render"]

# Same reason as the planner: the first turn is a long one with big images and a
# reasoning budget at max, and hermes aborts a call with no first byte inside
# its own 240s window.
STALE_TIMEOUT_S = "900"

DEFECT_KINDS = [
    "proportion", "geometry", "topology", "material", "colour",
    "missing", "extra", "placement", "orientation", "scale",
    "detail", "artifact",
]
SEVERITIES = ["major", "minor"]
CONFIDENCES = ["high", "medium", "low"]


# ── locating the subject ─────────────────────────────────────────────────────

VERDICT_STATUSES = ["RESOLVED", "UNCHANGED", "WORSE"]


def find_subject(name: str) -> Path:
    """blends/<name>/ — the organised output of one finished task or run."""
    d = BLENDS_DIR / name
    if not d.is_dir():
        available = sorted(p.name for p in BLENDS_DIR.iterdir()
                           if p.is_dir() and (p / "views").is_dir()) \
            if BLENDS_DIR.is_dir() else []
        raise SystemExit(
            f"[checker] no finished task at {d}.\n"
            f"          available: {', '.join(available) or '(none)'}\n"
            f"          bundle it first: python vb/bundle.py --run <run> --mode live --task <task>"
        )
    return d


def subject_assets(subject: Path) -> dict:
    """Everything the checker is allowed to see, and a complaint if it is thin."""
    task_dir = subject / "task"
    if not task_dir.is_dir():
        raise SystemExit(f"[checker] {subject} has no task/ folder")
    desc_file = task_dir / "task.md"
    if not desc_file.is_file():
        raise SystemExit(f"[checker] {task_dir} has no task.md")

    refs = sorted(p for p in task_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not refs:
        raise SystemExit(f"[checker] {task_dir} has no reference image")
    reference = refs[0]

    views_dir = subject / "views"
    views = sorted(p.name for p in views_dir.glob("*.png")) if views_dir.is_dir() else []
    missing = [v for v in EXPECTED_VIEWS if f"{v}.png" not in views]

    return {
        "task_dir": task_dir,
        "description": desc_file.read_text(encoding="utf-8").strip(),
        "reference": reference,
        "views_dir": views_dir,
        "views": views,
        "missing_views": missing,
        "manifest": subject / "manifest.json",
        "final_render": views_dir / "final_render.png",
    }


def manifest_digest(path: Path) -> str:
    """A few lines of scene inventory — the 'little' use of the .blend.

    The checker is meant to judge from images. But some defects are only
    visible in the inventory (a part that was never built at all, a material
    left on its default name), and reading them out of manifest.json costs
    nothing, where opening the .blend costs a headless Blender launch.
    """
    if not path.is_file():
        return "(no manifest.json)"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"(manifest.json unreadable: {exc})"
    objs = d.get("objects") or []
    meshes = d.get("meshes") or {}
    mats = d.get("materials") or []
    verts = sum(meshes.values()) if isinstance(meshes, dict) else 0
    return (
        f"- {len(objs)} objects, {len(meshes)} of them meshes, {verts:,} vertices total\n"
        f"- {len(mats)} materials: {', '.join(sorted(mats)[:14])}"
        f"{' ...' if len(mats) > 14 else ''}\n"
        f"- cameras: {', '.join(d.get('cameras') or []) or '(none)'}\n"
        f"- blend size: {d.get('size_mb', '?')} MB"
    )


def reviewer_skills() -> str:
    """Every Skills/Reviewer/*.md in full — this agent's own role skills.

    Same choice planner_agent.py makes for Skills/Planner: judging is what this
    agent is for, so its role's skills are always-on rather than indexed.
    """
    parts = []
    for f in sorted((ROOT / "Skills" / "Reviewer").glob("*.md")):
        parts.append(f"### Skills/Reviewer/{f.name}\n\n"
                     f"{f.read_text(encoding='utf-8').strip()}")
    return "\n\n---\n\n".join(parts) if parts else "(no reviewer skills yet)"


# ── prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the checker for a Blender build harness. You are given a task "
    "brief, the reference photograph it was built from, and renders of the "
    "finished 3D model. You find what is wrong with the model and report it as "
    "a structured defect list. You have a shell and a scratch folder: measure "
    "the images with real scripts rather than judging them by eye. You never "
    "see the build plan, and you do not need it."
)


def build_intro(*, task_name: str, description: str, reference_name: str,
                views: list[str], report_dir: Path, manifest: str,
                subject_name: str | None = None) -> str:
    rel_report = rel_to(report_dir, ROOT).as_posix()
    subject_name = subject_name or task_name
    view_lines = "\n".join(f"  - `blends/{subject_name}/views/{v}`" for v in views)
    return f"""\
# Checker — task `{task_name}`

## Your job

A build agent was given the brief below and a reference photograph, and it
produced a 3D model. **Find everything wrong with that model.**

You are not scoring it and you are not rewriting it. You are producing the
defect list that the rest of the loop acts on: each defect gets attributed to a
level (was the brief ambiguous, was the plan wrong, or did execution botch a
correct plan?), gets the cheapest remedy that plausibly fixes it, and then the
build is replayed to see whether the remedy actually worked. All of that keys
off what you write, so a vague defect is a wasted repair cycle.

## The brief the builder was given

{description}

## What you can look at

| path | what it is |
|---|---|
| `blends/{subject_name}/task/{reference_name}` | **the reference photograph** — ground truth |
| `blends/{subject_name}/task/task.md` | the brief, quoted above |
| `blends/{subject_name}/views/` | renders of the finished model (below) |
| `blends/{subject_name}/manifest.json` | scene inventory — objects, meshes, materials |
| `blends/{subject_name}/{subject_name}.blend` | the scene itself |

{view_lines}

What the views are:

- **`az_000` … `az_315`** — eight compass directions at eye level, 45 deg apart,
  0 deg looking from +X. All eight share **one camera distance**, so sizes are
  directly comparable between them; do not read a size difference between two
  azimuths as a modelling error.
- **`top` / `bottom`** — from directly above and below, at their own shared
  distance. `bottom` is where undersides, castor contact and open shells show up.
- **`front_solid`** — the mesh in **viewport Solid shading**: no materials, no
  textures, flat clay with cavity shading and an outline. This is the one to use
  for FORM and topology, because nothing is hidden by a nice material.
- **`final_render`** — the hero render the build itself produced, from the
  camera the builder chose. Use it for materials and overall impression.

The renders are all of the same scene, so a part that is missing from every view
is missing from the model.

## What you must NOT look at

**`blends/{subject_name}/plan/` is off limits.** Do not read it, list it, or grep
it. The run is audited afterwards and reading it invalidates the result.

This is not bureaucracy. If you read the plan you will start checking the model
against what it was *supposed* to be, and you will inherit exactly the blind
spots that produced the defects. A plan that never thought about whether the
castors touch the floor yields a build that ignores it and a review checklist
that does not mention it — and only a judge who never saw the plan finds it.
The photograph and the brief are the ground truth. Nobody's intentions are.

## First, look. Then measure.

Before you write any script, open the reference beside `final_render`, then
`top`, then `front_solid`, and write down **the five biggest differences a
person would notice, biggest first**. Put that list at the top of your notes.
It is what the whole measurement pass must then prove or drop, and it is where
the severity comes from: a person notices a purple coat or a paper-thin body
before a tail spike or a blank underside. Do not let what is easy to count
decide what matters.

Three checks run on every subject, whatever the object:

- **Width and depth.** From `top` and `front_solid`, the object's width and
  depth relative to its length or height, against the reference where it shows
  them and against a sanity ratio for the kind of object where it does not
  (a single side photo says nothing about width; a built animal, shoe or tool
  that is a slab from the top is wrong regardless).
- **Colour per part.** Median colour of each named part in `final_render`
  against the matching region of the reference. Report hue and lightness
  differences, not just "darker".
- **Attachment and construction.** For each named part: is it attached where it
  should be (a handle enters the bottom of a head, a foot is the end of a leg,
  laces lie on the tongue on the centreline), and is it a separate block where
  the reference has a continuous form? `manifest.json` gives you the object
  list; a part that exists as its own object where the reference shows one
  surface is worth reporting. A cavity built as added parts (a mouth made of
  gum blocks and lip tubes) instead of a cut is a defect of this kind.

Severity is by visibility, in this order: silhouette and proportion; missing,
misplaced or crudely built parts; surface and material; colour; cleanup.

## Method — measure, do not eyeball

Write short Python into `{rel_report}/scripts/` and run it with `bash`. Nothing goes into the working folder's root (no tmp_*.py, crops or notes beside the code): files left there are deleted at the next sync. Write the
file and run it by name; do not pipe it in with `python -c`, because you will
want to re-run it after you look at the output. `numpy`, `PIL` and `cv2` are
available.

**Before your first script, read these two** — they are short and they cover
where code runs and how to get a number out of an image without fooling
yourself:

```bash
python Tool_scripts/skill_help.py where-code-runs
python Tool_scripts/skill_help.py reading-an-image
```

Things that actually find defects:

- **Segment and compare silhouettes.** Threshold the model render and the
  reference to masks, normalise both to the same height, and overlay them. Where
  the outlines part company is a defect with a number attached.
- **Proportion ratios, not pixel counts.** "the seat sits at 0.31 of total
  height, the reference has it at 0.44" survives a change of framing; "the seat
  is 412 px up" does not. This is the single most useful measurement you can make.
- **Count things.** Slats, castors, legs, drawers, spokes. Miscounts are common,
  unambiguous and cheap to find.
- **Crop and look closely.** Cut a part out of a view, scale it up, and `read`
  it. Do this for anything you suspect but cannot yet measure.
- **Check the views against each other.** Something that looks right from the
  front and wrong from `az_090` is a depth defect. `bottom` and `top` catch
  whole classes of defect the hero render never shows.
- **Use `front_solid` for form.** If a shape looks wrong there but fine in
  `final_render`, the material is covering for the geometry — that is worth
  reporting as its own defect.
- **Read `manifest.json`** for the inventory. Default names like `Cube.003` or
  `Material.001` that survived into the finished scene are defects.

Scene inventory, so you do not have to go and get it:

{manifest}

Opening the `.blend` is allowed but should be rare — you can run a headless
query with
`blender --background <file> --python-expr "..."` if some question genuinely
cannot be answered from the images. Nearly all of them can.

**If you do measure geometry out of the .blend, do not use `bound_box`.**
`obj.bound_box` is the bounding box in the object's LOCAL space. Pushing its
eight corners through `matrix_world` gives you the axis-aligned box *around the
rotated box*, which is bigger than the object — and the error grows with the
rotation angle. A previous checker run measured caster wheels that way, found
five of them reaching 0.038-0.058 below the floor, and reported a floor-
intersection defect that does not exist: the unrotated wheel matched exactly
and every rotated one was inflated by precisely the amount it "penetrated".

Measure the actual vertices in world space instead, through the dependency
graph so modifiers are included:

```python
dg  = bpy.context.evaluated_depsgraph_get()
ob  = obj.evaluated_get(dg)
mw  = ob.matrix_world
zs  = [(mw @ v.co).z for v in ob.to_mesh().vertices]
low = min(zs)
```

Whenever you report a contact, clearance or intersection defect, say which of
the two you measured. A "high confidence" number produced the wrong way is
worse than no number: it sends a repair cycle after a defect that was never
there.

**Do not report what you have not measured or seen.** A defect you inferred from
the brief ("the task says five steps, so there is probably a material missing")
is worthless. Every defect needs evidence in an image or a number.

Equally: **do not invent defects to look thorough.** If the model is good, a
short list of real problems is a better result than a long list padded with
things that are actually fine. Say what is right in the summary.

## How many defects — the quota

The brief describes one **subject** unless it names separately standing objects:
a potted plant is one subject (pot, stem, roots and leaves are its parts); a
table with a chair beside it is two. Name them in `subjects`.

Report **at most 2 major and 2 minor defects per subject**. Some briefs have
two important, separately standing objects, such as a table and a chair: each
of them is its own subject and gets its own (2 major, 2 minor), so up to 4
major and 4 minor in all. Judge each one fully on its own; do not let the
worse object use up the other's share. Choose the ones that
most change what a person sees when they hold the final render next to the
photograph: a trunk twice too thick beats a rectangle hidden under an alpha,
a wrong overall proportion beats a colour a shade off. Twelve defects for one
plant is not thoroughness, it is a list nobody can act on: the loop fixes one
or two per round and needs to know which two matter. Everything else you found
goes into the verdict paragraph and an "Also noticed" section of the markdown
report, where it is kept but not counted. The check that runs when you finish
rejects a list over the quota.

## Budget — this is the part that goes wrong

You have about 60 turns. **Spend at most half of them measuring, then write.**

Write a first draft of `defects.json` by turn 30, with the defects you already
have evidence for. Then go back and dig into the ones you are unsure about. An
earlier agent in this harness ran out of turns with seventeen measurement
scripts on disk and nothing written; everything it learned was thrown away.

Measure a thing once. If a script already produced the number, read its output
again rather than re-deriving it.

## Your output

### 1. `{rel_report}/defects.json` — the deliverable

A single JSON object:

```json
{{
  "task": "{task_name}",
  "subjects": ["chair"],
  "verdict": "one paragraph: what the model gets right, and how bad the worst defect is",
  "defects": [
    {{
      "id": "chair.proportion.seat_height",
      "component": "chair",
      "kind": "proportion",
      "severity": "major",
      "summary": "Seat sits too low relative to total chair height",
      "expected": "seat top at 0.44 of total height (measured on the reference)",
      "observed": "seat top at 0.31 of total height (measured on az_270)",
      "evidence": {{
        "measurement": "reference seat/total = 0.44; model = 0.31; 30% short",
        "views": ["az_270.png", "front_solid.png"],
        "scripts": ["scripts/measure_seat_height.py"],
        "crops": ["scripts/seat_compare.png"]
      }},
      "confidence": "high"
    }}
  ]
}}
```

Field rules, all enforced by a check that runs the moment you finish:

- **`id`** — `<component>.<kind>.<slug>`, lowercase, `[a-z0-9_.]` only, unique
  within the file. This is the join key: the same defect found on a later
  attempt must get the same id, so name it after *what is wrong*, never after a
  measurement that will change ("`chair.proportion.seat_height`", not
  "`chair.proportion.seat_0_31`").
- **`component`** — which part of the subject. Use the names in the manifest
  where they fit.
- **`kind`** — one of: {", ".join(f"`{k}`" for k in DEFECT_KINDS)}.
- **`severity`** — `major` if a person comparing the model to the photograph
  would call it wrong; `minor` if they would call it imperfect. At most 2 of
  each per subject (see the quota above).
- **`subjects`** (top level) — the separately standing objects of the brief,
  usually one. Parts are not subjects.
- **`expected`** / **`observed`** — both concrete, both with numbers where a
  number exists.
- **`evidence.views`** — filenames from `views/` that show it. At least one.
- **`evidence.scripts`** / **`evidence.crops`** — paths relative to
  `{rel_report}/`, for whatever you wrote or produced. Optional but expected on
  anything you measured.
- **`confidence`** — `high` / `medium` / `low`. Be honest; a `low` defect that
  turns out real is more useful than one you dropped.
- **Do not add `attribution` or `remedy` fields.** You never saw the plan, the
  action files or the reviews, so you cannot say which part of the harness is
  at fault; a separate curator does that from the evidence. Any such field is
  stripped from your report before it is used.

### 2. `{rel_report}/{task_name}_defects.md`

The same content for a person to read: the verdict, then one section per defect,
worst first, with the evidence written out and the crops referenced inline.

## Finish

Reply with a short summary: how many defects, the worst one, what you measured,
and anything you suspected but could not confirm. Do not paste the JSON back —
it is already on disk.

---

{core.load_skills_index("Scripting")}

---

## Reviewer skills

These were written for the per-step reviewer in this harness, not for you, so
the parts about step checklists do not apply. The parts about how to judge, and
about verifying a value rather than accepting it, are exactly your job.

{reviewer_skills()}
"""


def build_verdict_intro(*, task_name: str, subject_name: str, description: str,
                        reference_name: str, views: list[str], report_dir: Path,
                        manifest: str, baseline: dict, baseline_rel: str,
                        baseline_subject: str | None) -> str:
    """Verdict mode (Version B section 4): judge a KNOWN defect list against a
    rebuilt model, id by id, and scan for new majors. Discovery has a quota,
    so a second discovery pass returns about four defects per object however
    good the model got; acceptance therefore has to be per defect id."""
    rel_report = rel_to(report_dir, ROOT).as_posix()
    view_lines = "\n".join(f"  - `blends/{subject_name}/views/{v}`" for v in views)
    rows = []
    for d in baseline.get("defects") or []:
        ev = d.get("evidence") or {}
        rows.append(
            f"- **`{d.get('id')}`** — {d.get('severity')} / {d.get('kind')} / "
            f"{d.get('component')}\n"
            f"    summary:  {d.get('summary')}\n"
            f"    expected: {d.get('expected')}\n"
            f"    observed BEFORE: {d.get('observed')}\n"
            f"    measured BEFORE: {ev.get('measurement') or '—'}\n"
            f"    views before: {', '.join(ev.get('views') or []) or '—'}"
        )
    baseline_block = "\n".join(rows) or "(no baseline defects)"
    before_views = (f"The renders of the PREVIOUS build are at "
                    f"`blends/{baseline_subject}/views/` (same twelve names), so you can "
                    f"put before and after side by side." if baseline_subject else
                    "The previous build's renders are not available; judge from the "
                    "recorded measurements above.")
    return f"""\
# Checker (verdict mode) — task `{task_name}`, rebuilt model `{subject_name}`

## Your job

A previous build of this task was judged and the defects below were found. The
harness was changed and the task was built again. **Your job is to say, for
each listed defect id, whether it is now RESOLVED, UNCHANGED or WORSE**, and
separately to scan the rebuilt model for any NEW major defect that was not in
the list. You are not scoring the model and you are not re-discovering its
whole defect list: the acceptance decision downstream is per id.

The rules of evidence are the same as before: measure with scripts, do not
eyeball; every judgement cites a view and, where there was a number before,
gives the same number now.

## The brief the builder was given

{description}

## The defects to judge (from `{baseline_rel}`)

{baseline_block}

For each one, re-take the measurement the way it was taken before where you
can (the scripts that produced the earlier numbers are in
`{Path(baseline_rel).parent.as_posix()}/scripts/`; you may read and re-run
them against the new views) and decide:

- **RESOLVED** — a person comparing model and photograph would no longer call
  this out. Not "better": gone, or within the tolerance a careful reviewer
  would accept.
- **UNCHANGED** — still present, whether identical or only partly improved.
  Say in `note` if it improved.
- **WORSE** — present and clearly worse than before.

## What you can look at

| path | what it is |
|---|---|
| `blends/{subject_name}/task/{reference_name}` | **the reference photograph** — ground truth |
| `blends/{subject_name}/task/task.md` | the brief, quoted above |
| `blends/{subject_name}/views/` | renders of the REBUILT model (below) |
| `blends/{subject_name}/manifest.json` | scene inventory — objects, meshes, materials |
| `blends/{subject_name}/{subject_name}.blend` | the rebuilt scene itself |

{view_lines}

{before_views}

The views are as before: `az_000`…`az_315` eight compass directions at one
shared distance, `top`/`bottom`, `front_solid` (viewport Solid shading, form
only) and `final_render` (the build's own camera). A part missing from every
view is missing from the model.

**`blends/{subject_name}/plan/` is off limits**, and so is every other plan
folder. The run is audited afterwards and reading a plan invalidates the
result.

Scene inventory of the rebuilt model:

{manifest}

Opening the `.blend` headlessly is allowed for a question the images cannot
answer (`blender --background <file> --python-expr "..."`). If you measure
geometry out of it, measure evaluated world-space vertices through the
depsgraph, never `bound_box` pushed through `matrix_world`.

## First, look. Then measure.

Before you write any script, open the reference beside `final_render`, then
`top`, then `front_solid`, and write down **the five biggest differences a
person would notice, biggest first**. Put that list at the top of your notes.
It is what the whole measurement pass must then prove or drop, and it is where
the severity comes from: a person notices a purple coat or a paper-thin body
before a tail spike or a blank underside. Do not let what is easy to count
decide what matters.

Three checks run on every subject, whatever the object:

- **Width and depth.** From `top` and `front_solid`, the object's width and
  depth relative to its length or height, against the reference where it shows
  them and against a sanity ratio for the kind of object where it does not
  (a single side photo says nothing about width; a built animal, shoe or tool
  that is a slab from the top is wrong regardless).
- **Colour per part.** Median colour of each named part in `final_render`
  against the matching region of the reference. Report hue and lightness
  differences, not just "darker".
- **Attachment and construction.** For each named part: is it attached where it
  should be (a handle enters the bottom of a head, a foot is the end of a leg,
  laces lie on the tongue on the centreline), and is it a separate block where
  the reference has a continuous form? `manifest.json` gives you the object
  list; a part that exists as its own object where the reference shows one
  surface is worth reporting. A cavity built as added parts (a mouth made of
  gum blocks and lip tubes) instead of a cut is a defect of this kind.

Severity is by visibility, in this order: silhouette and proportion; missing,
misplaced or crudely built parts; surface and material; colour; cleanup.

## Method — measure, do not eyeball

Write short Python into `{rel_report}/scripts/` and run it with `bash`
(`numpy`, `PIL`, `cv2` available). Nothing goes into the working folder's root (no tmp_*.py, crops or notes beside the code): files left there are deleted at the next sync. Read these two first:

```bash
python Tool_scripts/skill_help.py where-code-runs
python Tool_scripts/skill_help.py reading-an-image
```

## Budget

About 50 turns. Judge the listed defects first — they are the deliverable —
and write a first `verdict.json` by turn 25. Then spend what is left on the
scan for new majors. **Do not pad the new-defect list.** Report a new defect
only if it is major (a person would call the model wrong because of it), it
is not one of the listed ids under another name, and you have evidence.
Minor new issues may be listed but will not be acted on.

## Your output

### 1. `{rel_report}/verdict.json` — the deliverable

```json
{{
  "task": "{task_name}",
  "subject": "{subject_name}",
  "baseline": "{baseline_rel}",
  "verdict": "one paragraph: what changed between the two builds, overall",
  "judgements": [
    {{
      "id": "the id exactly as listed",
      "status": "RESOLVED",
      "observed_now": "concrete, with the number where there was one before",
      "note": "optional: partial improvement, caveats",
      "evidence": {{
        "measurement": "before X, now Y",
        "views": ["az_270.png"],
        "scripts": ["scripts/..."],
        "crops": ["scripts/..."]
      }},
      "confidence": "high"
    }}
  ],
  "new_defects": [
    {{
      "id": "<component>.<kind>.<slug>  — same id rules as discovery; must not reuse a listed id",
      "component": "…", "kind": "…", "severity": "major",
      "summary": "…", "expected": "…", "observed": "…",
      "evidence": {{"measurement": "…", "views": ["…"], "scripts": [], "crops": []}},
      "confidence": "high"
    }}
  ]
}}
```

Rules enforced the moment you finish: every listed id appears exactly once in
`judgements` with a `status` from {", ".join(f"`{s}`" for s in VERDICT_STATUSES)};
`evidence.views` names files that exist in `views/`; `new_defects` ids are
well formed and do not collide with the listed ids; `kind` from
{", ".join(f"`{k}`" for k in DEFECT_KINDS)}; `severity` `major`/`minor`.

### 2. `{rel_report}/{subject_name}_verdict.md`

The same content for a person: one section per listed defect with the before
and after numbers, then the new defects.

## Finish

Reply with a short summary: how many RESOLVED / UNCHANGED / WORSE, any new
majors, and what you could not determine.

---

{core.load_skills_index("Scripting")}
"""


# ── validation ───────────────────────────────────────────────────────────────

_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$")


def _validate_defect_entry(d: dict, i: int, view_names: set, seen: set,
                           problems: list, warnings: list, report_dir: Path) -> None:
    did = d.get("id") or ""
    tag = f"defect {did or i}"
    if not _ID_RE.match(did):
        problems.append(f"{tag}: id must be <component>.<kind>.<slug>, "
                        f"lowercase a-z0-9_ — got {did!r}")
    if did in seen:
        problems.append(f"{tag}: duplicate id — ids are the join key between "
                        f"attempts and must be unique")
    seen.add(did)
    for field in ("component", "summary", "expected", "observed"):
        if not str(d.get(field) or "").strip():
            problems.append(f"{tag}: {field} is empty")
    if d.get("kind") not in DEFECT_KINDS:
        problems.append(f"{tag}: kind {d.get('kind')!r} not one of {DEFECT_KINDS}")
    if d.get("severity") not in SEVERITIES:
        problems.append(f"{tag}: severity {d.get('severity')!r} not one of {SEVERITIES}")
    if d.get("confidence") not in CONFIDENCES:
        warnings.append(f"{tag}: confidence {d.get('confidence')!r} not one of {CONFIDENCES}")
    ev = d.get("evidence")
    if not isinstance(ev, dict):
        problems.append(f"{tag}: no evidence object")
        return
    evs = ev.get("views")
    if not isinstance(evs, list) or not evs:
        problems.append(f"{tag}: evidence.views must name at least one view")
    else:
        unknown = [v for v in evs if v not in view_names]
        if unknown:
            problems.append(f"{tag}: evidence.views names {unknown}, which are "
                            f"not files in views/")
    if not str(ev.get("measurement") or "").strip():
        warnings.append(f"{tag}: no measurement — a defect with no number behind "
                        f"it is hard to re-check after a repair")
    for rel in (ev.get("scripts") or []) + (ev.get("crops") or []):
        if not (report_dir / rel).exists():
            warnings.append(f"{tag}: evidence path {rel!r} does not exist")


def strip_checker_attribution(path: Path) -> int:
    """Remove `attribution`/`remedy` fields the checker has no basis to write.
    Returns how many defects carried them."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    n = 0
    for d in data.get("defects") or []:
        if isinstance(d, dict) and ("attribution" in d or "remedy" in d):
            d.pop("attribution", None)
            d.pop("remedy", None)
            n += 1
    if n:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return n


def check_verdict(report_dir: Path, task_name: str, subject_name: str,
                  views: list[str], baseline: dict) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    path = report_dir / "verdict.json"
    if not path.is_file():
        return [f"no verdict.json written into {report_dir}"], warnings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"verdict.json is not valid JSON: {exc}"], warnings
    if not isinstance(data, dict):
        return ["verdict.json must be a JSON object"], warnings
    if not (data.get("verdict") or "").strip():
        problems.append("no verdict paragraph")

    want = [d.get("id") for d in (baseline.get("defects") or []) if d.get("id")]
    js = data.get("judgements")
    if not isinstance(js, list):
        return problems + ["judgements is not a list"], warnings
    view_names = set(views)
    seen: dict[str, int] = {}
    for i, j in enumerate(js):
        if not isinstance(j, dict):
            problems.append(f"judgement[{i}] is not an object")
            continue
        jid = j.get("id") or ""
        tag = f"judgement {jid or i}"
        if jid not in want:
            problems.append(f"{tag}: id is not in the baseline list")
        seen[jid] = seen.get(jid, 0) + 1
        if j.get("status") not in VERDICT_STATUSES:
            problems.append(f"{tag}: status {j.get('status')!r} not one of {VERDICT_STATUSES}")
        if not str(j.get("observed_now") or "").strip():
            problems.append(f"{tag}: observed_now is empty")
        ev = j.get("evidence")
        if not isinstance(ev, dict):
            problems.append(f"{tag}: no evidence object")
        else:
            evs = ev.get("views")
            if not isinstance(evs, list) or not evs:
                problems.append(f"{tag}: evidence.views must name at least one view")
            else:
                unknown = [v for v in evs if v not in view_names]
                if unknown:
                    problems.append(f"{tag}: evidence.views names {unknown}, not in views/")
            if not str(ev.get("measurement") or "").strip():
                warnings.append(f"{tag}: no measurement behind the judgement")
        if j.get("confidence") not in CONFIDENCES:
            warnings.append(f"{tag}: confidence {j.get('confidence')!r} not one of {CONFIDENCES}")
    missing = [w for w in want if w not in seen]
    if missing:
        problems.append(f"{len(missing)} baseline id(s) not judged: {missing}")
    dupes = [k for k, v in seen.items() if v > 1]
    if dupes:
        problems.append(f"judged more than once: {dupes}")

    nd = data.get("new_defects")
    if nd is None:
        warnings.append("new_defects missing — treated as none")
    elif not isinstance(nd, list):
        problems.append("new_defects is not a list")
    else:
        seen_new: set[str] = set(want)
        for i, d in enumerate(nd):
            if not isinstance(d, dict):
                problems.append(f"new_defect[{i}] is not an object")
                continue
            if d.get("id") in want:
                problems.append(f"new defect {d.get('id')!r} reuses a baseline id — "
                                f"judge it under judgements instead")
            _validate_defect_entry(d, i, view_names, seen_new, problems, warnings, report_dir)
    md = report_dir / f"{subject_name}_verdict.md"
    if not md.is_file():
        warnings.append(f"{md.name} not written")
    return problems, warnings


def check_defects(report_dir: Path, task_name: str, views: list[str]
                  ) -> tuple[list[str], list[str]]:
    """Mechanical checks on defects.json. Returns (problems, warnings).

    Problems mean the file cannot be consumed by the rest of the loop.
    Warnings mean it can, but a downstream step will have a thin time of it.
    """
    problems: list[str] = []
    warnings: list[str] = []

    path = report_dir / "defects.json"
    if not path.is_file():
        return [f"no defects.json written into {report_dir}"], warnings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"defects.json is not valid JSON: {exc}"], warnings
    if not isinstance(data, dict):
        return ["defects.json must be a JSON object"], warnings

    if data.get("task") != task_name:
        warnings.append(f"task field is {data.get('task')!r}, expected {task_name!r}")
    if not (data.get("verdict") or "").strip():
        problems.append("no verdict")

    defects = data.get("defects")
    if not isinstance(defects, list):
        return problems + ["defects is not a list"], warnings
    if not defects:
        warnings.append("zero defects reported — possible, but rare enough to be "
                        "worth a second look at the summary")

    # the quota: 2 major + 2 minor per subject (a separately standing object of the
    # brief, usually one). Over-quota lists are rejected so the retry pass has to rank.
    subjects = data.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        warnings.append("no `subjects` list — assuming one subject for the quota")
        n_sub = 1
    else:
        n_sub = len(subjects)
        if n_sub > 3:
            problems.append(f"{n_sub} subjects declared — a subject is a separately standing "
                            f"object of the brief, not a part; a potted plant is one")
    n_major = sum(1 for d in defects if isinstance(d, dict) and str(d.get("severity", "")).lower() == "major")
    n_minor = sum(1 for d in defects if isinstance(d, dict) and str(d.get("severity", "")).lower() == "minor")
    cap = 2 * n_sub
    if n_major > cap or n_minor > cap:
        problems.append(f"{n_major} major / {n_minor} minor defects for {n_sub} subject(s): the quota "
                        f"is 2 major + 2 minor per subject. Keep the ones that most change what a "
                        f"person sees against the photograph; move the rest into the verdict text "
                        f"and an 'Also noticed' section of the markdown report")

    view_names = set(views)
    seen: set[str] = set()
    for i, d in enumerate(defects):
        if not isinstance(d, dict):
            problems.append(f"defect[{i}] is not an object")
            continue
        _validate_defect_entry(d, i, view_names, seen, problems, warnings, report_dir)

    md = report_dir / f"{task_name}_defects.md"
    if not md.is_file():
        warnings.append(f"{md.name} not written — defects.json is the deliverable, "
                        f"but the readable report was asked for too")
    scripts = report_dir / "scripts"
    if not scripts.is_dir() or not any(scripts.iterdir()):
        warnings.append("scripts/ is empty — the checker measured nothing, so every "
                        "defect above is an impression")
    return problems, warnings


def audit_plan_access(result: dict, task_name: str,
                      subject_name: str | None = None) -> list[str]:
    """Did the conversation touch a plan folder? Returns offending calls.

    The checker's independence is the whole reason its verdict means anything,
    so this is verified rather than trusted. Scans every tool call's arguments
    for a path into the plan folder of the task, the subject bundle, or the
    repo's plans/ tree.
    """
    names = {task_name, subject_name or task_name}
    needles = tuple(n for name in names for n in (
        f"blends/{name}/plan", f"blends\\{name}\\plan",
        f"{name}/plan/", f"{name}\\plan\\")) + (
        "plans/" + task_name, "plans\\" + task_name, "/plan/", "\\plan\\")
    hits: list[str] = []
    for m in result.get("messages") or []:
        for call in (m.get("tool_calls") or []):
            blob = json.dumps(call, default=str)
            if any(n in blob for n in needles):
                fn = (call.get("function") or {}).get("name") or call.get("name") or "?"
                hits.append(f"{fn}: {blob[:200]}")
    return hits


# ── main ─────────────────────────────────────────────────────────────────────

def check_task(task_name: str, *, force: bool = False, note: str = "",
               max_iterations: int = 90, subject_name: str | None = None,
               out_dir: Path | None = None, verdict_from: Path | None = None
               ) -> tuple[Path, list[str]]:
    """Discovery mode (default) or, with `verdict_from`, verdict mode.

    `subject_name` is the folder under blends/ to judge — a task name for the
    original build, a run name for a rebuild. `out_dir` overrides
    Checker/reports/<subject>.
    """
    subject_name = subject_name or task_name
    subject = find_subject(subject_name)
    assets = subject_assets(subject)
    verdict_mode = verdict_from is not None
    deliverable = "verdict.json" if verdict_mode else "defects.json"

    report_dir = out_dir or (REPORTS_DIR / subject_name)
    if (report_dir / deliverable).is_file() and not force:
        print(f"[checker] {report_dir}/{deliverable} exists — skipping "
              f"(use --force to redo)")
        return report_dir, []
    (report_dir / "scripts").mkdir(parents=True, exist_ok=True)

    if assets["missing_views"]:
        print(f"[checker] WARNING: views/ is missing {assets['missing_views']} — "
              f"re-run python vb/bundle.py --run <run> --mode live --task {task_name} --force")

    baseline: dict = {}
    if verdict_mode:
        try:
            baseline = json.loads(Path(verdict_from).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"[checker] cannot read baseline {verdict_from}: {exc}")
        if not baseline.get("defects"):
            raise SystemExit(f"[checker] baseline {verdict_from} lists no defects")

    core.load_api_keys()
    agent_env.ensure_plugin_env()          # also chdir()s to ROOT
    os.environ.setdefault("HERMES_API_CALL_STALE_TIMEOUT", STALE_TIMEOUT_S)

    if verdict_mode:
        baseline_rel = rel_to(Path(verdict_from).resolve(), ROOT).as_posix()
        baseline_subject = baseline.get("subject") or baseline.get("task")
        if not (BLENDS_DIR / str(baseline_subject) / "views").is_dir():
            baseline_subject = None
        intro = build_verdict_intro(
            task_name=task_name, subject_name=subject_name,
            description=assets["description"],
            reference_name=assets["reference"].name,
            views=assets["views"], report_dir=report_dir,
            manifest=manifest_digest(assets["manifest"]),
            baseline=baseline, baseline_rel=baseline_rel,
            baseline_subject=baseline_subject,
        )
    else:
        intro = build_intro(
            task_name=task_name,
            description=assets["description"],
            reference_name=assets["reference"].name,
            views=assets["views"],
            report_dir=report_dir,
            manifest=manifest_digest(assets["manifest"]),
            subject_name=subject_name,
        )
    if note:
        intro = ("# Instruction for this run\n\n"
                 f"{note}\n\n"
                 "This overrides anything below it that it contradicts.\n\n"
                 "---\n\n" + intro)
        print(f"[checker] note: {note}")

    from run_agent import AIAgent
    from agent.image_routing import build_native_content_parts

    # Two images up front: the thing it is judging against, and the headline
    # result. Everything else it opens on demand with `read` — the planner
    # learned the hard way that a first message stuffed with images never
    # returns inside the provider's time-to-first-byte window.
    attach = [str(assets["reference"])]
    if assets["final_render"].is_file():
        attach.append(str(assets["final_render"]))
    first_message, _ = build_native_content_parts(intro, image_paths=attach)

    cfg = MODELS.get("checker") or MODELS["planner"]
    kwargs = dict(
        provider=cfg["provider"],
        model=cfg["model"],
        api_key=core.api_key_for(cfg["provider"]),
        base_url=core.base_url_for(cfg["provider"]),
        quiet_mode=False,
        max_iterations=max_iterations,
        ephemeral_system_prompt=SYSTEM_PROMPT,
        enabled_toolsets=agent_env.CHECKER_TOOLSETS,
    )
    if cfg["provider"] == "openai":
        kwargs["reasoning_config"] = {"effort": OPENAI_REASONING_EFFORT}

    mode = "verdict" if verdict_mode else "discovery"
    print(f"[checker] task={task_name}  subject={subject_name}  mode={mode}  "
          f"model={cfg['model']}  views={len(assets['views'])}")
    print(f"[checker] writing into {report_dir}")
    t0 = time.time()
    result = AIAgent(**kwargs).run_conversation(first_message)
    wall = time.time() - t0
    print(f"[checker] finished in {wall:.0f}s")

    agent_env.check_tools(result, "checker")
    agent_env.record_usage(result, wall, report_dir / "usage.json",
                           tag="Checker", extra={"task": task_name, "subject": subject_name,
                                                 "mode": mode})

    summary = (result.get("final_response") or "").strip()
    (report_dir / "checker_summary.md").write_text(summary or "(no response)",
                                                   encoding="utf-8")

    if verdict_mode:
        problems, warnings = check_verdict(report_dir, task_name, subject_name,
                                           assets["views"], baseline)
    else:
        problems, warnings = check_defects(report_dir, task_name, assets["views"])
        stripped = strip_checker_attribution(report_dir / "defects.json")
        if stripped:
            warnings.append(f"stripped attribution/remedy fields from {stripped} defect(s)")
    leaks = audit_plan_access(result, task_name, subject_name)
    if leaks:
        problems.append(f"the checker read a plan folder in {len(leaks)} tool "
                        f"call(s) — this run is not independent and should be redone")

    if warnings:
        print(f"[checker] {len(warnings)} warning(s):")
        for w in warnings[:8]:
            print("   ~", w)
    if problems:
        print(f"[checker] PROBLEMS with {deliverable}:")
        for p in problems[:12]:
            print("   -", p)
    else:
        print(f"[checker] {deliverable} is well formed")
    if leaks:
        print("[checker] PLAN ACCESS VIOLATION:")
        for h in leaks[:4]:
            print("   !", h)

    try:
        data = json.loads((report_dir / deliverable).read_text(encoding="utf-8"))
        if verdict_mode:
            hist: dict[str, int] = {}
            for j in data.get("judgements") or []:
                hist[j.get("status")] = hist.get(j.get("status"), 0) + 1
            majors = [d for d in (data.get("new_defects") or [])
                      if d.get("severity") == "major"]
            print(f"[checker] verdict: {hist}  new majors: {len(majors)}")
        else:
            print(f"[checker] {len(data.get('defects') or [])} defect(s) reported")
    except Exception:
        pass

    (report_dir / "checker_check.json").write_text(json.dumps(
        {"mode": mode, "subject": subject_name, "problems": problems,
         "warnings": warnings, "plan_access": leaks}, indent=2), encoding="utf-8")
    return report_dir, problems


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Find the defects in one finished BlendCUA model.")
    ap.add_argument("--task", required=True,
                    help="task name, e.g. 08_desk_chair (its brief and reference)")
    ap.add_argument("--subject", default=None,
                    help="folder under blends/ to judge (default: the task; a run "
                         "name for a rebuilt model, e.g. 11_umbrella_run_002)")
    ap.add_argument("--out", default=None,
                    help="report folder (default: Checker/reports/<subject>)")
    ap.add_argument("--verdict-from", default=None, metavar="DEFECTS_JSON",
                    help="VERDICT MODE: judge each defect id in this earlier "
                         "defects.json as RESOLVED/UNCHANGED/WORSE and scan for "
                         "new majors; writes verdict.json")
    ap.add_argument("--force", action="store_true", help="re-check even if a report exists")
    ap.add_argument("--note", default="", help="extra instruction for this run")
    ap.add_argument("--retries", type=int, default=1,
                    help="re-check attempts if the deliverable comes back malformed")
    ap.add_argument("--max-iterations", type=int, default=90)
    args = ap.parse_args()

    out_dir = Path(args.out).resolve() if args.out else None
    verdict_from = Path(args.verdict_from).resolve() if args.verdict_from else None
    deliverable = "verdict.json" if verdict_from else "defects.json"
    kw = dict(max_iterations=args.max_iterations, subject_name=args.subject,
              out_dir=out_dir, verdict_from=verdict_from)

    _, problems = check_task(args.task, force=args.force, note=args.note, **kw)
    for attempt in range(args.retries):
        if not problems:
            break
        print(f"\n[checker] re-checking ({attempt + 1}/{args.retries}) — "
              f"feeding the problems back")
        note = (args.note + "\n\n" if args.note else "") + (
            f"Your previous {deliverable} was rejected by the format check:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\n\nFix exactly these. Keep every finding you already made — in the list, "
              "or, where the quota says the list is too long, in the verdict text and the "
              "'Also noticed' section of the markdown report. "
              "Your measurement scripts and crops are still on disk in scripts/."
        )
        _, problems = check_task(args.task, force=True, note=note, **kw)

    if problems:
        print(f"[checker] giving up after {args.retries} retry(ies) — "
              f"{len(problems)} problem(s) remain")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
