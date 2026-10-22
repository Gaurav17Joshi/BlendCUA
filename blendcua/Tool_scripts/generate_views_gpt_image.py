"""Generate canonical orthographic-style views of every train-task reference
with gpt-image-2, to gauge how well the model can re-project a single photo
into front / side / top views usable as Blender modelling guides.

Layout produced:

    synth_views/<model>/<task>/reference.png      copy of tasks/train/<task>/reference.*
    synth_views/<model>/<task>/<nn>_<view>.png    the generated views
    synth_views/<model>/<task>/manifest.json      prompts + timings + status
    synth_views/<model>/<task>/contact_sheet.png  reference + views side by side

<run> is one per model: baseline (gpt-image-2), flare, sunburst.

Some tasks need a preparation pass before the views can be asked for: the
desk_chair reference holds two objects that must be isolated first, the
Thor's-hammer reference is tilted and has to be stood upright, the human
reference is a Blender viewport grab that has to be cleaned of UI, and the
domino reference is a motion-blurred photograph that has to be frozen. Those
tasks list a prep job whose output becomes the source image for the views
that follow, so job order within a task is significant.

Keys are loaded by blendcua_core.load_api_keys() from the key file outside
the repo; the value only ever lives in this process's environment.

    python generate_views_gpt_image.py                 # all tasks, skip existing
    python generate_views_gpt_image.py --only 09 18    # task-number prefixes
    python generate_views_gpt_image.py --force         # regenerate
    python generate_views_gpt_image.py --quality high
    python generate_views_gpt_image.py --sheets-only   # rebuild contact sheets
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
AGENT_DIR = HERE.parent
SYNTH_ROOT = AGENT_DIR / "synth_views"   # outputs: synth_views/<model>/<task>/
TASKS = AGENT_DIR / "tasks" / "train"

sys.path.insert(0, str(AGENT_DIR))

SQUARE, LANDSCAPE, PORTRAIT = "1024x1024", "1536x1024", "1024x1536"

# Output root and model are set by main(); the defaults reproduce the original
# gpt-image-2 run exactly, so `python generate_views_gpt_image.py` is unchanged.
OUT = SYNTH_ROOT / "gpt-image-2"
MODEL = "gpt-image-2"

MODELS = {
    "gpt-image-2":            "baseline",
    "gpt-image-2.5-flare":    "flare",
    "gpt-image-2.5-sunburst": "sunburst",
}

# USD per 1M tokens, from the OpenAI pricing page, 2026-09-08. Both 2.5
# variants are priced the same per token, so any cost difference between them
# is a difference in how many tokens they spend, which is the thing worth
# measuring. Edit here if the published prices move.
PRICES = {
    "gpt-image-2":            {"text_in": 2.50, "image_in": 4.00,
                               "cached_text_in": 0.625, "cached_image_in": 1.00,
                               "out": 15.00},
    "gpt-image-2.5-flare":    {"text_in": 5.00, "image_in": 8.00,
                               "cached_text_in": 1.25, "cached_image_in": 2.00,
                               "out": 30.00},
    "gpt-image-2.5-sunburst": {"text_in": 5.00, "image_in": 8.00,
                               "cached_text_in": 1.25, "cached_image_in": 2.00,
                               "out": 30.00},
}


def usage_dict(usage) -> dict:
    """The images API usage object as a plain dict, whatever SDK shape it is."""
    if usage is None:
        return {}
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(usage, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:                             # noqa: BLE001
                pass
    if isinstance(usage, dict):
        return dict(usage)
    return {k: v for k, v in vars(usage).items() if not k.startswith("_")}


def estimate_cost(model: str, u: dict) -> dict:
    """Cost of one call from its usage block, in dollars.

    If the response does not split input into text and image tokens, all input
    is charged at the image rate, which is the higher of the two, so the number
    errs high rather than flattering the comparison. The assumption is recorded
    in the manifest next to the figure.
    """
    price = PRICES.get(model)
    if not price or not u:
        return {"usd": None, "note": "no usage returned, or no price for this model"}
    det = u.get("input_tokens_details") or {}
    text_in = det.get("text_tokens")
    image_in = det.get("image_tokens")
    cached = det.get("cached_tokens") or 0
    total_in = u.get("input_tokens") or 0
    out = u.get("output_tokens") or 0
    note = ""
    if text_in is None and image_in is None:
        image_in, text_in = total_in, 0
        note = "input not broken down; all input charged at the image rate"
    text_in, image_in = text_in or 0, image_in or 0
    billed_in = max(text_in + image_in - cached, 0)
    share = (image_in / (text_in + image_in)) if (text_in + image_in) else 1.0
    usd = (
        billed_in * share * price["image_in"]
        + billed_in * (1 - share) * price["text_in"]
        + cached * share * price["cached_image_in"]
        + cached * (1 - share) * price["cached_text_in"]
        + out * price["out"]
    ) / 1_000_000
    return {"usd": round(usd, 6), "note": note}


_UNSUPPORTED = ("unsupported", "not supported", "unknown parameter",
                "unrecognized", "does not support", "invalid parameter")


def unsupported_param(msg, kwargs):
    """Which of our kwargs the API just rejected, if the error says so.

    gpt-image-2.5 is new and its parameter surface is not guaranteed to match
    gpt-image-2. Rather than guess which of quality / background /
    output_format it accepts, send them all and drop whichever one it
    complains about, recording the drop in the manifest so the run stays
    honest about what was actually sent.
    """
    low = msg.lower()
    if not any(w in low for w in _UNSUPPORTED):
        return None
    for name in kwargs:
        if name in ("model", "prompt") or name not in low:
            continue
        return name
    return None


# Rules appended to every view prompt. The two things that go wrong most often
# with a re-projection are the model inventing a different object and the model
# keeping the original camera, so both are called out explicitly.
BG_GREY = ("on a flat neutral light-grey studio background, with even lighting and "
           "at most a faint contact shadow")
BG_WHITE = ("on a PURE WHITE background — pure white, RGB 255/255/255, with no grey "
            "tone anywhere, no gradient, no vignette and no shadow of any kind")


def common(bg: str = BG_GREY) -> str:
    return (
        "This is a modelling reference plate, not an art piece. Keep the SAME object "
        "identity, proportions, materials and colours as the supplied image — do not "
        "restyle, redesign or substitute it. Re-project the camera as instructed; do "
        f"not simply reproduce the original viewpoint. Render the object centred and "
        f"complete in frame with a small margin, {bg}. Use a "
        "long-lens, near-orthographic camera so the view reads flat, with minimal "
        "perspective convergence. No text, no labels, no watermark, no measurement "
        "marks, no extra props, no second copy of the object, no cropping."
    )


COMMON = common()

FRONT = (
    "Produce a straight-on FRONT elevation: the camera is level with the middle "
    "of the object and looks horizontally straight at its front, so the object's "
    "left and right sides are equally visible and neither the top nor the bottom "
    "face is seen."
)
SIDE = (
    "Produce a straight-on SIDE profile: the camera is level with the middle of "
    "the object and rotated exactly 90 degrees from the front, so the object is "
    "seen edge-on in pure profile with neither its front nor its back face visible."
)
TOP = (
    "Produce a TOP-DOWN plan view: the camera is directly above the object "
    "looking straight down at it, so only the upper surfaces are visible and the "
    "object reads as its footprint outline. No side faces should be visible."
)


def view(subject: str, direction: str, extra: str = "", bg: str = BG_GREY) -> str:
    parts = [subject, direction]
    if extra:
        parts.append(extra)
    parts.append(common(bg))
    return " ".join(parts)


def job(name, prompt, *, size=SQUARE, src=None, background="opaque"):
    """One image call. `src` names an earlier job's output in the same task;
    None means the task's reference image."""
    return {"name": name, "prompt": prompt, "size": size, "src": src,
            "background": background}


