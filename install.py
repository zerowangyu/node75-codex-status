#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install/uninstall the user service; preserve unrelated Codex hooks."""
import argparse
import copy
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from state import EVENTS

ROOT = Path(__file__).resolve().parent
APP = Path.home()/"Library/Application Support/Node75Codex"
CODEX_DIR = Path(os.environ.get("CODEX_HOME", str(Path.home()/".codex")))
HOOKS = CODEX_DIR/"hooks.json"
LABEL = "local.node75.codex-status"
PLIST = Path.home()/"Library/LaunchAgents"/(LABEL+".plist")
DOMAIN = "gui/"+str(os.getuid())
UI_LABEL = "local.node75.codex-menubar"
UI_APP = Path.home()/"Applications/Node75 Status.app"
UI_PLIST = PLIST.with_name(UI_LABEL+".plist")
COMMAND = shlex.quote(sys.executable)+" -B "+shlex.quote(str(APP/"node75_status.py"))+" hook"

def owned(handler):
    if not isinstance(handler, dict): return False
    command = handler.get("command")
    if not isinstance(command, str): return False
    try: tokens = shlex.split(command)
    except ValueError: return False
    return str(APP/"node75_status.py") in tokens and tokens[-1:] == ["hook"]

def merge(config, add):
    result = copy.deepcopy(config)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict): raise ValueError("hooks 必须为对象")
    for event in EVENTS:
        groups = hooks.get(event, [])
        if not isinstance(groups, list): raise ValueError(event+" 必须为数组")
        retained = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError(event+" 包含无效 Hook 组")
            group["hooks"] = [h for h in group["hooks"] if not owned(h)]
            if group["hooks"]: retained.append(group)
        if add: retained.append({"hooks": [{"type":"command", "command":COMMAND, "timeout":1}]})
        if retained: hooks[event] = retained
        else: hooks.pop(event, None)
    if not hooks: result.pop("hooks", None)
    return result

def read_hooks():
    if not HOOKS.exists(): return {}
    config = json.loads(HOOKS.read_text())
    if not isinstance(config, dict): raise ValueError("hooks.json 必须为对象")
    return config

def save_hooks(value):
    HOOKS.parent.mkdir(parents=True, exist_ok=True)
    if HOOKS.exists(): shutil.copy2(HOOKS, HOOKS.with_name("hooks.json.node75-backup-"+str(time.time_ns())))
    temp = HOOKS.with_name("hooks.json.node75.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")
    os.replace(temp, HOOKS)

def service(stop=False):
    if stop:
        return subprocess.run(["launchctl", "bootout", DOMAIN+"/"+LABEL], capture_output=True)
    # bootout can return before launchd has released the previous job's name.
    for attempt in range(20):
        result = subprocess.run(["launchctl", "bootstrap", DOMAIN, str(PLIST)],capture_output=True,text=True)
        if result.returncode == 0: return
        time.sleep(0.25)
    raise RuntimeError("后台服务启动失败："+result.stderr.strip())

def install_service():
    merged = merge(read_hooks(), True)  # Validate before touching the existing service.
    APP.mkdir(parents=True, exist_ok=True, mode=0o700)
    service(stop=True)
    for name in ("node75_led", "node75_led.c", "node75_status.py", "state.py", "usage.py", "install.py", "integration.py"):
        temporary = APP/(name+".new")
        shutil.copy2(ROOT/name, temporary)
        os.replace(temporary, APP/name)
    (APP/"node75_led").chmod(0o755)
    config = {
        "Label":LABEL, "ProgramArguments":[sys.executable,"-B",str(APP/"node75_status.py"),"daemon"],
        "RunAtLoad":True, "KeepAlive":True, "ThrottleInterval":10,
        "StandardOutPath":str(APP/"service.log"),"StandardErrorPath":str(APP/"service.log"),
    }
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(config))
    if merged != read_hooks(): save_hooks(merged)
    service()
    codex = shutil.which("codex") or "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
    (APP/"menubar-config.json").write_text(json.dumps({"python":sys.executable,"codex":codex})+"\n")

