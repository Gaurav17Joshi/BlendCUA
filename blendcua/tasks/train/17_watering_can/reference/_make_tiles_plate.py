"""Second plate: the same can on a blue tiled floor. gpt-image-2 images.edit from reference.png."""
import base64, sys, time, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "BlendCuavb_run"))
import blendcua_core; blendcua_core.load_api_keys(verbose=False)
from openai import OpenAI
SRC = HERE.parent / "reference.png"; DEST = HERE / "on_blue_tiles.png"
PROMPT = ("The supplied image shows a galvanised steel watering can standing on a plain light-grey ground. Change ONLY the "
          "ground: replace the grey floor with a floor of glossy blue square ceramic tiles with thin pale grout lines. The "
          "tiling must be a PERFECTLY REGULAR grid: every tile IDENTICAL in size and shape, all the same blue, the grout "
          "lines straight, evenly spaced and continuous across the whole floor, one set running left-right and one set "
          "running toward the horizon in correct perspective, like a real tiled floor with no irregular, half-size or "
          "misaligned tiles anywhere. Seen from the same camera. The can itself must stay EXACTLY as it "
          "is: same position in the frame, same size, same angle, same shape, same colours and reflections, not moved, "
          "not rotated, not rescaled, not redrawn, with the tiles appearing beneath it and a faint contact shadow where it "
          "stands. Keep the plain light-grey background wall above the floor. No other objects, no text, no watermark.")
if DEST.is_file() and "--force" not in sys.argv:
    print("exists"); sys.exit()
client = OpenAI(); t0 = time.time()
with SRC.open("rb") as fh:
    resp = client.images.edit(model="gpt-image-2", image=fh, prompt=PROMPT, size="1024x1024",
                              quality="high", background="opaque", output_format="png")
DEST.write_bytes(base64.b64decode(resp.data[0].b64_json))
(HERE / "_tiles_manifest.json").write_text(json.dumps({"source": SRC.name, "out": DEST.name, "prompt": PROMPT,
                                                        "seconds": round(time.time()-t0, 1)}, indent=1), encoding="utf-8")
print("ok", round(time.time()-t0, 1), "s")
