"""Acceptance (Version B section 8): keep each edit whose defect closed.

    python vb/accept.py --task 11_umbrella --round-dir Curator/reports/11_umbrella/round_01 \\
        --verdict Checker/reports/11_umbrella_run_002/verdict.json \\
        --rebuild mem/11_umbrella_run_002/rebuild.json \\
        --snapshot vb/state/11_umbrella/round_01/store_before

A round produced at most two edits and one rebuild. Each edit is judged on
its own group of defect ids:

  1. every id in the group comes back RESOLVED in verdict mode,
  2. no new MAJOR defect appears anywhere in the result,
  3. for R1, geometry outside the declared region hashes identically.

Edits that pass are kept, with the before/after written next to them. Edits
whose defect did not close are dropped and their files restored from the
round's store snapshot. If one group closed and another came back WORSE the
whole round fails and both are dropped: one rebuild cannot tell which edit
did what.
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[1])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def _rel(p: Path | None) -> str | None:
    if p is None:
        return None
    try:
        return str(rel_to(Path(p).resolve(), C.ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def _status_map(verdict: dict) -> dict[str, dict]:
    return {j.get("id"): j for j in verdict.get("judgements") or []}


def _new_majors(verdict: dict, baseline_ids: set[str]) -> list[dict]:
    out = []
    for d in verdict.get("new_defects") or []:
        if d.get("severity") != "major":
            continue
        did = str(d.get("id") or "")
        # a re-description of a baseline defect under another slug is not new
        stem = ".".join(did.split(".")[:2])
        if any(b.startswith(stem + ".") for b in baseline_ids):
            d = {**d, "note": "shares component.kind with a baseline id — treated as a "
                              "re-description, not a regression"}
            out.append({**d, "counts": False})
            continue
        out.append({**d, "counts": True})
    return out


def decide(task: str, round_dir: Path, verdict_path: Path, rebuild_path: Path | None,
           snapshot: Path | None, *, strict_new_majors: bool = True,
           dry_run: bool = False) -> dict:
    curation = C.read_json(round_dir / "curation.json", {})
    applied = C.read_json(round_dir / "apply" / "applied.json", {}) or {}
    verdict = C.read_json(verdict_path, {})
    rebuild = C.read_json(rebuild_path, {}) if rebuild_path else {}
    baseline = C.read_json(C.ROOT / verdict.get("baseline", ""), {}) if verdict.get("baseline") else {}
    baseline_ids = {d.get("id") for d in baseline.get("defects") or []}
    status = _status_map(verdict)
    majors = _new_majors(verdict, baseline_ids)
    counting_majors = [m for m in majors if m.get("counts")]
    geometry = rebuild.get("geometry") or {}
    path = rebuild.get("path") or applied.get("widest") or "?"

    groups = {g.get("group_id"): g for g in curation.get("groups") or []}
    remedies = {r.get("group_id"): r for r in curation.get("remedies") or []}
    applied_by = {r.get("group_id"): r for r in applied.get("remedies") or []}

    results = []
    any_worse = False
    for gid, rem in remedies.items():
        g = groups.get(gid) or {}
        if not g.get("chosen"):
            continue
        ids = g.get("defect_ids") or []
        st = {i: (status.get(i) or {}).get("status", "UNJUDGED") for i in ids}
        closed = all(v == "RESOLVED" for v in st.values()) and bool(ids)
        worse = any(v == "WORSE" for v in st.values())
        any_worse |= worse
        reasons = []
        if not closed:
            reasons.append(f"target not closed: {st}")
        if counting_majors and strict_new_majors:
            reasons.append(f"{len(counting_majors)} new major defect(s) in the result")
        ap = applied_by.get(gid) or {}
        if path == "R1" and geometry.get("measured"):
            expected = set(ap.get("expected_changed_objects") or [])
            moved = set(geometry.get("changed", [])) | set(geometry.get("added", [])) \
                | set(geometry.get("removed", []))
            stray = sorted(moved - expected) if expected else []
            if stray:
                reasons.append(f"R1 hash rule: geometry moved outside the declared "
                               f"region: {stray[:6]}")
        files = []
        for part in ("local_fix", "durable_record"):
            files += [str(f).replace("\\", "/") for f in ((ap.get(part) or {}).get("files") or [])]
        resolved_ids = [i for i, v in st.items() if v in ("RESOLVED", "IMPROVED")]
        results.append({
            "group_id": gid, "defect_ids": ids, "statuses": st, "closed": closed,
            "worse": worse, "case": rem.get("case"), "rebuild": rem.get("rebuild"),
            "files": files, "keep": not reasons, "reasons": reasons,
            "durable_record": rem.get("durable_record"),
            # not kept, but not useless either: something in it closed a defect and nothing
            # got worse. The salvage step reads the reverted edit (store_after) and writes the
            # part that is shown to have worked into the skills.
            "salvage": bool(reasons) and not worse and bool(resolved_ids)
                       and not (counting_majors and strict_new_majors),
            "resolved_ids": resolved_ids,
        })

    closed_any = any(r["closed"] for r in results)
    if closed_any and any_worse:
        for r in results:
            if r["keep"]:
                r["keep"] = False
                r["reasons"].append("round failed: one group closed while another got "
                                    "WORSE, and one rebuild cannot tell which edit did what")
                # this group closed its defects and nothing in it got worse: exactly what
                # the salvage step is for (the WORSE belongs to the other group)
                r["salvage"] = bool(r["resolved_ids"]) and not (counting_majors and strict_new_majors)

    kept = [r for r in results if r["keep"]]
    dropped = [r for r in results if not r["keep"]]

    # revert dropped remedies' files, unless a kept remedy shares the file
    kept_files = {f for r in kept for f in r["files"]}
    reverted: list[str] = []
    if dropped and snapshot and snapshot.is_dir() and not dry_run:
        if not kept:
            # nothing survived: the harness goes back to the entering snapshot
            reverted = restore_whole_store(snapshot, task, round_dir)
        else:
            files = sorted({f for r in dropped for f in r["files"]} - kept_files)
            reverted = C.restore_files(snapshot, files)
    shared = sorted({f for r in dropped for f in r["files"]} & kept_files)

    # the before/after record next to every kept edit
    acc_dir = round_dir / "accepted"
    if kept and not dry_run:
        acc_dir.mkdir(exist_ok=True)
    before_by = {d.get("id"): d for d in baseline.get("defects") or []}
    for r in kept:
        rec = {
            "task": task, "group_id": r["group_id"], "case": r["case"],
            "rebuild_path": path, "kept_at": C.now(),
            "before_run": baseline.get("subject") or baseline.get("task"),
            "after_run": verdict.get("subject"),
            "defects": [{
                "id": i, "status": r["statuses"].get(i),
                "before": (before_by.get(i) or {}).get("observed"),
                "after": (status.get(i) or {}).get("observed_now"),
                "measurement_before": ((before_by.get(i) or {}).get("evidence") or {}).get("measurement"),
                "measurement_after": ((status.get(i) or {}).get("evidence") or {}).get("measurement"),
                "views_before": ((before_by.get(i) or {}).get("evidence") or {}).get("views"),
                "views_after": ((status.get(i) or {}).get("evidence") or {}).get("views"),
            } for i in r["defect_ids"]],
            "files": r["files"],
            "durable_record": r["durable_record"],
            "note": ("R2/R3 are stochastic: a single successful rebuild is weaker evidence "
                     "than an R1 accept" if path in ("R2", "R3") else
                     "R1: deterministic replay of corrected actions"),
        }
        if not dry_run:
            C.write_json(acc_dir / f"{r['group_id']}.json", rec)
            C.log_event({"event": "remedy_kept", **{k: rec[k] for k in
                         ("task", "group_id", "case", "rebuild_path", "before_run",
                          "after_run", "files")},
                         "defects": [d["id"] for d in rec["defects"]]})
    for r in dropped:
        if not dry_run:
            C.log_event({"event": "remedy_dropped", "task": task, "group_id": r["group_id"],
                         "case": r["case"], "rebuild_path": path, "statuses": r["statuses"],
                         "reasons": r["reasons"], "files": r["files"],
                         "attribution": (groups.get(r["group_id"]) or {}).get("attribution")})

    # defects nobody acted on, with their attributions kept
    unacted = []
    chosen_ids = {i for r in results for i in r["defect_ids"]}
    for g in curation.get("groups") or []:
        if g.get("chosen"):
            continue
        unacted.append({"group_id": g.get("group_id"), "defect_ids": g.get("defect_ids"),
                        "severity": g.get("severity"),
                        "attribution": [a.get("class") for a in g.get("attribution") or []],
                        "now": {i: (status.get(i) or {}).get("status", "UNJUDGED")
                                for i in g.get("defect_ids") or []}})
    survived = [i for i in baseline_ids if (status.get(i) or {}).get("status") != "RESOLVED"]
    if not dry_run:
        C.log_event({"event": "round_summary", "task": task, "round_dir": _rel(round_dir),
                     "rebuild_path": path, "kept": [r["group_id"] for r in kept],
                     "dropped": [r["group_id"] for r in dropped],
                     "new_majors": [m.get("id") for m in counting_majors],
                     "survived": survived, "unacted": unacted})

    summary = {
        "task": task, "round_dir": _rel(round_dir), "verdict": _rel(verdict_path),
        "rebuild_path": path, "results": results,
        "kept": [r["group_id"] for r in kept], "dropped": [r["group_id"] for r in dropped],
        "new_majors": majors, "geometry": geometry, "reverted": reverted,
        "shared_files_left_in_place": shared, "survived": survived, "unacted": unacted,
        "closed_any": closed_any, "at": C.now(), "dry_run": dry_run,
        "salvage": [r["group_id"] for r in results if r.get("salvage") and not r["keep"]],
    }
    if not dry_run:
        C.write_json(round_dir / "acceptance.json", summary)
    return summary


def restore_whole_store(snapshot: Path, task: str, round_dir: Path | None = None) -> list[str]:
    """The round's edits back as the round started.

    Restricted to what THIS round touched — the files its applied.json lists,
    plus anything under plans/<task>/ and the generated tool index — so a
    round of one task cannot resurrect edits another task's round dropped
    while the two overlapped in time. Without an applied.json (the remedy step
    itself failed) every difference from the snapshot is reverted."""
    manifest = C.read_json(snapshot / "_manifest.json", {})
    now = C.store_manifest(task)
    files = sorted(set(manifest) | set(now))
    changed = [f for f in files if manifest.get(f) != now.get(f)]
    applied = C.read_json(round_dir / "apply" / "applied.json", {}) if round_dir else {}
    ch = (applied or {}).get("changes") or {}
    claimed = set(ch.get("modified", [])) | set(ch.get("created", [])) | set(ch.get("deleted", []))
    for r in (applied or {}).get("remedies") or []:
        for part in ("local_fix", "durable_record"):
            claimed |= {str(f).replace("\\", "/") for f in ((r.get(part) or {}).get("files") or [])}
    if claimed:
        changed = [f for f in changed if f in claimed or f.startswith(f"plans/{task}/")
                   or f.startswith("Tool_scripts/Tools_ref/")]
    return C.restore_files(snapshot, changed)


def main() -> None:
    ap = argparse.ArgumentParser(description="Keep or drop each remedy of a round.")
    ap.add_argument("--task", required=True)
    ap.add_argument("--round-dir", required=True)
    ap.add_argument("--verdict", required=True)
    ap.add_argument("--rebuild", default=None, help="mem/<run>/rebuild.json")
    ap.add_argument("--snapshot", default=None, help="store snapshot taken before the round")
    ap.add_argument("--lenient-new-majors", action="store_true",
                    help="do not fail a closed remedy because a new major appeared")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = decide(a.task, Path(a.round_dir).resolve(), Path(a.verdict).resolve(),
               Path(a.rebuild).resolve() if a.rebuild else None,
               Path(a.snapshot).resolve() if a.snapshot else None,
               strict_new_majors=not a.lenient_new_majors, dry_run=a.dry_run)
    print(json.dumps({k: s[k] for k in ("kept", "dropped", "new_majors", "survived",
                                         "reverted")}, indent=2, default=str))
    raise SystemExit(0 if s["kept"] else 1)


if __name__ == "__main__":
    main()
