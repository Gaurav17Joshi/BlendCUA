"""Make front / side / top modelling plates for one task with gpt-image-2 and put them in the
task folder, so the planner and executor get straight views up front.

    python Tool_scripts/make_task_plates.py 10_low_poly_dog [--quality high] [--force]

Uses generate_views_gpt_image.py's prompts, client handling and manifest (outputs land in
synth_views/gpt-image-2/<task>/ as usual), then copies the plates to
tasks/train/<task>/reference/{front,side,top}_plate.png and writes a contact sheet there.
Keys come from blendcua_core.load_api_keys() (the key file outside the repo); never printed.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
import generate_views_gpt_image as G  # noqa: E402

WHITE = G.BG_WHITE

S_HUMAN_APOSE = ("The supplied image shows a low-poly flat-shaded faceted human figure standing in a "
                 "relaxed A-pose (arms held out and angled down at roughly 30 degrees below horizontal, "
                 "feet slightly apart), wearing a red t-shirt, dark trousers and dark shoes, with no "
                 "facial detail; it is a Blender viewport screenshot.")
SUBJECT = {
    "10_low_poly_dog": G.S_DOG,
    "11_human_fire_juggling": S_HUMAN_APOSE,
}
JOBS = {
    "11_human_fire_juggling": [
        G.job("01_front", S_HUMAN_APOSE + " Re-render the SAME figure as a clean modelling reference, "
              "but RE-POSED into a strict T-POSE: both arms raised to shoulder height and held straight "
              "out horizontally to the sides, level with the shoulders, elbows straight, palms facing "
              "down, fingers together; legs straight and feet slightly apart as before. Remove the dark "
              "viewport background, the grid and axis lines and the mouse cursor, and place the whole "
              "figure " + WHITE + ". Keep the same proportions, the flat-shaded faceted low-poly look, "
              "the red t-shirt with short sleeves, the dark trousers, the dark shoes and the featureless "
              "face. Do not smooth the model, do not add facial detail, do not restyle it. Straight-on "
              "front view, level camera, whole figure in frame with a small margin, no text, no shadow.",
              size=G.PORTRAIT, background="opaque"),
    ],
    "10_low_poly_dog": [
        G.job("01_side", G.view(G.S_DOG, G.SIDE, "This is the same LEFT-side profile the supplied "
              "photo already shows: keep the dog's exact standing pose, proportions and markings, "
              "but as a clean modelling plate — the whole dog including all four paws, the tail and "
              "the open mouth with the tongue, edge-on, level camera, no grass, no ground, no shadow.",
              bg=WHITE), size=G.LANDSCAPE, background="opaque"),
        G.job("02_front", G.view(G.S_DOG, G.FRONT, "A head-on view: the camera is level with the dog "
              "and directly in front of its chest, so the body is bilaterally symmetrical, both front "
              "legs, both ears and the tan chest and muzzle markings read symmetrically. Same standing "
              "pose, same black-and-tan Rottweiler, no grass, no ground, no shadow.",
              bg=WHITE), size=G.SQUARE, background="opaque"),
        G.job("03_top", G.view(G.S_DOG, G.TOP, "A plan view from directly above the standing dog: the "
              "black back and the symmetrical outline of head, ears, shoulders, ribcage, hindquarters "
              "and tail, with the legs hidden beneath the body, no grass, no ground, no shadow.",
              bg=WHITE), size=G.LANDSCAPE, background="opaque"),
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--quality", default="high", choices=["low", "medium", "high"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.task not in JOBS:
        print("no job list for", a.task, "— add one in JOBS"); return 1
    import blendcua_core
    blendcua_core.load_api_keys(verbose=False)
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not available"); return 2
    from openai import OpenAI
    client = OpenAI()
    G.OUT.mkdir(parents=True, exist_ok=True)
    rec = G.run_task(a.task, JOBS[a.task], client, quality=a.quality, force=a.force, only_jobs=None)
    dest = ROOT / "tasks" / "train" / a.task / "reference"
    dest.mkdir(exist_ok=True)
    for j in rec["jobs"]:
        if j.get("status") in ("ok", "skipped-exists"):
            name = j["name"].split("_", 1)[1] + "_plate.png"
            shutil.copy2(G.OUT / a.task / j["file"], dest / name)
            print(f"  -> {dest / name}  ({j.get('seconds', '?')}s, ${(j.get('cost') or {}).get('usd', '?')})")
        else:
            print(f"  {j['name']}: {j.get('status')} {j.get('error', '')}")
    # contact sheet from the generator's own routine needs PLAN[task]; build a simple one here
    try:
        from PIL import Image, ImageDraw
        plates = [("reference", G.reference_for(a.task))] + [(n, dest / f"{n}_plate.png") for n in ("side", "front", "top") if (dest / f"{n}_plate.png").is_file()]
        cell, pad, lh = 420, 12, 26
        sheet = Image.new("RGB", (len(plates) * (cell + pad) + pad, cell + lh + 2 * pad), (245, 245, 245))
        d = ImageDraw.Draw(sheet)
        for i, (n, p) in enumerate(plates):
            im = Image.open(p).convert("RGB"); im.thumbnail((cell, cell))
            cx = pad + i * (cell + pad)
            sheet.paste(im, (cx + (cell - im.width) // 2, pad + lh + (cell - im.height) // 2))
            d.text((cx + 4, pad), n, fill=(30, 30, 30))
        sheet.save(dest / "plates_contact.png")
        print("  contact sheet:", dest / "plates_contact.png")
    except Exception as e:  # noqa: BLE001
        print("contact sheet skipped:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
