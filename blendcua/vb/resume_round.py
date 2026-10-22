"""Resume a round whose rebuild died mid-build (Blender closed, machine slept).

    python vb/resume_round.py --task 18_thors_hammer --round 1 --dead-run 18_thors_hammer_run_002 --from-step 2

Copies the finished steps of the dead run into a fresh run, replays them into
the (restarted) Blender session, runs the executor for the remaining steps,
then bundles, judges in verdict mode, and accepts — the same tail as
version_b.py, with the round's state updated to point at the new run.
"""
from __future__ import annotations
import sys as _vp_sys, pathlib as _vp_pl; _vp_sys.path.insert(0, str(_vp_pl.Path(__file__).resolve().parents[1])); from viewpaths import rel_to  # noqa: E402,E702  (junction-tolerant relative paths for worker views)

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C      # noqa: E402
import rebuild as R     # noqa: E402
import accept as A      # noqa: E402
import version_b as V   # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--dead-run", required=True)
    ap.add_argument("--from-step", type=int, required=True)
    ap.add_argument("--lenient-new-majors", action="store_true")
    a = ap.parse_args()

    st = V.load_state(a.task)
    rs = st["rounds"].setdefault(str(a.round), {})
    rd = V.round_dir(a.task, a.round)
    snap = C.VB_STATE / a.task / f"round_{a.round:02d}" / "store_before"
    logs = C.VB_STATE / a.task / "logs"
    path = rs.get("path", "R3")

    out = R.execute_r2(a.task, from_step=a.from_step, base_run=a.dead_run,
                       log=logs / f"round{a.round}_build_resumed.log")
    new_run = out.get("run")
    out["path"] = path
    out["resumed_from"] = {"dead_run": a.dead_run, "from_step": a.from_step}
    R._record(new_run, out)
    rs.update(new_run=new_run, rebuild=out, bundle_ok=bool(out.get("ok")), stage="rebuild",
              resumed_from=a.dead_run)
    V.save_state(st)
    if not out.get("ok"):
        print(f"[resume] rebuild failed: {out.get('error')}")
        raise SystemExit(1)

    verdict = V.stage_verdict(a.task, new_run, logs / f"round{a.round}_verdict.log",
                              subject=st.get("base_subject"))
    rs["stage"] = "verdict"
    V.save_state(st)
    summary = A.decide(a.task, rd, verdict, C.MEM / new_run / "rebuild.json", snap,
                       strict_new_majors=not a.lenient_new_majors)
    rs.update(stage="accept", kept=summary["kept"], dropped=summary["dropped"],
              survived=summary["survived"])
    st["kept"] = (st.get("kept") or []) + summary["kept"]
    st["finished"] = C.now()
    V.save_state(st)
    print(f"[resume] round {a.round}: kept {summary['kept'] or 'nothing'}, "
          f"dropped {summary['dropped'] or 'nothing'}, {len(summary['survived'])} survive")
    if summary["kept"]:
        note = (f"# Version B — {a.task}\n\nKept: {', '.join(summary['kept'])}\n\n"
                f"See Curator/reports/{a.task}/round_*/accepted/*.json.\n")
        snapd = V.snapshot_harness(a.task, note)
        st["snapshot"] = str(rel_to(snapd, C.ROOT)) if snapd else None
        V.save_state(st)


if __name__ == "__main__":
    main()
