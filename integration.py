#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inspect our integration via local configuration and official read-only hooks/list."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
import install
from state import EVENTS
from usage import read_official

def codex_path():
    try:
        config = json.loads((install.APP/"menubar-config.json").read_text())
        if isinstance(config.get("codex"), str): return config["codex"]
    except (OSError, ValueError, TypeError): pass
    return shutil.which("codex") or "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"

def own_metadata(response):
    rows = []
    for entry in response.get("data", []):
        if not isinstance(entry, dict): continue
        for item in entry.get("hooks", []):
            if not isinstance(item, dict) or not install.owned(item): continue
            if item.get("source") != "user" or item.get("sourcePath") != str(install.HOOKS): continue
            event = item.get("eventName", "")
            if not isinstance(event, str): continue
            event = event[:1].upper()+event[1:]
            if event not in EVENTS: continue
            rows.append({"event":event,"enabled":item.get("enabled") is True,
                         "trust":item.get("trustStatus", "unknown")})
    return rows

def inspect():
    configured, definitions = set(), {"hooks": {}}
    config_error = None
    try:
        config = install.read_hooks()
        hooks = config.get("hooks", {})
        if not isinstance(hooks, dict): raise ValueError("invalid hooks")
        for event in EVENTS:
            groups = hooks.get(event, [])
            if not isinstance(groups, list): raise ValueError("invalid event")
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    raise ValueError("invalid group")
                handlers = [h for h in group["hooks"] if install.owned(h)]
                if handlers:
                    configured.add(event)
                    definitions["hooks"].setdefault(event, []).append({"hooks": handlers})
    except (OSError, ValueError, TypeError): config_error = "Hook 配置无法读取，请先检查 Codex 配置。"
    trust_error, metadata = None, None
    executable = codex_path()
    available = Path(executable).is_file() and os.access(executable, os.X_OK)
    if available:
        try:
            metadata = own_metadata(read_official(executable, "hooks/list", {"cwds":[str(Path.home())]}))
        except (OSError, ValueError, RuntimeError, TimeoutError):
            trust_error = "未能读取官方 Hook 状态，请在 Codex /hooks 中核对。"
    else: trust_error = "未找到官方 Codex CLI。"
    trusted = {m["event"] for m in metadata or [] if m["trust"] in ("trusted", "managed")}
    active = {m["event"] for m in metadata or [] if m["trust"] in ("trusted", "managed") and m["enabled"]}
    permission = None
    # TCC access belongs to the controlling background process, not the UI's child.
    try:
        status = json.loads((install.APP/"status.json").read_text())
        if (install.APP/"status.sock").exists():
            if isinstance(status.get("inputMonitoring"), bool): permission = status["inputMonitoring"]
            elif status.get("hardware") == "connected": permission = True
    except (OSError, ValueError, TypeError): pass
    snapshot = {"checkedAt":time.time(), "installed":install.PLIST.is_file(),
                "running":(install.APP/"status.sock").exists(), "configured":len(configured),
                "trusted":len(trusted) if metadata is not None else None,
                "active":len(active) if metadata is not None else None,
                "expected":len(EVENTS), "codexAvailable":available,"inputMonitoring":permission,
                "configurationError":config_error,"trustError":trust_error,
                "definitions":json.dumps(definitions,ensure_ascii=False,indent=2)}
    install.APP.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary = install.APP/"integration.tmp"
    temporary.write_text(json.dumps(snapshot,ensure_ascii=False)+"\n")
    temporary.chmod(0o600)
    os.replace(temporary,install.APP/"integration.json")
    return snapshot

def review_terminal():
    executable = codex_path()
    if not Path(executable).is_file(): raise RuntimeError("未找到 Codex CLI。")
    install.APP.mkdir(parents=True,exist_ok=True,mode=0o700)
    command = install.APP/"Codex-Hook-审阅.command"
    # This opens the real CLI. The human enters /hooks and reviews its definitions.
    script = "#!/bin/zsh\n"+"print -r -- '进入 Codex 后输入 /hooks，审阅 Node75 的 7 个状态 Hook。已信任的无需重复确认。'\n"
    script += "cd -- "+shlex.quote(str(Path.home()))+"\n"
    script += "env TERM=xterm-256color "+shlex.quote(executable)+"\n"
    command.write_text(script)
    command.chmod(0o700)
    subprocess.run(["open","-a","Terminal",str(command)],check=True)

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="Node75 Codex 接入检查与官方审阅入口")
    parser.add_argument("command",choices=("inspect","review-terminal"))
    action=parser.parse_args().command
    if action=="inspect":
        snapshot=inspect()
        print(json.dumps({k:v for k,v in snapshot.items() if k!="definitions"},ensure_ascii=False))
    else: review_terminal()
