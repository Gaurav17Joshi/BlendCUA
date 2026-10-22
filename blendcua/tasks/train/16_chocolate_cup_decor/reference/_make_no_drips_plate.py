"""Second edit: remove the chocolate drips running down the outside of the mug in
_step1_table_cleared.png with gpt-image-2 (images.edit, quality high) -> edited.png.

    python reference/_make_no_drips_plate.py [--force]     # from the task folder
"""
import base64, sys, time, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]          # Blenduse
sys.path.insert(0, str(ROOT / "BlendCuavb_run"))
import blendcua_core
blendcua_core.load_api_keys(verbose=False)
from openai import OpenAI

SRC = HERE / "_step1_table_cleared.png"
DEST = HERE / "edited.png"
PROMPT = ("The supplied image is a 3D render of a glossy pink cartoon mug of hot chocolate with a black cartoon face "
          "(two round eyes with highlights, two brows, a smile), whipped cream on top with chocolate sauce drizzled over "
          "the cream, cocoa dust, mini marshmallows on the cream and a striped candy cane leaning in the cup, on a plain "
          "wooden table with a blurred wooden background. Keep everything EXACTLY as it is -- same mug, same position, "
          "same size, same viewpoint, same face, same cream, same drizzle ON the cream, same marshmallows, same candy "
          "cane, same table and background -- with ONE change: remove all the chocolate sauce that has run over the rim "
          "and is dripping down the OUTSIDE of the mug (every drip and run on the pink body, front, sides and by the "
          "handle). Where the drips were, show the clean glossy pink mug surface and the clean rim. The chocolate on top "
          "of the cream and the dark hot chocolate surface inside the cup stay as they are. No text, no watermark.")

if DEST.is_file() and "--force" not in sys.argv:
    print("edited.png exists"); sys.exit()
client = OpenAI(); t0 = time.time(); err = None
for attempt in range(3):
    try:
        with SRC.open("rb") as fh:
            resp = client.images.edit(model="gpt-image-2", image=fh, prompt=PROMPT, size="1536x1024",
                                      quality="high", background="opaque", output_format="png")
        DEST.write_bytes(base64.b64decode(resp.data[0].b64_json)); break
    except Exception as e:
        err = f"{type(e).__name__}: {e}"; print("attempt", attempt, err); time.sleep(5)
(HERE / "_no_drips_manifest.json").write_text(json.dumps({"plate": DEST.name, "source": SRC.name, "prompt": PROMPT,
    "seconds": round(time.time() - t0, 1), "error": err}, indent=1), encoding="utf-8")
print("edited.png", "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
