"""Clean-up pass: remove the grain / mottled patches accumulated over several gpt-image-2 edits of
option F1 (edited.png), keeping the image otherwise identical. Writes archive/clean_1.png, clean_2.png.

    python reference/_make_clean.py [--force]     # from the task folder
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

SRC = HERE / "archive" / "option_F1.png"; OUT = HERE / "archive"
PROMPT = ("The supplied image is a 3D cartoon robot character render: a retro TV set head with a glowing face and two "
          "antennae, an orange puffy zip-up jacket, short dark blue rods out of the cuffs ending in chrome ball hands "
          "with three claw fingers, and a grey box chassis with a black ribbed tyre half hidden in it, on a blue backdrop "
          "with soft diagonal bands. The image has degraded: the surfaces (the red TV shell, the orange jacket, the blue "
          "backdrop) show a mottled, grainy, patchy texture that is not part of the design. "
          "Reproduce the image EXACTLY -- same robot, same size, same position, same framing, same straight-on view, "
          "same colours, same lighting, same backdrop bands -- as a clean, crisp, noise-free 3D render: the TV shell "
          "a smooth matte plastic, the jacket a smooth soft puffy fabric, the backdrop clean flat blue with its soft "
          "bands, the chrome parts clean and sharp. Remove all grain, mottling and patchy artefacts. Change nothing "
          "else. No text, no watermark.")

client = OpenAI()
def run(i):
    dest = OUT / f"clean_{i}.png"
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
    print(f"clean_{i}", "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
    return {"out": dest.name, "source": str(SRC.relative_to(HERE)), "prompt": PROMPT,
            "seconds": round(time.time() - t0, 1), "error": err}
with ThreadPoolExecutor(2) as ex:
    log = list(ex.map(run, [1, 2]))
(OUT / "_clean_manifest.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
