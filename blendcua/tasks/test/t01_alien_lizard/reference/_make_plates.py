"""Front and side plates of the alien bust from reference.png with gpt-image-2 (images.edit, quality high).

    python reference/_make_plates.py            # from the task folder; skips plates that exist
    python reference/_make_plates.py --force
"""
import base64, sys, time, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]          # Blenduse
sys.path.insert(0, str(ROOT / "BlendCuavb_run"))
import blendcua_core
blendcua_core.load_api_keys(verbose=False)
from openai import OpenAI

SRC = HERE.parent / "reference.png"
SUBJECT = ("The supplied image is a 3D-sculpted bust of a green reptilian alien creature, seen from a three-quarter "
           "angle: a bald domed head; on each side of the head a large glossy green eye set forward and a smaller "
           "one just behind it, both in wrinkled sockets; two nostril pits on the snout; a wide lipless mouth with "
           "small pointed teeth and a flat red tongue hanging out; a small ear pit on the cheek; a long thin skin "
           "flap hanging from the back of the head down past the neck; a thick neck and the upper chest, cut off "
           "flat below the shoulders like a portrait bust; fine scaly leathery skin. ")
KEEP = ("This is a modelling reference plate, not an art piece. Keep the SAME creature: same proportions, same "
        "features, same skin and colours, same expression with the tongue out. Re-project the camera as instructed; "
        "do not simply reproduce the original viewpoint. Long-lens, near-orthographic camera so the view reads flat. "
        "Centred and complete in frame with a small margin, on a flat neutral light-grey studio background "
        "(RGB about 200/200/200), no shadow on the background, no text, no watermark, no second copy of the creature.")
PLATES = {
    "front_plate.png": SUBJECT + "Produce a straight-on FRONT view: the camera is level with the creature's eyes and "
        "looks directly at its face, so the head is perfectly symmetrical left-to-right, both large eyes and both "
        "smaller eyes are visible, the two nostril pits sit either side of the centre line, the mouth is seen "
        "straight on with the tongue hanging down the middle, the two skin flaps show at the back of the head "
        "either side, and the shoulders are seen square on. " + KEEP,
    "side_plate.png": SUBJECT + "Produce a straight-on SIDE profile: the camera is level with the creature's eyes "
        "and looks at its LEFT side, the snout pointing to the left of the frame, so the profile of the domed head, "
        "the brow, the snout with one nostril pit, the mouth line with the tongue, and the throat and chest are seen "
        "edge-on; the near large eye and the smaller eye behind it are seen from the side; the skin flap hangs from "
        "the back of the head at the right. Pure profile, no part of the far side visible. " + KEEP,
}

client = OpenAI()
log = []
for name, prompt in PLATES.items():
    dest = HERE / name
    if dest.is_file() and "--force" not in sys.argv:
        print(name, "exists"); continue
    t0 = time.time(); err = None
    for attempt in range(3):
        try:
            with SRC.open("rb") as fh:
                resp = client.images.edit(model="gpt-image-2", image=fh, prompt=prompt, size="1024x1536",
                                          quality="high", background="opaque", output_format="png")
            dest.write_bytes(base64.b64decode(resp.data[0].b64_json)); break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"; print(name, "attempt", attempt, err); time.sleep(5)
    log.append({"plate": name, "source": SRC.name, "prompt": prompt, "seconds": round(time.time() - t0, 1), "error": err})
    print(name, "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
(HERE / "_plates_manifest.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
