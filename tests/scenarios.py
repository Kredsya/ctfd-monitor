"""Black-box HTTP fixture and isolated on-disk workspace for lifecycle tests."""
import copy
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from ctfd_monitor import app as m

REPO = Path(__file__).resolve().parents[1]


class Scenario(unittest.TestCase):
    def setUp(self):
        original = {k:v for k,v in vars(m).items() if k.isupper()}
        self.addCleanup(lambda: vars(m).update(original))
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.routes = {}
        self.requests = []
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                fixture.requests.append((self.path, dict(self.headers)))
                route = fixture.routes.get(urlsplit(self.path).path, (404, {'success':False}, {}))
                if callable(route):
                    route = route(self)
                if route is None:
                    return
                status, value, headers = route
                if self.path.startswith('/api/') and (self.headers.get('Authorization') != 'Token fixture-token' or self.headers.get('Content-Type') != 'application/json'):
                    status, value, headers = 401, {'success':False}, {}
                body = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(status)
                for key, value in headers.items(): self.send_header(key, str(value))
                self.end_headers()
                try: self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        def finish():
            self.server.shutdown(); self.server.server_close(); thread.join()
        self.addCleanup(finish)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.profile = self.root / 'competition.toml'
        # Explicitly disable helpers ONLY for independent network/storage tests.
        # Default/helper contracts are tested separately without this override.
        self.profile.write_text(f'url="{self.url}"\nroot="work"\nhelpers=[]\n')
        os.environ['CTFD_MONITOR_TOKEN'] = 'fixture-token'
        m.configure(self.profile)
        self.ok('/api/v1/users/me', {'id': 7, 'name': 'Player'})
        self.ok('/api/v1/teams/me', {'id': 7, 'name': 'Team', 'score':0})
        self.ok('/api/v1/teams/me/solves', [])
        self.ok('/api/v1/users/me/solves', [])
        self.ok('/api/v1/scoreboard', [{'account_id':7, 'name':'Team', 'score':0, 'pos':1}])
        self.monitor = self.new_monitor()

    def ok(self, path, data):
        self.routes[path] = (200, {'success':True, 'data':data}, {})

    def new_monitor(self):
        monitor = m.Monitor(m.SharedState(), threading.Event())
        self.addCleanup(lambda: monitor.executor.shutdown(wait=True, cancel_futures=True))
        return monitor

    def challenge(self, **changes):
        detail = {'id':1, 'name':'Example', 'category':'misc', 'value':100, 'description':'first', 'files':[], 'hints':[]}
        detail.update(changes)
        return self.monitor.normalize_challenge(detail, detail)

    def publish(self, details):
        self.ok('/api/v1/challenges', details)
        for detail in details: self.ok(f"/api/v1/challenges/{detail['id']}", detail)

    def cycle(self, monitor=None):
        monitor = monitor or self.monitor
        current, raw = monitor.fetch_snapshot()
        monitor.process_snapshot(current, raw)
        return current

    def download(self, body=b'content', name='file.bin', headers=None, monitor=None):
        monitor = monitor or self.monitor
        self.routes['/files/' + name] = (200, body, headers or {})
        challenge = self.challenge(files=['/files/' + name])
        file = challenge['files'][0]
        deploy = monitor.prepare_challenge(challenge)
        monitor.download_worker(challenge, file, deploy, True, (1, name))
        return challenge, file, deploy
