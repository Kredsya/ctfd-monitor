import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

class IntegrationTests(unittest.TestCase):
    def test_headless_download_restart_and_probe(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.headers.get('Authorization') != 'Token test-token' or self.headers.get('Content-Type') != 'application/json':
                    self.send_response(401); self.end_headers()
                    self.wfile.write(b'{"success":false}')
                    return
                data = {'id': 1, 'name': 'Demo', 'category': 'misc', 'value': 100, 'description': 'hello', 'files': ['/files/demo.txt']}
                routes = {'/api/v1/users/me': {'id': 7, 'name': 'User'}, '/api/v1/teams/me': {'id': 7, 'name': 'Team'}, '/api/v1/challenges': [data], '/api/v1/challenges/1': data, '/api/v1/teams/me/solves': [], '/api/v1/scoreboard': [{'account_id': 7, 'name': 'Team', 'score': 100, 'pos': 1}]}
                if self.path == '/files/demo.txt':
                    self.send_response(200); self.end_headers(); self.wfile.write(b'attachment'); return
                self.send_response(200 if self.path in routes else 404)
                self.end_headers()
                self.wfile.write(json.dumps({'success': self.path in routes, 'data': routes.get(self.path)}).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                profile = root / 'config.toml'
                profile.write_text(f'url="http://127.0.0.1:{server.server_port}"\nroot="work"\npoll_interval=0.1\n')
                env = {k: v for k, v in os.environ.items() if not k.startswith('CTFD_MONITOR_')}
                env['CTFD_MONITOR_TOKEN'] = 'test-token'
                command = [sys.executable, '-m', 'ctfd_monitor', '--config', str(profile)]
                probe = subprocess.run(command + ['probe'], env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(probe.returncode, 0, probe.stderr)
                self.assertEqual(json.loads(probe.stdout)['checks']['challenges'], 'ok')
                for _ in range(2):
                    process = subprocess.Popen(command + ['--headless', 'run'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    lines = []
                    live = threading.Event()
                    def collect():
                        for line in process.stdout:
                            lines.append(line)
                            if json.loads(line)['status'] == 'LIVE':
                                live.set()
                    reader = threading.Thread(target=collect, daemon=True)
                    reader.start()
                    try:
                        deadline = time.monotonic() + 10
                        attachment = root / 'work/Demo/chall/deploy/demo.txt'
                        while time.monotonic() < deadline:
                            if attachment.exists() and list((root / 'work/.ctfd-monitor').glob('*/current.json')):
                                break
                            if process.poll() is not None: break
                            time.sleep(0.05)
                        self.assertEqual(attachment.read_bytes(), b'attachment')
                        self.assertTrue(live.wait(10), "monitor did not report LIVE")
                    finally:
                        process.send_signal(signal.SIGTERM)
                        process.wait(timeout=10)
                        reader.join(timeout=5)
                        err = process.stderr.read()
                        out = "".join(lines)
                        process.stdout.close()
                        process.stderr.close()
                    self.assertEqual(process.returncode, 0, err)
                    self.assertTrue(any(json.loads(line)['status'] == 'LIVE' for line in out.splitlines()), out)
                events = next((root / 'work/.ctfd-monitor').glob('*/events.jsonl')).read_text().splitlines()
                self.assertEqual(sum(json.loads(line)['kind'] == 'NEW' for line in events), 1)
        finally:
            server.shutdown(); server.server_close(); thread.join()
