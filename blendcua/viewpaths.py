"""Junction-tolerant relative paths for worker views.

A worker view (harness/wK) reaches the shared data folders (mem, plans, blends, ...) through
directory junctions. `Path.resolve()` expands a junction to the real folder, so a resolved path
under the view's `plans/` is really `<main>/plans/...` and `relative_to(<view>)` raises.
`rel_to(p, base)` gives the same repo-relative path whether `p` is spelled through the view or
through the real folder, because the data folders have the same names in both.
"""
from __future__ import annotations

from pathlib import Path, PurePath


def main_dir(base: Path) -> Path:
    """The real project folder for a view (harness/wK -> the folder holding harness/)."""
    base = Path(base)
    if base.parent.name == "harness" and (base.parent.parent / "harness").is_dir():
        return base.parent.parent
    return base


def rel_to(p, base) -> Path:
    """`Path(p).relative_to(base)`, tolerant of junctions and of an already resolved `p`."""
    p = Path(p)
    base = Path(base)
    candidates = [base]
    try:
        rb = base.resolve()
        if rb != base:
            candidates.append(rb)
    except OSError:
        pass
    md = main_dir(base)
    if md != base:
        candidates.append(md)
        try:
            candidates.append(md.resolve())
        except OSError:
            pass
    for b in candidates:
        try:
            return p.relative_to(b)
        except ValueError:
            continue
    try:
        rp = p.resolve()
    except OSError:
        rp = p
    for b in candidates:
        try:
            return rp.relative_to(b)
        except ValueError:
            continue
    raise ValueError(f"{p} is not under {base} (nor its real folder)")
