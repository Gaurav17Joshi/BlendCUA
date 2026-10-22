"""Turn a run into the folder the checker judges: blends/<run>/.

    python vb/bundle.py --run 11_umbrella_run_002 --mode live
    python vb/bundle.py --run 11_umbrella_run_002 --mode replay

    blends/<run>/
        <run>.blend               the scene, textures packed
        manifest.json             object / mesh / material inventory
        render_plan_camera.png    the scene's own camera (what the reviewer saw)
        render_three_quarter.png  a fitted three-quarter view
        views/                    az_000..az_315, top, bottom, front_solid,
                                  final_render (copy of the plan-camera render)
        plan/  task/              copies, so the folder is self-contained
        geom_digest.json          per-object mesh hashes (the R1 hash rule)
        bundle.json               provenance

Two modes. `live` saves whatever is in the Blender session right now, which
is the finished state after blendcua_agent.py returns (R2/R3). `replay`
first rebuilds the scene from the run's action files in one dispatch (R1,
or re-bundling an old run). The twelve views are rendered by a HEADLESS
Blender on the saved .blend, so the GUI session is never asked to open a
file.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

VIEW_NAMES = ["az_%03d" % a for a in (0, 45, 90, 135, 180, 225, 270, 315)] + \
             ["top", "bottom", "front_solid"]


def _load_sfb():
    """save_final_blend.py as a module: its SAVE/PROOF/FIT templates and the
    replay-then-save path are exactly what a bundle needs."""
    spec = importlib.util.spec_from_file_location(
        "save_final_blend", C.TOOL_SCRIPTS / "save_final_blend.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_blender() -> str | None:
    if os.environ.get("BLENDER"):
        return os.environ["BLENDER"]
    for base in (r"C:\Program Files\Blender Foundation",
                 r"C:\Program Files (x86)\Blender Foundation"):
        if os.path.isdir(base):
            for name in sorted(os.listdir(base), reverse=True):
                exe = os.path.join(base, name, "blender.exe")
                if os.path.isfile(exe):
                    return exe
    return None


def _flat_paths(run: str) -> dict:
    return {
        "blend": C.BLENDS / f"{run}.blend",
        "json": C.BLENDS / f"{run}.json",
        "png": C.BLENDS / f"{run}.png",
        "fit": C.BLENDS / f"{run}_fit.png",
    }


def save_live(run: str, *, timeout: float = 900.0) -> bool:
    """Save the live scene + the two presentation renders as flat files."""
    sfb = _load_sfb()
    C.BLENDS.mkdir(exist_ok=True)
    fp = _flat_paths(run)
    st, dt = C.dispatch(sfb.SAVE_TMPL.format(out=str(fp["blend"]), report=str(fp["json"])),
                        300, "save")
    if st is None or not st.get("ok"):
        print(f"[bundle] SAVE FAILED: {str((st or {}).get('error'))[-400:]}")
        return False
    print(f"[bundle] saved {fp['blend'].name} in {dt:.1f}s")
    st, dt = C.dispatch(sfb.PROOF_TMPL.format(png=str(fp["png"])), timeout, "proof render")
    if st is None or not st.get("ok"):
        print(f"[bundle] proof render failed: {str((st or {}).get('error'))[-300:]}")
    else:
        print(f"[bundle] proof render {dt:.1f}s")
    st, dt = C.dispatch(sfb.FIT_TMPL.format(png=str(fp["fit"])), timeout, "fit render")
    if st is None or not st.get("ok"):
        print(f"[bundle] fit render failed: {str((st or {}).get('error'))[-300:]}")
    else:
        print(f"[bundle] fit render {dt:.1f}s")
    return True


def replay_and_save(run: str, *, timeout: float = 1800.0) -> bool:
    ok, err, n = C.batch_replay(run, timeout_s=timeout, label="bundle replay")
    if not ok:
        print(f"[bundle] REPLAY FAILED ({n} actions): {err[-600:]}")
        return False
    return save_live(run)


def reshape(run: str, task: str) -> Path:
    dest = C.BLENDS / run
    dest.mkdir(parents=True, exist_ok=True)
    fp = _flat_paths(run)
    rename = {"blend": f"{run}.blend", "json": "manifest.json",
              "png": "render_plan_camera.png", "fit": "render_three_quarter.png"}
    for key, name in rename.items():
        if fp[key].is_file():
            shutil.move(str(fp[key]), str(dest / name))
    for src, sub in ((C.PLANS / task, "plan"), (C.task_dir(task), "task")):
        if src.is_dir():
            if (dest / sub).is_dir():
                shutil.rmtree(dest / sub)
            shutil.copytree(src, dest / sub,
                            ignore=shutil.ignore_patterns("__pycache__", "_archive*", "*.blend"))
    return dest


def render_views(dest: Path, run: str, *, force: bool = False) -> bool:
    views = dest / "views"
    views.mkdir(exist_ok=True)
    have = [n for n in VIEW_NAMES if (views / f"{n}.png").is_file()]
    if len(have) == len(VIEW_NAMES) and not force:
        print(f"[bundle] views already present")
    else:
        blender = find_blender()
        if not blender:
            print("[bundle] no blender.exe found for the headless views (set BLENDER)")
            return False
        blend = dest / f"{run}.blend"
        t0 = time.time()
        proc = subprocess.run([blender, "--background", str(blend), "--python",
                               str(C.TOOL_SCRIPTS / "render_views.py"), "--", str(views)],
                              capture_output=True, text=True, cwd=str(C.ROOT),
                              encoding="utf-8", errors="replace")
        got = [n for n in VIEW_NAMES if (views / f"{n}.png").is_file()]
        print(f"[bundle] views {len(got)}/{len(VIEW_NAMES)} in {time.time() - t0:.0f}s")
        if len(got) != len(VIEW_NAMES):
            for line in [l for l in (proc.stdout or "").splitlines() if "[views]" in l][-6:]:
                print("    " + line)
            for line in (proc.stderr or "").strip().splitlines()[-4:]:
                print("    ! " + line)
            return False
    src = dest / "render_plan_camera.png"
    if src.is_file():
        shutil.copy2(src, views / "final_render.png")
    return (views / "final_render.png").is_file()


def bundle_run(run: str, *, mode: str = "live", task: str | None = None,
               force: bool = False, base_run: str | None = None,
               digest: bool = True) -> Path | None:
    task = task or C.task_of_run(run)
    dest = C.BLENDS / run
    if (dest / "views" / "final_render.png").is_file() and not force:
        print(f"[bundle] blends/{run} already complete")
        return dest
    if not C.blender_up():
        print("[bundle] Blender server is not listening on 6666")
        return None
    ok = save_live(run) if mode == "live" else replay_and_save(run)
    if not ok:
        return None
    if digest:
        d = C.geom_digest(run)
        if d is not None:
            print(f"[bundle] geometry digest: {d.get('n_objects')} objects, "
                  f"scene {d.get('scene_hash')}")
    dest = reshape(run, task)
    if digest and (C.MEM / run / "geom_digest.json").is_file():
        shutil.copy2(C.MEM / run / "geom_digest.json", dest / "geom_digest.json")
    if not render_views(dest, run, force=force):
        print("[bundle] view rendering incomplete")
        return None
    C.write_json(dest / "bundle.json", {
        "run": run, "task": task, "mode": mode, "base_run": base_run,
        "at": C.now(), "views": sorted(p.name for p in (dest / "views").glob("*.png")),
    })
    print(f"[bundle] -> blends/{run}")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description="Bundle a run into blends/<run>/ for the checker.")
    ap.add_argument("--run", required=True)
    ap.add_argument("--mode", choices=["live", "replay"], default="live")
    ap.add_argument("--task", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-digest", action="store_true")
    a = ap.parse_args()
    out = bundle_run(a.run, mode=a.mode, task=a.task, force=a.force, digest=not a.no_digest)
    raise SystemExit(0 if out else 1)


if __name__ == "__main__":
    main()