# ── subjects ────────────────────────────────────────────────────────────────
# Written from the reference plates themselves so the model is told what it is
# looking at; a bare "the object" prompt drifts badly on the odder shapes.

S_BOX = ("The supplied image shows a closed corrugated cardboard shipping box with "
         "taped flaps and two printed white labels on one face, photographed from a "
         "three-quarter angle.")
S_CHESS = ("The supplied image shows two boxwood Staunton chess pieces standing side "
           "by side: a pawn on the left and a taller rook with four crenellations on "
           "the right, both with green felt bases.")
S_GLASS = ("The supplied image shows a single clear crystal wine glass with a tapered "
           "bowl, a long thin stem and a round foot.")
S_STONE = ("The supplied image shows a rectangular art-deco cast-stone datestone "
           "carved with the numerals 1934, with three graduated incised vertical "
           "grooves at each of the four corners and a stepped moulding along the "
           "bottom edge.")
S_CAN = ("The supplied image shows a tall slim black Monster Energy drinks can with "
         "the green claw-mark logo and a silver aluminium top.")
S_GATE = ("The supplied image shows a flat rectangular wrought-iron gate panel: a "
          "black rectangular frame, an upper half of symmetrical scroll and volute "
          "scrollwork around a central fleur-de-lis finial, and a lower half of "
          "plain vertical bars with scrolled corner spandrels.")
S_PLANT = ("The supplied image shows a potted Monstera deliciosa: a terracotta pot "
           "holding a cluster of pale aerial roots and stems carrying about seven "
           "large fenestrated split leaves.")
S_DESK = ("The supplied image shows an isolated light-oak office desk with a "
          "rectangular top, a pedestal of drawers on each side with chrome bar "
          "handles, and a recessed knee-hole with a back panel.")
S_CHAIR = ("The supplied image shows an isolated office task chair with a blue "
           "upholstered seat and backrest, black plastic arms and back support, a "
           "gas-lift column and a five-star base on castors.")
S_SKULL = ("The supplied image shows a real adult human skull with the mandible "
           "attached, full upper and lower dentition and visible cranial sutures.")
S_LAMP = ("The supplied image shows a white Anglepoise-style articulated desk lamp: "
          "a round weighted base, two spring-loaded parallelogram arms with black "
          "springs, and a conical shade with a black cable.")
S_UMBRELLA = ("The supplied image shows an open navy-blue umbrella with a cream "
              "fringed hem, eight canopy panels, a wooden shaft with a finial and a "
              "wooden crook handle.")
S_TABLE = ("The supplied image shows a square white cloth draped over a round dark "
           "mahogany pedestal table with a turned column and three carved scrolled "
           "cabriole feet; the cloth hangs in four points past the table edge.")
S_DOMINO = ("The supplied image shows a line of about eight black dominoes with "
            "white and yellow pips standing on a white surface, mid-topple, "
            "photographed with heavy motion blur.")
S_SHOE = ("The supplied image shows a royal-blue Nike Free Run mesh running shoe "
          "with a white Swoosh, a white segmented sole with black flex grooves and "
          "yellow lace tips.")
S_LANTERN = ("The supplied image shows a green cast-iron street lantern: a stepped "
             "square base, an ornate column with a spiral twist and scrollwork "
             "cartouche, and a tapered four-sided glazed lantern head lit from "
             "inside with warm amber light.")
S_HOURGLASS = ("The supplied image shows a wooden hourglass: two round oak end discs "
               "joined by four turned columns with ball finials, holding a "
               "blown-glass double bulb with pale sand running through it.")
S_SHARK = ("The supplied image shows a great white shark in full left-side profile: "
           "torpedo body with grey dorsal countershading over a white belly, "
           "triangular first dorsal fin, pectoral fins, gill slits and an open mouth "
           "of teeth.")
# NOTE: the original wording of this said "gold bands and rivets top and bottom",
# which is simply wrong about the object — the bands ring the head near its two
# ENDS, perpendicular to the handle. gpt-image-2 obeyed the wrong words over the
# reference image and produced a tall slab with horizontal bands. See PROMPTING.md.
S_HAMMER = ("The supplied image shows a stylised Thor's hammer: a blocky cracked "
            "grey stone head, a dark metal collar, a wooden handle with a red "
            "leather wrap and a dark metal pommel.")

# The geometry the reference actually shows, stated once and reused by the
# variants that are allowed to know it.
HAMMER_GEOM = (
    "Mjolnir geometry, exactly as the reference shows it: the stone head is a BLOCK "
    "whose long axis runs PERPENDICULAR to the handle, and a gold band studded with "
    "rivets wraps right around the head near EACH END of that long axis, close to "
    "the two flat striking faces. The handle meets the middle of one long face of "
    "the head at 90 degrees, through a dark metal collar. So in an upright "
    "front view the head sits at the top as a horizontal block that is clearly "
    "WIDER than it is tall — roughly one and a half times wider than tall — the two "
    "gold bands read as VERTICAL bands, one near the left end and one near the right "
    "end of the head, and the two striking faces are at the extreme left and right. "
    "The gold bands are NOT horizontal and do NOT run across the top and bottom of "
    "the head. The handle drops vertically from the centre of the head's underside."
)

HAMMER_UPRIGHT = (
    "the handle vertical and pointing straight down with the pommel at the bottom "
    "and the head level at the top, square to the camera, no tilt and no diagonal "
    "composition"
)
S_HUMAN = ("The supplied image shows a low-poly flat-shaded faceted human figure in a "
           "T-pose wearing a red t-shirt and dark trousers, with no facial detail.")
S_DOG = ("The supplied image shows a black-and-tan Rottweiler standing in left-side "
         "profile on grass, head up and mouth open.")


# ── the plan ────────────────────────────────────────────────────────────────
# A front view is only requested where the reference is not already a usable
# straight-on front. Tasks whose reference is already frontal get side + top.

