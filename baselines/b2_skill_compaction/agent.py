"""B2's per-task agent: one conversation, one Blender, until finish or budget.

    python agent.py --task-dir tasks/train/02_iron_gate --run-dir runs/02_iron_gate_run_001 --worker 0

What it does, in order:
  1. copies the skill library into <run>/skills (importable in Blender) and
     retrieves the relevant skills (retrieval.py) -- unless the library is empty;
  2. starts a fresh GUI Blender for this worker;
  3. runs the conversation: brief + reference images + skills in, tool calls out;
  4. saves the live scene as <run>/final.blend (images packed);
  5. writes usage.json and status.json.

Everything the model says and every tool call and result goes to
<run>/trajectory.jsonl; every piece of code it runs is kept under <run>/actions/.
One review round (added at the user's request, beyond the original brief): the
builder's first `finish` hands the live scene to a reviewer agent -- same model,
same Blender, able to inspect, render and screenshot it -- whose critique goes
back to the builder, which gets one more pass; its second `finish` is final.
Nothing here plans or runs a checker, defect attribution or rebuild loop.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import b2_config as CFG
import library as L
import llm
import retrieval
from blender_link import BlenderDown, BlenderLink, BlenderTimeout

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
OUT_CAP = 12_000          # chars of tool output returned to the model per call


def jdump(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=str)


# ── tools offered to the model ───────────────────────────────────────────────

def _fn(name, desc, props, required):
    return {"type": "function", "name": name, "description": desc, "strict": False,
            "parameters": {"type": "object", "properties": props, "required": required,
                           "additionalProperties": False}}


TOOLS = [
    _fn("run_python", "Execute Python code inside the live Blender session (bpy). Returns "
        "printed output and any traceback. Namespace persists between calls.",
        {"code": {"type": "string"},
         "timeout_s": {"type": "integer", "description": "seconds, default 600, max 2400"}},
        ["code"]),
    _fn("screenshot", "Capture the Blender GUI's 3D viewport and show it to you.", {}, []),
    _fn("view_image", "Show you an image file (absolute path).",
        {"path": {"type": "string"}}, ["path"]),
    _fn("host_python", "Run Python 3.12 on the host (numpy, scipy, Pillow), cwd = work folder. "
        "Returns stdout/stderr.",
        {"code": {"type": "string"},
         "timeout_s": {"type": "integer", "description": "seconds, default 300, max 1800"}},
        ["code"]),
    _fn("generate_image", "Generate or edit an image with gpt-image-2 and save it as PNG.",
        {"prompt": {"type": "string"},
         "output_path": {"type": "string", "description": "absolute .png path in the work folder"},
         "input_images": {"type": "array", "items": {"type": "string"},
                          "description": "absolute paths of images to edit/derive from"},
         "size": {"type": "string", "enum": ["1024x1024", "1536x1024", "1024x1536", "auto"]},
         "background": {"type": "string", "enum": ["auto", "opaque", "transparent"]},
         "quality": {"type": "string", "enum": ["low", "medium", "high", "auto"]}},
        ["prompt", "output_path"]),
    _fn("load_skill", "Show the full doc and code of a skill in your library.",
        {"name": {"type": "string"}}, ["name"]),
    _fn("finish", "Call when the scene is complete. The live scene is then saved as the deliverable.",
        {"summary": {"type": "string"}}, ["summary"]),
]
if CFG.NO_LIBRARY:      # the ablation has no library, so no way to load from one
    TOOLS = [t for t in TOOLS if t["name"] != "load_skill"]


class Agent:
    def __init__(self, task_dir: Path, run_dir: Path, worker: int, freeze: bool):
        self.task_dir = task_dir.resolve()
        self.task = self.task_dir.name
        self.run_dir = run_dir.resolve()
        self.run = self.run_dir.name
        self.worker = worker
        self.freeze = freeze
        self.work = self.run_dir / "work"
        self.actions = self.run_dir / "actions"
        self.skills_dir = self.run_dir / "skills"
        for d in (self.work, self.actions):
            d.mkdir(parents=True, exist_ok=True)
        self.traj = open(self.run_dir / "trajectory.jsonl", "a", encoding="utf-8")
        self.console = open(self.run_dir / "console.log", "a", encoding="utf-8", errors="replace")
        self.usage = llm.Usage()          # the agent conversation
        self.aux_usage = llm.Usage()      # retrieval
        self.t0 = time.time()
        self.n_action = 0
        self.tool_counts: dict[str, int] = {}
        self.blender_codes: list[str] = []
        self.restarts = 0
        self.image_gens = 0
        self.image_usage = {"input_tokens": 0, "output_tokens": 0}
        self.last_ckpt = time.time()
        self.ckpt = self.run_dir / "checkpoint.blend"
        self.ckpt_action = 0
        self.loaded_skills: list[str] = []
        self.warned_soft = False
        self.link = BlenderLink(worker, self.run_dir)
        self.finish_summary = None
        self.end_reason = None
        self.role = "build"               # "review" while the reviewer is using the tools
        self.review_usage = llm.Usage()
        self.review_done = False
        self.review_text = None
        self.first_finish_summary = None
        self.review_calls = 0

    # ── logging ──────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        self.console.write(line + "\n")
        self.console.flush()

    def event(self, kind: str, **data) -> None:
        self.traj.write(jdump({"t": round(time.time() - self.t0, 2), "type": kind, **data}) + "\n")
        self.traj.flush()

    def minutes(self) -> float:
        return (time.time() - self.t0) / 60

    def total_cost(self) -> float:
        return self.usage.cost + self.aux_usage.cost + self.review_usage.cost

    # ── setup ────────────────────────────────────────────────────────────
    def reference_images(self) -> list[Path]:
        top = sorted(p for p in self.task_dir.iterdir() if p.suffix.lower() in IMG_EXT)
        sub = self.task_dir / "reference"
        more = sorted(p for p in sub.iterdir() if p.suffix.lower() in IMG_EXT) if sub.is_dir() else []
        return top + more

    def build_prompt(self) -> tuple[str, list]:
        task_text = (self.task_dir / "task.md").read_text(encoding="utf-8")
        index = {} if CFG.NO_LIBRARY else L.copy_library(self.skills_dir)
        refs = self.reference_images()
        L.log("task_start", task=self.task, run=self.run, library_size=len(index),
              frozen=self.freeze, no_library=CFG.NO_LIBRARY)
        picked, reason = [], "no library (ablation)" if CFG.NO_LIBRARY else "library empty"
        if index:
            picked, reason = retrieval.select(self.task, task_text, refs[0] if refs else None,
                                              index, usage=self.aux_usage, log=self.log)
        for n in picked:
            L.log("retrieve", task=self.task, run=self.run, skill=n)
        self.log(f"library {len(index)} skills; retrieved {picked} ({reason[:200]})")
        self.library_size = len(index)
        self.retrieved = picked
        self.library_names = sorted(index)
        self.event("retrieval", library_size=len(index), selected=picked, reason=reason)

        tmpl = (CFG.ROOT / "prompts" / "system.md").read_text(encoding="utf-8")
        system = tmpl.format(
            blender_version=self.blender_version, default_timeout=CFG.DEFAULT_EXEC_TIMEOUT_S,
            max_timeout=CFG.MAX_EXEC_TIMEOUT_S, **L.prompt_blocks(index, picked),
            task_dir=str(self.task_dir), work_dir=str(self.work), typical_min=60,
            soft_cost=CFG.SOFT_COST_USD, soft_wall=CFG.SOFT_WALL_MIN,
            hard_cost=CFG.HARD_COST_USD, hard_wall=CFG.HARD_WALL_MIN)

        text = [f"# Task: {self.task}\n\n{task_text.strip()}\n",
                "Reference images (shown below, in this order):\n" +
                "\n".join(f"- {p}" for p in refs)]
        extra = [p for p in self.task_dir.iterdir() if p.is_file() and p.suffix.lower() not in IMG_EXT
                 and p.name != "task.md"]
        if extra:
            text.append("Other task files: " + ", ".join(str(p) for p in extra))
        for n in picked:
            t = L.skill_text(n, self.skills_dir)
            if t:
                text.append(t)
        content = [{"type": "input_text", "text": "\n\n".join(text)}]
        for p in refs:
            content.append({"type": "input_text", "text": f"Image: {p.name}"})
            content.append(llm.image_part(p))
        return system, [{"role": "user", "content": content}]

    # ── Blender plumbing ─────────────────────────────────────────────────
    def blender_setup(self) -> None:
        # No skills folder in the no-library ablation, so nothing to import from.
        path_line = ("" if CFG.NO_LIBRARY else
                     f"p = {str(self.skills_dir)!r}\n"
                     "sys.path.insert(0, p) if p not in sys.path else None\n")
        code = (f"import sys, os\n{path_line}"
                f"os.chdir({str(self.work)!r})\n"
                "import bpy\nprint(bpy.app.version_string)")
        r = self.link.run_python(code, timeout=60)
        self.blender_version = (r.get("output") or "").strip() or "5.2"

    def restart_blender(self, why: str) -> str:
        self.restarts += 1
        self.log(f"restarting Blender ({why})")
        L_ok = self.ckpt.is_file()
        self.link.start(open_blend=self.ckpt if L_ok else None)
        self.blender_setup()
        self.event("blender_restart", why=why, from_checkpoint=L_ok, checkpoint_action=self.ckpt_action)
        if L_ok:
            return (f"Blender was restarted ({why}). The scene was restored from the checkpoint "
                    f"saved after action {self.ckpt_action}; work after that is lost and the "
                    "Python namespace was reset.")
        return (f"Blender was restarted ({why}) with an empty default scene (no checkpoint yet); "
                "the Python namespace was reset.")

    def maybe_checkpoint(self) -> None:
        if time.time() - self.last_ckpt < CFG.CHECKPOINT_EVERY_S:
            return
        try:
            r = self.link.save(self.ckpt, copy=True, timeout=600)
            if r.get("ok"):
                self.ckpt_action = self.n_action
                self.event("checkpoint", action=self.n_action)
        except (BlenderTimeout, BlenderDown) as e:
            self.log(f"checkpoint failed: {e}")
        self.last_ckpt = time.time()

    # ── tools ────────────────────────────────────────────────────────────
    def save_action(self, kind: str, code: str, result: dict) -> Path:
        self.n_action += 1
        p = self.actions / f"{self.n_action:04d}_{kind}.py"
        header = (f"# action {self.n_action} ({kind}) at {self.minutes():.1f} min; "
                  f"ok={result.get('ok')} elapsed={result.get('elapsed_s')}s\n")
        p.write_text(header + code, encoding="utf-8")
        out = (result.get("output") or "") + (("\n" + result["error"]) if result.get("error") else "")
        (self.actions / f"{self.n_action:04d}_{kind}.out.txt").write_text(out, encoding="utf-8")
        return p

    @staticmethod
    def clip(text: str, cap: int = OUT_CAP) -> str:
        if len(text) <= cap:
            return text
        return text[: cap // 2] + f"\n...[{len(text) - cap} chars cut]...\n" + text[-cap // 2:]

    def tool_run_python(self, code: str, timeout_s=None) -> tuple[str, list]:
        timeout = min(int(timeout_s or CFG.DEFAULT_EXEC_TIMEOUT_S), CFG.MAX_EXEC_TIMEOUT_S)
        note = ""
        try:
            r = self.link.run_python(code, timeout=timeout)
        except BlenderTimeout:
            r = {"ok": False, "output": "", "error": f"TIMEOUT: no result after {timeout}s",
                 "elapsed_s": timeout}
            note = self.restart_blender(f"a run_python call exceeded {timeout}s")
        except BlenderDown as e:
            r = {"ok": False, "output": "", "error": f"Blender crashed or became unreachable: {e}",
                 "elapsed_s": None}
            note = self.restart_blender("Blender crashed")
        self.save_action("blender" if self.role == "build" else "review", code, r)
        if self.role == "build":
            self.blender_codes.append(code)
        if r.get("ok"):
            self.maybe_checkpoint()
        text = f"ok={r.get('ok')} elapsed={r.get('elapsed_s')}s\n"
        if r.get("output"):
            text += "--- output ---\n" + r["output"]
        if r.get("error"):
            text += "\n--- error ---\n" + r["error"]
        if note:
            text += "\n--- harness ---\n" + note
        return self.clip(text), []

    def tool_screenshot(self) -> tuple[str, list]:
        p = self.work / "screens" / f"viewport_{self.n_action:04d}_{int(time.time())}.png"
        p.parent.mkdir(exist_ok=True)
        try:
            r = self.link.screenshot(p)
        except (BlenderTimeout, BlenderDown) as e:
            return f"screenshot failed: {e}\n" + self.restart_blender("screenshot hung"), []
        if not r.get("ok") or not p.is_file():
            return f"screenshot failed: {r.get('error')}", []
        return f"viewport screenshot saved to {p}", [p]

    def tool_view_image(self, path: str) -> tuple[str, list]:
        p = Path(path)
        if not p.is_file():
            return f"no such file: {path}", []
        return f"showing {p}", [p]

    def tool_host_python(self, code: str, timeout_s=None) -> tuple[str, list]:
        timeout = min(int(timeout_s or 300), 1800)
        script = self.actions / f"{self.n_action + 1:04d}_host.py"
        script.write_text(code, encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        t = time.time()
        try:
            p = subprocess.run([CFG.PY, str(script)], cwd=str(self.work), capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
            ok, out, err = p.returncode == 0, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            ok, out, err = False, (e.stdout or "") if isinstance(e.stdout, str) else "", f"TIMEOUT after {timeout}s"
        r = {"ok": ok, "output": out, "error": err or None, "elapsed_s": round(time.time() - t, 1)}
        self.save_action("host", code, r)
        text = f"ok={ok} elapsed={r['elapsed_s']}s\n" + (out or "")
        if err:
            text += "\n--- stderr ---\n" + err
        return self.clip(text), []

    def tool_generate_image(self, prompt: str, output_path: str, input_images=None, size="auto",
                            background="auto", quality="high") -> tuple[str, list]:
        import base64
        out = Path(output_path)
        if not out.is_absolute():
            out = self.work / out
        out.parent.mkdir(parents=True, exist_ok=True)
        kw = dict(model=CFG.IMAGE_MODEL, prompt=prompt, size=size or "auto",
                  quality=quality or "high", background=background or "auto")
        t = time.time()
        files = []
        try:
            if input_images:
                files = [open(p, "rb") for p in input_images]
                r = llm.image_client().images.edit(image=files, **kw)
            else:
                r = llm.image_client().images.generate(**kw)
        except Exception as e:  # noqa: BLE001
            return f"generate_image failed: {type(e).__name__}: {str(e)[:800]}", []
        finally:
            for f in files:
                f.close()
        out.write_bytes(base64.b64decode(r.data[0].b64_json))
        self.image_gens += 1
        u = getattr(r, "usage", None)
        if u:
            self.image_usage["input_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
            self.image_usage["output_tokens"] += int(getattr(u, "output_tokens", 0) or 0)
        self.event("image_generated", path=str(out), prompt=prompt, inputs=input_images,
                   seconds=round(time.time() - t, 1))
        return f"saved {out} ({time.time() - t:.0f}s)", [out]

    def tool_load_skill(self, name: str) -> tuple[str, list]:
        t = L.skill_text(name, self.skills_dir)
        if t is None:
            return f"no skill named {name!r}. Available: {', '.join(self.library_names) or 'none'}", []
        if name not in self.loaded_skills:
            self.loaded_skills.append(name)
            L.log("load_on_demand", task=self.task, run=self.run, skill=name)
        return t, []

    def dispatch(self, name: str, args: dict) -> tuple[str, list]:
        self.tool_counts[name] = self.tool_counts.get(name, 0) + 1
        fn = {"run_python": self.tool_run_python, "screenshot": self.tool_screenshot,
              "view_image": self.tool_view_image, "host_python": self.tool_host_python,
              "generate_image": self.tool_generate_image, "load_skill": self.tool_load_skill}.get(name)
        if name == "finish":
            if not self.review_done and self.total_cost() < CFG.HARD_COST_USD \
                    and self.minutes() < CFG.HARD_WALL_MIN - 10:
                self.first_finish_summary = args.get("summary", "")
                review = self.run_reviewer(self.first_finish_summary)
                return ("[harness] Before the scene is final, an independent reviewer inspected it "
                        "in Blender (renders and screenshots from several angles). Its review is "
                        "below. You now get ONE more pass: fix what you judge worth fixing, "
                        "check the result, then call `finish` again -- that one is final.\n\n"
                        "## Review\n\n" + review), []
            self.finish_summary = args.get("summary", "")
            return "Finishing: the scene will now be saved.", []
        if fn is None:
            return f"unknown tool {name}", []
        try:
            return fn(**args)
        except TypeError as e:
            return f"bad arguments for {name}: {e}", []
        except Exception as e:  # noqa: BLE001
            return f"tool {name} failed in the harness: {type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}", []

    # ── the review round ─────────────────────────────────────────────────
    def run_reviewer(self, builder_summary: str) -> str:
        """One reviewer conversation on the live scene. Returns the review text."""
        self.review_done = True
        self.role = "review"
        review_dir = self.run_dir / "review"
        review_dir.mkdir(exist_ok=True)
        t0 = time.time()
        try:
            self.link.save(self.run_dir / "pre_review.blend", copy=True, timeout=600)
        except Exception as e:  # noqa: BLE001
            self.log(f"pre-review save failed: {e}")
        self.log("review round: reviewer starting")
        self.event("review_start", builder_summary=builder_summary)
        tmpl = (CFG.ROOT / "prompts" / "reviewer.md").read_text(encoding="utf-8")
        system = tmpl.format(blender_version=self.blender_version, task_dir=str(self.task_dir),
                             review_dir=str(review_dir), max_calls=CFG.REVIEW_MAX_CALLS)
        task_text = (self.task_dir / "task.md").read_text(encoding="utf-8")
        refs = self.reference_images()
        content = [{"type": "input_text", "text":
                    f"# Brief ({self.task})\n\n{task_text.strip()}\n\nReference images:\n" +
                    "\n".join(f"- {p}" for p in refs) +
                    f"\n\n# The builder's finish summary\n\n{builder_summary}\n\n"
                    "Inspect the scene now and submit your review."}]
        for p in refs:
            content += [{"type": "input_text", "text": f"Image: {p.name}"}, llm.image_part(p)]
        items = [{"role": "user", "content": content}]
        tools = [t for t in TOOLS if t["name"] in ("run_python", "screenshot", "view_image")] + [
            _fn("submit_review", "Hand your review to the builder (ends your turn).",
                {"review": {"type": "string"}}, ["review"])]
        review, nudged = None, False
        while review is None:
            if self.review_calls >= CFG.REVIEW_MAX_CALLS or self.total_cost() >= CFG.HARD_COST_USD:
                if nudged:
                    break
                items.append({"role": "user", "content": [{"type": "input_text", "text":
                              "[harness] Review budget used up: call submit_review now with your review."}]})
                nudged = True
            try:
                resp, dt = llm.create(instructions=system, input=items, tools=tools,
                                      parallel_tool_calls=True, log=self.log)
            except Exception as e:  # noqa: BLE001
                self.log(f"reviewer API error: {e}")
                break
            c_cost = self.review_usage.add(resp.usage, dt)
            if resp.usage and resp.usage.input_tokens > CFG.PRUNE_AT_TOKENS:
                self.prune(items)
            out = [o.model_dump(exclude_none=True) for o in resp.output]
            items.extend(out)
            calls = [o for o in out if o["type"] == "function_call"]
            texts = [c.get("text", "") for o in out if o["type"] == "message"
                     for c in o.get("content", []) if c.get("type") == "output_text"]
            self.event("review_model", text="\n".join(texts),
                       reasoning_summary="\n".join(x.get("text", "") for o in out if o["type"] == "reasoning"
                                                    for x in o.get("summary", [])),
                       tool_calls=[{"name": c["name"], "arguments": c["arguments"][:4000]} for c in calls],
                       cost=round(c_cost, 5), seconds=round(dt, 1))
            self.log(f"review turn {self.review_usage.calls}: [{', '.join(c['name'] for c in calls)}] "
                     f"${self.total_cost():.3f} {self.minutes():.1f}min")
            if not calls:
                if texts and nudged:
                    review = "\n".join(texts)
                    break
                items.append({"role": "user", "content": [{"type": "input_text", "text":
                              "[harness] Use your tools to inspect, then call submit_review."}]})
                nudged = True
                continue
            shown = []
            for c in calls:
                try:
                    args = json.loads(c.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if c["name"] == "submit_review":
                    review = args.get("review", "")
                    items.append({"type": "function_call_output", "call_id": c["call_id"], "output": "submitted"})
                    continue
                self.review_calls += 1
                fn = {"run_python": self.tool_run_python, "screenshot": self.tool_screenshot,
                      "view_image": self.tool_view_image}.get(c["name"])
                try:
                    result, imgs = fn(**args) if fn else (f"unknown tool {c['name']}", [])
                except Exception as e:  # noqa: BLE001
                    result, imgs = f"tool failed: {type(e).__name__}: {e}", []
                self.event("review_tool", name=c["name"], result=result[:3000], images=[str(p) for p in imgs])
                items.append({"type": "function_call_output", "call_id": c["call_id"], "output": result})
                shown += [(c["name"], p) for p in imgs]
            if shown:
                content = []
                for name, p in shown:
                    try:
                        content += [{"type": "input_text", "text": f"Image from {name}: {p}"}, llm.image_part(p)]
                    except Exception as e:  # noqa: BLE001
                        content.append({"type": "input_text", "text": f"(could not load {p}: {e})"})
                items.append({"role": "user", "content": content})
        if not review:
            review = "(The reviewer did not produce a review; use your own judgement for this last pass.)"
        self.review_text = review
        (self.run_dir / "review.md").write_text(review, encoding="utf-8")
        self.event("review", review=review, seconds=round(time.time() - t0, 1),
                   usage=self.review_usage.as_dict())
        self.log(f"review round done in {(time.time() - t0) / 60:.1f} min, ${self.review_usage.cost:.3f}")
        self.role = "build"
        return review

    # ── context control ──────────────────────────────────────────────────
    def prune(self, items: list, aggressive: bool = False) -> int:
        """Stub old images and long old tool outputs; drop old reasoning.
        The first message (brief + references) is never touched."""
        keep_imgs = 1 if aggressive else 3
        keep_outputs = 10 if aggressive else 30
        keep_reason = 2 if aggressive else 6
        changed = 0
        img_msgs = [i for i, it in enumerate(items) if i > 0 and it.get("role") == "user"
                    and any(c.get("type") == "input_image" for c in it.get("content", []))]
        for i in img_msgs[:-keep_imgs] if keep_imgs else img_msgs:
            new = []
            for c in items[i]["content"]:
                if c.get("type") == "input_image":
                    new.append({"type": "input_text", "text": "[older image removed from context]"})
                    changed += 1
                else:
                    new.append(c)
            items[i]["content"] = new
        outs = [i for i, it in enumerate(items) if it.get("type") == "function_call_output"]
        for i in outs[:-keep_outputs]:
            o = items[i].get("output", "")
            if isinstance(o, str) and len(o) > 600:
                items[i]["output"] = o[:300] + "\n...[older output trimmed]...\n" + o[-200:]
                changed += 1
        calls = [i for i, it in enumerate(items) if it.get("type") == "function_call"]
        for i in calls[:-keep_outputs]:
            a = items[i].get("arguments", "")
            if len(a) > 3000:
                items[i]["arguments"] = json.dumps({"code": "[older code trimmed from context; "
                                                   "see actions/ folder]\n" + a[:1500]})
                changed += 1
        reas = [i for i, it in enumerate(items) if it.get("type") == "reasoning"]
        drop = set(reas[:-keep_reason])
        if drop:
            # Output items keep ids that tie them to their turn's reasoning item;
            # once that item is gone, the ids must go too or the API rejects them.
            cut = max(drop)
            for i, it in enumerate(items):
                if i < cut and it.get("type") in ("function_call", "message"):
                    it.pop("id", None)
            items[:] = [it for i, it in enumerate(items) if i not in drop]
            changed += len(drop)
        return changed

    # ── main loop ────────────────────────────────────────────────────────
    def run_loop(self, system: str, items: list) -> None:
        nudges = 0
        pending_note: list[str] = []
        prune_next = False
        while True:
            # budget
            cost, mins = self.total_cost(), self.minutes()
            if cost >= CFG.HARD_COST_USD or mins >= CFG.HARD_WALL_MIN or \
                    sum(self.tool_counts.values()) >= CFG.MAX_TOOL_CALLS:
                self.end_reason = (f"hard cap (cost ${cost:.2f}, {mins:.0f} min, "
                                   f"{sum(self.tool_counts.values())} tool calls)")
                self.log(self.end_reason)
                return
            if not self.warned_soft and (cost >= CFG.SOFT_COST_USD or mins >= CFG.SOFT_WALL_MIN):
                self.warned_soft = True
                pending_note.append(
                    f"[harness] Budget notice: ${cost:.2f} spent, {mins:.0f} minutes elapsed. The run "
                    f"stops at ${CFG.HARD_COST_USD:.2f} or {CFG.HARD_WALL_MIN} minutes. Wrap up: "
                    "get the scene into its best finished state and call finish.")
            if pending_note:
                items.append({"role": "user", "content": [{"type": "input_text", "text": "\n".join(pending_note)}]})
                pending_note = []
            if prune_next:
                n = self.prune(items)
                self.event("prune", changed=n)
                self.log(f"pruned context ({n} changes)")
                prune_next = False

            try:
                resp, dt = llm.create(instructions=system, input=items, tools=TOOLS,
                                      parallel_tool_calls=True, log=self.log)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "context" in msg.lower() or "too long" in msg.lower() or "maximum" in msg.lower():
                    n = self.prune(items, aggressive=True)
                    self.log(f"context error; aggressive prune ({n}) and retry: {msg[:200]}")
                    self.event("prune", changed=n, aggressive=True, error=msg[:500])
                    if n:
                        continue
                self.end_reason = f"API error: {type(e).__name__}: {msg[:500]}"
                self.log(self.end_reason)
                return
            call_cost = self.usage.add(resp.usage, dt)
            if resp.usage and resp.usage.input_tokens > CFG.PRUNE_AT_TOKENS:
                prune_next = True

            out_items = [o.model_dump(exclude_none=True) for o in resp.output]
            items.extend(out_items)
            texts, reasoning, calls = [], [], []
            for o in out_items:
                if o["type"] == "message":
                    texts += [c.get("text", "") for c in o.get("content", []) if c.get("type") == "output_text"]
                elif o["type"] == "reasoning":
                    reasoning += [s.get("text", "") for s in o.get("summary", [])]
                elif o["type"] == "function_call":
                    calls.append(o)
            u = resp.usage
            self.event("model", text="\n".join(texts), reasoning_summary="\n".join(reasoning),
                       tool_calls=[{"name": c["name"], "call_id": c["call_id"], "arguments": c["arguments"]} for c in calls],
                       usage={"input": u.input_tokens if u else None,
                              "cached": (u.input_tokens_details.cached_tokens if u and u.input_tokens_details else None),
                              "output": u.output_tokens if u else None},
                       cost=round(call_cost, 5), seconds=round(dt, 1), status=resp.status)
            self.log(f"turn {self.usage.calls}: {len(calls)} call(s) "
                     f"[{', '.join(c['name'] for c in calls)}] in={u.input_tokens if u else '?'} "
                     f"out={u.output_tokens if u else '?'} ${self.total_cost():.3f} {self.minutes():.1f}min")

            if not calls:
                nudges += 1
                if nudges > 3:
                    self.end_reason = "model stopped calling tools"
                    return
                items.append({"role": "user", "content": [{"type": "input_text", "text":
                              "[harness] No tool call in your last turn. Keep working on the scene, "
                              "or call `finish` if it is complete."}]})
                continue
            nudges = 0

            shown: list[tuple[str, Path]] = []
            for c in calls:
                try:
                    args = json.loads(c.get("arguments") or "{}")
                except json.JSONDecodeError as e:
                    args = None
                    result, imgs = f"could not parse arguments as JSON: {e}", []
                if args is not None:
                    result, imgs = self.dispatch(c["name"], args)
                self.event("tool", name=c["name"], call_id=c["call_id"],
                           args=args if c["name"] != "run_python" else {"code_file": f"actions/{self.n_action:04d}_blender.py"},
                           result=result[:4000], images=[str(p) for p in imgs])
                items.append({"type": "function_call_output", "call_id": c["call_id"], "output": result})
                shown += [(c["name"], p) for p in imgs]
            if shown:
                content = []
                for name, p in shown:
                    try:
                        part = llm.image_part(p)
                    except Exception as e:  # noqa: BLE001
                        content.append({"type": "input_text", "text": f"(could not load {p}: {e})"})
                        continue
                    content += [{"type": "input_text", "text": f"Image from {name}: {p}"}, part]
                items.append({"role": "user", "content": content})
            if self.finish_summary is not None:
                self.end_reason = "finished"
                return

    # ── entry ────────────────────────────────────────────────────────────
    def execute(self) -> dict:
        status = {"task": self.task, "run": self.run, "worker": self.worker, "phase": "running",
                  "started_at": L.now(), "freeze": self.freeze, "agent_pid": os.getpid()}
        (self.run_dir / "status.json").write_text(jdump(status), encoding="utf-8")
        produced, final_note = False, None
        try:
            self.link.start()
            self.blender_setup()
            system, items = self.build_prompt()
            (self.run_dir / "system_prompt.md").write_text(system, encoding="utf-8")
            (self.run_dir / "first_message.txt").write_text(items[0]["content"][0]["text"], encoding="utf-8")
            self.event("start", task=self.task, model=CFG.MODEL, effort=CFG.REASONING_EFFORT)
            self.run_loop(system, items)
        except Exception as e:  # noqa: BLE001
            self.end_reason = f"harness error: {type(e).__name__}: {e}"
            self.log(self.end_reason + "\n" + traceback.format_exc())
        # deliverable
        final = self.run_dir / "final.blend"
        for attempt in range(2):
            try:
                if not self.link.alive():
                    self.restart_blender("save at end")
                r = self.link.save(final, copy=False, timeout=1200)
                produced = bool(r.get("ok")) and final.is_file()
                final_note = (r.get("output") or "") + (r.get("error") or "")
                if produced:
                    break
            except Exception as e:  # noqa: BLE001
                final_note = f"{type(e).__name__}: {e}"
                self.link.stop()
        self.log(f"final.blend {'saved' if produced else 'NOT saved'}: {str(final_note)[-300:]}")
        self.link.stop()

        referenced = L.referenced_skills(self.blender_codes, self.library_names if hasattr(self, "library_names") else [])
        for n in referenced:
            L.log("reference", task=self.task, run=self.run, skill=n,
                  retrieved=n in getattr(self, "retrieved", []), loaded=n in self.loaded_skills)
        usage = {
            "task": self.task, "run": self.run, "model": CFG.MODEL, "reasoning_effort": CFG.REASONING_EFFORT,
            "end_reason": self.end_reason, "finished_by_agent": self.end_reason == "finished",
            "produced_blend": produced, "finish_summary": self.finish_summary,
            "wall_clock_min": round(self.minutes(), 1),
            "agent": self.usage.as_dict(), "retrieval": self.aux_usage.as_dict(),
            "review": {"happened": self.review_done, "usage": self.review_usage.as_dict(),
                       "tool_calls": self.review_calls, "first_finish_summary": self.first_finish_summary,
                       "text": self.review_text},
            "cost_usd": round(self.total_cost(), 4),
            "tool_calls": sum(self.tool_counts.values()), "tool_calls_by_name": self.tool_counts,
            "blender_actions": len(self.blender_codes), "blender_restarts": self.restarts,
            "image_generations": self.image_gens, "image_tokens": self.image_usage,
            "skills": {"library_size_at_start": getattr(self, "library_size", 0),
                       "retrieved": getattr(self, "retrieved", []),
                       "loaded_on_demand": self.loaded_skills,
                       "referenced_in_code": referenced},
            "finished_at": L.now(),
        }
        (self.run_dir / "usage.json").write_text(json.dumps(usage, indent=2), encoding="utf-8")
        status.update(phase="agent_done", produced_blend=produced, end_reason=self.end_reason,
                      agent_finished_at=L.now())
        (self.run_dir / "status.json").write_text(jdump(status), encoding="utf-8")
        self.event("end", **{k: usage[k] for k in ("end_reason", "produced_blend", "cost_usd", "wall_clock_min")})
        return usage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    u = Agent(Path(a.task_dir), Path(a.run_dir), a.worker, a.freeze).execute()
    print(json.dumps({k: u[k] for k in ("end_reason", "produced_blend", "cost_usd", "wall_clock_min")}))
    sys.exit(0 if u["produced_blend"] else 2)


if __name__ == "__main__":
    main()
