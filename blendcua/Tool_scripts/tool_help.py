#!/usr/bin/env python3
"""Print a tool's full docstring, so the prompt never has to carry it.

    python Tool_scripts/tool_help.py apply_chain
    python Tool_scripts/tool_help.py handle.apply_chain     # if the name is ambiguous
    python Tool_scripts/tool_help.py --module handle        # everything in one module
    python Tool_scripts/tool_help.py --search silhouette    # find it by what it does

Reads `Tools_code/` with `ast`, so it works from anywhere and never imports
Blender. Costs one `bash` call and nothing when unused — which is why the
docstrings can be as long as they need to be.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# The docstrings are full of em-dashes and arrows, and this gets run from a
# Windows console defaulting to cp1252 — without this every one of them comes
# back as a replacement char, which is exactly the kind of noise that makes an
# agent distrust a tool and stop using it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CODE_DIR = Path(__file__).resolve().parent / "Tools_code"
SKIP_DIRS = ("_vendor", "__pycache__")


def modname(path: Path) -> str:
    return ".".join(path.relative_to(CODE_DIR).with_suffix("").parts)


def walk():
    for path in sorted(CODE_DIR.rglob("*.py")):
        if any(d in path.parts for d in SKIP_DIRS) or path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        yield modname(path), path, tree


def signature(fn: ast.FunctionDef) -> str:
    a = fn.args
    parts: list[str] = []
    defaults = [None] * (len(a.args) - len(a.defaults)) + list(a.defaults)
    for arg, dflt in zip(a.args, defaults):
        parts.append(arg.arg if dflt is None
                     else f"{arg.arg}={ast.unparse(dflt)}")
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    if a.kwonlyargs and not a.vararg:
        parts.append("*")
    for arg, dflt in zip(a.kwonlyargs, a.kw_defaults):
        parts.append(arg.arg if dflt is None
                     else f"{arg.arg}={ast.unparse(dflt)}")
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    return f"{fn.name}({', '.join(parts)})"


def show(mod: str, path: Path, fn: ast.FunctionDef) -> None:
    print("=" * 72)
    print(f"{mod}.{signature(fn)}")
    print(f"{path.as_posix()}:{fn.lineno}")
    print("=" * 72)
    doc = ast.get_docstring(fn)
    print(doc.strip() if doc
          else "(no docstring — read the source at the line above)")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", help="function name, or module.function")
    ap.add_argument("--module", "-m", help="print every public function in a module")
    ap.add_argument("--search", "-s", help="substring match against name + docstring")
    args = ap.parse_args()

    if not (args.name or args.module or args.search):
        ap.print_help()
        return 2

    hits = 0

    if args.module:
        want = args.module.replace("/", ".").removesuffix(".py")
        for mod, path, tree in walk():
            if mod != want:
                continue
            for n in tree.body:
                if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
                    show(mod, path, n)
                    hits += 1
        if not hits:
            print(f"no module '{want}'. Modules: "
                  + ", ".join(m for m, _, _ in walk()), file=sys.stderr)
            return 1
        return 0

    if args.search:
        needle = args.search.lower()
        found = []
        for mod, path, tree in walk():
            for n in tree.body:
                if not isinstance(n, ast.FunctionDef) or n.name.startswith("_"):
                    continue
                doc = ast.get_docstring(n) or ""
                if needle in n.name.lower() or needle in doc.lower():
                    line = doc.strip().split("\n")[0] if doc else "(undocumented)"
                    found.append((f"{mod}.{n.name}", line))
        width = max((len(q) for q, _ in found), default=0)
        for qual, line in found:
            print(f"{qual:<{width}}  {line}")
        hits = len(found)
        if found:
            print(f"\n{hits} match(es). Full docstring: "
                  f"python Tool_scripts/tool_help.py <name>")
        if not hits:
            print(f"nothing matches '{args.search}'", file=sys.stderr)
            return 1
        return 0

    # Bare name, or module.function
    want_mod, _, want_fn = args.name.rpartition(".")
    for mod, path, tree in walk():
        if want_mod and mod != want_mod:
            continue
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.name == want_fn:
                show(mod, path, n)
                hits += 1
    if not hits:
        print(f"no tool named '{args.name}'. Try: "
              f"python Tool_scripts/tool_help.py --search {want_fn}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
