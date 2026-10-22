"""Summarise Version B state for one or every task, as text and as
vb/state/REPORT.md.

    python vb/report.py
    python vb/report.py --task 11_umbrella
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def task_report(task: str) -> list[str]:
    st = C.read_json(C.VB_STATE / task / "state.json", {}) or {}
    lines = [f"## {task}", ""]
    if not st:
        return lines + ["(no state)", ""]
    base = st.get("base_run")
    defects = C.read_json(C.CHECKER_REPORTS / task / "defects.json", {}) or {}
    ds = defects.get("defects") or []
    lines.append(f"- base run `{base}`; discovery found {len(ds)} defect(s): "
                 + ", ".join(f"`{d['id']}` ({d['severity']})" for d in ds))
    for n, rs in sorted((st.get("rounds") or {}).items()):
        rd = C.CURATOR_REPORTS / task / f"round_{int(n):02d}"
        cur = C.read_json(rd / "curation.json", {}) or {}
        chosen = [g for g in cur.get("groups") or [] if g.get("chosen")]
        lines.append(f"- **round {n}** stage `{rs.get('stage')}`, path {rs.get('path')}, "
                     f"rebuilt run `{rs.get('new_run')}`")
        for g in chosen:
            rem = next((r for r in cur.get("remedies") or [] if r.get("group_id") == g.get("group_id")), {})
            att = "/".join(a.get("class") for a in g.get("attribution") or [])
            lines.append(f"    - group `{g.get('group_id')}` [{g.get('severity')}, {att}] "
                         f"case {rem.get('case')} -> {rem.get('rebuild')}: {g.get('root_cause', '')[:140]}")
        acc = C.read_json(rd / "acceptance.json", {}) or {}
        if acc:
            for r in acc.get("results") or []:
                lines.append(f"    - {'KEPT' if r['keep'] else 'DROPPED'} `{r['group_id']}`: "
                             f"{r['statuses']}" + (f" — {'; '.join(r['reasons'])}" if r["reasons"] else ""))
            nm = [m.get("id") for m in acc.get("new_majors") or [] if m.get("counts")]
            lines.append(f"    - new majors counted: {nm or 'none'}; survived: "
                         f"{len(acc.get('survived') or [])}/{len(ds)}")
        verdict = C.read_json(C.CHECKER_REPORTS / str(rs.get("new_run")) / "verdict.json", {}) or {}
        if verdict:
            hist: dict[str, int] = {}
            for j in verdict.get("judgements") or []:
                hist[j.get("status")] = hist.get(j.get("status"), 0) + 1
            lines.append(f"    - verdict over all {len(ds)} ids: {hist}")
        applied = C.read_json(rd / "apply" / "applied.json", {}) or {}
        for r in applied.get("remedies") or []:
            files = ((r.get("local_fix") or {}).get("files") or []) + \
                    ((r.get("durable_record") or {}).get("files") or [])
            lines.append(f"    - files for `{r.get('group_id')}`: {', '.join(f'`{f}`' for f in files)}")
    if st.get("kept"):
        lines.append(f"- kept overall: {st['kept']}; snapshot {st.get('snapshot')}")
    lines.append("")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", action="append", default=[])
    a = ap.parse_args()
    tasks = a.task or sorted(p.name for p in C.VB_STATE.iterdir()
                             if p.is_dir() and (p / "state.json").is_file())
    out = ["# Version B report", "", f"generated {C.now()}", ""]
    for t in tasks:
        out += task_report(t)
    text = "\n".join(out)
    (C.VB_STATE / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
