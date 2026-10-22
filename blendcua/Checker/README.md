# Checker

The **CHECKER** block of method b (`md_files/method_variants_handoff.md` §4).

```
TASK -> PLAN + BUILD -> RESULT -> [CHECKER] -> ATTRIBUTE -> CHEAPEST REMEDY
     -> REWIND + REPLAY -> [CHECKER] -> FIXED? -> KEEP -> HARNESS
```

It looks at a finished model and finds what is wrong with it. Everything
downstream keys off its output, so it is the first thing method b needs.

    python Checker/checker_agent.py --task 08_desk_chair

## What it sees, and what it does not

| given | withheld |
|---|---|
| `blends/<Task>/task/` — the brief and the reference photograph | **`blends/<Task>/plan/`** |
| `blends/<Task>/views/` — twelve renders of the result | |
| `blends/<Task>/manifest.json` — scene inventory | |
| `blends/<Task>/<Task>.blend` — sparingly | |

**The plan is withheld on purpose.** A checker that reads the plan checks the
model against what it was supposed to be, and inherits the blind spots that
caused the defects in the first place: a plan that never considered whether the
castors touch the floor produces a build that ignores it *and* a review
checklist that does not mention it. Only a judge who never saw the plan finds
that. The photograph and the brief are the ground truth.

This is verified, not trusted — `audit_plan_access()` scans every tool call the
conversation made for a path into the plan folder and fails the run if it finds
one.

For the same reason the checker must stay **outside whatever the remedy step is
allowed to edit**. If a remedy can touch the checker, the cheapest way to make
`FIXED?` say yes is to weaken the check. Same concern that motivated the
add-only rule for reviewer skills in the current loop.

It works mostly from images. `manifest.json` covers the questions that need the
scene rather than a picture (a part never built, a material left on
`Material.001`) without paying for a Blender launch.

## Output

    Checker/reports/<Task>/
        defects.json          the deliverable
        <Task>_defects.md     the same thing to read
        scripts/              its own measurement scripts, crops, overlays
        checker_summary.md    what it said when it finished
        checker_check.json    validation result + plan-access audit
        usage.json            cost of the call

### `defects.json`

```json
{
  "task": "08_desk_chair",
  "verdict": "one paragraph",
  "defects": [
    {
      "id": "chair.proportion.seat_height",
      "component": "chair",
      "kind": "proportion",
      "severity": "major",
      "summary": "Seat sits too low relative to total chair height",
      "expected": "seat top at 0.44 of total height (reference)",
      "observed": "seat top at 0.31 of total height (az_270)",
      "evidence": {
        "measurement": "reference 0.44, model 0.31, 30% short",
        "views": ["az_270.png", "front_solid.png"],
        "scripts": ["scripts/measure_seat_height.py"],
        "crops": ["scripts/seat_compare.png"]
      },
      "confidence": "high"
    }
  ]
}
```

**`id` is the join key** and the reason the schema is this strict. Method a
needs D1 and D2 matched defect-by-defect to tell whether naming a defect in the
plan closed it; method b needs to ask "is *this* defect fixed?" after a replay.
Both fail if the same defect comes back under a different name, so the id must
describe *what is wrong* and never a measurement that will change:
`chair.proportion.seat_height`, not `chair.proportion.seat_0_31`.

`check_defects()` enforces the shape — id format and uniqueness, `kind` and
`severity` from fixed vocabularies, non-empty `expected`/`observed`, and
`evidence.views` naming files that actually exist in `views/`. A malformed
report is fed back and re-checked (`--retries`).

## Makeup

A near-copy of `planner_agent.py`: same shape of job (one long image-heavy
conversation with a shell and a scratch folder, measure first and write
second), so it uses the same `agent_env` plugin setup, the same
`STALE_TIMEOUT_S`, the same turn-budget discipline, the same
`record_usage`/`check_tools`, and the same "problems fed back, retry" loop.

Two central-config entries were added rather than hardcoded:

- `models.py` -> `MODELS["checker"]`
- `agent_env.py` -> `CHECKER_TOOLSETS = ["blendcua_fs"]`

`blendcua_fs` only. The checker never builds anything, and `blendcua`'s
`write_and_run` is gated on an active step context — there is no step in
progress when the checker runs, so offering it could only ever produce a
refusal.

Its role skills are `Skills/Reviewer/*.md`, injected in full, the same way the
planner gets `Skills/Planner/*.md`. `Skills/Scripting` is indexed, not inlined.

## Verdict mode

Discovery has a quota, so a second discovery pass on a rebuilt model returns
about four defects per object however good it got. Acceptance in Version B is
therefore per defect id:

    python Checker/checker_agent.py --task 11_umbrella --subject 11_umbrella_run_002         --verdict-from Checker/reports/11_umbrella/defects.json

Given the earlier `defects.json`, the checker judges each id RESOLVED /
UNCHANGED / WORSE against the rebuilt model's twelve views (the earlier
build's views are named so before and after can sit side by side), retaking
the same measurement, and separately scans for NEW major defects. It writes
`verdict.json` into `Checker/reports/<subject>/`; `check_verdict()` enforces
that every baseline id is judged exactly once, statuses come from the fixed
vocabulary, and new-defect ids are well formed and do not reuse a baseline id.
The plan-access audit covers the subject's plan copy, `plans/<task>`, and any
`blends/*/plan/`.

`--subject` names the folder under `blends/` (a run name for a rebuild; the
bundle is made by `vb/bundle.py`), `--out` overrides the report folder.

## What consumes it

`Curator/` does ATTRIBUTE + REMEDY, `Curator/apply_remedy.py` carries the
remedy out, `vb/rebuild.py` rebuilds, and `vb/accept.py` keeps or drops each
edit on this file's verdict. See `vb/README.md`.

The checker used to fill in `attribution` and `remedy` fields itself. It has no
basis for that (it never saw the plan, the action files or the reviews), so the
prompt now forbids the fields and `strip_checker_attribution()` removes any it
still writes.
