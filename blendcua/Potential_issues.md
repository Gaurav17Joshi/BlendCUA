# Potential issues: running BlendCuavb_run on this machine

Found while setting the project up on `C:\Users\kunal` (2026-09-14/15) and starting the
`17_watering_can` + `18_tree` run. The project was built on another machine (`C:\Users\render`),
so most of these come from moving it. Each entry: what you see, why, and what was done.

**Status key:** FIXED = handled on this machine · WORKAROUND = handled outside the harness code ·
OPEN = still there, watch for it.

---

## How to start a run here

```powershell
Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\Users\kunal\.venvs\blendcua\run_can_and_tree.ps1'
```

- Worker 0 (port 6666) takes the first task in `--tasks`, worker 1 (port 6667) the second.
- The launcher runs in its own console window. Closing that window stops both workers;
  running the same command again continues where they stopped.
- Log: `run_v2.log` (driver), `run_v2_console_can_tree.log` (everything, UTF-8),
  ledger `tasks\PROGRESS.csv`.
- For other tasks, copy the launcher and change the `--tasks` line. Keep its PATH line (see 4).
  `run_cup_and_snoopy.ps1` (16 + 19) is such a copy; `chain_next_run.ps1` waits for one run's
  driver to exit and starts the next, so two batches can be queued overnight.

---

## 1. No Python on the machine: FIXED

- **Seen:** only the Microsoft Store `python.exe` placeholder; no conda. The README says
  `conda activate blendcua`, but the original machine's config shows it actually ran a plain
  Python 3.12 (`C:\Users\render\AppData\Local\Programs\Python\Python312`).
- **Done:** Python 3.12.10 (user install) and a venv at `C:\Users\kunal\.venvs\blendcua`.
- **Watch:** the project has **no requirements file**. What is installed:
  `hermes-agent[mcp]==0.19.0` (brings `mcp 1.26.0`), `openai`, `pyyaml`, `pillow`, `numpy`,
  `anyio`, `py-spy` (diagnostics only). The hermes-agent version the original runs used is
  unknown; a `pip freeze` from the original machine would pin it. Worth adding a
  `requirements.txt`.

## 2. `mcp` 2.x breaks the dispatch server: FIXED

- **Seen:** every build ends ~30 s after it starts with `build did not finish`. Console shows
  `MCP server 'blendcua_dispatch' initial connection failed ... Connection closed` and
  `[BlendCUA] MCP tools registered: []`.
- **Why:** `mcp_dispatch_server.py` does `from mcp.server.fastmcp import FastMCP`; `mcp` 2.x
  renamed that module, so the server dies on import.
- **Fix:** install `hermes-agent[mcp]==0.19.0`, which pins `mcp==1.26.0`. Never
  `pip install mcp` on its own.
- **Check:** `python mcp_dispatch_server.py` from a worker view should keep running, not print
  a `ModuleNotFoundError`.

## 3. Git not installed; the full installer needs admin: WORKAROUND

- **Done:** PortableGit 2.55.0 (official, signed) at `C:\Users\kunal\PortableGit`, added to
  the user PATH. The harness needs git for `harness\store.git` and the worker views, and the
  agents' `bash` tool needs Git's bash.
- **Optional:** a normal install from an admin shell: `winget install --id Git.Git -e --source winget`.

## 4. Step subagents freeze at start (git hang inside hermes): WORKAROUND

- **Seen:** the build starts, `step_001` exists but no action files ever appear. The last line
  in `harness\wK\.hermes_home*\logs\agent.log` is
  `conversation turn ... Step-Subagent Task`, with no API calls after it. Processes
  `git.exe -C ...\harness\wK status --porcelain=2 --branch` are left running with their
  parent gone, using no CPU.
- **Why:** hermes-agent builds the subagent's system prompt with a `git status` probe
  (`agent/coding_context.py`, 2.5 s timeout). On timeout it kills the process it started;
  with PortableGit that is only a launcher (`bin\git.exe` / `cmd\git.exe`). The real
  `mingw64\bin\git.exe` keeps the output pipe open and Python on Windows waits for it forever.
  Reproduced and confirmed on 2026-09-15.
- **Fix in place:** the launcher puts `C:\Users\kunal\PortableGit\mingw64\bin` **first** on
  PATH, so the real git is what gets killed and hermes carries on after 2.5 s. Any other way
  of starting `run_v2.py` needs the same PATH.
