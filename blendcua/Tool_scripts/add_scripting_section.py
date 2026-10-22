"""Insert the standard '## Scripting' section into a plan's preamble (before its first
`## Step N` header), so every step's subagent sees it. Idempotent.

    python Tool_scripts/add_scripting_section.py plans/Bat/Bat_plan.md [...]
    python Tool_scripts/add_scripting_section.py --all      # exemplars + every task plan
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# the same header rule blendcua_core.parse_plan uses, so the section lands in the preamble
STEP_HDR = re.compile(r"^#{1,3}\s+Step\s+(\d+)\s*(?:[—–]|-{1,2})\s*(.+?)\s*$", re.M)
MARK = "## Scripting — read the reference with a script before you build"

SECTION = f"""{MARK}

**Scripting** means writing a small Python program, saved as a `.py` file in the step's
`scripts/` folder (`mem/<run>/steps/step_NNN/scripts/`), that reads the reference image
or the Blender scene and **prints numbers or draws an overlay**: a material mask and its
row table, the axis and floor rows, a part's outline traced into a polygon, a thickness,
colour medians, the built outline drawn back on the reference with a residual. Shell-side
with PIL/numpy for pictures (`Tool_scripts/Tools_code/outline_trace.py` has the pieces),
Blender-side for the scene (`perceive.reference_outline`, bounds per row). It is not the
action that builds the part and it is not reasoning in prose about what the picture shows.

Every step that builds a shape does this **before its first build action** and saves what
it found (`scripts/<part>.json` and the trace drawn on the reference as a PNG); the build
action reads that file instead of retyping numbers; the check at the end of the step is the
same kind of script (outline on the reference, residual per row). A construction step
whose `scripts/` folder is empty has built its shape from memory, not from this reference,
and fails review on that alone. See `Skills/Scripting/measure-before-you-build.md`.

"""


def patch(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        return "already"
    m = STEP_HDR.search(text)
    if not m:
        return "no step header"
    new = text[:m.start()].rstrip("\n") + "\n\n" + SECTION + text[m.start():]
    path.write_text(new, encoding="utf-8")
    return "inserted"


def main(argv):
    if "--all" in argv:
        names = [ln.strip() for ln in (ROOT / "plans" / "EXEMPLARS.txt").read_text().splitlines()
                 if ln.strip() and not ln.startswith("#")]
        files = [ROOT / "plans" / n / f"{n}_plan.md" for n in names]
        files += sorted((ROOT / "plans").glob("0*/0*_plan.md"))
    else:
        files = [Path(a) for a in argv if not a.startswith("--")]
    for f in files:
        print(f"{patch(f):>14}  {f.relative_to(ROOT) if f.is_absolute() else f}")


if __name__ == "__main__":
    main(sys.argv[1:])
