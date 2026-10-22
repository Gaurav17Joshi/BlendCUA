"""Bundle a run for the checker from a SAVED .blend, without the live Blender server.

    python vb/bundle_from_blend.py --run 17_shark --task 17_shark --blend ../BlendCuaLoop_try/mem/17_shark_run_001/checkpoints/step_007.blend

For runs built elsewhere (the Mac originals keep checkpoints/step_N.blend) whose
Windows replay is not faithful. Runs headless Blender three times: save+manifest,
proof render from the scene camera, three-quarter fit render (the same templates
save_final_blend.py uses in the GUI), then reshapes into blends/<run>/ and renders
the 12 checker views.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import bundle as B  # noqa: E402


def headless(blender: str, blend: Path, code: str, label: str, timeout: float = 1800.0) -> bool:
    script = C.VB_STATE / "logs" / f"bundle_from_blend_{label}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(code, encoding="utf-8")
    proc = subprocess.run([blender, "--background", str(blend), "--python", str(script)],
                          capture_output=True, text=True, cwd=str(C.ROOT),
                          encoding="utf-8", errors="replace", timeout=timeout)
    tail = [l for l in (proc.stdout or "").splitlines() if l.startswith("[")][-3:]
    for l in tail:
        print("   ", l[:200])
    if proc.returncode != 0:
        print(f"[bundle_from_blend] {label} failed rc={proc.returncode}")
        for l in (proc.stderr or "").strip().splitlines()[-6:]:
            print("    !", l[:200])
    return proc.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="bundle name under blends/ (task name for an original build)")
    ap.add_argument("--task", default=None)
    ap.add_argument("--blend", required=True, help="saved .blend of the finished scene")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    task = a.task or C.task_of_run(a.run)
    src = Path(a.blend).resolve()
    if not src.is_file():
        raise SystemExit(f"no such blend: {src}")
    blender = B.find_blender()
    if not blender:
        raise SystemExit("no blender.exe found (set BLENDER)")
    dest = C.BLENDS / a.run
    if (dest / "views" / "final_render.png").is_file() and not a.force:
        print(f"[bundle_from_blend] blends/{a.run} already complete (use --force)")
        return
    sfb = B._load_sfb()
    fp = B._flat_paths(a.run)
    C.BLENDS.mkdir(exist_ok=True)
    print(f"[bundle_from_blend] {src.name} -> blends/{a.run}")
    if not headless(blender, src, sfb.SAVE_TMPL.format(out=str(fp["blend"]), report=str(fp["json"])), "save"):
        raise SystemExit(1)
    # the two renders run on the SAVED copy so packed images resolve from it
    if not headless(blender, fp["blend"], sfb.PROOF_TMPL.format(png=str(fp["png"])), "proof"):
        print("[bundle_from_blend] proof render failed; continuing")
    if not headless(blender, fp["blend"], sfb.FIT_TMPL.format(png=str(fp["fit"])), "fit"):
        print("[bundle_from_blend] fit render failed; continuing")
    dest = B.reshape(a.run, task)
    if not B.render_views(dest, a.run, force=True):
        raise SystemExit("[bundle_from_blend] view rendering incomplete")
    C.write_json(dest / "bundle.json", {
        "run": a.run, "task": task, "mode": "from_blend", "source_blend": str(src),
        "at": C.now(), "views": sorted(p.name for p in (dest / "views").glob("*.png")),
    })
    print(f"[bundle_from_blend] -> blends/{a.run}")


if __name__ == "__main__":
    main()
