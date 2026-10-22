"""Front and side plates of the wheeled TV-head robot with gpt-image-2 (images.edit, quality high).
front_plate.png = edited.png (option F1) with the blue backdrop replaced by a plain grey ground;
side_plate.png  = the same robot re-projected in left profile, made from front_plate.png.

    python reference/_make_plates.py [--force]     # from the task folder
"""
import base64, sys, time, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]          # Blenduse
sys.path.insert(0, str(ROOT / "BlendCuavb_run"))
import blendcua_core
blendcua_core.load_api_keys(verbose=False)
from openai import OpenAI

SUBJECT = ("The supplied image is a 3D cartoon robot character seen straight from the front: a retro TV set for a head "
           "(rounded red-brown shell, cream front bezel, dark curved screen with a face of two glowing rectangles and a "
           "short bar, a channel strip and two knobs on the right, two thin antennae with balls on top), an orange puffy "
           "zip-up jacket for the body with a front zip and two zipped pockets, short dark blue rods out of the sleeve "
           "cuffs ending in chrome ball hands with three curved claw fingers, and instead of legs a short grey metal box "
           "chassis under the jacket hem with a single large black ribbed tyre half hidden inside it, resting on the "
           "ground. ")
KEEP = ("This is a modelling reference plate, not an art piece. Keep the SAME character: same parts, same proportions, "
        "same colours, same pose. Long-lens, near-orthographic camera so the view reads flat. Centred and complete in "
        "frame with a small margin, on a flat neutral light-grey studio background (RGB about 200/200/200) with no "
        "backdrop shapes, no shadow on the background, no text, no watermark, no second copy of the robot.")
PLATES = [
    ("front_plate.png", "edited.png", SUBJECT + "Reproduce this image EXACTLY -- same robot, same size, same framing, "
        "same straight-on front view, same lighting on the robot -- with ONE change: replace the blue backdrop "
        "entirely with a flat neutral light-grey studio background. " + KEEP),
    ("side_plate.png", "front_plate.png", SUBJECT + "Produce a straight-on SIDE profile: the camera is level with the "
        "screen and looks at the robot's LEFT side, the screen facing the left of the frame, so the TV head reads as a "
        "box with the bezel at the left and the deeper rounded back of the set at the right, the antennae rise from "
        "the top, the jacket is seen from the side with one sleeve nearest the camera and the short rod and chrome "
        "claw hand hanging below its cuff, the box chassis is seen from the side, and the tyre is seen as a full "
        "circle with its ribbed tread around the rim, its lower part below the chassis touching the ground. Pure "
        "profile: the screen face is not visible. " + KEEP),
]

client = OpenAI(); log = []
for name, src, prompt in PLATES:
    dest = HERE / name; source = HERE / src
    if dest.is_file() and "--force" not in sys.argv:
        print(name, "exists"); continue
    t0 = time.time(); err = None
    for attempt in range(3):
        try:
            with source.open("rb") as fh:
                resp = client.images.edit(model="gpt-image-2", image=fh, prompt=prompt, size="1024x1536",
                                          quality="high", background="opaque", output_format="png")
            dest.write_bytes(base64.b64decode(resp.data[0].b64_json)); break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"; print(name, "attempt", attempt, err); time.sleep(5)
    log.append({"plate": name, "source": src, "prompt": prompt, "seconds": round(time.time() - t0, 1), "error": err})
    print(name, "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
(HERE / "_plates_manifest.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
