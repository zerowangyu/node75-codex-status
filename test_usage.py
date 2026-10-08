import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import usage

class UsageTests(unittest.TestCase):
    def test_prefers_actual_codex_bucket_and_window_duration(self):
        value = {"rateLimits": {"primary": {"usedPercent": 90, "windowDurationMins": 300}},
                 "rateLimitsByLimitId": {"codex": {"primary": {
                     "usedPercent": 13, "windowDurationMins": 10080, "resetsAt": 12345}}}}
        self.assertEqual(usage.windows(value), [{"name":"每周", "short":"周", "remainingPercent":87,
                         "windowDurationMins":10080, "resetsAt":12345}])

    def test_missing_windows_are_not_zero_and_percent_is_clamped(self):
        self.assertEqual(usage.windows({"rateLimits": {"primary": None, "secondary": {"usedPercent": None}}}), [])
        self.assertEqual(usage.windows({"rateLimitsByLimitId": {"other": {}}, "rateLimits": {"primary": {"usedPercent": 0}}}), [])
        values = usage.windows({"rateLimits": {"primary":{"usedPercent":120,"windowDurationMins":300},
                                              "secondary":{"usedPercent":-5,"windowDurationMins":10080}}})
        self.assertEqual([v["remainingPercent"] for v in values], [0,100])
        self.assertEqual(usage.windows({"rateLimits":{"primary":{"usedPercent": True}}}), [])

    def test_refresh_keeps_old_values_but_marks_them_stale(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(usage,"RUNTIME",Path(directory)):
            response = {"accountId":"DO_NOT_STORE", "credits":"DO_NOT_STORE", "rateLimits": {
                "primary":{"usedPercent":13,"windowDurationMins":10080}}}
            with patch.object(usage,"read_quota",return_value=response):
                first = usage.refresh("fake")
            with patch.object(usage,"read_quota",side_effect=TimeoutError()):
                second = usage.refresh("fake")
            self.assertTrue(second["stale"])
            self.assertEqual(second["windows"],first["windows"])
            self.assertEqual(second["updatedAt"],first["updatedAt"])
            cache = Path(directory)/"quota.json"
            self.assertNotIn("DO_NOT_STORE",cache.read_text())
            self.assertEqual(cache.stat().st_mode & 0o777,0o600)

    def test_official_protocol_reads_quota_without_starting_a_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            executable=Path(directory)/"fake-codex"
            executable.write_text("#!"+sys.executable+"\n"+'''import json,sys
for line in sys.stdin:
    message=json.loads(line)
    method=message["method"]
    if method=="initialize":
        print(json.dumps({"id":message["id"],"result":{}}),flush=True)
    elif method=="initialized":
        pass
    elif method=="account/rateLimits/read" and message["params"]=={"excludeResetCreditDetails":True}:
        print(json.dumps({"method":"account/rateLimits/updated","params":{}}),flush=True)
        print(json.dumps({"id":message["id"],"result":{"rateLimits":{"primary":{"usedPercent":25,"windowDurationMins":300}}}}),flush=True)
    else:
        sys.exit(2)
''')
            executable.chmod(0o755)
            result=usage.read_quota(str(executable),timeout=2)
            self.assertEqual(usage.windows(result)[0]["remainingPercent"],75)

if __name__ == "__main__": unittest.main()
