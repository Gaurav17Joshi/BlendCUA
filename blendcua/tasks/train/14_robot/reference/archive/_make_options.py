"""Variants of the TV-head robot with ball-and-three-finger hands and a single wheel instead of legs,
made with gpt-image-2 (images.edit, quality high). Both original.png (the TV-head robot) and
robot_alt.png (the wheeled robot) are passed as input images.

    python reference/_make_options.py [--force] [A B ...]     # from the task folder
"""
import base64, sys, time, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]          # Blenduse
sys.path.insert(0, str(ROOT / "BlendCuavb_run"))
import blendcua_core
blendcua_core.load_api_keys(verbose=False)
from openai import OpenAI

MAIN = HERE / "original.png"; ALT = HERE / "robot_alt.png"; OUT = HERE / "options"
BASE = ("The FIRST supplied image is a 3D cartoon robot character: a retro TV set for a head (rounded red-brown shell, "
        "cream front bezel, dark curved screen with a face of two glowing rectangles and a short bar, a channel strip "
        "and two knobs on the right, two thin antennae with balls on top), an orange puffy zip-up jacket for the body "
        "with a front zip and two zipped pockets, thin dark blue rod arms, dark gloved hands with orange pads, thin dark "
        "blue rod legs and chunky white sneakers, on a plain blue backdrop. The SECOND supplied image is a different "
        "robot, used only as a reference for its single large black ribbed tyre wheel with a metal hub. "
        "Produce the FIRST robot with these two changes and NOTHING else changed -- same TV head, same face, same "
        "antennae, same orange jacket, same pose, same viewpoint, same blue backdrop, same proportions, character "
        "standing upright centred and complete in frame: "
        "(1) HANDS: replace each gloved hand with a polished chrome metal ball at the end of the arm, with three simple "
        "smooth metal fingers coming out of the ball, slightly curled. "
        "(2) LEGS: remove both legs and the sneakers entirely; ")
VARIANTS = {
    "A": BASE + "in their place, directly under the hem of the jacket, a single large black ribbed rubber tyre wheel "
         "like the one in the second image, held in a simple grey metal fork (a U-shaped yoke with an axle through the "
         "hub) that comes down out of the jacket. The wheel rests on the ground and carries the whole robot. Keep the "
         "thin dark blue rod arms.",
    "B": BASE + "in their place, a short grey metal box chassis under the jacket hem, and inside it, half hidden, a "
         "single large black ribbed rubber tyre wheel like the one in the second image, its lower half showing below "
         "the chassis and resting on the ground. Keep the thin dark blue rod arms.",
    "C": BASE + "in their place, directly under the hem of the jacket, a single large black ribbed rubber tyre wheel "
         "like the one in the second image, held in a simple grey metal fork with an axle through the hub, resting on "
         "the ground. ALSO change the arms: instead of thin rods, make them jointed chrome metal tube arms with a ball "
         "joint at the shoulder and elbow, like the arms of the second image, ending in the chrome ball hands with "
         "three fingers.",
    "D": BASE + "in their place, a single medium-sized black ribbed rubber tyre wheel like the one in the second image, "
         "with a visible chrome hub cap, mounted on a short vertical chrome post that comes straight down from the "
         "centre of the jacket hem, with a small round grey metal skirt where the post meets the jacket. The wheel "
         "rests on the ground. Keep the thin dark blue rod arms.",
}

client = OpenAI()
want = [a for a in sys.argv[1:] if a in VARIANTS] or list(VARIANTS)
def run(key):
    dest = OUT / f"option_{key}.png"
    if dest.is_file() and "--force" not in sys.argv:
        return {"option": key, "skipped": True}
    t0 = time.time(); err = None
    for attempt in range(3):
        try:
            with MAIN.open("rb") as f1, ALT.open("rb") as f2:
                resp = client.images.edit(model="gpt-image-2", image=[f1, f2], prompt=VARIANTS[key], size="1024x1536",
                                          quality="high", background="opaque", output_format="png")
            dest.write_bytes(base64.b64decode(resp.data[0].b64_json)); break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"; print(key, "attempt", attempt, err); time.sleep(5)
    print(key, "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
    return {"option": key, "out": dest.name, "inputs": [MAIN.name, ALT.name], "prompt": VARIANTS[key],
            "seconds": round(time.time() - t0, 1), "error": err}
with ThreadPoolExecutor(4) as ex:
    log = list(ex.map(run, want))
(OUT / "_options_manifest.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