PLAN: dict[str, list[dict]] = {
    "01_cardboard_box": [
        job("01_front", view(S_BOX, FRONT, "The front face is the one carrying the two "
            "printed labels; show it flat-on as a single rectangle."), size=SQUARE),
        job("02_side", view(S_BOX, SIDE, "Show the plain unlabelled side face flat-on "
            "as a single rectangle, with the taped seam running along the top edge."),
            size=SQUARE),
        # v1 came out as a tall portrait carton, taller than the front view
        job("02_side_v2", view(S_BOX, SIDE, "Show the plain unlabelled side face "
            "flat-on, with the packing tape crossing the top edge. CRITICAL "
            "proportions: the box HEIGHT is exactly the same as in the front view — "
            "this carton is slightly wider than it is tall and only a little shallower "
            "than it is wide, so the side elevation is a broad, almost square "
            "rectangle. It must NOT come out as a tall portrait box."), size=SQUARE),
        job("03_top", view(S_BOX, TOP, "Show the closed top flaps and the strip of "
            "packing tape running down the centre seam."), size=SQUARE),
    ],
    "02_chess_staunton": [
        job("01_side", view(S_CHESS, SIDE, "Both pieces are lathed and rotationally "
            "symmetric, so the profile silhouette must match the reference exactly; "
            "keep the pawn on the left and the rook on the right, standing on the "
            "same ground line."), size=SQUARE),
        # v1 drifted: pawn grew relative to the rook, the rook slimmed down and
        # the whole plate warmed towards orange
        job("01_side_v2", view(S_CHESS, SIDE, "Both pieces are lathed solids of "
            "revolution, so a side view is geometrically IDENTICAL to the front view: "
            "the result must be indistinguishable from the reference in silhouette. "
            "Do not redesign either piece. Hold all of these exactly: the pawn stands "
            "about seven tenths the height of the rook; the rook's crenellated crown "
            "is only slightly narrower than its flared base; the rook body tapers "
            "gently from base to collar; the pawn is a sphere on a narrow collar over "
            "a flared trumpet base; both sit on green felt discs. Keep the pale "
            "boxwood colour of the reference — do not warm it towards orange or "
            "yellow. Same spacing, same ground line, pawn on the left, rook on the "
            "right."), size=SQUARE),
        job("02_top", view(S_CHESS, TOP, "Looking straight down, the pawn reads as "
            "concentric circles with its ball finial at the centre and the rook as a "
            "ring with four square crenellation gaps around a hollow centre."),
            size=SQUARE),
    ],
    "03_wine_glass": [
        job("01_side", view(S_GLASS, SIDE, "The glass is a lathed solid of revolution, "
            "so the side profile must be identical in silhouette to the reference: "
            "same bowl taper, same stem length, same foot diameter."), size=PORTRAIT),
        job("02_top", view(S_GLASS, TOP, "Looking straight down the axis, the glass "
            "reads as concentric circles: the rim, the thinning wall, the bowl "
            "interior, the stem and the foot beyond."), size=SQUARE),
    ],
    "04_datestone_1934": [
        job("01_side", view(S_STONE, SIDE, "Show the stone edge-on so its depth from "
            "front face to back reads clearly, with the stepped bottom moulding "
            "projecting; the carved numerals are not visible from here."), size=SQUARE),
        job("02_top", view(S_STONE, TOP, "The camera is mounted on the ceiling directly "
            "above the stone, pointing straight down at the floor. All you can see is "
            "the narrow weathered top edge of the slab: a long thin horizontal "
            "rectangle running across the frame, the width of the stone by the depth "
            "of the block. The carved 1934 face is pointing away from the camera and "
            "must NOT be visible — do not show the numerals or the corner grooves."),
            size=LANDSCAPE),
    ],
    "05_energy_can": [
        job("01_side", view(S_CAN, SIDE, "Rotate the can 90 degrees about its vertical "
            "axis so the part of the wraparound label that was at the right edge now "
            "faces the camera; keep the same can silhouette, neck taper and silver top."),
            size=PORTRAIT),
        # v1 shrank the can to a thin rod and threw the label away
        job("01_side_v2", view(S_CAN, SIDE, "The can is a right circular cylinder, so "
            "its SILHOUETTE is identical from every horizontal direction: exactly the "
            "same height and exactly the same width as the reference, roughly five "
            "times taller than it is wide, with the same shoulder taper and the same "
            "rolled base. Do NOT make it narrower, do not turn it into a thin tube or "
            "a rod. The only thing that changes is which part of the wraparound label "
            "faces the camera — spin the can 90 degrees about its vertical axis so the "
            "artwork that ran off the right-hand edge of the reference is now centred, "
            "with the green claw logo wrapping in from one side."), size=PORTRAIT),
        job("02_top", view(S_CAN, TOP, "Looking straight down on the can, showing the "
            "silver aluminium lid, the stay-tab and the rolled rim as concentric "
            "circles."), size=SQUARE),
    ],
    "06_iron_gate": [
        job("01_side", view(S_GATE, SIDE, "The panel is flat, so from the side it reads "
            "as a tall narrow vertical slab: show the thickness of the frame and the "
            "flat bar stock of the scrollwork edge-on."), size=SQUARE),
        job("02_top", view(S_GATE, TOP, "The gate panel is standing upright and the "
            "camera is mounted on the ceiling directly above it, pointing straight "
            "down. All you can see is the narrow top rail of the frame seen end-on: a "
            "single long thin horizontal bar across the frame, showing the "
            "rectangular cross-section of the iron. The scrollwork is directly "
            "underneath and hidden by the rail, so it must NOT be visible — do not "
            "show the face of the gate."), size=LANDSCAPE),
    ],
    "07_monstera_pot": [
        job("01_side", view(S_PLANT, SIDE, "Rotate the plant 90 degrees about the pot's "
            "vertical axis; keep the same pot, the same number of leaves and the same "
            "overall height and spread."), size=PORTRAIT),
        job("02_top", view(S_PLANT, TOP, "Looking straight down from above the plant, "
            "the leaves radiate outward around the centre and the circular rim of the "
            "terracotta pot is visible between them."), size=SQUARE),
        # v1 re-grew the plant: longer stems, fewer leaves, roots fused to a trunk
        job("01_side_v2", view(S_PLANT, SIDE, "Keep the SAME specimen, not another "
            "plant of the same species: the same seven large leaves at the same "
            "sizes, the same short stubby leaf stems, the same dense curtain of pale "
            "aerial roots around a short central stem, and the same terracotta pot at "
            "the same relative scale — the pot is roughly a third of the total height. "
            "Do NOT lengthen or thin the stems, do not reduce the number of leaves, "
            "and do not fuse the aerial roots into a single thick trunk. The only "
            "change is that the whole plant has been spun 90 degrees about the pot's "
            "vertical axis, so the leaves that faced the camera now point left and "
            "right."), size=PORTRAIT),
        # a single leaf, flat on, for the geometry-nodes leaf the task asks for
        job("03_leaf_front",
            "The supplied image shows a potted Monstera deliciosa. Take ONE of its "
            "large fenestrated leaves and show that single leaf on its own, laid out "
            "completely flat and photographed straight down onto it, the way a "
            "pressed botanical specimen is plated. The whole leaf fills the frame "
            "with a small margin: the heart-shaped blade spread flat and symmetrical "
            "about its midrib, every deep marginal split and every oval hole open and "
            "clearly readable, the side veins running out from the midrib to each "
            "lobe, and a short length of the green stalk at the base. Same leaf "
            "colour, same glossy dark-green upper surface and same shape family as "
            "the plant in the reference. One leaf only — no pot, no stems, no other "
            "leaves, no hand, no text. Flat neutral light-grey background, even "
            "lighting, no shadow.", size=SQUARE),
    ],
    "08_desk_chair": [
        # prep: split the two objects, then six views off the isolates
        job("00_isolate_desk",
            "The supplied image shows a light-oak office desk with an office chair in "
            "front of it. Isolate ONLY the desk. Remove the chair and the floor and "
            "background entirely. Keep the desk exactly as photographed — same "
            "perspective, same wood colour, same drawers and chrome handles, same open "
            "drawers on the left pedestal — and reconstruct only the part of the desk "
            "that the chair was covering. Output the desk alone on a fully transparent "
            "background. No text, no shadow, no added objects.",
            size=LANDSCAPE, background="transparent"),
        job("01_isolate_chair",
            "The supplied image shows a light-oak office desk with a blue office task "
            "chair in front of it. Isolate ONLY the chair. Remove the desk and the "
            "floor and background entirely. Keep the chair exactly as photographed — "
            "same perspective, same blue upholstery, black arms, gas lift and "
            "five-star castor base — and reconstruct only the parts of the chair that "
            "the desk was occluding. Output the chair alone on a fully transparent "
            "background. No text, no shadow, no added objects.",
            size=LANDSCAPE, background="transparent"),
        # v1 of both isolates ignored background=transparent and returned a dark
        # studio backdrop with a rim-light halo; the desk also gained a bowed top
        job("00_isolate_desk_v2",
            "The supplied image shows a light-oak office desk with an office chair in "
            "front of it. Isolate ONLY the desk. Remove the chair, the floor and the "
            "background entirely. OUTPUT REQUIREMENT: a cut-out on a FULLY "
            "TRANSPARENT background — every pixel that is not desk must be "
            "transparent alpha. Do NOT paint a dark backdrop, a vignette, a gradient, "
            "a rim light, a glow or a drop shadow behind it. Keep the desk exactly as "
            "photographed: same perspective, same wood colour, same drawers and "
            "chrome bar handles, same open drawers on the left pedestal, and a "
            "STRAIGHT rectangular desk top — do not bow or curve the front edge and "
            "do not restyle it into an executive desk. Reconstruct only the part the "
            "chair was covering.",
            size=LANDSCAPE, background="transparent"),
        job("01_isolate_chair_v2",
            "The supplied image shows a light-oak office desk with a blue office task "
            "chair in front of it. Isolate ONLY the chair. Remove the desk, the floor "
            "and the background entirely. OUTPUT REQUIREMENT: a cut-out on a FULLY "
            "TRANSPARENT background — every pixel that is not chair must be "
            "transparent alpha. Do NOT paint a black backdrop, a spotlight, a glow "
            "halo, a rim light or a drop shadow behind it. Keep the chair exactly as "
            "photographed: same perspective, same flat even lighting, same blue "
            "upholstery, black arms, gas lift and five-star castor base. Reconstruct "
            "only the parts the desk was occluding.",
            size=LANDSCAPE, background="transparent"),
        job("02_desk_front", view(S_DESK, FRONT, "This is the user-facing front of the "
            "desk: a pedestal of drawers at each side and the knee-hole recess between "
            "them. Close the open drawers and reconstruct any part of the desk that "
            "the original photograph cropped off."),
            src="00_isolate_desk", size=LANDSCAPE),
        job("03_desk_side", view(S_DESK, SIDE, "Show one pedestal end-on, so the depth "
            "of the desk top and the height of the pedestal read clearly. Close the "
            "open drawers and reconstruct any part cropped off in the original."),
            src="00_isolate_desk", size=LANDSCAPE),
        # v1 read as a lone chest of drawers with no desk top spanning above it
        job("03_desk_side_v2", view(S_DESK, SIDE, "Show the WHOLE desk seen from one "
            "end, not a single pedestal on its own: the top slab spans across the "
            "frame with its edge overhanging slightly, and directly below it the flat "
            "outer side panel of the near pedestal runs down to the floor. The drawer "
            "fronts face away from the camera, so at most the ends of the chrome "
            "handles peek past the edge. It must read as a desk in profile — top plus "
            "pedestal. The desk is about 600-700 mm deep against about 750 mm high, so "
            "the silhouette is only slightly taller than it is wide."),
            src="00_isolate_desk_v2", size=LANDSCAPE),
        job("04_desk_top", view(S_DESK, TOP, "Looking straight down, the desk reads as "
            "one plain rectangular top; show its full uncropped footprint."),
            src="00_isolate_desk", size=LANDSCAPE),
        # v1 was technically correct and completely uninformative — a bare board
        job("04_desk_top_v2", view(S_DESK, TOP, "The desk stands on a flat neutral "
            "floor and the camera looks straight down at it. The top itself is a plain "
            "rectangle, roughly twice as wide as it is deep, with a STRAIGHT front "
            "edge. Light it so the two pedestals underneath throw a clear shadow onto "
            "the floor beyond the edges of the top, which reveals the desk's real "
            "footprint — the plate must carry more information than a bare board."),
            src="00_isolate_desk_v2", size=LANDSCAPE),
        job("05_chair_front", view(S_CHAIR, FRONT, "The camera faces the seat and the "
            "front of the backrest, with both armrests symmetrical and the five-star "
            "base spread evenly below."),
            src="01_isolate_chair", size=SQUARE),
        job("06_chair_side", view(S_CHAIR, SIDE, "Show the chair in pure profile so the "
            "backrest rake, the seat depth, the arm shape and the column height read "
            "clearly."), src="01_isolate_chair", size=SQUARE),
        job("07_chair_top", view(S_CHAIR, TOP, "Looking straight down, showing the seat "
            "pad, the top edge of the backrest, both armrests and the five arms of the "
            "base radiating out below."), src="01_isolate_chair", size=SQUARE),
    ],
    "09_skull": [
        job("01_front", view(S_SKULL, FRONT, "A true anterior view: both orbits equally "
            "visible and symmetrical, the nasal aperture on the midline, the upper and "
            "lower teeth in occlusion, both zygomatic arches level. Complete the "
            "symmetry that the three-quarter view hides."), size=SQUARE),
        job("02_side", view(S_SKULL, SIDE, "A true lateral view: the cranial vault, "
            "brow ridge, one zygomatic arch, the temporal region, the jaw hinge, the "
            "ramus and the chin, with only one orbit visible in profile."), size=SQUARE),
        job("03_top", view(S_SKULL, TOP, "A true superior view of the cranial vault "
            "looking straight down, showing the coronal and sagittal sutures and the "
            "oval outline of the skull from above."), size=SQUARE),
    ],
    "10_anglepoise_repose": [
        job("01_front", view(S_LAMP, FRONT, "Turn the lamp so the camera looks straight "
            "into the open mouth of the conical shade, with the arms receding behind "
            "it and the round base below. Keep the same arm pose as the reference."),
            size=SQUARE),
        job("02_side", view(S_LAMP, SIDE, "A pure profile of the posed lamp, showing "
            "the full linkage geometry: base, lower arm, elbow, upper arm and the "
            "shade angle, with both springs visible along the arms. Keep the same arm "
            "pose and joint angles as the reference."), size=SQUARE),
        job("03_top", view(S_LAMP, TOP, "Looking straight down on the posed lamp: the "
            "round base reads as a circle, the arms as bars reaching away from it and "
            "the shade as an ellipse at the far end."), size=SQUARE),
    ],
    "11_umbrella": [
        job("01_front", view(S_UMBRELLA, FRONT, "A straight-on side elevation of the "
            "whole open umbrella held upright with the handle at the bottom: the "
            "canopy reads as a symmetrical dome, the fringe as a level band, and the "
            "shaft and crook handle hang straight down on the vertical centre line."),
            size=SQUARE),
        job("02_side", view(S_UMBRELLA, SIDE, "CRITICAL: the umbrella stays FULLY OPEN "
            "— do not close it, do not fold it, do not furl the canopy into a cone. "
            "The canopy dome keeps exactly the same wide spread, height and fringe "
            "line as the reference. The only change is that the whole umbrella is "
            "spun about its own vertical shaft by 22.5 degrees, so a rib seam points "
            "straight at the camera instead of the middle of a panel. Handle vertical "
            "at the bottom, dome symmetrical, fringe a level band all the way round."),
            size=SQUARE),
        job("03_top", view(S_UMBRELLA, TOP, "Looking straight down on the open canopy: "
            "a circle divided into eight equal panels by the eight rib seams "
            "radiating from the central finial, with the fringe as a ring around the "
            "hem."), size=SQUARE),
    ],
    "12_tablecloth_drape": [
        job("01_front", view(S_TABLE, FRONT, "A straight-on elevation at table height: "
            "the cloth's front hem is a level edge with a hanging point at each "
            "corner, and the carved pedestal foot shows beneath."), size=SQUARE),
        job("02_side", view(S_TABLE, "Produce a CORNER-ON view. Spin the whole set-up "
            "45 degrees about the table's vertical axis, so that instead of a flat "
            "hem edge facing the camera, one hanging CORNER POINT of the square cloth "
            "is nearest the camera and aimed straight at it.", "The near corner hangs "
            "as a single sharp point on the vertical centre line, dropping lower than "
            "the hems, and the two hem edges either side of it recede away "
            "diagonally to the left and right. This must look clearly different from "
            "a straight-on elevation. Same table, same cloth, same drape."),
            size=SQUARE),
        job("03_top", view(S_TABLE, TOP, "Looking straight down: the draped cloth reads "
            "as a square with softly rounded corners, with the fold creases running "
            "out from the round table top underneath."), size=SQUARE),
        # v1 produced an eight-pointed star: the four real corners PLUS four
        # invented points at the middles of the edges
        job("03_top_v2", view(S_TABLE, TOP, "COUNT THE CORNERS. The cloth is a single "
            "SQUARE, so it has exactly FOUR corners and exactly FOUR straight hem "
            "edges. Seen from directly above it reads as a plain square: four corner "
            "points, one at each corner, and between them four straight edges. Do NOT "
            "put points, peaks or diamonds in the middles of the edges — there is "
            "nothing there but a straight hem. The result must not look like a star. "
            "Inside the square, soft diagonal fold creases run from each corner in "
            "towards the centre where the round table top holds the cloth up, and the "
            "dark wooden feet just show past two or three of the edges."), size=SQUARE),
    ],
    "13_domino_cascade": [
        job("00_clean_side",
            S_DOMINO + " Re-render the same scene completely sharp with the motion "
            "blur removed, freezing the topple at the same instant: eight black "
            "dominoes in one straight line on a plain white surface, each leaning a "
            "little further than the one behind it, seen from a level camera at the "
            "side of the line. Keep the same spacing and the same lean angles. Flat "
            "neutral background, no text, no motion streaks, no extra dominoes.",
            size=LANDSCAPE),
        job("01_front", view(S_DOMINO, FRONT, "The camera is at the end of the line "
            "looking straight along it, so the nearest domino's pip face fills the "
            "centre and the rest recede directly behind it. Show the dominoes sharp, "
            "with no motion blur."), src="00_clean_side", size=SQUARE),
        job("02_top", view(S_DOMINO, TOP, "Looking straight down on the line: eight "
            "sharp rectangles in a row on a plain surface, showing the gap between "
            "each domino and the next. No motion blur."),
            src="00_clean_side", size=LANDSCAPE),
        # v1 laid the dominoes flat face-up and evened out the spacing
        job("02_top_v2", view(S_DOMINO, TOP, "The dominoes are STANDING ON EDGE on the "
            "surface — they are not lying flat. From directly above, each one "
            "therefore reads as a NARROW RECTANGULAR BAR: you are looking at its thin "
            "top edge, about 8 mm across by 40 mm long. The pip faces point sideways "
            "and are NOT visible from above, so do not draw any pips and do not lay "
            "the tiles down flat. Show all eight bars in one straight line with the "
            "gap between each one clearly readable, and make the leaning ones appear "
            "progressively wider than the upright ones, because a tipped domino "
            "presents more of its face to a camera overhead."),
            src="00_clean_side", size=LANDSCAPE),
    ],
    "14_sneaker": [
        job("01_front", view(S_SHOE, FRONT, "A head-on view from the toe: the camera "
            "looks straight at the front of the shoe, so the toe box is symmetrical, "
            "the laces run up the centre and the sole reads as a flat band across the "
            "bottom."), size=SQUARE),
        job("02_top", view(S_SHOE, TOP, "Looking straight down on the shoe: the "
            "lacing, the tongue, the collar opening and the outline of the mesh upper, "
            "with the sole hidden beneath."), size=LANDSCAPE),
        job("03_bottom", view(S_SHOE, "Produce a BOTTOM view: the camera is directly "
            "below the shoe looking straight up at the outsole, so the whole tread "
            "pattern is visible flat-on.", "Show the white segmented sole with its "
            "black flex grooves and the tread pattern across heel, midfoot and "
            "forefoot."), size=LANDSCAPE),
    ],
    "15_street_lantern": [
        job("01_front", view(S_LANTERN, FRONT, "A straight-on elevation of the whole "
            "lantern standing vertically, the column dead centre and the lantern head "
            "square to the camera showing one full glazed face. Keep the warm lit glow "
            "inside the head."), size=PORTRAIT),
        job("02_side", view(S_LANTERN, SIDE, "The same upright lantern rotated 45 "
            "degrees about its vertical axis, so a corner rib of the four-sided "
            "lantern head faces the camera and the profile of the scrollwork "
            "cartouche on the column reads edge-on."), size=PORTRAIT),
        # v1 thinned the post to a pole and deleted the scrollwork cartouche
        job("02_side_v2", view(S_LANTERN, SIDE, "Spin the lantern 45 degrees about its "
            "vertical axis. CRITICAL: the post keeps exactly the same thickness and "
            "the same proportions as the reference — do NOT slim it down into a plain "
            "pole and do not stretch it taller. Every piece of ornament survives the "
            "rotation: the broad scrollwork cartouche on the upper column keeps its "
            "full width and its volutes, now seen at an angle; below it the spiral "
            "twist, then the diamond lattice band, then the stepped flared base. The "
            "only change is the viewing angle — a corner rib of the four-sided lantern "
            "head now points at the camera."), size=PORTRAIT),
        job("03_top", view(S_LANTERN, TOP, "Looking straight down on the lantern from "
            "above: the finial at the centre, the square pyramidal roof of the head "
            "around it, and the base plinth showing beyond as a square."), size=SQUARE),
    ],
    "16_hourglass": [
        job("01_side", view(S_HOURGLASS, SIDE, "Rotate the hourglass 45 degrees about "
            "its vertical axis so a different pair of the four turned columns is "
            "nearest the camera; keep the same silhouette, the same glass bulbs and "
            "the same sand level in each bulb."), size=PORTRAIT),
        # v1 barely rotated (still two columns) and restarted the sand running
        job("01_side_v2", view(S_HOURGLASS, SIDE, "Spin the hourglass 45 degrees about "
            "its vertical axis so that ALL FOUR turned columns are visible, spaced "
            "around the round end discs — two nearer the camera towards the left and "
            "right, two further back between them — instead of the two that overlap "
            "in the reference. Keep the sand exactly as the reference has it: the same "
            "quantity in the upper bulb forming the same cone, the same pile in the "
            "lower bulb. Do NOT add a falling stream of sand and do not change the "
            "fill levels. Same overall height, same disc diameter."), size=PORTRAIT),
        job("02_top", view(S_HOURGLASS, TOP, "Looking straight down: the round top disc "
            "reads as a circle with the four ball finials of the columns spaced evenly "
            "around it and the neck of the glass bulb visible at the centre."),
            size=SQUARE),
    ],
    "17_shark": [
        job("01_front", view(S_SHARK, FRONT, "A head-on anterior view: the camera is "
            "level with the shark and directly in front of its snout, so the body is "
            "bilaterally symmetrical, both pectoral fins spread evenly to the sides, "
            "the mouth and teeth face the camera and the dorsal fin rises on the "
            "centre line. Keep the grey-over-white countershading."), size=SQUARE),
        job("02_top", view(S_SHARK, TOP, "A dorsal plan view: the camera is directly "
            "above the shark looking straight down, showing the full grey top surface, "
            "the symmetrical pectoral and pelvic fins, the dorsal fin on the midline "
            "and the tail. The body reads as a symmetrical torpedo outline."),
            size=LANDSCAPE),
        # same two views, on pure white instead of studio grey
        job("01_front_v2", view(S_SHARK, FRONT, "A head-on anterior view: the camera "
            "is level with the shark and directly in front of its snout, so the body "
            "is bilaterally symmetrical, both pectoral fins spread evenly to the "
            "sides, the mouth and teeth face the camera and the dorsal fin rises on "
            "the centre line. Keep the grey-over-white countershading. The shark must "
            "be cut out cleanly against the white — no grey studio floor, no backdrop "
            "sweep, no drop shadow under it.", bg=BG_WHITE), size=SQUARE),
        job("02_top_v2", view(S_SHARK, TOP, "A dorsal plan view: the camera is "
            "directly above the shark looking straight down, showing the full grey top "
            "surface, the symmetrical pectoral and pelvic fins, the dorsal fin on the "
            "midline and the tail. The body reads as a symmetrical torpedo outline. "
            "The shark must be cut out cleanly against the white — no grey studio "
            "floor, no backdrop sweep, no drop shadow under it.", bg=BG_WHITE),
            size=LANDSCAPE),
    ],
    "18_thors_hammer": [
        # prep: stand it up first, then take the views off the upright plate
        job("00_upright_front",
            S_HAMMER + " In the supplied image the hammer is tilted diagonally across "
            "the frame and seen from a three-quarter angle. Re-render the SAME hammer "
            "standing perfectly upright and square to the camera: the handle vertical "
            "and pointing straight down with the pommel at the bottom, the head level "
            "at the top with its long side facing the camera, and the two gold bands "
            "horizontal. No tilt, no rotation, no diagonal composition. Keep the same "
            "stone head, gold bands and rivets, metal collar, wooden handle, red "
            "leather wrap and pommel, and the same stylised look. Centre it on a flat "
            "neutral light-grey background. No text, no extra objects.",
            size=PORTRAIT),
        # ── prompt experiment ────────────────────────────────────────────────
        # Same source, same size, same quality; only the wording changes. Two
        # variables crossed: how the change of view is FRAMED (re-render vs
        # rotate vs pure in-plane rotation) and whether the prompt CARRIES the
        # correct geometry. `00_upright_front` above is cell (re-render, wrong
        # geometry) and is the baseline. Findings in PROMPTING.md.
        job("f_b_rotate",                       # rotate framing, no geometry
            S_HAMMER + " Do not draw a new hammer — take THIS hammer and rotate it. "
            "It is currently lying along a diagonal, handle down to the lower left "
            "and head up to the upper right. Rotate it so that it stands upright: " +
            HAMMER_UPRIGHT + ". Everything about the object stays as it is — same "
            "head shape and size, same bands and rivets in the same places on the "
            "head, same collar, same wooden handle, same red wrap, same pommel, same "
            "stylised look. Only its orientation changes. Centre it on a flat neutral "
            "light-grey background. No text, no extra objects.",
            size=PORTRAIT),
        job("f_c_geometry",                     # re-render framing + geometry
            S_HAMMER + " In the supplied image the hammer is tilted diagonally across "
            "the frame and seen from a three-quarter angle. Re-render the SAME hammer "
            "standing upright and square to the camera: " + HAMMER_UPRIGHT + ". " +
            HAMMER_GEOM + " Keep the same stone head, gold bands and rivets, metal "
            "collar, wooden handle, red leather wrap and pommel, and the same "
            "stylised look. Centre it on a flat neutral light-grey background. No "
            "text, no extra objects.",
            size=PORTRAIT),
        job("f_d_rotate_geometry",              # rotate framing + geometry
            S_HAMMER + " Do not draw a new hammer — take THIS hammer and rotate it. "
            "It is currently lying along a diagonal, handle down to the lower left "
            "and head up to the upper right. Rotate it so that it stands upright: " +
            HAMMER_UPRIGHT + ". Only its orientation changes; nothing about the "
            "object itself changes. " + HAMMER_GEOM + " Centre it on a flat neutral "
            "light-grey background. No text, no extra objects.",
            size=PORTRAIT),
        job("f_e_inplane",                      # in-plane rotation ONLY
            S_HAMMER + " Rotate the WHOLE PICTURE clockwise by about 50 degrees, as if "
            "you were turning the photograph itself on the table, so that the handle "
            "ends up vertical with the pommel at the bottom and the head at the top. "
            "This is a flat in-plane rotation and nothing else: keep the exact same "
            "three-quarter camera angle on the hammer, the same lighting, the same "
            "shapes, the same perspective, the same everything. Do not re-draw the "
            "hammer, do not turn it towards the camera, do not change which faces are "
            "visible. Put it on a flat neutral light-grey background instead of the "
            "dark one, centred and complete in frame. No text, no extra objects.",
            size=PORTRAIT),
        job("f_f_from_inplane",                 # two-step: square up from f_e
            S_HAMMER + " The hammer in this image already stands upright with the "
            "handle vertical, but it is still seen from a three-quarter angle so the "
            "head is turned away at a corner. Keep the upright orientation exactly as "
            "it is and swing the CAMERA round to face the head straight on, so the "
            "hammer is square to the camera: " + HAMMER_UPRIGHT + ". " + HAMMER_GEOM +
            " Change nothing else — same head, same bands and rivets, same collar, "
            "same handle, same wrap, same pommel, same background. No text, no extra "
            "objects.",
            src="f_e_inplane", size=PORTRAIT),
        # ─────────────────────────────────────────────────────────────────────
        job("01_side", view(S_HAMMER, SIDE, "Keep the hammer upright with the handle "
            "vertical, and rotate it 90 degrees about that vertical axis so the camera "
            "looks straight at one flat square striking face of the head. The head "
            "reads as a symmetrical square block, narrower than in the front view, "
            "with the gold bands running straight across it."),
            src="00_upright_front", size=PORTRAIT),
        job("02_top", view(S_HAMMER, TOP, "Looking straight down on the upright hammer "
            "from above: the top face of the stone head is a rectangle framed by the "
            "gold band, and the handle is hidden directly beneath it."),
            src="00_upright_front", size=SQUARE),
    ],
    "19_human_thinker": [
        job("00_clean_front",
            S_HUMAN + " The supplied image is a Blender viewport screenshot. Re-render "
            "the SAME figure as a clean reference plate: remove the dark viewport "
            "background, the grid floor lines, the axis lines and the mouse cursor, "
            "and place the figure on a flat neutral light-grey background. Keep the "
            "T-pose exactly, keep the flat-shaded faceted low-poly look, the red "
            "t-shirt, the dark trousers, the dark shoes and the featureless face. Do "
            "not smooth the model or add facial detail. Straight-on front view, whole "
            "figure in frame.",
            size=PORTRAIT),
        job("01_side", view(S_HUMAN, SIDE, "Keep the T-pose and the flat-shaded "
            "faceted low-poly look: the figure stands in pure profile with the arms "
            "extended straight out towards and away from the camera, so they read as "
            "foreshortened. Same height, same proportions, no facial detail."),
            src="00_clean_front", size=PORTRAIT),
        job("02_top", view(S_HUMAN, TOP, "Looking straight down on the T-posed figure: "
            "the head at the centre, the shoulders and the two outstretched arms "
            "reading as a bar across the frame, and the feet hidden beneath. Keep the "
            "faceted low-poly look."), src="00_clean_front", size=SQUARE),
    ],
    "20_low_poly_dog": [
        job("01_front", view(S_DOG, FRONT, "A head-on view: the camera is level with "
            "the dog and directly in front of its chest, so the body is bilaterally "
            "symmetrical, both front legs and both ears are visible and the tan chest "
            "and muzzle markings read symmetrically. Same standing pose, same "
            "black-and-tan Rottweiler markings. Put it on a neutral studio background "
            "rather than grass."), size=SQUARE),
        job("02_top", view(S_DOG, TOP, "A plan view from directly above the standing "
            "dog: the black back and the symmetrical outline of head, shoulders, "
            "ribcage, hindquarters and tail, with the legs hidden beneath the body. "
            "Put it on a neutral studio background rather than grass."),
            size=LANDSCAPE),
    ],
}


