"""
Usage:
    python Tool_scripts/screenshot.py
    python Tool_scripts/screenshot.py --timelag 2
    python Tool_scripts/screenshot.py --timelag 2 --output screenshots/my_shot.png
"""

import argparse
import os
import subprocess
import time
from datetime import datetime

parser = argparse.ArgumentParser(description="Take a screenshot with an optional time delay.")
parser.add_argument("--timelag", type=float, default=0, help="Seconds to wait before capturing (default: 0)")
parser.add_argument("--output", type=str, default=None, help="Output file path (default: screenshots/<timestamp>.png)")
args = parser.parse_args()

if args.output is None:
    os.makedirs("screenshots", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    args.output = f"screenshots/screenshot_{timestamp}.png"
else:
    parent = os.path.dirname(args.output)
    if parent:
        os.makedirs(parent, exist_ok=True)

if args.timelag > 0:
    print(f"[BlendCUA] Taking screenshot in {args.timelag}s... (switch to your target window)")
    time.sleep(args.timelag)

subprocess.run(["screencapture", "-x", args.output], check=True)
print(f"[BlendCUA] Screenshot saved: {args.output}")
