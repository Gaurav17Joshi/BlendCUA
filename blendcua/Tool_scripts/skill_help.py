#!/usr/bin/env python3
"""Print a skill, so the prompt only has to carry its one-line trigger.

    python Tool_scripts/skill_help.py measure-or-eyeball
    python Tool_scripts/skill_help.py --role Executor        # everything for one role
    python Tool_scripts/skill_help.py --search coordinate    # find it by what it covers
    python Tool_scripts/skill_help.py --list                 # every skill, by role

The same split of labour as `tool_help.py`: the prompt carries names and
triggers, the full text is one `bash` call away and costs nothing when unused.
Skills are read from `Skills/<Role>/*.md`, each with `name` and `description`
in its frontmatter.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Skill text is full of arrows and em-dashes and this gets run from a Windows
# console defaulting to cp1252 — same reason tool_help.py does this.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

SKILLS_DIR = Path(__file__).resolve().parent.parent / "Skills"


def frontmatter(text: str) -> dict:
    """The `key: value` block between the first two `---` lines."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def all_skills() -> list[dict]:
    out = []
    for role_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        # a skill may sit in a subfolder of its role (Skills/Planner/Gpt_images/...); only
        # files with a frontmatter name count, so a README beside evidence files is not a skill
        for f in sorted(role_dir.rglob("*.md")):
            text = f.read_text(encoding="utf-8", errors="replace")
            fm = frontmatter(text)
            if f.parent != role_dir and not fm.get("name"):
                continue
            out.append({
                "role": role_dir.name,
                "name": fm.get("name", f.stem),
                "description": fm.get("description", ""),
                "path": f,
                "text": text,
            })
    return out


def index_block(*roles: str) -> str:
    """The compact block that goes in a prompt. Names and triggers only."""
    skills = all_skills()
    if roles:
        wanted = {r.lower() for r in roles}
        skills = [s for s in skills if s["role"].lower() in wanted]
    if not skills:
        return "(no skills)"
    lines = []
    for role in dict.fromkeys(s["role"] for s in skills):
        lines.append(f"\n**{role}**")
        for s in (x for x in skills if x["role"] == role):
            lines.append(f"- `{s['name']}` — {s['description']}")
    return "\n".join(lines).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Print a skill in full.")
    ap.add_argument("name", nargs="?", help="skill name, e.g. measure-or-eyeball")
    ap.add_argument("--role", help="print every skill for one role")
    ap.add_argument("--search", help="find skills whose name or description matches")
    ap.add_argument("--list", action="store_true", help="list every skill")
    ap.add_argument("--index", nargs="*", metavar="ROLE",
                    help="print the prompt index block for these roles")
    args = ap.parse_args()

    skills = all_skills()
    if not skills:
        print(f"no skills under {SKILLS_DIR}", file=sys.stderr)
        raise SystemExit(1)

    if args.index is not None:
        print(index_block(*args.index))
        return

    if args.list:
        for role in dict.fromkeys(s["role"] for s in skills):
            print(f"\n{role}")
            for s in (x for x in skills if x["role"] == role):
                print(f"  {s['name']:34s} {s['description']}")
        return

    if args.role:
        hits = [s for s in skills if s["role"].lower() == args.role.lower()]
        if not hits:
            print(f"no role {args.role!r}. roles: "
                  f"{', '.join(dict.fromkeys(s['role'] for s in skills))}", file=sys.stderr)
            raise SystemExit(1)
        for s in hits:
            print(f"\n{'=' * 72}\n{s['role']}/{s['name']}\n{'=' * 72}\n")
            print(s["text"].strip())
        return

    if args.search:
        q = args.search.lower()
        hits = [s for s in skills if q in s["name"].lower() or q in s["description"].lower()
                or q in s["text"].lower()]
        if not hits:
            print(f"nothing matches {args.search!r}")
            return
        for s in hits:
            print(f"  {s['role']}/{s['name']:32s} {s['description']}")
        return

    if not args.name:
        ap.print_help()
        return

    hits = [s for s in skills if s["name"].lower() == args.name.lower()]
    if not hits:
        hits = [s for s in skills if args.name.lower() in s["name"].lower()]
    if not hits:
        print(f"no skill called {args.name!r}. Try --list or --search.", file=sys.stderr)
        raise SystemExit(1)
    for s in hits:
        print(f"{'=' * 72}\n{s['role']}/{s['name']}\n{'=' * 72}\n")
        print(s["text"].strip())


if __name__ == "__main__":
    main()