# ── runner ──────────────────────────────────────────────────────────────────

def reference_for(task: str) -> Path:
    for ext in (".png", ".jpg", ".jpeg"):
        p = TASKS / task / f"reference{ext}"
        if p.is_file():
            return p
    raise FileNotFoundError(f"no reference image for {task}")


def run_task(task: str, jobs: list[dict], client, *, quality: str, force: bool,
             only_jobs: tuple[str, ...] | None = None) -> dict:
    out_dir = OUT / task
    out_dir.mkdir(parents=True, exist_ok=True)

    ref = reference_for(task)
    ref_copy = out_dir / f"reference{ref.suffix.lower()}"
    if not ref_copy.is_file() or force:
        shutil.copy2(ref, ref_copy)

    # carry forward what a previous run recorded, so a --jobs retry doesn't
    # blank out the entries for the jobs it isn't touching
    prior: dict[str, dict] = {}
    mf = out_dir / "manifest.json"
    if mf.is_file():
        try:
            prior = {j["name"]: j for j in json.loads(mf.read_text(encoding="utf-8"))["jobs"]}
        except Exception:                                 # noqa: BLE001
            prior = {}

    record = {"task": task, "reference": ref.name, "model": MODEL,
              "quality": quality, "jobs": []}
    for spec in jobs:
        dest = out_dir / f"{spec['name']}.png"
        src = out_dir / f"{spec['src']}.png" if spec["src"] else ref_copy

        entry = {"name": spec["name"], "file": dest.name, "source": src.name,
                 "size": spec["size"], "background": spec["background"],
                 "prompt": spec["prompt"]}

        if only_jobs and not spec["name"].startswith(only_jobs):
            record["jobs"].append(prior.get(spec["name"], {**entry, "status": "not-run"}))
            continue
        if dest.is_file() and not force:
            entry["status"] = "skipped-exists"
            record["jobs"].append(entry)
            print(f"  [{task}] {spec['name']}: exists, skipping")
            continue
        if not src.is_file():
            entry["status"] = "skipped-no-source"
            record["jobs"].append(entry)
            print(f"  [{task}] {spec['name']}: SOURCE MISSING ({src.name}), skipping")
            continue

        started = time.time()
        last_err = None
        kwargs = {"model": MODEL, "prompt": spec["prompt"],
                  "background": spec["background"], "output_format": "png",
                  "size": spec["size"], "quality": quality}
        dropped = []
        entry["model"] = MODEL
        for attempt in range(1, 6):
            try:
                with src.open("rb") as fh:
                    resp = client.images.edit(image=fh, **kwargs)
                raw = getattr(resp.data[0], "b64_json", None)
                if not raw:
                    raise RuntimeError(f"{MODEL} returned no b64_json")
                dest.write_bytes(base64.b64decode(raw))
                entry["status"] = "ok"
                entry["bytes"] = dest.stat().st_size
                entry["attempts"] = attempt
                u = usage_dict(getattr(resp, "usage", None))
                if u:
                    entry["usage"] = u
                    entry["cost"] = estimate_cost(MODEL, u)
                if dropped:
                    entry["dropped_params"] = dropped
                break
            except Exception as exc:                      # noqa: BLE001
                last_err = f"{type(exc).__name__}: {exc}"
                bad = unsupported_param(last_err, kwargs)
                if bad:
                    kwargs.pop(bad, None)
                    dropped.append(bad)
                    print(f"  [{task}] {spec['name']}: {MODEL} rejected {bad!r}, retrying without it")
                    continue
                print(f"  [{task}] {spec['name']}: attempt {attempt} failed — {last_err}")
                if attempt < 5:
                    time.sleep(4 * attempt)
        else:
            entry["status"] = "failed"
            entry["error"] = last_err
            if dropped:
                entry["dropped_params"] = dropped

        entry["seconds"] = round(time.time() - started, 1)
        record["jobs"].append(entry)
        print(f"  [{task}] {spec['name']}: {entry['status']} ({entry['seconds']}s)")

    (out_dir / "manifest.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8")
    return record


