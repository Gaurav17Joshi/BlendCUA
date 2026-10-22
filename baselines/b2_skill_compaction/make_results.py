"""Collect every B2 run into ../Results/ as one readable set.

    python make_results.py

Re-runnable: it reads the run folders directly, so running it again after more
tasks finish refreshes everything. It writes

    Results/README.md          what was run, the headline table, the findings
    Results/summary.csv        one row per (entrant, task) -- every metric
    Results/head_to_head.md    per-task comparison across entrants
    Results/by_entrant/        the per-entrant tables run_b2.py generates

Nothing is computed twice: the numbers come from each run's usage.json, which
the agent wrote at the end of the task.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "Results"

# tag -> (label, model, harness, library?, billing)
ENTRANTS = {
    "luna":         ("luna",             "gpt-5.6-luna",                    "B2 loop",     True,  "api"),
    "luna_nolib":   ("luna no-library",  "gpt-5.6-luna",                    "B2 loop",     False, "api"),
    "deepseek":     ("deepseek",         "deepseek/deepseek-v4.1-flash",    "B2 loop",     True,  "api"),
    "muse":         ("muse",             "meta/muse-spark-1.3-contributor", "B2 loop",     True,  "api"),
    "claude":       ("opus",             "claude-opus-5",                   "Claude Code", True,  "plan"),
    "fable":        ("fable",            "claude-fable-5-1",                "Claude Code", True,  "plan"),
    "fable_nolib":  ("fable no-library", "claude-fable-5-1",                "Claude Code", False, "plan"),
    "sonnet_nolib": ("sonnet no-library", "claude-sonnet-5",                "Claude Code", False, "plan"),
    "sonnet":       ("sonnet",           "claude-sonnet-5",                 "Claude Code", True,  "plan"),
    # run on BLENDER-1 (24 Sept); gpt-6 profiles priced with luna-5.6's table -> "$" is an equivalent
    "luna6max":        ("luna6 max",               "gpt-6-luna (max)",  "B2 loop", True,  "eq"),
    "luna6max_nolib":  ("luna6 max no-library",    "gpt-6-luna (max)",  "B2 loop", False, "eq"),
    "luna6high":       ("luna6 high",              "gpt-6-luna (high)", "B2 loop", True,  "eq"),
    "luna6high_nolib": ("luna6 high no-library",   "gpt-6-luna (high)", "B2 loop", False, "eq"),
    "sol6":            ("sol6 (not in paper)",     "gpt-6-sol (max)",   "B2 loop", True,  "eq"),
    "opus55":          ("opus 5.5",                "claude-opus-5-5 (max)", "Claude Code", True, "plan"),
}

FIELDS = ["entrant", "model", "harness", "library", "billing", "split", "task", "run",
          "wall_clock_min", "cost_usd", "tool_calls", "blender_actions", "blender_restarts",
          "output_tokens", "review_min_tool_calls", "skills_retrieved", "skills_used",
          "skills_used_names", "blend_mb", "produced_blend", "bundled", "end_reason"]


def read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def rows() -> list[dict]:
    out = []
    for tag, (label, model, harness, lib, billing) in ENTRANTS.items():
        runs = ROOT / f"runs{'_' + tag if tag != 'main' else ''}"
        if not runs.is_dir():
            continue
        for d in sorted(runs.glob("*_run_*")):
            st_ = read(d / "status.json") or {}
            if st_.get("phase") != "done":
                continue
            u = read(d / "usage.json")
            if not u:
                continue
            blend = d / "final.blend"
            sk = u.get("skills", {})
            rev = u.get("review", {}) or {}
            out.append({
                "entrant": label, "model": model, "harness": harness,
                "library": "yes" if lib else "no", "billing": billing,
                "split": "test", "task": u["task"], "run": u["run"],
                "wall_clock_min": u.get("wall_clock_min"),
                "cost_usd": round(u.get("cost_usd") or 0, 4),
                "tool_calls": u.get("tool_calls"),
                "blender_actions": u.get("blender_actions"),
                "blender_restarts": u.get("blender_restarts"),
                "output_tokens": (u.get("agent") or {}).get("output_tokens"),
                "review_min_tool_calls": rev.get("tool_calls") if rev.get("happened") else None,
                "skills_retrieved": len(sk.get("retrieved", [])),
                "skills_used": len(sk.get("referenced_in_code", [])),
                "skills_used_names": " ".join(sk.get("referenced_in_code", [])),
                "blend_mb": round(blend.stat().st_size / 1e6, 2) if blend.is_file() else None,
                "produced_blend": u.get("produced_blend"),
                "bundled": st_.get("bundled"),
                "end_reason": u.get("end_reason"),
            })
    return out


SLUG = {"opus": "opus", "fable": "fable", "fable no-library": "fable_no-library",
        "sonnet no-library": "sonnet_no-library", "sonnet": "sonnet",
        "luna": "luna", "luna no-library": "luna_no-library", "deepseek": "deepseek",
        "muse": "muse", "luna6 max": "luna6max", "luna6 max no-library": "luna6max_no-library",
        "luna6 high": "luna6high", "luna6 high no-library": "luna6high_no-library",
        "sol6 (not in paper)": "sol6", "opus 5.5": "opus55"}


def place(src: Path, dst: Path) -> None:
    """Hardlink src to dst, falling back to a copy. The deliverables are ~1 GB;
    a hardlink is the same bytes on the same volume, costs nothing, and reads
    exactly like a real file to anything judging it."""
    if dst.exists():
        if dst.stat().st_size == src.stat().st_size:
            return
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def deliverables(rs: list[dict]) -> int:
    """Lay the judge folders out by task: every entrant's attempt side by side,
    with the brief and reference plates once per task."""
    n = 0
    for r in rs:
        tag = next(t for t, v in ENTRANTS.items() if v[0] == r["entrant"])
        bundle = ROOT / f"blends_{tag}" / r["run"]
        if not bundle.is_dir():
            continue
        task_dir = OUT / "deliverables" / r["task"]
        ent_dir = task_dir / SLUG[r["entrant"]]
        for f in bundle.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(bundle)
            if rel.parts[0] == "task":          # the brief: once per task, not per entrant
                place(f, task_dir / "_brief" / Path(*rel.parts[1:]))
                continue
            if f.suffix == ".blend":            # same name in every entrant folder: <task>.blend
                place(f, ent_dir / f"{r['task']}.blend")
                continue
            place(f, ent_dir / rel)
            n += 1
        (ent_dir / "_run_facts.json").write_text(json.dumps({
            k: r[k] for k in ("entrant", "model", "harness", "library", "run",
                              "wall_clock_min", "cost_usd", "billing", "tool_calls",
                              "blender_actions", "skills_used_names", "end_reason")},
            indent=2), encoding="utf-8")
    return n


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def fmt(v, spec=""):
    return "–" if v is None else (format(v, spec) if spec else str(v))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "by_entrant").mkdir(exist_ok=True)
    rs = rows()

    with open(OUT / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rs)

    for tag in ENTRANTS:
        src = ROOT / f"RESULTS_{tag}.md"
        if src.is_file():
            shutil.copy2(src, OUT / "by_entrant" / src.name)
    if (ROOT / "RESULTS.md").is_file():
        shutil.copy2(ROOT / "RESULTS.md", OUT / "by_entrant" / "RESULTS_train_luna.md")

    # ── headline ────────────────────────────────────────────────────────
    L = ["# BlendCUA baseline B2 — test-split results", "",
         "Every entrant below runs the **same B2 baseline**: the same Blender session over the",
         "same TCP channel, the same seven tools, the same system prompt, one review round per",
         "task, and the same bundler producing the judge folder. They differ only in the model,",
         "the harness that drives it, and whether the skill library is available.", "",
         "The library, where used, is the frozen 54-skill one the 20-task training curriculum",
         "produced; every test run is `--freeze`, so none of them writes to it.", "",
         "## Entrants", "",
         "| entrant | model | harness | skill library | billing |",
         "|---|---|---|---|---|"]
    seen = []
    for r in rs:
        k = (r["entrant"], r["model"], r["harness"], r["library"], r["billing"])
        if k not in seen:
            seen.append(k)
    for e, m, h, lib, b in seen:
        bill = ("real API spend" if b == "api" else
                "priced at gpt-5.6-luna rates — the $ column is a token-budget equivalent, not money spent"
                if b == "eq" else
                "Claude subscription — the $ column is the list-price equivalent, not money spent")
        L.append(f"| {e} | `{m}` | {h} | {lib} | {bill} |")

    L += ["", "## Headline", "",
          "| entrant | tasks done | total $ | median $/task | median min | finished by agent | "
          "Blender restarts | skills used |", "|---|---|---|---|---|---|---|---|"]
    for e, *_ in seen:
        sub = [r for r in rs if r["entrant"] == e]
        costs = [r["cost_usd"] for r in sub]
        L.append(f"| {e} | {len(sub)}/10 | {sum(costs):.2f} | {fmt(med(costs), '.2f')} | "
                 f"{fmt(med([r['wall_clock_min'] for r in sub]), '.0f')} | "
                 f"{sum(1 for r in sub if r['end_reason'] == 'finished')}/{len(sub)} | "
                 f"{sum(r['blender_restarts'] or 0 for r in sub)} | "
                 f"{sum(r['skills_used'] for r in sub)} |")

    L += ["", "**Read the `$` column carefully.** For luna, deepseek and muse it is real API",
          "spend. For the Claude entrants the run is billed to a Claude subscription and nothing",
          "is charged per token; the figure is the list-price equivalent Claude Code reports, kept",
          "only so the columns are comparable. The gpt-6 entrants (luna6, sol6) are priced with",
          "gpt-5.6-luna's table, so their $ is the same token budget, not what was billed; sol6 at",
          "gpt-6-sol's published rates is about $19 for its 4 builds. sol6 is for reference only,",
          "not part of the paper.", "",
          "## What the skill library did", ""]
    for e, *_ in seen:
        sub = [r for r in rs if r["entrant"] == e]
        if not sub or sub[0]["library"] == "no":
            continue
        ret = sum(r["skills_retrieved"] for r in sub)
        use = sum(r["skills_used"] for r in sub)
        tasks = sum(1 for r in sub if r["skills_used"])
        L.append(f"- **{e}**: {ret} skills retrieved into context over {len(sub)} tasks, "
                 f"{use} actually used in the code it ran, on {tasks}/{len(sub)} tasks.")
    L += ["",
          "Retrieval puts up to 8 skills in the prompt; \"used\" counts a skill whose module name",
          "appears in the Blender code the agent actually ran. The gap between the two is the",
          "finding: most retrieved skills are read and then not imported. The no-library entrants",
          "are the controlled test of whether that matters — they never see a skill at all, and",
          "their prompt is ~3.6K characters against ~31K with the library.", "",
          "## Files", "",
          "- **`deliverables/`** — the actual output to judge: one folder per task, one folder",
          "  per entrant inside it, each with the saved `.blend`, twelve renders from the same",
          "  bundler, the geometry digest and the run's facts. Start at `deliverables/README.md`.",
          "- `summary.csv` — one row per (entrant, task), every metric",
          "- `head_to_head.md` — per-task comparison across entrants",
          "- `by_entrant/` — the full per-entrant tables, including the 20-task training run", "",
          "The files under `deliverables/` are hardlinks to `Blend_baselinB2/blends_<entrant>/`,",
          "so they take no extra disk and read as ordinary files. Copying or zipping the folder",
          "materialises them normally.", "",
          f"Generated by `Blend_baselinB2/make_results.py` from {len(rs)} completed runs.", ""]
    (OUT / "README.md").write_text("\n".join(L), encoding="utf-8")

    # ── per task ────────────────────────────────────────────────────────
    H = ["# Per-task comparison", "",
         "Same task, same harness, different entrant. `$` is real spend for luna/deepseek/muse",
         "and list-price equivalent plan usage for the Claude entrants (see README).", ""]
    for task in sorted({r["task"] for r in rs}):
        sub = sorted((r for r in rs if r["task"] == task), key=lambda r: r["wall_clock_min"] or 0)
        H += [f"## {task}", "",
              "| entrant | library | min | $ | tool calls | Blender actions | blend MB | skills used |",
              "|---|---|---|---|---|---|---|---|"]
        for r in sub:
            names = f" ({r['skills_used_names'].replace(' ', ', ')})" if r["skills_used"] else ""
            H.append(f"| {r['entrant']} | {r['library']} | {fmt(r['wall_clock_min'])} | "
                     f"{r['cost_usd']:.2f} | {fmt(r['tool_calls'])} | {fmt(r['blender_actions'])} | "
                     f"{fmt(r['blend_mb'])} | {r['skills_used']}{names} |")
        H.append("")
    (OUT / "head_to_head.md").write_text("\n".join(H), encoding="utf-8")

    n_files = deliverables(rs)

    J = ["# Deliverables — for judging", "",
         "One folder per task; inside it, one folder per entrant, so the attempts can be",
         "compared side by side against the same brief.", "",
         "```",
         "deliverables/<task>/_brief/        the task.md and the reference plates",
         "deliverables/<task>/<entrant>/",
         "    <task>.blend                   the deliverable, images packed",
         "    views/final_render.png         the scene as the agent left it",
         "    views/front_solid.png          solid shading, no materials -- shows the geometry",
         "    views/az_000..az_315.png       eight turntable angles",
         "    views/top.png, bottom.png",
         "    render_three_quarter.png       framed hero render",
         "    render_plan_camera.png         the agent's own camera",
         "    geom_digest.json               object/vert/face counts, materials, animation",
         "    manifest.json, bundle.json     what the bundler recorded",
         "    _run_facts.json                model, harness, library, time, spend",
         "```", "",
         "Every file here is produced by the **same bundler** from the saved `.blend`, so the",
         "renders are directly comparable: same camera logic, same lighting fallback, same",
         "resolution. Nothing was re-rendered or touched by hand.", "",
         "## What to judge", "",
         "Read `_brief/task.md` and the reference plates first, then compare each entrant's",
         "renders against them. `front_solid.png` is the honest view of the geometry, since",
         "materials and lighting can flatter a bad mesh. `geom_digest.json` says whether the",
         "animation or simulation the brief asked for is actually in the file.", "",
         "Note the entrants differ in *harness* as well as model: luna, deepseek and muse run in",
         "B2's own loop, the Claude entrants in Claude Code. `<entrant>/_run_facts.json` and the",
         "top-level `README.md` give the full configuration, including whether the skill library",
         "was available.", "",
         "## What is here", "",
         "| task | entrants |", "|---|---|"]
    for task in sorted({r["task"] for r in rs}):
        ents = sorted(SLUG[r["entrant"]] for r in rs if r["task"] == task)
        J.append(f"| {task} | {', '.join(ents)} |")
    J.append("")
    (OUT / "deliverables" / "README.md").write_text("\n".join(J), encoding="utf-8")
    print(f"placed {n_files} deliverable files")

    print(f"wrote {OUT}")
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(OUT)}  ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
