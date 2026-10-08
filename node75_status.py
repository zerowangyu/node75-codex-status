#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Local-only hook client and single-owner Node75 status service."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time
from state import Aggregator, normalize

ROOT = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get("NODE75_RUNTIME", str(Path.home()/"Library/Application Support/Node75Codex")))
SOCKET = RUNTIME/"status.sock"

class Preview:
    """Short visual override; real session events still update underneath it."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = None
        self.until = 0

    def handle(self, event):
        if not isinstance(event, dict) or event.get("control") != "preview":
            return False
        mode = event.get("state")
        if mode == "idle":
            self.state = None
        elif mode in ("running", "attention", "completed"):
            self.state = mode
            self.until = self.clock()+5
        return True

    def effective(self, fallback):
        if self.state is not None and self.clock() < self.until:
            return self.state
        self.state = None
        return fallback

def send(event):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(0.25)
        client.connect(str(SOCKET))
        client.sendall(json.dumps(event, separators=(",", ":")).encode()+b"\n")

def hook():
    raw = {}
    try:
        raw = json.load(sys.stdin)
        event = normalize(raw)
        if event:
            send(event)
    except (OSError, ValueError, TypeError):
        pass  # Status reporting never blocks or fails a Codex operation.
    if isinstance(raw, dict) and raw.get("hook_event_name") == "Stop":
        print("{}")

def daemon():
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(RUNTIME, 0o700)
    lock = (RUNTIME/"owner.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("状态服务已经运行")
    halted = False
    def stop(signum, frame):
        nonlocal halted
        halted = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    aggregate = Aggregator()
    preview = Preview()
    helper = None
    desired = None
    health = "idle"
    input_access = None
    last_health = None
    helper_buffer = b""
    next_restart = 0
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        SOCKET.unlink(missing_ok=True)  # Only the lock owner can remove a stale socket.
        server.bind(str(SOCKET)); os.chmod(SOCKET, 0o600); server.listen(16)
        print("状态服务已启动："+str(SOCKET), flush=True)
        while not halted:
            if helper is None or helper.poll() is not None:
                if time.monotonic() >= next_restart:
                    if helper is not None:
                        helper.communicate(timeout=1)
                    helper = subprocess.Popen([str(ROOT/"node75_led")], stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    helper_buffer = b""; desired = None; health = "connecting"; input_access = None
                    next_restart = time.monotonic()+2
            watches = [server]
            if helper is not None and helper.poll() is None:
                watches.append(helper.stdout)
            readable, _, _ = select.select(watches, [], [], 0.1)
            for ready in readable:
                if ready is server:
                    conn, _ = server.accept()
                    with conn:
                        conn.settimeout(0.15)
                        data = b""
                        try:
                            while b"\n" not in data and len(data) <= 4096:
                                part = conn.recv(4096)
                                if not part: break
                                data += part
                            if len(data) <= 4096:
                                event = json.loads(data)
                                if not preview.handle(event):
                                    normalized = normalize(event)
                                    if normalized:
                                        aggregate.handle(normalized)
                                        receipt = RUNTIME/"hook-receipt.tmp"
                                        receipt.write_text(json.dumps({"event": normalized["hook_event_name"],
                                                                      "receivedAt": time.time()})+"\n")
                                        os.replace(receipt, RUNTIME/"hook-receipt.json")
                        except (OSError, ValueError, TypeError):
                            pass
                else:
                    helper_buffer += os.read(ready.fileno(), 4096)
                    while b"\n" in helper_buffer:
                        line, helper_buffer = helper_buffer.split(b"\n", 1)
                        message = line.decode(errors="replace")
                        if message.startswith("ACCESS input-monitoring "):
                            input_access = message.split()[2].rstrip(";") == "0"
                        if message.startswith("ERROR"):
                            health = message
                        elif message.startswith("CONNECTED"):
                            health = "connected"
                        elif message == "RESTORED":
                            health = "idle"
                        print(message, flush=True)
            current = preview.effective(aggregate.effective())
            if helper is not None and helper.poll() is None and current != desired:
                try:
                    helper.stdin.write((current+"\n").encode()); helper.stdin.flush()
                    desired = current
                except (BrokenPipeError, OSError):
                    desired = None; health = "helper unavailable"
            snapshot = {"state": current, "hardware": health, "sessions": len(aggregate.sessions),
                        "preview": preview.state is not None, "inputMonitoring": input_access}
            if snapshot != last_health:
                temporary = RUNTIME/"status.tmp"
                temporary.write_text(json.dumps(snapshot, ensure_ascii=False)+"\n")
                os.replace(temporary, RUNTIME/"status.json"); last_health = snapshot
                print("状态："+json.dumps(snapshot, ensure_ascii=False), flush=True)
    finally:
        if helper is not None and helper.poll() is None:
            try:
                helper.communicate(b"idle\nquit\n", timeout=3)
            except subprocess.TimeoutExpired:
                helper.terminate()
                try: helper.wait(timeout=3)
                except subprocess.TimeoutExpired: helper.kill(); helper.wait()
        server.close(); SOCKET.unlink(missing_ok=True); lock.close()

def main():
    parser = argparse.ArgumentParser(description="Node75 Codex 无线白灯状态提示")
    parser.add_argument("command", choices=("daemon", "hook", "status", "preview"))
    parser.add_argument("--mode", choices=("running", "attention", "completed", "idle"),
                        help="预览指定灯效5秒，然后恢复真实聊天状态")
    args = parser.parse_args()
    if args.command == "hook": hook()
    elif args.command == "daemon": daemon()
    elif args.command == "status":
        print((RUNTIME/"status.json").read_text() if SOCKET.exists() and (RUNTIME/"status.json").exists() else "状态服务尚未启动")
    else:
        if args.mode:
            send({"control": "preview", "state": args.mode})
        else:
            try:
                for mode in ("running", "attention", "completed"):
                    send({"control": "preview", "state": mode})
                    print(mode, flush=True); time.sleep(5)
            finally:
                send({"control": "preview", "state": "idle"})

if __name__ == "__main__":
    main()
