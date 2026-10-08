#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the native accessory app with Apple's Swift compiler."""
from pathlib import Path
import plistlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
APP = ROOT/"Node75 Status.app"
MACOS = APP/"Contents/MacOS"
RESOURCES = APP/"Contents/Resources"
MACOS.mkdir(parents=True, exist_ok=True)
RESOURCES.mkdir(parents=True, exist_ok=True)
payload = RESOURCES/"Payload"
payload.mkdir(parents=True, exist_ok=True)
for name in ("node75_led", "node75_led.c", "node75_status.py", "state.py", "usage.py", "install.py", "integration.py"):
    shutil.copy2(ROOT/name, payload/name)
subprocess.run(["xcrun", "swiftc", "-O", "-swift-version", "5", "-target", "arm64-apple-macosx12.0",
                "menubar.swift", "-o", str(MACOS/"Node75MenuBar"), "-framework", "AppKit"], cwd=ROOT, check=True)
info = {"CFBundleIdentifier": "local.node75.codex-menubar", "CFBundleExecutable": "Node75MenuBar",
        "CFBundleName": "Node75 Status", "CFBundleDisplayName": "Node75 状态灯", "CFBundlePackageType": "APPL",
        "CFBundleVersion": "4", "CFBundleShortVersionString": "1.3.1", "LSUIElement": True,
        "LSMinimumSystemVersion": "12.0", "NSHighResolutionCapable": True}
(APP/"Contents/Info.plist").write_bytes(plistlib.dumps(info))
shutil.copy2(ROOT/"README.md", RESOURCES/"README.md")
shutil.copy2(ROOT/"LICENSE", RESOURCES/"LICENSE")
shutil.copytree(ROOT/"docs", RESOURCES/"docs", dirs_exist_ok=True)
subprocess.run(["codesign", "--force", "--sign", "-", str(APP)], check=True)
print("已构建："+str(APP))
