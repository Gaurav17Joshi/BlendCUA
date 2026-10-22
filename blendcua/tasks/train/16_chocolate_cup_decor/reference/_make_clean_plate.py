"""Step 1: clear the table around the mug in original.png with gpt-image-2 (images.edit, quality high).

    python reference/_make_clean_plate.py [--force]     # from the task folder
"""
import base64, sys, time, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]          # Blenduse
sys.path.insert(0, str(ROOT / "BlendCuavb_run"))
import blendcua_core
blendcua_core.load_api_keys(verbose=False)
from openai import OpenAI

SRC = HERE / "original.png"
DEST = HERE / "_step1_table_cleared.png"
PROMPT = ("The supplied image is a 3D render of a glossy pink cartoon mug of hot chocolate with a black cartoon face, "
          "whipped cream on top with chocolate sauce drizzled over it and dripping down the outside of the mug, cocoa "
          "dust on the cream, mini marshmallows on the cream and a striped candy cane leaning in the cup, standing on a "
          "wooden table with a blurred wooden background. Keep the mug and everything ON it and IN it EXACTLY as it is: "
          "same position, same size, same viewpoint, same face, same drips, same cream, same marshmallows on the cream, "
          "same candy cane. Remove every object lying on the table around the mug: all the loose mini marshmallows, the "
          "round peppermint swirl candy and the dark chocolate squares, and the small specks floating in the air. "
          "Fill the cleared table with the same plain wooden surface, continuous grain, with the mug's soft shadow and "
          "reflection kept. Same lighting, same wooden background, no text, no watermark.")

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
(HERE / "_clean_manifest.json").write_text(json.dumps({"plate": DEST.name, "source": SRC.name, "prompt": PROMPT,
    "seconds": round(time.time() - t0, 1), "error": err}, indent=1), encoding="utf-8")
print("edited.png", "ok" if not err else "FAILED", round(time.time() - t0, 1), "s")
