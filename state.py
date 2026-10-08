# SPDX-License-Identifier: MIT
"""Codex event aggregation; no prompt, tool arguments, or transcript is retained."""
import time

EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest", "Stop", "Interrupt", "SessionEnd")

def normalize(event):
    if not isinstance(event, dict):
        return None
    name, session = event.get("hook_event_name"), event.get("session_id")
    if name not in EVENTS or not isinstance(session, str) or not session or len(session) > 256:
        return None
    # Subagents use their parent's session_id; their Stop must not finish the parent.
    if event.get("agent_id") or event.get("subagent_id"):
        return None
    result = {"hook_event_name": name, "session_id": session}
    tool = event.get("tool_name", "")
    if isinstance(tool, str) and tool.endswith(("request_user_input", "request_user_input_async")):
        result["question"] = True
        if name == "PostToolUse":
            response = event.get("tool_response")
            result["question_pending"] = isinstance(response, dict) and response.get("accepted") is True
    # Normalized events are sent across the socket; preserve only these booleans.
    if event.get("question") is True:
        result["question"] = True
        result["question_pending"] = event.get("question_pending") is True
    turn = event.get("turn_id")
    if isinstance(turn, str) and len(turn) <= 256:
        result["turn_id"] = turn
    return result

class Aggregator:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.sessions = {}

    def handle(self, event):
        event = normalize(event)
        if event is None:
            return
        name, session = event["hook_event_name"], event["session_id"]
        current = self.sessions.get(session)
        turn = event.get("turn_id")
        if current and turn and current.get("turn_id") and turn != current["turn_id"] and name != "UserPromptSubmit":
            return  # Ignore delayed events from a previous turn.
        if name in ("Interrupt", "SessionEnd"):
            self.sessions.pop(session, None)
            return
        if current and current["state"] == "completed" and name in ("PreToolUse", "PostToolUse"):
            return  # Late tool completions cannot restart a finished turn.
        reason = None
        state = "attention" if name == "PermissionRequest" else "completed" if name == "Stop" else "running"
        if name == "PermissionRequest": reason = "permission"
        if event.get("question") and (name == "PreToolUse" or event.get("question_pending")):
            state, reason = "attention", "question"
        elif current and current.get("reason") == "question" and name != "UserPromptSubmit":
            if not (name == "PostToolUse" and event.get("question") and not event.get("question_pending")):
                state, reason = "attention", "question"
        self.sessions[session] = {"state": state, "reason": reason, "at": self.clock(), "turn_id": turn or (current or {}).get("turn_id")}

    def effective(self):
        now = self.clock()
        self.sessions = {k: v for k, v in self.sessions.items()
                         if now-v["at"] < (10 if v["state"] == "completed" else 43200)}
        states = {v["state"] for v in self.sessions.values()}
        return next((s for s in ("attention", "running", "completed") if s in states), "idle")
