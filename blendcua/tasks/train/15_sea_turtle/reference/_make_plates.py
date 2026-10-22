"""Top and bottom plates of the turtle from reference.png with gpt-image-2 (images.edit, quality high).

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
SUBJECT = ("The supplied image shows a green sea turtle swimming, seen from above and behind at a three-quarter "
           "angle: an oval carapace covered in large scutes (a row down the middle with larger ones either side), "
           "both front flippers spread out to the sides, both rear flippers, a short tail and the head with its "
           "scaled skin, on a plain grey background. ")
KEEP = ("This is a modelling reference plate, not an art piece. Keep the SAME turtle: same proportions, same shell "
        "pattern and colours, same spread pose of the flippers. Re-project the camera as instructed; do not simply "
        "reproduce the original viewpoint. Long-lens, near-orthographic camera so the view reads flat. Centred and "
        "complete in frame with a small margin, on a flat neutral light-grey studio background (RGB about 200/200/200), "
        "no shadow, no water, no text, no watermark, no second copy of the turtle.")
PLATES = {
    "top_plate.png": SUBJECT + "Produce a TOP-DOWN plan view: the camera is directly above the turtle looking straight "
        "down, the head pointing to the top of the frame and the tail to the bottom, so the carapace reads as its full "
        "oval outline with the scute pattern laid out symmetrically, the two front flippers spread left and right and "
        "the two rear flippers and the tail visible behind. No side of the shell should be visible. " + KEEP,
    "bottom_plate.png": SUBJECT + "Produce a BOTTOM-UP view: the camera is directly below the turtle looking straight "
        "up at its underside, the head pointing to the top of the frame and the tail to the bottom. This shows the "
        "plastron -- the flat pale cream-yellow belly shield of a green sea turtle, with its faint plate seams -- the "
        "pale undersides of all four flippers spread in the same pose, the underside of the head and neck, and the rim "
        "of the darker carapace just visible around the edge. " + KEEP,
    "side_plate.png": SUBJECT + "Produce a straight-on SIDE profile: the camera is level with the turtle and looks at "
        "its LEFT side, the head pointing to the left of the frame and the tail to the right, so the carapace reads as a "
        "low dome over the flat pale plastron, the head and neck extend forward at the left, the near front flipper "
        "sweeps out toward the camera and down, the far one is mostly hidden behind the body, and the near rear flipper "
        "shows at the right. Pure profile: neither the top of the shell nor the underside is seen face-on. " + KEEP,
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
                resp = client.images.edit(model="gpt-image-2", image=fh, prompt=prompt, size="1536x1024",
                                          quality="high", background="opaque", output_format="png")
            dest.write_bytes(base64.b64decode(resp.data[0].b64_json)); break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"; print(name, "attempt", attempt, err); time.sleep(5)
    log.append({"plate": name, "source": SRC.name, "prompt": prompt, "seconds": round(time.time() - t0, 1), "error": err})
    print(name, "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
(HERE / "_plates_manifest.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
