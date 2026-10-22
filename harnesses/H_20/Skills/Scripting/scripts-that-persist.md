---
name: scripts-that-persist
description: Writing the throwaway script so it is not throwaway — where to put it, what to print, and how to make the next run of it free.
---

# Scripts that persist

The diagnostic you write to answer a question will be needed again after the next
fix. Write it accordingly, and the second and third look cost nothing.

## Save it, then run it by name

```bash
# no
python -c "from PIL import Image; ..."
python - <<'PY'
...
PY

# yes
# write  mem/<run>/steps/step_001/scripts/crop_head.py
bash: python mem/<run>/steps/step_001/scripts/crop_head.py
```

Piping code in leaves nothing behind. You will want the same crop after every
change, and a saved script re-runs in one short call while an inline one has to be
retyped from memory — slightly differently each time, so its answers are not
comparable.

`scripts/` is created for you inside each step. **A step that produced no `.py`
files in `scripts/` almost certainly did not look closely at what it built.**

## Name it after the question

`crop_head_profile.py`, `scan_photo_rows.py`, `compare_rings.py`,
`measure_silhouette.py`. Six weeks later the filename is the only documentation
that survives, and a directory of `check1.py … check7.py` is unreadable.

## Print one line that answers the question

The caller sees the output, not the code. Make the last line a verdict:

```python
print(f"PASS ring radii {radii} mm, all within 15-21")
print(f"FAIL req={req} used={used} stations={n} ZEROS={zeros}")
```

Include the inputs in the output. `stations=25` alone is not reproducible;
`requested=32 used=25 stations=25 dropped=4` tells you what was asked as well as
what happened, which is what you need when the number changes next time.

## Assert what you assume, before you write anything

A patch script that edits several files should check every match first and only
then write:

```python
for old, new in subs:
    n = s.count(old)
    assert n == 1, f"{n} matches for {old[:55]!r}"
    s = s.replace(old, new)
p.write_text(s, encoding="utf-8")     # only reached if every match was exact
```

The write is after the loop, so a failed assertion leaves the file untouched
rather than half-edited. This caught a wrong line-wrap guess with nothing to undo.

## Two mechanical traps on this machine

**Heredocs mangle non-ASCII.** `python - <<'PY'` with an em-dash in a pattern
arrives as `?` and the match silently fails. Write the script to a file with the
`Write` tool instead — the only reliable way to get exact text into Python here.

**The console is cp1252.** A script printing an em-dash raises
`UnicodeEncodeError` and takes your output with it. Either force UTF-8:

```python
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError): pass
```

or keep the output ASCII. `PYTHONIOENCODING=utf-8` in front of the command works
too, for one-offs.

## Keep the data next to the picture

When a script produces a measurement and a render, save both, and save the numbers
as JSON rather than only in the log line. The next script reads the JSON instead
of recomputing, and a later disagreement can be settled by looking at what was
actually measured rather than by measuring again.
