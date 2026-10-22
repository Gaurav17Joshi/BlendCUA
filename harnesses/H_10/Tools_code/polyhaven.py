"""Fetch CC0 PBR texture sets from Poly Haven.

Why this and not a texture found by searching the web: Poly Haven publishes a
JSON API, every asset is CC0 (no attribution required, though this module
records it anyway), and each asset ships a matched SET — diffuse, roughness,
normal, AO, displacement — at the same resolution and alignment. A single
photograph pulled off a search result is a colour map and nothing else, and
half of one is a lighting photograph rather than an albedo.

    import polyhaven as ph
    files = ph.fetch("marble_rock_01", ["Diffuse", "Rough", "nor_gl"],
                     res="2k", fmt="jpg", dest=".../textures/source")

Downloads are CACHED on disk: an action that has already fetched its texture
re-runs offline, which matters because these action files are meant to be
replayable months later.
"""

import json
import os
import urllib.request

API = "https://api.polyhaven.com"
UA = {"User-Agent": "blendcua/1.0 (texture fetch)"}

# What each map is FOR, and the colour space it must be read in. Getting the
# second one wrong is the classic silent texture bug: a roughness map read as
# sRGB is still a picture, just the wrong numbers.
MAPS = {
    "Diffuse": ("base colour, lighting removed", "sRGB"),
    "Rough":   ("roughness, 0 = mirror, 1 = chalk", "Non-Color"),
    "nor_gl":  ("tangent-space normal, OpenGL (+Y up) — the one Blender "
                "wants; nor_dx has green inverted", "Non-Color"),
    "AO":      ("ambient occlusion of the photographed surface", "Non-Color"),
    "Displacement": ("height, for displacement or parallax", "Non-Color"),
}


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def info(asset):
    """Poly Haven metadata for one asset id, as a dict.

    Use it to confirm an asset id exists and see its categories/tags
    before spending a download on it.
    """
    return json.loads(_get("%s/info/%s" % (API, asset)))


def files(asset):
    """The full download manifest for one asset id, as a dict.

    Nested by map name, then resolution, then format — check here for
    which map names and resolutions actually exist before calling
    `fetch`, whose defaults do not fit every asset.
    """
    return json.loads(_get("%s/files/%s" % (API, asset)))


def fetch(asset, maps=("Diffuse", "Rough", "nor_gl"), res="2k", fmt="jpg",
          dest=".", index=None):
    """Download `maps` for `asset`. Returns {map: local path}.

    Anything already on disk is left alone, so this is safe to call on every
    replay.
    """
    os.makedirs(dest, exist_ok=True)
    out = {}
    need = [m for m in maps
            if not os.path.exists(os.path.join(
                dest, "%s_%s_%s.%s" % (asset, _slug(m), res, fmt)))]

    idx = index
    if need and idx is None:
        idx = files(asset)

    for m in maps:
        local = os.path.join(dest, "%s_%s_%s.%s"
                             % (asset, _slug(m), res, fmt))
        if not os.path.exists(local):
            entry = idx.get(m)
            if entry is None:
                raise KeyError("%s has no %r map (has: %s)"
                               % (asset, m, ", ".join(sorted(idx))))
            url = entry[res][fmt]["url"]
            with open(local, "wb") as f:
                f.write(_get(url))
        out[m] = local
    return out


def _slug(m):
    return {"Diffuse": "diff", "Rough": "rough", "nor_gl": "nor_gl",
            "nor_dx": "nor_dx", "AO": "ao",
            "Displacement": "disp"}.get(m, m.lower())


def write_credit(asset, dest, meta=None):
    """Leave the provenance next to the files, not in a commit message."""
    meta = meta or info(asset)
    path = os.path.join(dest, "SOURCE.txt")
    with open(path, "w") as f:
        f.write("asset:    %s (%s)\n" % (meta.get("name", asset), asset))
        f.write("source:   Poly Haven — https://polyhaven.com/a/%s\n" % asset)
        f.write("licence:  %s\n" % meta.get("license", "CC0"))
        f.write("authors:  %s\n" % ", ".join(meta.get("authors", {})))
        f.write("\nDownloaded by Tools_code/polyhaven.py. CC0: no attribution\n"
                "required, recorded here so the asset's origin is not a\n"
                "mystery six months from now.\n")
    return path
