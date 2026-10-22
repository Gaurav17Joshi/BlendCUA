"""
Step-by-step screenshot trail. Numbered sequence so the agent (and
humans) can scan the build history left-to-right.
"""

import os
import shutil

from .view import render_viewport


class Trail:
    """Numbered screenshot directory.

    Each shot() takes a fresh viewport render; each copy() pulls in an
    already-rendered overlay so it sits alongside the step screenshots.
    """

    def __init__(self, dir_path, logger=print):
        self.dir = dir_path
        self.n = 0
        self.log = logger
        os.makedirs(self.dir, exist_ok=True)

    def shot(self, label=""):
        self.n += 1
        out = os.path.join(self.dir, f"{self.n:03d}_{label}.png")
        render_viewport(out)
        self.log(f"[BlendCUA] Trail → {out}")
        return out

    def copy(self, src, label=""):
        if not os.path.exists(src):
            return None
        self.n += 1
        ext = os.path.splitext(src)[1] or ".png"
        dst = os.path.join(self.dir, f"{self.n:03d}_{label}{ext}")
        shutil.copy2(src, dst)
        self.log(f"[BlendCUA] Trail copy → {dst}")
        return dst
