"""Trajectory -> skills, after each training task (Voyager / SkillWeaver style).

    python compaction.py --run 02_iron_gate_run_001

Reads the finished run -- every piece of code the agent ran in Blender with its
result, the agent's own remarks, its finish summary, and renders of the saved
scene -- and asks the same model as the agent to distil what WORKED into
reusable skills. A skill is both:

  * code: a Python module of parameterised, documented functions (bpy/bmesh/
    mathutils), importable in Blender as `import <name>`;
  * prose: a short doc (what it does, when to use it, how to call it, pitfalls
    the trajectory ran into).

The compactor sees the library's index and the full text of every skill this
run retrieved, loaded or referenced, so it can improve an existing skill
(`replaces`) instead of writing a near-duplicate. Every skill is checked before
it is stored: the code must parse, define at least one public function, have
no top-level side effects, and import cleanly in a headless Blender. Failures
go back to the model once with the errors; what still fails is dropped and
logged.

Nothing here judges the finished MODEL: there is no checker and no defect
attribution. The only evidence is the agent's own trajectory.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import tempfile
from pathlib import Path

import b2_config as CFG
import library as L
import llm

DIGEST_CAP = 450_000      # chars of trajectory text shown to the compactor

SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "skills": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "when_to_use": {"type": "string"},
                "doc": {"type": "string"},
                "code": {"type": "string"},
                "replaces": {"type": "string"},
            },
            "required": ["name", "description", "when_to_use", "doc", "code", "replaces"],
            "additionalProperties": False}},
    },
    "required": ["analysis", "skills"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You maintain a library of reusable Blender skills for an agent that builds 3D
scenes from a brief and reference images by writing bpy code. The agent has just finished the
task below. Your job is to distil its trajectory into skills that will make FUTURE, DIFFERENT
tasks faster and better -- the library is the only thing the agent carries from task to task.

What a skill is:
- `code`: one self-contained Python module (it will be saved as `<name>.py` and imported inside
  Blender with `import <name>`). Parameterised functions with docstrings (arguments, units,
  return value). Imports at the top (bpy, bmesh, mathutils, math, numpy, etc. are available in
  Blender). NO top-level side effects: only imports, constants, function and class definitions.
  Operators that need a 3D-view context must build the override themselves (the agent's code runs
  from a timer with no active area).
- `doc`: markdown -- what it does, when to use it, a short usage example, and the pitfalls the
  trajectory actually hit (errors, retries, things that looked right but were not).
- `name`: snake_case module name, 3-60 chars, starting with a letter.
- `description`: one sentence. `when_to_use`: one sentence naming the kinds of objects/tasks.
- `replaces`: the name of an existing library skill this one supersedes (an improved or
  generalised version; keep its useful functions working), or "" for a new skill.

How to choose:
- Base skills on code that WORKED in the trajectory (ran without error and contributed to the
  final scene), generalised: replace task-specific numbers with parameters, keep the proven
  technique. Fold the fixes from retries into the code so the next task does not repeat them.
- Prefer procedures that transfer across objects (a modelling technique, a material setup, a
  rig/animation/simulation recipe, a reference-image measurement routine, a render/camera/
  scene-finishing routine, a verification routine) over one-off object builders. A builder for a
  whole object is worth keeping only when it is parameterised enough to be reused.
- Write between 1 and 5 skills. Do not duplicate: if a library skill covers the same ground,
  improve it via `replaces` instead of adding a sibling.
- If the trajectory has nothing worth keeping, return an empty list and say why in `analysis`.
"""


def _action_pairs(run_dir: Path) -> list[dict]:
    acts = sorted((run_dir / "actions").glob("*_blender.py")) + sorted((run_dir / "actions").glob("*_host.py"))
    out = []
    for p in sorted(acts):
        res = p.with_name(p.stem + ".out.txt")
        code = p.read_text(encoding="utf-8", errors="replace")
        first = code.splitlines()[0] if code else ""
        out.append({"n": int(p.name[:4]), "kind": "blender" if "_blender" in p.name else "host",
                    "ok": "ok=True" in first, "code": code,
                    "result": res.read_text(encoding="utf-8", errors="replace") if res.is_file() else ""})
    return out


