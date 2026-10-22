"""Hash the scene's geometry so two runs of the same actions can be compared.

The curator is asked to prove a tool by replaying the actions that motivated it
and checking the result is unchanged. That check needs three things: a way to
reach Blender, a way to get numbers back, and a definition of "unchanged". This
file is the third.

Blender's GUI build swallows stdout, so nothing a replay prints ever reaches the
caller. Every function here therefore *writes a file* and the caller reads it
afterwards. That is not a workaround to tidy up later — it is the only channel
out of a dispatched script.

The hash deliberately ignores things a correct refactor is allowed to change:
object creation order, vertex/polygon iteration order, modifier stack names, the
transform used to arrive at a vertex position. It compares where the geometry
ended up, rounded to a tolerance, because a tool that reaches the same shape by
a different route is a tool that works. Face winding, face connectivity, loose
edges, and duplicate vertices remain part of the representation.
"""

import hashlib
import json
import os

# 1e-5 m. Float error accumulates through modifier evaluation, so exact equality
# fails on replays that are genuinely identical; a micrometre is far below any
# tolerance a review check uses.
QUANTUM = 1e-5

# Blender's working directory is its own install folder — "C:\Program Files\
# Blender Foundation\Blender 5.2" — not the harness root, and that folder is not
# writable. A dispatched script that opens "mem/x.json" therefore fails with
# PermissionError rather than writing where the caller is looking. Every path
# through this module is resolved against the harness root instead, so a caller
# can pass the same relative path it would use from the shell.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve(path):
    """Absolute path, interpreting a relative one against the harness root."""
    return path if os.path.isabs(path) else os.path.join(_ROOT, path)


def _q(x):
    """Quantise a coordinate so float noise does not change the hash."""
    return int(round(float(x) / QUANTUM))


def _canonical_cycle(values):
    """Return a polygon cycle independent of its arbitrary starting vertex."""
    values = tuple(values)
    if not values:
        return values
    return min(values[index:] + values[:index]
               for index in range(len(values)))


def object_digest(obj, *, evaluated=True):
    """Hash of one object's evaluated world-space geometry.

    ``evaluated`` hashes the mesh *after* modifiers, which is what a reviewer
    sees and what a tool must preserve. Pass False to hash the base mesh, which
    is what you want when asking whether a refactor changed the modifier stack
    rather than the result.
    """
    import bpy
    if obj.type != 'MESH':
        return {"name": obj.name, "type": obj.type, "hash": None}

    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get()
        src = obj.evaluated_get(dg)
        mesh = src.to_mesh()
    else:
        src, mesh = obj, obj.data

    try:
        mw = obj.matrix_world
        h = hashlib.sha256()
        vertex_tokens = [
            (_q(co.x), _q(co.y), _q(co.z))
            for co in (mw @ vertex.co for vertex in mesh.vertices)
        ]
        # Blender is free to emit the same mesh with a different vertex or
        # polygon iteration order after an operator run.  Those ordering
        # details are not geometry.  Canonicalise by quantised world-space
        # vertex tokens, then keep face winding and connectivity so a real
        # topology/orientation change still changes the digest.  Rotating the
        # starting index of a polygon is also an ordering detail; reversing
        # its winding is intentionally not.
        face_tokens = []
        for poly in mesh.polygons:
            coords = tuple(vertex_tokens[index] for index in poly.vertices)
            face_tokens.append(_canonical_cycle(coords))
        edge_tokens = []
        for edge in mesh.edges:
            a, b = (vertex_tokens[index] for index in edge.vertices)
            edge_tokens.append(tuple(sorted((a, b))))
        payload = (sorted(vertex_tokens), sorted(face_tokens), sorted(edge_tokens))
        h.update(repr(payload).encode("ascii"))
        out = {
            "name": obj.name,
            "type": "MESH",
            "verts": len(mesh.vertices),
            "faces": len(mesh.polygons),
            "hash": h.hexdigest()[:16],
        }
    finally:
        if evaluated:
            src.to_mesh_clear()
    return out


def scene_digest(*, evaluated=True, include_empties=False):
    """Digest of every mesh in the scene, ordered by name so it is stable."""
    import bpy
    objs = [o for o in bpy.context.scene.objects
            if o.type == 'MESH' or (include_empties and o.type == 'EMPTY')]
    per = [object_digest(o, evaluated=evaluated) for o in sorted(objs, key=lambda o: o.name)]
    combined = hashlib.sha256()
    for d in per:
        combined.update((d["name"] + ":" + str(d["hash"])).encode())
    return {
        "objects": per,
        "n_objects": len(per),
        "total_verts": sum(d.get("verts", 0) for d in per),
        "scene_hash": combined.hexdigest()[:16],
        "evaluated": evaluated,
    }


def write_digest(path, *, evaluated=True, note=""):
    """Compute the scene digest and write it to ``path`` as JSON.

    This is the call a replay script ends with. The path must be somewhere the
    caller can read afterwards — under ``mem/`` by convention.
    """
    d = scene_digest(evaluated=evaluated)
    d["note"] = note
    full = resolve(path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    d["written_to"] = full
    return d


def compare(before_path, after_path):
    """Diff two digest files. Read this from the shell, not from Blender.

    Returns a verdict dict whose ``identical`` field is the answer the curator
    needs: True means the refactor preserved the geometry and the tool may be
    committed.
    """
    with open(resolve(before_path), encoding="utf-8") as f:
        a = json.load(f)
    with open(resolve(after_path), encoding="utf-8") as f:
        b = json.load(f)

    ha = {o["name"]: o for o in a["objects"]}
    hb = {o["name"]: o for o in b["objects"]}
    changed = sorted(n for n in set(ha) & set(hb) if ha[n]["hash"] != hb[n]["hash"])
    return {
        "identical": a["scene_hash"] == b["scene_hash"],
        "scene_hash_before": a["scene_hash"],
        "scene_hash_after": b["scene_hash"],
        "only_before": sorted(set(ha) - set(hb)),
        "only_after": sorted(set(hb) - set(ha)),
        "changed": changed,
        "vert_delta": b["total_verts"] - a["total_verts"],
    }