# ── contact sheets ──────────────────────────────────────────────────────────

def contact_sheet(task: str) -> Path | None:
    """Reference plus every generated view in one strip, each panel labelled."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    out_dir = OUT / task
    plates: list[tuple[str, Path]] = []
    for ext in (".png", ".jpg", ".jpeg"):
        p = out_dir / f"reference{ext}"
        if p.is_file():
            plates.append(("reference", p))
            break
    for spec in PLAN[task]:
        p = out_dir / f"{spec['name']}.png"
        if p.is_file():
            plates.append((spec["name"], p))
    if len(plates) < 2:
        return None

    cell, pad, label_h = 420, 12, 26
    cols = min(len(plates), 5)
    rows = (len(plates) + cols - 1) // cols
    row_h = cell + label_h + pad
    sheet = Image.new("RGB", (cols * (cell + pad) + pad, rows * row_h + pad),
                      (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for i, (name, path) in enumerate(plates):
        col, row = i % cols, i // cols
        im = Image.open(path).convert("RGBA")
        # alpha-composite onto white so a transparent cut-out is actually visible
        flat = Image.new("RGBA", im.size, (255, 255, 255, 255))
        flat.alpha_composite(im)
        im = flat.convert("RGB")
        im.thumbnail((cell, cell))
        cx, cy = pad + col * (cell + pad), pad + row * row_h
        sheet.paste(im, (cx + (cell - im.width) // 2,
                         cy + label_h + (cell - im.height) // 2))
        draw.text((cx + 4, cy + 6), name, fill=(30, 30, 30))

    dest = out_dir / "contact_sheet.png"
    sheet.save(dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None,
                    help="task name prefixes, e.g. 09 18 or 09_skull")
    ap.add_argument("--jobs", nargs="*", default=None,
                    help="job-name prefixes within the selected tasks, e.g. 02_top")
    ap.add_argument("--force", action="store_true", help="regenerate existing images")
    ap.add_argument("--quality", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--workers", type=int, default=4,
                    help="tasks generated in parallel (jobs inside a task stay ordered)")
    ap.add_argument("--sheets-only", action="store_true",
                    help="skip generation, just rebuild the contact sheets")
    ap.add_argument("--model", default="gpt-image-2", choices=sorted(MODELS),
                    help="which image model to run (default: the original gpt-image-2)")
    ap.add_argument("--out", default=None,
                    help="output root; defaults to the folder this model is registered "
                         "under in MODELS, as a subfolder of synth_views/")
    ap.add_argument("--probe", action="store_true",
                    help="run ONE plate, print what the API accepted and what it cost, "
                         "then stop. Do this before a full run of a new model.")
    args = ap.parse_args()

    global MODEL, OUT
    MODEL = args.model
    OUT = Path(args.out).expanduser().resolve() if args.out else SYNTH_ROOT / MODELS[MODEL]
    OUT.mkdir(parents=True, exist_ok=True)

    tasks = sorted(PLAN)
    if args.only:
        wanted = tuple(args.only)
        tasks = [t for t in tasks if t.startswith(wanted)]
    if not tasks:
        print("no tasks matched --only")
        return 1

    if not args.sheets_only:
        import blendcua_core
        names = blendcua_core.load_api_keys(verbose=False)
        if not os.environ.get("OPENAI_API_KEY"):
            print(f"OPENAI_API_KEY not available (key file supplied: {names})")
            return 2
        from openai import OpenAI
        client = OpenAI()

        if args.probe:
            t = tasks[0]
            spec = PLAN[t][0]
            print(f"probe: {MODEL} on {t}/{spec['name']}, writing into {OUT}")
            rec = run_task(t, [spec], client, quality=args.quality, force=True,
                           only_jobs=None)
            job0 = rec["jobs"][0]
            print(json.dumps({k: job0.get(k) for k in
                              ("status", "seconds", "attempts", "dropped_params",
                               "usage", "cost", "error")}, indent=2))
            return 0 if job0.get("status") == "ok" else 3

        total = sum(len(PLAN[t]) for t in tasks)
        print(f"{len(tasks)} task(s), {total} image call(s), "
              f"model={MODEL}, quality={args.quality}, out={OUT}")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            only_jobs = tuple(args.jobs) if args.jobs else None
            futures = {pool.submit(run_task, t, PLAN[t], client,
                                   quality=args.quality, force=args.force,
                                   only_jobs=only_jobs): t
                       for t in tasks}
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    fut.result()
                except Exception as exc:                  # noqa: BLE001
                    print(f"[{t}] TASK FAILED: {type(exc).__name__}: {exc}")

    index = []
    for t in tasks:
        sheet = contact_sheet(t)
        mf = OUT / t / "manifest.json"
        rec = json.loads(mf.read_text(encoding="utf-8")) if mf.is_file() else {"jobs": []}
        ok = sum(1 for j in rec["jobs"] if j.get("status") in ("ok", "skipped-exists"))
        index.append({"task": t, "views": len(rec["jobs"]), "ok": ok,
                      "contact_sheet": sheet.name if sheet else None})
        print(f"[{t}] {ok}/{len(rec['jobs'])} plates" + (f", sheet={sheet.name}" if sheet else ""))

    (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

    # run-level totals, so a cost/time comparison does not have to re-derive them
    n = ok_n = 0
    secs = 0.0
    usd = 0.0
    toks = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    priced = 0
    for t in tasks:
        mf = OUT / t / "manifest.json"
        if not mf.is_file():
            continue
        for j in json.loads(mf.read_text(encoding="utf-8"))["jobs"]:
            if j.get("status") not in ("ok", "failed"):
                continue
            n += 1
            ok_n += j.get("status") == "ok"
            secs += j.get("seconds") or 0.0
            for k in toks:
                toks[k] += (j.get("usage") or {}).get(k) or 0
            cu = (j.get("cost") or {}).get("usd")
            if cu is not None:
                usd += cu
                priced += 1
    summary = {"model": MODEL, "quality": args.quality, "root": OUT.name,
               "tasks": len(tasks), "calls": n, "ok": ok_n,
               "seconds_total": round(secs, 1),
               "seconds_mean": round(secs / n, 1) if n else None,
               "tokens": toks, "usd_total": round(usd, 4) if priced else None,
               "usd_mean": round(usd / priced, 5) if priced else None,
               "calls_priced": priced}
    (OUT / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