def trajectory_digest(run_dir: Path) -> str:
    """Chronological text: the agent's remarks and each action with its outcome."""
    remarks: list[tuple[float, str]] = []
    for line in (run_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "model":
            t = "\n".join(x for x in (e.get("reasoning_summary"), e.get("text")) if x)
            if t.strip():
                remarks.append((e["t"], t.strip()))
        elif e.get("type") == "review":
            remarks.append((e["t"], "REVIEWER'S CRITIQUE (the builder then had one more pass):\n"
                            + (e.get("review") or "")))
    acts = _action_pairs(run_dir)
    blocks = []
    for a in acts:
        code = a["code"]
        res = a["result"]
        if not a["ok"]:
            code = code if len(code) < 2500 else code[:1500] + "\n# ...[cut]...\n" + code[-600:]
            res = res[-1200:]
        else:
            res = res[:600] + ("..." if len(res) > 600 else "")
        blocks.append(f"### action {a['n']} ({a['kind']}, {'OK' if a['ok'] else 'FAILED'})\n"
                      f"```python\n{code}\n```\nresult:\n```\n{res}\n```")
    rem = [f"[agent @ {t / 60:.1f} min] {txt[:1500]}" for t, txt in remarks]
    text = "## Agent remarks (chronological)\n\n" + "\n\n".join(rem) + \
           "\n\n## Actions (chronological)\n\n" + "\n\n".join(blocks)
    # shrink until it fits: first failed actions' code, then the oldest successful code
    if len(text) > DIGEST_CAP:
        for i, a in enumerate(acts):
            if len("\n".join(blocks)) + sum(map(len, rem)) < DIGEST_CAP:
                break
            if not a["ok"]:
                blocks[i] = f"### action {a['n']} ({a['kind']}, FAILED)\nerror tail:\n```\n{a['result'][-500:]}\n```"
        i = 0
        while len("\n".join(blocks)) + sum(map(len, rem)) > DIGEST_CAP and i < len(blocks):
            if acts[i]["ok"]:
                c = acts[i]["code"]
                blocks[i] = (f"### action {acts[i]['n']} ({acts[i]['kind']}, OK) [code shortened]\n"
                             f"```python\n{c[:600]}\n# ...\n```")
            i += 1
        text = "## Agent remarks (chronological)\n\n" + "\n\n".join(rem) + \
               "\n\n## Actions (chronological)\n\n" + "\n\n".join(blocks)
    return text[:DIGEST_CAP + 50_000]


ALLOWED_TOP = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign,
               ast.AnnAssign, ast.If, ast.Try)


def static_check(s: dict) -> tuple[list[str], list[str]]:
    """Returns (errors, public function names)."""
    errs = []
    if not L.NAME_RE.match(s["name"] or ""):
        errs.append(f"bad name {s['name']!r}")
    try:
        tree = ast.parse(s["code"])
    except SyntaxError as e:
        return errs + [f"SyntaxError: {e}"], []
    fns = []
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
                and isinstance(node.value.value, str):
            continue  # docstring
        if not isinstance(node, ALLOWED_TOP):
            errs.append(f"top-level statement at line {node.lineno} ({type(node).__name__}) is a side effect")
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            fns.append(node.name)
    if not fns:
        errs.append("no public function defined")
    return errs, fns


def blender_import_check(skills: list[dict]) -> dict[str, str]:
    """Import every module in a headless Blender. Returns {name: error} for failures."""
    if not skills:
        return {}
    with tempfile.TemporaryDirectory(dir=str(CFG.STATE)) as td:
        td = Path(td)
        for s in skills:
            (td / f"{s['name']}.py").write_text(s["code"], encoding="utf-8")
        # existing library first so a skill may import another skill
        report = td / "report.json"
        script = td / "_check.py"
        script.write_text(
            "import sys, json, importlib, traceback\nsys.dont_write_bytecode = True\n"
            f"sys.path.insert(0, {str(CFG.SKILLS)!r}); sys.path.insert(0, {str(td)!r})\n"
            f"names = {[s['name'] for s in skills]!r}\nres = {{}}\n"
            "for n in names:\n"
            "    try:\n        importlib.import_module(n); res[n] = None\n"
            "    except BaseException:\n        res[n] = traceback.format_exc()[-1500:]\n"
            f"open({str(report)!r}, 'w').write(json.dumps(res))\n", encoding="utf-8")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        subprocess.run([CFG.BLENDER, "-b", "--factory-startup", "--python", str(script)],
                       capture_output=True, timeout=600, env=env)
        try:
            res = json.loads(report.read_text())
        except (OSError, json.JSONDecodeError):
            return {s["name"]: "import check did not run" for s in skills}
    return {k: v for k, v in res.items() if v}


