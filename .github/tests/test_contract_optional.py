import json
import os
from unittest.mock import patch
from scenarios import Scenario, m

class OptionalContracts(Scenario):
    def test_codex_missing_binary_is_reported(self):
        with patch.object(m.shutil,'which',return_value=None), self.assertRaises(RuntimeError):
            m.Monitor.read_codex_weekly_usage()

    def test_codex_response_parsing_uses_longest_window_and_terminates_child(self):
        binary=self.root/'codex-fixture'
        response={'id':1,'result':{'rateLimits':{'primary':{'windowDurationMins':300,'usedPercent':90},'secondary':{'windowDurationMins':10080,'usedPercent':25}}}}
        binary.write_text('#!/usr/bin/env python3\nimport sys,json,time\nsys.stdin.readline(); sys.stdin.readline()\nprint('+repr(json.dumps(response))+',flush=True)\ntime.sleep(30)\n')
        binary.chmod(0o755)
        with patch.object(m.shutil,'which',return_value=str(binary)):
            result=m.Monitor.read_codex_weekly_usage()
        self.assertEqual(result['remaining_percent'],75)
        self.assertEqual(result['window_minutes'],10080)
