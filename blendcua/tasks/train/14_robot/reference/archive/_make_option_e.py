"""Option E: option_A's proportions with option_B's box-chassis wheel and claw hands, gpt-image-2
(images.edit, quality high). option_A.png is the base image, option_B.png the parts reference.

    python reference/_make_option_e.py [--force]     # from the task folder
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

OUT = HERE / "options"; A = OUT / "option_A.png"; B = OUT / "option_B.png"
PROMPT = ("The FIRST supplied image is a 3D cartoon robot character: a retro TV set for a head with a glowing face, "
          "two antennae, an orange puffy zip-up jacket for the body, thin dark blue rod arms ending in chrome ball hands "
          "with three fingers, and instead of legs a single large black ribbed tyre wheel held in a grey metal fork "
          "under the jacket hem, on a plain blue backdrop. The SECOND supplied image is the same character drawn with "
          "different proportions; use it ONLY as the reference for two parts: its wheel mount and its hands. "
          "Produce the FIRST image with its EXACT proportions, size, framing, pose and viewpoint unchanged -- same TV "
          "head size relative to the body, same jacket, same rod arms, same blue backdrop, whole character complete in "
          "frame with a margin below the wheel -- and only these two changes: "
          "(1) WHEEL MOUNT: replace the grey metal fork with the wheel housing from the second image: a short grey "
          "metal box chassis sitting directly under the jacket hem, as wide as the hem, with the black ribbed tyre "
          "half hidden inside it so only its lower half shows below the chassis and rests on the ground. "
          "(2) HANDS: replace the hands with the hands from the second image: a polished chrome ball at the end of each "
          "arm with three simple curved chrome claw-like fingers, slightly spread. "
          "Nothing else changes. No text, no watermark.")

client = OpenAI()
def run(i):
    dest = OUT / f"option_E{i}.png"
    if dest.is_file() and "--force" not in sys.argv:
        return {"option": f"E{i}", "skipped": True}
    t0 = time.time(); err = None
    for attempt in range(3):
        try:
            with A.open("rb") as f1, B.open("rb") as f2:
                resp = client.images.edit(model="gpt-image-2", image=[f1, f2], prompt=PROMPT, size="1024x1536",
                                          quality="high", background="opaque", output_format="png")
            dest.write_bytes(base64.b64decode(resp.data[0].b64_json)); break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"; print(i, "attempt", attempt, err); time.sleep(5)
    print(f"E{i}", "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
    return {"option": f"E{i}", "out": dest.name, "inputs": [A.name, B.name], "prompt": PROMPT,
            "seconds": round(time.time() - t0, 1), "error": err}
with ThreadPoolExecutor(3) as ex:
    log = list(ex.map(run, [1, 2, 3]))
(OUT / "_option_e_manifest.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
