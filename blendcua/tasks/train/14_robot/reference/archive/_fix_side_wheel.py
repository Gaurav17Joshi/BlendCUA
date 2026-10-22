"""Fix the side plate: the tyre sat forward of the body; move it back so it is centred under the
chassis. gpt-image-2 (images.edit, quality high) on archive/side_plate_wheel_forward.png ->
archive/side_fix_1.png, side_fix_2.png; the chosen one is copied to side_plate.png.

    python reference/_fix_side_wheel.py [--force]     # from the task folder
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

SRC = HERE / "archive" / "side_plate_wheel_forward.png"; OUT = HERE / "archive"
PROMPT = ("The supplied image is a straight-on LEFT-SIDE profile of a 3D cartoon robot on a plain grey ground: a retro "
          "TV set head (screen facing left), two antennae, an orange puffy jacket seen from the side with the near "
          "sleeve and a chrome claw hand below its cuff, a grey metal box chassis under the jacket hem, and a single "
          "large black ribbed tyre seen as a full circle, its upper part inside the chassis and its lower part below "
          "it touching the ground. The tyre is currently placed too far forward (to the left), sticking out in front "
          "of the chassis. Reproduce the image EXACTLY -- same robot, same size, same framing, same view, same "
          "colours, same grey background -- with ONE change: move the tyre backward (to the right) so that its centre "
          "is directly below the centre of the chassis and of the jacket, the tyre sitting symmetrically inside the "
          "chassis with the same amount of tread showing in front of and behind the chassis, still touching the ground "
          "at the bottom. The chassis, jacket, hand, head and antennae do not move. No text, no watermark.")

client = OpenAI()
def run(i):
    dest = OUT / f"side_fix_{i}.png"
    if dest.is_file() and "--force" not in sys.argv:
        return {"out": dest.name, "skipped": True}
    t0 = time.time(); err = None
    for attempt in range(3):
        try:
            with SRC.open("rb") as fh:
                resp = client.images.edit(model="gpt-image-2", image=fh, prompt=PROMPT, size="1024x1536",
                                          quality="high", background="opaque", output_format="png")
            dest.write_bytes(base64.b64decode(resp.data[0].b64_json)); break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"; print(i, "attempt", attempt, err); time.sleep(5)
    print(f"side_fix_{i}", "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
    return {"out": dest.name, "source": str(SRC.relative_to(HERE)), "prompt": PROMPT,
            "seconds": round(time.time() - t0, 1), "error": err}
with ThreadPoolExecutor(2) as ex:
    log = list(ex.map(run, [1, 2]))
(OUT / "_side_fix_manifest.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
