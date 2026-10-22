---
name: where-code-runs
description: Blender-side versus shell-side — which of your scripts belongs where, and what happens when you get it wrong.
---

# Where code runs

You have two places to run Python and they are not interchangeable.

| | `write_and_run` | `bash` |
|---|---|---|
| runs | **inside** the live Blender session | a separate process |
| can touch | `bpy`, `bmesh`, the scene | files, images, numpy, anything on disk |
| costs | an action from the step's budget | nothing |
| time limit | **30 s**, and it blocks the whole session | minutes, blocks nothing |

**The rule: `write_and_run` is for the 3D scene. Everything else goes in `bash`.**

## What "blocks the whole session" means

An action file does not run *alongside* Blender, it runs *inside* it. While your
script is executing, Blender is doing nothing else — not rendering, not answering
the next action, not responding to anyone.

A reviewer needed the reference photograph's cross-sections, and wrote the obvious
thing:

```python
px = ref.data.pixels                 # a 2036 x 1534 image
for y in range(h):
    k = (y * w + x) * 4
    nonwhite = min(px[k], px[k+1], px[k+2]) < thresh
```

That is ~235,000 individual `bpy.types.Image.pixels` reads, each going through
RNA. It blew the 30-second limit, and because the socket serves one client at a
time, the next four actions timed out behind it too. **Four minutes of dead
session for a scan that takes under a second in a subprocess.**

The tell is a run where several actions in a row report a timeout with no error
text. That is not Blender hanging — it is Blender busy. Do not retry; look at what
the previous action asked it to do.

## If you genuinely must touch pixels inside Blender

Bulk-copy, never index:

```python
buf = numpy.empty(len(ref.data.pixels), dtype=numpy.float32)
ref.data.pixels.foreach_get(buf)      # one C-level call
```

`foreach_get` moves the whole buffer at once. The per-element path is the trap.

## What belongs in `bash`

Anything that reads a file, crops a render, scans for an edge, compares two
images, walks the repo, or looks up how a tool works. All of it is faster, none of
it costs an action, and none of it can freeze the session.

Do not paste `inspect.getsource` into an action file to find out what a function
does — that spends a Blender action to print text. Use:

```bash
python Tool_scripts/tool_help.py silhouette_vs_reference
```

## What belongs in `write_and_run`

- Building or modifying geometry.
- Reading the scene: vertex positions, modifiers, object lists, mesh statistics.
- Setting the viewport and taking a render — the screenshot has to come from
  inside.
- Overlay/preview calls, which render through the live viewport.

A useful pattern is to split one question across both: an action file dumps what
it can see to JSON, then a shell script does the arithmetic and the drawing.

## Wait on your own marker, never a shared one

`mem/exec_status.json` holds **one** result: the last script the server ran, for
whoever asked. If anything else is talking to the same Blender — a leftover
script from a run you killed, a probe you sent while thinking — your wait can be
satisfied by *their* completion, and from then on every step you take reads the
previous step's answer. It does not look like a race; it looks like a render that
finished in 0.5 s and a file that is not on disk.

If you send more than one script, make each one stamp its own file and wait for
that:

```python
body += f"
open({token!r}, 'w').close()
"     # token unique per dispatch
send(body)
while not os.path.exists(token): time.sleep(0.25)
```

Then a leftover script can only delay you, never lie to you. Same shape as the
bug in `dispatch_timeouts_investigation.md`, where the server and the client
disagreed about which `exec_status.json` they meant.

```python
# in the action: cheap to read, cheap to write
json.dump({"rings": rings}, open(f"{step_dir}/scripts/dump_rings.json", "w"))
shot("dumped 17 rings")
```

```bash
# in the shell: the slow part, and re-runnable for free
python mem/<run>/steps/step_001/scripts/compare_rings.py
```
