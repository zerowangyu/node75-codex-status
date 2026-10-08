#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the Apple Silicon app locally without installing or changing hooks."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    subprocess.run([
        "xcrun", "clang", "-O2", "-Wall", "-Wextra", "-Werror",
        "-arch", "arm64", "-mmacosx-version-min=12.0", "node75_led.c",
        "-framework", "CoreFoundation", "-framework", "CoreGraphics",
        "-framework", "IOKit", "-o", "node75_led",
    ], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-B", str(ROOT/"build_menubar.py")], cwd=ROOT, check=True)
