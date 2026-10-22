"""Compare a replayed bundle with the run's own saved checkpoint (the Mac original).

    python Tool_scripts/compare_checkpoint.py --run 17_shark_run_001

Reads blends/<run>/manifest.json (written by the replay bundle) and, headlessly, the last
mem/<run>/checkpoints/step_N.blend; reports objects missing/extra and per-mesh vertex-count
differences. A faithful replay has the same objects with the same vertex counts; sculpt and
texture actions that silently failed show up as vertex counts that stayed at the base mesh.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vb"))
import common as C  # noqa: E402
import bundle as B  # noqa: E402

DUMP = r'''
import bpy, json, sys
out = sys.argv[sys.argv.index("--") + 1]
d = {"objects": sorted(o.name for o in bpy.data.objects),
     "meshes": {o.name: len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH"},
     "materials": sorted(m.name for m in bpy.data.materials),
     "images": sorted(im.name for im in bpy.data.images)}
open(out, "w").write(json.dumps(d))
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    man = C.read_json(C.BLENDS / a.run / "manifest.json")
    if not man:
        raise SystemExit(f"no blends/{a.run}/manifest.json (replay-bundle the run first)")
    cps = sorted((C.MEM / a.run / "checkpoints").glob("step_*.blend"))
    if not cps:
        raise SystemExit(f"no checkpoints under mem/{a.run}")
    cp = cps[-1]
    out = C.MEM / a.run / "checkpoint_inventory.json"
    script = C.MEM / a.run / "_dump_inventory.py"
    script.write_text(DUMP, encoding="utf-8")
    blender = B.find_blender()
    subprocess.run([blender, "--background", str(cp), "--python", str(script), "--", str(out)],
                   capture_output=True, text=True, cwd=str(ROOT))
    script.unlink(missing_ok=True)
    ref = C.read_json(out)
    if not ref:
        raise SystemExit("headless inventory failed")
    ro, mo = set(ref["objects"]), set(man.get("objects") or [])
    print(f"[compare] {a.run}: checkpoint {cp.name} has {len(ro)} objects, replay has {len(mo)}")
    missing, extra = sorted(ro - mo), sorted(mo - ro)
    if missing:
        print(f"  missing in replay ({len(missing)}): {missing[:12]}")
    if extra:
        print(f"  extra in replay ({len(extra)}): {extra[:12]}")
    rm, mm = ref["meshes"], man.get("meshes") or {}
    diffs = [(n, rm[n], mm[n]) for n in sorted(set(rm) & set(mm)) if rm[n] != mm[n]]
    same = len(set(rm) & set(mm)) - len(diffs)
    print(f"  meshes: {same} identical vertex counts, {len(diffs)} differ")
    for n, r, m in diffs[:20]:
        print(f"    {n}: checkpoint {r} verts, replay {m}")
    print(f"  materials: checkpoint {len(ref['materials'])}, replay {len(man.get('materials') or [])};"
          f" images: checkpoint {len(ref['images'])}, replay {len(man.get('images') or [])}")
    verdict = "FAITHFUL" if not missing and not diffs else "DIFFERS"
    print(f"[compare] {verdict}")
    C.write_json(C.BLENDS / a.run / "checkpoint_compare.json",
                 {"checkpoint": cp.name, "missing": missing, "extra": extra, "vertex_diffs": diffs, "verdict": verdict})


if __name__ == "__main__":
    main()