- **Cleaner fix (needs a code change):** hermes' `agent.coding_context: off`. It cannot be set
  by hand, because `blendcua_agent.py` rewrites `config.yaml` from scratch every run; it would
  have to be added to the `config` dict there (around line 98).
- **If it happens anyway:** stop the run, kill the stray `git.exe status` processes, rerun.

## 5. `bash` must be Git's bash, not WSL's: WORKAROUND

- The agents' `bash` tool takes the first `bash` on PATH (`shutil.which`). Windows can have a
  WSL `bash.exe` in System32, which comes before user PATH entries and cannot see Windows paths.
- The launcher puts PortableGit's `bin` ahead of System32 for the run.

## 6. API key file: FIXED

- Location: `C:\Users\kunal\blendcua.env.txt`, one line `OPENAI_API_KEY=...`. It must be
  **outside** the project; the loader refuses a key file inside it.
- **Traps met:**
  - Windows hides extensions, so Notepad saved `blendcua.env.txt.txt`.
  - A UTF-8 byte-order mark would break the name on line 1: PowerShell's `Set-Content` and
    `Out-File` add one; Windows 11 Notepad and `[IO.File]::WriteAllText` do not.
- Every role uses OpenAI `gpt-5.6-luna`; `gpt-image-2` is used for plates and leaf images.
  Both were available on the key as of 2026-09-15.

## 7. Paths from the original machine (`C:\Users\render`)

