from contextlib import ExitStack
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch
import install
import integration
from state import EVENTS
from usage import read_official

class IntegrationTests(unittest.TestCase):
    def paths(self, directory, stack):
        app=Path(directory)/"App"
        hooks=Path(directory)/"Codex/hooks.json"
        plist=Path(directory)/"Agents/service.plist"
        command=shlex.quote(sys.executable)+" -B "+shlex.quote(str(app/"node75_status.py"))+" hook"
        for name,value in (("APP",app),("HOOKS",hooks),("PLIST",plist),("COMMAND",command)):
            stack.enter_context(patch.object(install,name,value))
        return app,hooks,plist,command

    def test_gui_repair_is_idempotent_and_preserves_other_hooks(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            app,hooks,plist,command=self.paths(directory,stack)
            hooks.parent.mkdir(parents=True)
            other={"type":"command","command":"echo preserve"}
            hooks.write_text(json.dumps({"description":"keep", "hooks":{"Stop":[{"hooks":[other]}]}}))
            stack.enter_context(patch.object(install,"service"))
            install.install_service()
            first=hooks.read_bytes()
            first_mtime=hooks.stat().st_mtime_ns
            backups=list(hooks.parent.glob("hooks.json.node75-backup-*"))
            install.install_service()
            self.assertEqual(hooks.read_bytes(),first)
            self.assertEqual(hooks.stat().st_mtime_ns,first_mtime)
            self.assertEqual(list(hooks.parent.glob("hooks.json.node75-backup-*")),backups)
            config=json.loads(first)
            self.assertEqual(config["description"],"keep")
            self.assertIn(other,config["hooks"]["Stop"][0]["hooks"])
            self.assertEqual(len(config["hooks"]),7)
            install.disconnect()
            self.assertEqual(install.read_hooks(),{"description":"keep","hooks":{"Stop":[{"hooks":[other]}]}})
            self.assertFalse(plist.exists())

    def test_official_metadata_filters_other_hooks_and_scopes(self):
        ours={"eventName":"preToolUse","command":install.COMMAND,"source":"user",
              "sourcePath":str(install.HOOKS),"enabled":True,"trustStatus":"trusted"}
        other=dict(ours,command="echo secret-unrelated")
        project=dict(ours,source="project")
        result=integration.own_metadata({"data":[{"hooks":[ours,other,project]}]})
        self.assertEqual(result,[{"event":"PreToolUse","enabled":True,"trust":"trusted"}])
        self.assertNotIn("secret-unrelated",json.dumps(result))

    def test_unavailable_official_trust_is_unknown_not_trusted(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            app,hooks,plist,command=self.paths(directory,stack)
            install.save_hooks(install.merge({},True))
            stack.enter_context(patch.object(integration,"codex_path",return_value=sys.executable))
            stack.enter_context(patch.object(integration,"read_official",side_effect=RuntimeError()))
            snapshot=integration.inspect()
            self.assertEqual(snapshot["configured"],7)
            self.assertIsNone(snapshot["trusted"])
            self.assertIsNone(snapshot["active"])
            self.assertIsNotNone(snapshot["trustError"])

    def test_official_client_cannot_write_trust_or_start_tasks(self):
        with patch("usage.subprocess.Popen") as spawn:
            for method in ("hooks/trust","thread/start","turn/start"):
                with self.assertRaises(ValueError): read_official("unused",method,{})
            spawn.assert_not_called()

    def test_access_is_read_from_the_controlling_background_process(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            app,hooks,plist,command=self.paths(directory,stack)
            app.mkdir()
            (app/"status.sock").touch()
            (app/"status.json").write_text(json.dumps({"hardware":"connected","inputMonitoring":True}))
            stack.enter_context(patch.object(integration,"codex_path",return_value=sys.executable))
            stack.enter_context(patch.object(integration,"read_official",return_value={"data":[]}))
            native=stack.enter_context(patch.object(integration.subprocess,"run"))
            self.assertTrue(integration.inspect()["inputMonitoring"])
            native.assert_not_called()

    def test_review_entry_opens_normal_official_cli_without_bypass(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            app,hooks,plist,command=self.paths(directory,stack)
            stack.enter_context(patch.object(integration,"codex_path",return_value=sys.executable))
            native=stack.enter_context(patch.object(integration.subprocess,"run"))
            integration.review_terminal()
            entry=app/"Codex-Hook-审阅.command"
            text=entry.read_text()
            self.assertIn("/hooks",text)
            self.assertNotIn("dangerously",text)
            self.assertIn("env TERM=xterm-256color "+shlex.quote(sys.executable),text)
            self.assertEqual(entry.stat().st_mode & 0o777,0o700)
            native.assert_called_once_with(["open","-a","Terminal",str(entry)],check=True)

if __name__ == "__main__": unittest.main()
