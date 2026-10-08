import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from state import Aggregator, normalize
from install import COMMAND, merge
from node75_status import Preview

def event(name, session="a", turn="1", **fields):
    return dict(hook_event_name=name, session_id=session, turn_id=turn, **fields)

class StateTests(unittest.TestCase):
    def setUp(self):
        self.time=0
        self.a=Aggregator(lambda:self.time)

    def test_multiple_sessions_do_not_clear_each_other(self):
        self.a.handle(event("UserPromptSubmit"))
        self.a.handle(event("UserPromptSubmit","b"))
        self.a.handle(event("Stop"))
        self.assertEqual(self.a.effective(),"running")
        self.a.handle(event("PermissionRequest","b"))
        self.assertEqual(self.a.effective(),"attention")
        self.a.handle(event("PreToolUse","b"))
        self.a.handle(event("Stop","b"))
        self.assertEqual(self.a.effective(),"completed")
        self.time=10
        self.assertEqual(self.a.effective(),"idle")

    def test_late_events_and_interrupt(self):
        self.a.handle(event("UserPromptSubmit",turn="2"))
        self.a.handle(event("Stop",turn="1"))
        self.assertEqual(self.a.effective(),"running")
        self.a.handle(event("Stop",turn="2"))
        self.a.handle(event("PostToolUse",turn="2"))
        self.assertEqual(self.a.effective(),"completed")
        self.a.handle(event("Interrupt",turn="2"))
        self.assertEqual(self.a.effective(),"idle")

    def test_question_remains_pending_until_user_reply(self):
        self.a.handle(event("UserPromptSubmit"))
        self.a.handle(normalize(event("PostToolUse",tool_name="request_user_input_async",tool_response={"accepted":True})))
        self.a.handle(event("PostToolUse"))
        self.a.handle(event("Stop"))
        self.assertEqual(self.a.effective(),"attention")
        self.a.handle(event("UserPromptSubmit",turn="2"))
        self.assertEqual(self.a.effective(),"running")

    def test_invalid_and_sensitive_fields(self):
        self.assertIsNone(normalize([]))
        self.assertIsNone(normalize(event("Stop",session="")))
        value=normalize(event("Stop",prompt="private",tool_input={"secret":"private"}))
        self.assertNotIn("private",json.dumps(value))
        self.assertIsNone(normalize(event("Stop",agent_id="child")))

    def test_install_merge_preserves_unrelated_handlers(self):
        other={"type":"command","command":"echo unrelated"}
        old={"description":"keep","hooks":{"Stop":[{"matcher":"*","hooks":[other]}]}}
        added=merge(old,True)
        self.assertEqual(merge(added,True),added)
        self.assertEqual(merge(added,False),old)
        self.assertEqual(added["hooks"]["Stop"][-1]["hooks"][0]["command"],COMMAND)
        self.assertEqual(old["hooks"]["Stop"][0]["hooks"],[other])

    def test_hook_client_sends_only_status_and_returns_valid_stop_json(self):
        with tempfile.TemporaryDirectory(prefix="n75-test-") as directory:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.bind(directory+"/status.sock"); server.listen(1); server.settimeout(3)
                received=[]
                def receive():
                    connection,_=server.accept()
                    with connection:
                        connection.settimeout(2)
                        data=b""
                        while not data.endswith(b"\n"): data+=connection.recv(4096)
                        received.append(json.loads(data))
                thread=threading.Thread(target=receive,daemon=True);thread.start()
                result=subprocess.run([sys.executable,"-B",str(Path(__file__).with_name("node75_status.py")),"hook"],
                    input=json.dumps(event("Stop",prompt="private",tool_input={"secret":"private"})),
                    text=True,capture_output=True,timeout=3,env=dict(os.environ,NODE75_RUNTIME=directory))
                thread.join(3)
                self.assertEqual(result.returncode,0)
                self.assertEqual(json.loads(result.stdout),{})
                self.assertEqual(received,[event("Stop")])

    def test_absent_daemon_does_not_block_hook(self):
        with tempfile.TemporaryDirectory(prefix="n75-test-") as directory:
            result=subprocess.run([sys.executable,"-B",str(Path(__file__).with_name("node75_status.py")),"hook"],
                input=json.dumps(event("PermissionRequest")),text=True,capture_output=True,timeout=2,
                env=dict(os.environ,NODE75_RUNTIME=directory))
            self.assertEqual((result.returncode,result.stdout),(0,""))

    def test_preview_expires_and_restores_live_session(self):
        preview=Preview(lambda:self.time)
        self.a.handle(event("UserPromptSubmit"))
        preview.handle({"control":"preview","state":"completed"})
        self.assertEqual(preview.effective(self.a.effective()),"completed")
        self.a.handle(event("PermissionRequest"))
        self.time=5
        self.assertEqual(preview.effective(self.a.effective()),"attention")
        self.assertEqual(len(self.a.sessions),1)

    def test_preview_cancel_and_unrelated_event(self):
        preview=Preview(lambda:self.time)
        self.assertFalse(preview.handle(event("Stop")))
        self.assertFalse(preview.handle([]))
        preview.handle({"control":"preview","state":"attention"})
        preview.handle({"control":"preview","state":"idle"})
        self.assertEqual(preview.effective("running"),"running")
        preview.handle({"control":"preview","state":"arbitrary"})
        self.assertEqual(preview.effective("idle"),"idle")

if __name__ == "__main__": unittest.main()