def install():
    install_service()
    if (ROOT/"Node75 Status.app").is_dir(): install_menubar()
    print("已安装 Node75 无线白灯状态服务。")
    print("首次使用：在 Codex 的 Hook 审阅界面信任这 7 个新增 Hook；CLI 可输入 /hooks。")
    print("未修改 Hook 信任记录，也未绕过首次信任要求。")
    print("服务状态："+str(APP/"status.json"))

def stop_menubar():
    subprocess.run(["launchctl", "bootout", DOMAIN+"/"+UI_LABEL], capture_output=True)
    pattern = "^"+re.escape(str(UI_APP/"Contents/MacOS/Node75MenuBar"))+"( |$)"
    subprocess.run(["pkill", "-f", pattern],capture_output=True)
    for _ in range(20):
        if subprocess.run(["pgrep", "-f", pattern],capture_output=True).returncode != 0: return
        time.sleep(0.1)
    raise RuntimeError("菜单栏程序尚未退出，请关闭后重试。")

def install_menubar():
    source = ROOT/"Node75 Status.app"
    if not source.is_dir(): raise RuntimeError("菜单栏程序尚未构建，请先运行 build_menubar.py。")
    first_install = not UI_APP.exists()
    APP.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ("usage.py",):
        script = APP/(name+".new")
        shutil.copy2(ROOT/name, script)
        os.replace(script, APP/name)
    codex = shutil.which("codex") or "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
    (APP/"menubar-config.json").write_text(json.dumps({"python":sys.executable,"codex":codex})+"\n")
    stop_menubar()
    UI_APP.parent.mkdir(parents=True, exist_ok=True)
    temporary = UI_APP.with_name("Node75 Status.app.new")
    if temporary.exists(): shutil.rmtree(temporary)
    shutil.copytree(source, temporary)
    if UI_APP.exists(): shutil.rmtree(UI_APP)
    os.replace(temporary, UI_APP)
    if first_install or UI_PLIST.exists():
        config = {"Label": UI_LABEL, "ProgramArguments": [str(UI_APP/"Contents/MacOS/Node75MenuBar")],
                  "RunAtLoad": True, "StandardOutPath": str(APP/"menubar.log"),
                  "StandardErrorPath": str(APP/"menubar.log")}
        APP.mkdir(parents=True, exist_ok=True)
        UI_PLIST.parent.mkdir(parents=True, exist_ok=True)
        UI_PLIST.write_bytes(plistlib.dumps(config))
    # Launch once through LaunchServices now; launchd reads the login plist next login.
    subprocess.run(["open", str(UI_APP), "--args", "--show-panel"], check=True)
    print("菜单栏已安装并启动："+str(UI_APP))

def disconnect():
    merged = merge(read_hooks(), False)
    service(stop=True)
    if merged != read_hooks(): save_hooks(merged)
    PLIST.unlink(missing_ok=True)
    print("已移除本程序的 Codex 接入，保留菜单栏、额度显示和其他 Hook。")

def uninstall():
    disconnect()
    stop_menubar()
    UI_PLIST.unlink(missing_ok=True)
    print("已停用状态服务并移除本程序的 Hook；保留源码、日志和备份。")

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="Node75 Codex 状态灯安装管理")
    parser.add_argument("action", choices=("install","uninstall","review","menubar","integrate","disconnect"))
    action=parser.parse_args().action
    if action=="install": install()
    elif action=="uninstall": uninstall()
    elif action=="menubar": install_menubar()
    elif action=="integrate":
        install_service()
        print("服务与 7 个 Hook 已配置。首次信任请通过 Codex 官方 /hooks 审阅；已信任的定义无需重复确认。")
    elif action=="disconnect": disconnect()
    else: print(json.dumps(merge(read_hooks(),True),ensure_ascii=False,indent=2))
