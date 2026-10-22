"""Populate tasks/train and tasks/test from ../Tasks/Pool40.

    python make_tasks.py                 # the default split from SELECTION.md
    python make_tasks.py --train 1,3,4   # your own picks, by pool number
    python make_tasks.py --list          # show the pool and stop

A task folder is deliberately thin — a reference image and a sentence:

    tasks/train/01_pallet_stack/
        reference.png
        task.md

Everything else (the plan, the measurements, the scripts) is the planner's job,
not something you write here.

The image copied in is the pool's `edited.png` when there is one, and
`original.*` otherwise — the same rule the pool's own README describes.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POOL = ROOT.parent / "Tasks" / "Pool40" / "images"
TASKS = ROOT / "tasks"

# from Tasks/Pool40/SELECTION.md — change with --train / --test
DEFAULT_TRAIN = [1, 3, 4, 6, 8, 9, 10, 11, 13, 14, 16, 17, 19, 20, 22, 23, 24, 25, 28, 30]
DEFAULT_TEST = [26, 31, 32, 33, 34, 35, 36, 37, 38, 40]

# one line per task: what the builder is being asked for
DESCRIPTIONS = {
    1: "Model a stack of six identical EUR wooden pallets, with the blocks, bottom runners and top deck boards of each pallet correct, and a plain pine material.",
    2: "Model a closed corrugated cardboard shipping box, UV unwrap it, and place the two printed panels on the front face.",
    3: "Model a white ceramic diner mug — tapered body, thickened rolled rim, hollow interior, D-shaped handle — with a glossy ceramic material.",
    4: "Model the pawn and the rook as lathed solids from their profiles, and cut the rook's crenellations.",
    5: "Model a clear crystal wine glass by lathing its profile, with a wall that thins toward the rim, and give it a glass material.",
    6: "Model the art-deco datestone: the stepped stone block, its corner motifs, and the raised numerals 1934.",
    7: "Model an analogue wall clock face: bezel, dial, twelve Roman numerals placed radially, sixty minute ticks, and two hands.",
    8: "Model an aluminium energy drink can, UV unwrap the body with a single back seam, and wrap the label around it without vertical stretch.",
    9: "Model an oak wine barrel from a radial array of bowed staves with four steel hoops, texture it, and paint the pale weathering along the lower stave edges.",
    10: "Model a wrought-iron gate panel: the frame, the vertical bars, and the symmetrical scrollwork above them, as swept curves.",
    11: "Model a Thonet No. 14 bentwood chair — two nested back hoops, seat frame, splayed legs and the reinforcing ring — as swept curves.",
    12: "Model a rotary dial telephone: the body, the finger-wheel dial, the handset in its cradle, and the coiled cord.",
    13: "Model a vintage Anglepoise lamp as separate parts — stepped base, two parallel-link arms with pivots and springs, conical shade — with metal and enamel materials.",
    14: "Model the flattened crystal decanter and its stopper, then reproduce the photograph: its lighting, its backdrop and its camera.",
    15: "Model a neon script sign as a swept tube following the letterforms, on its backing panel, and light it so the glow spills onto the panel.",
    16: "Model the double-helix spiral ramp with its stepped balustrade, four turns, and the octagonal skylight, then frame the camera to match the photograph. The relief carving is out of scope.",
    17: "Build a gravel path meeting a lawn edge, scattering the gravel with geometry nodes at the density and size spread shown.",
    18: "Model a potted Monstera: the pot, the stem cluster with aerial roots, and eight to ten fenestrated leaves instanced with per-leaf variation.",
    19: "Model the desk and the office chair and assemble them: drawers open to different extents, chair tucked at the angle shown, castors on the floor.",
    20: "Model a weathered granite boulder — blocky, with flat cleavage faces meeting at sharp arrises and a split across the middle — and sculpt the surface break-up.",
    21: "Model a human skull with the mandible as a separate object, and sculpt the suture lines and surface detail.",
    22: "Model three meshing spur gears on parallel shafts, then animate the train turning for 60 frames with the ratios correct.",
    23: "Rig the Anglepoise lamp with an armature and an IK chain, keeping the parallel linkage parallel, and pose it to match this second configuration.",
    24: "Model a wooden artist's mannequin: fourteen turned parts, ball joints seated in their sockets, standing on its disc base.",
    25: "Rig the mannequin with a fifteen-bone armature, bind and repair the weights, and pose it to match the photograph.",
    26: "Model the robot: bevelled torso with panel details, CRT head with an emissive face, two segmented arms with claws, ribbed skirt and antenna. Light it and pose the raised arm.",
    27: "Model an opened umbrella — shaft, handle, eight ribs and stretchers — and simulate the canopy tenting between the ribs.",
    28: "Model a round pedestal table and simulate a square cloth draped over it, settling to the rest state shown.",
    29: "Set up twelve dominoes as rigid bodies at the spacing shown, topple them, and produce the frame in the reference.",
    30: "Take the rigged mannequin and key a 24-frame looping walk cycle matching this contact sheet, with no foot slide during stance.",
    31: "Model a vintage 35 mm SLR camera: chrome top plate with its dials and levers, leatherette body, and a lens with knurled rings.",
    32: "Model a running shoe — layered upper panels with stitched seams, laced eyelets, padded collar and grooved outsole — and UV it.",
    33: "Model the chess board and all 32 pieces, and place them in the starting position with every piece centred on its square.",
    34: "Model an ornate cast-iron street lantern and light it at night: warm glow through the glazing, spill on the ironwork, falloff into the dark.",
    35: "Model a nautilus shell cut in half: a logarithmic spiral swept with a growing section, with about thirty chamber walls arrayed along it.",
    36: "Model an origami paper crane from flat planes only — every surface developable, every crease sharp, no bevels.",
    37: "Model a classic road bicycle: lugged frame tubes, fork, two spoked wheels, chainring and chain, saddle and drop bars.",
    38: "Model a wooden-framed hourglass and simulate the sand: a heap above, a falling stream, and a cone building below.",
    39: "Model an antique desk fan — cast base, motor housing, six brass blades, wire cage — then animate the blades spinning while the head yaws.",
    40: "Model an egret with layered flight feathers, rig its wings, and key one wing-beat cycle with the primaries spreading on the downstroke.",
}


def pool_folders() -> dict[int, Path]:
    out = {}
    for p in sorted(POOL.iterdir()):
        if p.is_dir():
            m = re.match(r"(\d+)_", p.name)
            if m:
                out[int(m.group(1))] = p
    return out


def reference_in(folder: Path) -> Path:
    edited = folder / "edited.png"
    if edited.is_file():
        return edited
    originals = sorted(folder.glob("original.*"))
    if not originals:
        raise SystemExit(f"[tasks] no image in {folder}")
    return originals[0]


def make(split: str, numbers: list[int], folders: dict[int, Path]) -> None:
    dest_root = TASKS / split
    dest_root.mkdir(parents=True, exist_ok=True)
    for n in numbers:
        if n not in folders:
            print(f"[tasks] pool has no #{n} — skipped")
            continue
        src = folders[n]
        dst = dest_root / src.name
        dst.mkdir(parents=True, exist_ok=True)
        ref = reference_in(src)
        shutil.copy2(ref, dst / f"reference{ref.suffix.lower()}")
        desc = DESCRIPTIONS.get(n, "(no description written for this task yet)")
        (dst / "task.md").write_text(
            f"# {src.name}\n\n{desc}\n\n"
            f"The reference image in this folder is the specification. Match it.\n",
            encoding="utf-8")
        print(f"[tasks] {split}/{src.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Populate tasks/ from Tasks/Pool40.")
    ap.add_argument("--train", help="comma-separated pool numbers (default: SELECTION.md picks)")
    ap.add_argument("--test", help="comma-separated pool numbers")
    ap.add_argument("--list", action="store_true", help="list the pool and exit")
    ap.add_argument("--clean", action="store_true", help="empty tasks/ before writing")
    args = ap.parse_args()

    if not POOL.is_dir():
        raise SystemExit(f"[tasks] pool not found at {POOL}")
    folders = pool_folders()

    if args.list:
        for n in sorted(folders):
            mark = "train" if n in DEFAULT_TRAIN else ("test" if n in DEFAULT_TEST else "spare")
            print(f"  {n:2d}  {folders[n].name:24s} {mark}")
        return

    if args.clean:
        for split in ("train", "test"):
            d = TASKS / split
            if d.is_dir():
                shutil.rmtree(d)

    train = [int(x) for x in args.train.split(",")] if args.train else DEFAULT_TRAIN
    test = [int(x) for x in args.test.split(",")] if args.test else DEFAULT_TEST
    make("train", train, folders)
    make("test", test, folders)
    print(f"\n[tasks] {len(train)} train, {len(test)} test")


if __name__ == "__main__":
    main()
