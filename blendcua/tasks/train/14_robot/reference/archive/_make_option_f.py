"""Option F: option_E2 with the wheel seen dead-on from the front and shorter rod arms, gpt-image-2
(images.edit, quality high).

    python reference/_make_option_f.py [--force]     # from the task folder
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

OUT = HERE / "options"; SRC = OUT / "option_E2.png"
PROMPT = ("The supplied image is a 3D cartoon robot character seen straight from the front: a retro TV set for a head "
          "with a glowing face and two antennae, an orange puffy zip-up jacket for the body, thin dark blue rod arms "
          "coming out of the sleeves and ending in chrome ball hands with three curved claw fingers, and instead of "
          "legs a short grey metal box chassis under the jacket hem with a single large black ribbed tyre half hidden "
          "inside it, resting on the ground, on a plain blue backdrop. "
          "Reproduce this image EXACTLY -- same character, same proportions, same size, same framing, same head, same "
          "jacket, same chassis, same hands, same backdrop, same lighting -- with only these two changes: "
          "(1) WHEEL: the tyre is currently turned slightly so part of its side face and hub shows. Show it instead "
          "seen DEAD-ON from the front, its axle running exactly left-to-right, so only the black ribbed tread band "
          "faces the camera as a symmetrical rounded rectangle under the chassis, with no side face and no hub visible, "
          "the tread ribs running horizontally across it. "
          "(2) ARMS: the dark blue rod forearms that come out of the jacket sleeves are too long. Shorten each rod to "
          "about half its current length, so the chrome ball hands hang just below the sleeve cuffs, level with the "
          "top of the chassis, with the same slight outward angle. "
          "Nothing else changes. No text, no watermark.")

client = OpenAI()
def run(i):
    dest = OUT / f"option_F{i}.png"
    if dest.is_file() and "--force" not in sys.argv:
        return {"option": f"F{i}", "skipped": True}
    t0 = time.time(); err = None
    for attempt in range(3):
        try:
            with SRC.open("rb") as fh:
                resp = client.images.edit(model="gpt-image-2", image=fh, prompt=PROMPT, size="1024x1536",
                                          quality="high", background="opaque", output_format="png")
            dest.write_bytes(base64.b64decode(resp.data[0].b64_json)); break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"; print(i, "attempt", attempt, err); time.sleep(5)
    print(f"F{i}", "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
    return {"option": f"F{i}", "out": dest.name, "inputs": [SRC.name], "prompt": PROMPT,
            "seconds": round(time.time() - t0, 1), "error": err}
with ThreadPoolExecutor(3) as ex:
    log = list(ex.map(run, [1, 2, 3]))
(OUT / "_option_f_manifest.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
