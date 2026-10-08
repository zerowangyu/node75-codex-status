#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read quota through the signed-in official Codex app-server, without reading credentials."""
import argparse
import json
import math
import os
from pathlib import Path
import select
import shutil
import subprocess
import time

RUNTIME = Path(os.environ.get("NODE75_RUNTIME", str(Path.home()/"Library/Application Support/Node75Codex")))

def windows(response):
    by_id = response.get("rateLimitsByLimitId")
    if isinstance(by_id, dict) and by_id:
        limits = by_id.get("codex")
    else:
        limits = response.get("rateLimits")
    if not isinstance(limits, dict): return []
    result = []
    for key, fallback in (("primary", "主额度"), ("secondary", "次额度")):
        value = limits.get(key)
        if not isinstance(value, dict): continue
        used = value.get("usedPercent")
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used): continue
        minutes = value.get("windowDurationMins")
        name, short = fallback, fallback
        if minutes == 300: name, short = "5 小时", "5h"
        elif minutes == 10080: name, short = "每周", "周"
        elif isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0:
            name = str(minutes//60)+" 小时" if minutes % 60 == 0 else str(minutes)+" 分钟"
            short = str(minutes//60)+"h" if minutes % 60 == 0 else str(minutes)+"m"
        reset = value.get("resetsAt")
        result.append({"name": name, "short": short, "remainingPercent": max(0, min(100, 100-used)),
                       "windowDurationMins": minutes if isinstance(minutes, int) and not isinstance(minutes, bool) else None,
                       "resetsAt": reset if isinstance(reset, (int, float)) and not isinstance(reset, bool) else None})
    return sorted(result, key=lambda item: item["windowDurationMins"] or float("inf"))

def read_official(executable, method, params, timeout=25):
    # JSON-RPC over local stdio. No thread/start, turn/start, login or reset methods.
    if method not in ("account/rateLimits/read", "hooks/list"):
        raise ValueError("only read-only methods are supported")
    process = subprocess.Popen([executable, "app-server", "--stdio"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    buffer = b""
    deadline = time.monotonic()+timeout
    def write(message):
        process.stdin.write(json.dumps(message).encode()+b"\n")
        process.stdin.flush()
    def receive(identifier):
        nonlocal buffer
        while time.monotonic() < deadline:
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                try: response = json.loads(line)
                except ValueError: continue
                if isinstance(response, dict) and response.get("id") == identifier:
                    if "error" in response: raise RuntimeError("quota unavailable")
                    return response.get("result")
            ready, _, _ = select.select([process.stdout], [], [], max(0, deadline-time.monotonic()))
            if ready:
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk: raise RuntimeError("app-server closed")
                buffer += chunk
                if len(buffer) > 2_000_000: raise RuntimeError("unexpected response size")
        raise TimeoutError("quota read timed out")
    try:
        write({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "node75_status", "title": "Node75 状态灯", "version": "1.3.1"},
            "capabilities": {"explicitGatewayOauth": True}}})
        receive(1)
        write({"method": "initialized"})
        write({"id": 2, "method": method, "params": params})
        value = receive(2)
        if not isinstance(value, dict): raise ValueError("quota unavailable")
        return value
    finally:
        process.stdin.close()
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        process.stdout.close()

def read_quota(executable, timeout=25):
    return read_official(executable, "account/rateLimits/read", {"excludeResetCreditDetails": True}, timeout)

def refresh(executable=None):
    now = time.time()
    cache = RUNTIME/"quota.json"
    try:
        config = json.loads((RUNTIME/"menubar-config.json").read_text())
    except (OSError, ValueError): config = {}
    executable = executable or config.get("codex") or shutil.which("codex")
    try:
        if not executable: raise FileNotFoundError("Codex CLI unavailable")
        values = windows(read_quota(executable))
        snapshot = {"windows": values, "updatedAt": now, "checkedAt": now, "stale": False,
                    "error": None if values else "额度数据暂不可用"}
    except (OSError, ValueError, RuntimeError, TimeoutError):
        try:
            previous = json.loads(cache.read_text())
        except (OSError, ValueError): previous = {}
        snapshot = {"windows": previous.get("windows", []), "updatedAt": previous.get("updatedAt"),
                    "checkedAt": now, "stale": True, "error": "额度刷新失败，显示上次记录"}
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = cache.with_name("quota.tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False)+"\n")
    temporary.chmod(0o600)
    os.replace(temporary, cache)
    return snapshot

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="通过已登录的 Codex 查询剩余使用额度")
    parser.add_argument("command", choices=("refresh",))
    parser.add_argument("--codex", help="官方 Codex CLI 路径")
    args = parser.parse_args()
    print(json.dumps(refresh(args.codex), ensure_ascii=False))