def compact(run: str, log=print) -> dict:
    run_dir = CFG.RUNS / run
    usage_j = json.loads((run_dir / "usage.json").read_text(encoding="utf-8"))
    task = usage_j["task"]
    task_dir = next(p for p in CFG.TASKS.glob(f"*/{task}") if p.is_dir())
    task_text = (task_dir / "task.md").read_text(encoding="utf-8")
    index = L.read_index()
    used = sorted(set(usage_j["skills"]["retrieved"]) | set(usage_j["skills"]["loaded_on_demand"])
                  | set(usage_j["skills"]["referenced_in_code"]))
    used_text = "\n\n".join(t for t in (L.skill_text(n) for n in used if n in index) if t)
    digest = trajectory_digest(run_dir)

    head = (f"{INSTRUCTIONS}\n\n# The task: {task}\n\n{task_text}\n\n"
            f"# How the run ended\n\nend: {usage_j['end_reason']}; saved .blend: "
            f"{usage_j['produced_blend']}; {usage_j['blender_actions']} Blender actions in "
            f"{usage_j['wall_clock_min']} min.\nAgent's finish summary: {usage_j.get('finish_summary')}\n\n"
            f"# Current library index\n\n{L.index_listing(index)}\n\n"
            f"# Library skills this run used (full text)\n\n{used_text or '(none)'}\n\n"
            f"# Trajectory\n\n{digest}\n\n"
            "# Images\nFirst the task's reference, then renders of the scene the agent saved.")
    content = [{"type": "input_text", "text": head}]
    refs = sorted(p for p in task_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if refs:
        content.append(llm.image_part(refs[0], max_side=1024))
    bdir = CFG.BLENDS / run
    for name in ("render_plan_camera.png", "render_three_quarter.png", "views/front_solid.png"):
        p = bdir / name
        if p.is_file():
            content += [{"type": "input_text", "text": f"render: {name}"}, llm.image_part(p, max_side=1024)]

    usage = llm.Usage()
    msgs = [{"role": "user", "content": content}]
    fmt = {"format": {"type": "json_schema", "name": "skills", "schema": SCHEMA, "strict": True}}
    accepted, rejected, analysis = [], [], ""
    pending: list[dict] = []
    for round_ in range(2):
        r, dt = llm.create(input=msgs, text=fmt, log=log)
        usage.add(r.usage, dt)
        data = json.loads(r.output_text)
        analysis = analysis or data.get("analysis", "")
        cands = data.get("skills", [])
        problems = {}
        good = []
        for s in cands:
            s["name"] = (s.get("name") or "").strip()
            errs, fns = static_check(s)
            if errs:
                problems[s["name"]] = "; ".join(errs)
            else:
                s["functions"] = fns
                good.append(s)
        problems.update(blender_import_check(good))
        accepted += [s for s in good if s["name"] not in problems]
        pending = [s for s in cands if s["name"] in problems]
        if not pending:
            break
        if round_ == 0:
            msgs += [{"role": "assistant", "content": [{"type": "output_text", "text": r.output_text}]},
                     {"role": "user", "content": [{"type": "input_text", "text":
                      "These skills failed validation. Return ONLY corrected versions of them "
                      "(same schema; the accepted ones are already stored):\n\n" +
                      "\n\n".join(f"- {n}: {e}" for n, e in problems.items())}]}]
        else:
            rejected = [{"name": s["name"], "error": problems[s["name"]]} for s in pending]

    written = []
    accepted = list({s["name"]: s for s in accepted}.values())
    for s in accepted:
        repl = (s.get("replaces") or "").strip() or None
        if repl and repl not in index:
            repl = None
        kind = L.put_skill(s["name"], code=s["code"], doc=s["doc"], description=s["description"],
                           when_to_use=s["when_to_use"], functions=s["functions"], task=task, run=run,
                           replaces=repl)
        L.log(kind, task=task, run=run, skill=s["name"], replaces=repl, functions=s["functions"])
        written.append({"name": s["name"], "kind": kind, "replaces": repl, "functions": s["functions"]})
    for s in rejected:
        L.log("rejected", task=task, run=run, skill=s["name"], error=s["error"][:500])
    result = {"run": run, "task": task, "analysis": analysis, "written": written,
              "rejected": rejected, "library_size_after": len(L.read_index()),
              "usage": usage.as_dict(), "at": L.now()}
    (run_dir / "compaction.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log(f"[compaction] {run}: {len(written)} skill(s) written "
        f"({', '.join(w['kind'] + ':' + w['name'] for w in written)}), {len(rejected)} rejected, "
        f"${usage.cost:.3f}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    compact(a.run)


if __name__ == "__main__":
    main()
