import importlib.util
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ctfd_monitor import app as m

class Tests(unittest.TestCase):
    def test_profile_isolation_and_validation(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            p = Path(d) / 'profile.toml'
            p.write_text('url="https://one.example"\n')
            m.configure(p)
            first = m.STATE_DIR
            self.assertFalse(m.KOTH_ENABLED)
            p.write_text('url="https://two.example"\n')
            m.configure(p)
            self.assertNotEqual(first, m.STATE_DIR)
            p.write_text('url="https://two.example"\npoll_interval=0\n')
            with self.assertRaises(ValueError):
                m.configure(p)

    def test_cookie_login_and_route_cache(self):
        counts = {}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                if self.path == '/api/v2/auth/login':
                    self.send_response(404); self.end_headers(); return
                if self.path != '/login' or b'nonce=test-nonce' not in body:
                    self.send_response(403); self.end_headers(); return
                self.send_response(200)
                self.send_header('Set-Cookie', 'session=test; Path=/')
                self.end_headers()
            def do_GET(self):
                counts[self.path] = counts.get(self.path, 0) + 1
                if self.path == '/login':
                    self.send_response(200); self.end_headers()
                    self.wfile.write(b'<input name="nonce" value="test-nonce">'); return
                if self.path == '/missing':
                    self.send_response(404); self.end_headers(); return
                if self.headers.get('Cookie') != 'session=test':
                    self.send_response(401); self.end_headers(); return
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"success":true,"data":{"id":1}}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(m, 'TOKEN', ''):
                client = m.CTFdClient(f'http://127.0.0.1:{server.server_port}', 'user', 'password')
                client.login()
                self.assertTrue(client.logged_in)
                for _ in range(2):
                    client.request_json_routes(('/missing', '/available'))
                self.assertEqual(counts['/missing'], 1)
                self.assertEqual(counts['/available'], 2)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_redirect_removes_credentials_and_local_files_rejected(self):
        request = m.urllib.request.Request('https://ctf.example/a', headers={'Authorization': 'Token secret', 'Cookie': 'session=secret'})
        redirected = m.SafeRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://cdn.example/a')
        self.assertIsNone(redirected.get_header('Authorization'))
        self.assertIsNone(redirected.get_header('Cookie'))
        with self.assertRaises(ValueError):
            m.CTFdClient('https://ctf.example', '', '').open_file('file:///etc/passwd')

    def test_http_token_fallback_and_external_cookie(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                seen.append((self.path, self.headers.get('Authorization'), self.headers.get('Cookie')))
                if self.path.startswith('/api/') and self.headers.get('Content-Type') != 'application/json':
                    self.send_response(401); self.end_headers(); return
                if self.path == '/missing':
                    self.send_response(404)
                else:
                    self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"success":true,"data":[]}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            with patch.object(m, 'TOKEN', 'test-token'):
                client = m.CTFdClient(url, '', '', 'test-token')
                client.login()
                client.request_json_routes(('/missing', '/available'))
                self.assertEqual(seen[0][1], 'Token test-token')
                cookie = m.http.cookiejar.Cookie(0, 'session', 'secret', None, False, '127.0.0.1', False, False, '/', True, False, None, True, None, None, {})
                client.cookies.set_cookie(cookie)
                with client.open_file(f'http://localhost:{server.server_port}/file') as response:
                    response.read()
                self.assertIsNone(seen[-1][2])
                self.assertIsNone(seen[-1][1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

if __name__ == '__main__': unittest.main()
