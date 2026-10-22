"""Bundle a finished B2 run for the judge, with the main system's own bundler.

    python bundle_b2.py --run 02_iron_gate_run_001

Writes Blend_baselinB2/blends/<run>/ exactly as BlendCuavb_run/vb/bundle.py
does: <run>.blend, manifest.json, render_plan_camera.png,
render_three_quarter.png, views/ (the twelve checker views), task/,
geom_digest.json, bundle.json.

How it stays identical: it imports BlendCuavb_run/vb/bundle.py and common.py
and uses their functions and templates unchanged (SAVE/PROOF/FIT templates from
save_final_blend.py, render_views.py for the twelve views, geom_digest.py for
the digest) -- only the module-level PATHS are pointed into Blend_baselinB2, so
nothing is ever written under BlendCuavb_run. It follows bundle_from_blend.py
(headless, from <run>/final.blend) rather than `--mode live`, because live mode
dispatches to the main experiment's Blender on port 6666; B2's own GUI Blender
is closed by the time bundling runs. The framing and lighting code paths are
the same in both modes.

One addition: the proof and fit renders use whatever engine the scene is set
to, and a headless Blender renders Cycles on the CPU, so a GPU-enable prelude is
put in front of those two templates (render settings are otherwise untouched).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import b2_config as CFG

sys.path.insert(0, str(CFG.MAIN / "vb"))
import common as C  # noqa: E402
import bundle as B  # noqa: E402

# Point the bundler's module-level paths at B2. TOOL_SCRIPTS / TOOLS_CODE stay
# pointing at the main repo: those are the scripts being reused, read-only.
C.BLENDS = CFG.BLENDS
C.MEM = CFG.STATE / "bundle_mem"
C.VB_STATE = CFG.STATE / "bundle_state"
C.PLANS = CFG.STATE / "no_plans"          # B2 has no plans; reshape() skips a missing dir
C.TASKS = CFG.TASKS
C.ROOT = CFG.ROOT                          # cwd for the headless view renders


def _task_dir(task: str) -> Path:
    """Any split under B2's tasks/ (the main helper knows only train/test)."""
    for d in sorted(CFG.TASKS.glob(f"*/{task}")):
        if d.is_dir():
            return d
    raise SystemExit(f"[bundle_b2] no task folder for {task} under {CFG.TASKS}")


C.task_dir = _task_dir

GPU_PRELUDE = '''
import sys; sys.dont_write_bytecode = True
import bpy
try:
    _p = bpy.context.preferences.addons["cycles"].preferences
    for _b in ("OPTIX", "CUDA"):
        try:
            _p.compute_device_type = _b; _p.refresh_devices()
            if any(d.type == _b for d in _p.devices):
                for d in _p.devices: d.use = d.type == _b
                for _s in bpy.data.scenes: _s.cycles.device = "GPU"
                break
        except Exception: pass
except Exception as _e:
    print("[b2] gpu prelude:", _e)
'''

DIGEST = '''
import sys; sys.dont_write_bytecode = True
sys.path.insert(0, {tools!r})
import geom_digest
geom_digest.write_digest({out!r}, evaluated=True, note={run!r})
'''


def headless(blend: Path, code: str, label: str, run: str, timeout: float = 2400) -> bool:
    script = CFG.STATE / "bundle_scripts" / f"{run}_{label}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(code, encoding="utf-8")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run([CFG.BLENDER, "--background", str(blend), "--python-exit-code", "1", "--python", str(script)],
                              capture_output=True, text=True, cwd=str(CFG.ROOT), env=env,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[bundle_b2] {label} timed out after {timeout}s")
        return False
    if proc.returncode != 0:
        print(f"[bundle_b2] {label} failed rc={proc.returncode}")
        for l in ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-8:]:
            print("    !", l[:240])
    return proc.returncode == 0


def bundle(run: str, *, force: bool = False) -> Path | None:
    run_dir = CFG.RUNS / run
    src = run_dir / "final.blend"
    task = C.task_of_run(run)
    if not src.is_file():
        print(f"[bundle_b2] {run}: no final.blend")
        return None
    dest = CFG.BLENDS / run
    if (dest / "views" / "final_render.png").is_file() and not force:
        print(f"[bundle_b2] blends/{run} already complete")
        return dest
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sfb = B._load_sfb()
    fp = B._flat_paths(run)
    CFG.BLENDS.mkdir(exist_ok=True)
    if not headless(src, sfb.SAVE_TMPL.format(out=str(fp["blend"]), report=str(fp["json"])), "save", run):
        return None
    if not headless(fp["blend"], GPU_PRELUDE + sfb.PROOF_TMPL.format(png=str(fp["png"])), "proof", run):
        print("[bundle_b2] proof render failed; continuing")
    if not headless(fp["blend"], GPU_PRELUDE + sfb.FIT_TMPL.format(png=str(fp["fit"])), "fit", run):
        print("[bundle_b2] fit render failed; continuing")
    digest_tmp = C.MEM / run / "geom_digest.json"
    headless(fp["blend"], DIGEST.format(tools=str(C.TOOLS_CODE), out=str(digest_tmp), run=run), "digest", run)
    dest = B.reshape(run, task)
    if digest_tmp.is_file():
        import shutil
        shutil.copy2(digest_tmp, dest / "geom_digest.json")
    ok = B.render_views(dest, run, force=True)
    C.write_json(dest / "bundle.json", {
        "run": run, "task": task, "mode": "from_blend (B2)", "source_blend": str(src),
        "system": "B2 skill-compaction baseline", "at": C.now(), "views_complete": ok,
        "views": sorted(p.name for p in (dest / "views").glob("*.png")),
    })
    print(f"[bundle_b2] -> blends/{run} (views {'complete' if ok else 'INCOMPLETE'})")
    return dest if ok else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    raise SystemExit(0 if bundle(a.run, force=a.force) else 1)


if __name__ == "__main__":
    main()