| Where | Status |
|---|---|
| `harness\store.git` `core.worktree` and the `w0`/`w1` worktree links | FIXED (`git config --file`, `git worktree repair`) |
| `.hermes_home*\config.yaml` (Python path, key file) | FIXED: rewritten by `blendcua_agent.py` every run |
| Action files in old `mem\<run>\steps\` (`TOOLS_CODE = r"C:\Users\render\..."`) | OPEN: replaying an old run needs the paths rewritten (as `vb/import_run.py` does) |
| `.blend` checkpoints link images by absolute path, some to `...\BlendCuaLoop_try\plans\17_shark\...` | OPEN, see below |
| `Tool_scripts\win_blender_server.py` `_DEFAULT_ROOT` | harmless: only used if `__file__` cannot be read |

**Images in old checkpoints.** A replay that loads an old checkpoint (for example
`08_shark_run_001\checkpoints\step_007.blend`) gets its reference images at 0×0, and every
perception tool then fails with `ZeroDivisionError`. Options:
- a junction so the old paths resolve (admin shell):
  `New-Item -ItemType Directory C:\Users\render; New-Item -ItemType Junction -Path C:\Users\render\Joshi -Target C:\Users\kunal\Joshi`
- in the code: pack images or make paths relative before `checkpoint.save_step`, or remap
  missing image paths after `checkpoint.load_step`.

## 8. An empty failed run keeps a finished build "unfinished": FIXED once, can recur

- `run_v2.py` judges a task's build by the **first** `mem\<task>_run_*` folder that has a
  `steps\` folder. A failed attempt that left an empty `step_001` makes every later build of
  that task look incomplete, so the driver never moves on to bundle and rounds.
- **Fix:** move empty failed runs out of `mem\`. The six from 2026-09-15 are in
  `mem_old\2026-09-15_failed_launch\`.

## 9. File tools refuse `plans\`, `mem\`, `tasks\` inside worker views: OPEN (predates this machine)

- **Seen:** `Tool read returned error: '...plans\...' is outside the project directory`, also
  for `mem/<run>/steps/...` writes.
- **Why:** in `harness\wK` those folders are junctions to the shared ones, and the plugin's
  path guard resolves the junction and rejects the target.
- **Effect:** agents fall back to `bash`/Python for those files. It costs a few turns per step
  and does not block the build. The original machine's shark log shows the same errors.

## 10. Console log encoding: FIXED

- `Tee-Object` in Windows PowerShell writes UTF-16, so the old `run_v2_console.log` now holds
  UTF-8 and UTF-16 parts. The launcher writes `run_v2_console_can_tree.log` as UTF-8 instead.

## 11. Tree task: gpt-image needs a longer `bash` timeout

- One gpt-image-2 image takes up to ~2 minutes; the agents' `bash` tool defaults to 45 s
  (max 600). `18_tree\task.md` tells the agent to pass a longer `timeout`.
- Changes made in `Tasks\Intial_Set\<task>` are not picked up by the loop; copy them to
  `tasks\train\NN_<task>` (the watering-can material line had to be synced by hand once).

## 12. No Pillow inside the worker Blenders: FIXED

- **Seen:** actions that call `reference_audit`/`reference_curve_mapping` fail with
  `ModuleNotFoundError: No module named 'PIL'`, and from then on, for the rest of that Blender
  session, with `ImportError: cannot import name '_imaging' from 'PIL'
  (C:\Users\kunal\.venvs\blendcua\Lib\site-packages\PIL\...)`. 14 times on worker 0 on
  2026-09-15/16; the agent works around each one, so it costs turns rather than blocking.
- **Why:** Blender 5.2 ships Python 3.13 and no Pillow, so the project vendors one at
  `Tool_scripts/Tools_code/_vendor` (Pillow 12.3.0, cp313). That folder is gitignored, and the
  workers run from git worktrees, so **the views never had it**. `_pil()`'s fallback to
  `_vendor` found nothing either, and the executor's own workaround — the venv's Pillow, built
  for 3.12 — then failed on `_imaging` every time.
- **Fix:** `harness.py` copies `_vendor` into each view in `_copy_code` and lists it in
  `EXCLUDE`, so the untracked sweep leaves it; both views were given a copy by hand as well.
  `_pil()` in `reference_audit.py` and `reference_curve_mapping.py` now catches `ImportError`
  (not only `ModuleNotFoundError`), drops a half-imported `PIL` from `sys.modules` and puts
  `_vendor` first (store commit `ff1f53c`).
- **Watch:** `_vendor` is per-Blender-version. After a Blender upgrade, rebuild it with
  `"<blender>\5.2\python\bin\python.exe" -m pip install --target=Tool_scripts/Tools_code/_vendor Pillow`.
  A Blender already running when the copy appears keeps its old `sys.path`; the fix bites from
  the next Blender start.
- **Existing stores:** `harness.py` writes `EXCLUDE` to `harness/store.git/info/exclude` only
  when it creates the store, so a store made before this change keeps the old list and each
  sync deletes `_vendor` and copies it back (logged as "discarded 123 unreviewed file(s)").
  This machine's exclude file was rewritten from `harness.EXCLUDE` on 2026-09-17.
- **Locked DLLs:** once a worker's Blender has imported the vendored Pillow it holds the `.pyd`
  files open, and Windows will not overwrite a loaded DLL. The first version of the copy used a
  plain `copytree` and the next sync of that view failed with `WinError 32` (20_low_poly_well,
  2026-09-17 07:16). `_copy_code` now skips files that are already identical (size + mtime).
  A driver started before that change still has the old code loaded.

---

## Machine limits (measured 2026-09-14)

- **It is a VM** (QEMU/KVM): 4 cores / 8 threads of a Xeon Silver 4110, fixed at 2.1 GHz;
  64 GB RAM; 4× RTX 2080 Ti (11 GB). **The CPU is the bottleneck, not the GPUs.**
  - 2 Blender instances at once: fine, about 10% slower per step.
  - 4 at once: steps about 1.85× slower, with stalls of 7-31 s.
  - Cycles "GPU" renders are mostly CPU-side setup: 12.6 s alone, about 2× at 4 instances.
  - More vCPUs from the host would be the biggest single improvement.
- **RDP:** the viewport gets the real GPU because the "use hardware graphics adapters for RDP"
  policy is on. A minimised or disconnected RDP session may stop redrawing (untested); keep it
  connected during runs.
- **Blender "Not Responding"** during a long action (a render, a heavy sculpt) is normal:
  actions run on Blender's main thread. The window recovers when the action ends.
- **Blender start:** the server handshake took 69 s once (usually ~5 s); `win_start_blender.py`
  waits up to 120 s.
- The README note "the client gives Blender 30 s to acknowledge" is out of date: the dispatch
  timeout is `DISPATCH_TIMEOUT_S = 2000` in `blendcua_core.py`.
- `08_shark_run_002` cannot be replayed step 1→7 as it stands: steps 3-7 were carried over from
  run_001 and step 3 loads run_001's step-7 checkpoint (see that run's README).
