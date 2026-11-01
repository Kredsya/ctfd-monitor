import json
import fcntl
import struct
import termios
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import tarfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ctfd_monitor.config import load_profile

REPO = Path(__file__).resolve().parents[2]


def interactive_install(root, answers, env):
    master, slave = pty.openpty()
    process = subprocess.Popen([sys.executable, str(root / 'install.py')], stdin=slave, stdout=slave, stderr=slave, env=env, cwd='/tmp')
    os.close(slave)
    transcript = b''
    pending = b''
    deadline = time.monotonic() + 20
    index = 0
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                transcript += chunk
                pending += chunk
                if index < len(answers) and answers[index][0].encode() in pending:
                    os.write(master, (answers[index][1] + '\n').encode())
                    index += 1
                    pending = b''
            elif process.poll() is not None:
                break
        process.wait(timeout=5)
        return process.returncode, transcript.decode(errors='replace')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)


class InstallerTests(unittest.TestCase):
    def test_clone_setup_run_both_auth_modes_and_failed_reinstall(self):
        self.check_setup_and_run('checkout')

    def test_sdist_setup_run_both_auth_modes_and_failed_reinstall(self):
        self.check_setup_and_run('sdist')

    def check_setup_and_run(self, distribution):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def reply(self, status, data):
                self.send_response(status)
                self.end_headers()
                self.wfile.write(json.dumps({'success': status == 200, 'data': data}).encode())
            def authed(self):
                return self.headers.get('Cookie') == 'session=test' or (self.headers.get('Authorization') == 'Token test-secret-token' and self.headers.get('Content-Type') == 'application/json')
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                if self.path == '/api/v2/auth/login':
                    self.reply(404, None); return
                if self.path == '/login' and b'password=test-secret-password' in body and b'nonce=nonce' in body:
                    self.send_response(200)
                    self.send_header('Set-Cookie', 'session=test; Path=/')
                    self.end_headers()
                else: self.reply(401, None)
            def do_GET(self):
                if self.path == '/login':
                    self.send_response(200); self.end_headers()
                    self.wfile.write(b'<input name="nonce" value="nonce">'); return
                if not self.authed():
                    self.reply(401, None); return
                user = {'id': 1, 'name': 'Player', 'team_id': None}
                if self.path == '/files/provided.txt':
                    self.send_response(200); self.end_headers(); self.wfile.write(b'provided attachment'); return
                challenge = {'id':1,'name':'Installed problem','category':'misc','description':'fixture description','value':100,'files':['/files/provided.txt']}
                routes = {'/api/v1/users/me': user, '/api/v1/challenges': [challenge], '/api/v1/challenges/1': challenge, '/api/v1/users/me/solves': [], '/api/v1/scoreboard': []}
                self.reply(200 if self.path in routes else 404, routes.get(self.path))
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                if distribution == 'sdist':
                    archive=max((REPO/'dist').glob('ctfd_monitor-*.tar.gz'),key=lambda p:p.stat().st_mtime)
                    with tarfile.open(archive) as package:
                        package.extractall(root,filter='data')
                    root=next(root.glob('ctfd_monitor-*'))
                else:
                    shutil.copytree(REPO / 'src', root / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
                    for name in ('install.py', 'ctfd-monitor.py', '22.sh', '25.sh'):
                        if (REPO / name).is_file():
                            shutil.copy2(REPO / name, root / name)
                env = {k:v for k,v in os.environ.items() if not k.startswith('CTFD_MONITOR_') and k != 'PYTHONPATH'}
                env['PATH'] = os.defpath  # Isolate optional local Codex accounts.
                for mode in ('1', '2'):
                    with self.subTest(mode=mode):
                        answers = [('대회 URL: ', f'http://127.0.0.1:{server.server_port}'), ('비밀번호]: ', mode)]
                        answers += [('CTFd 토큰: ', 'test-secret-token')] if mode == '1' else [('아이디: ', 'player'), ('비밀번호: ', 'test-secret-password')]
                        code, transcript = interactive_install(root, answers, env)
                        self.assertEqual(code, 0, transcript)
                        self.assertNotIn('test-secret-token', transcript)
                        self.assertNotIn('test-secret-password', transcript)
                        profile = root / '.ctfd-monitor-local/competition.toml'
                        config = load_profile(profile)
                        self.assertNotIn('account_mode',config)
                        secret = profile.parent / config['credentials_file']
                        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
                        self.assertEqual(profile.parent.stat().st_mode & 0o777, 0o700)
                        self.assertEqual(len(list(profile.parent.glob('credentials-*.json'))), 1)
                        doctor = subprocess.run([sys.executable, str(root / 'ctfd-monitor.py'), 'doctor'], cwd='/tmp', env=env, capture_output=True, text=True, timeout=10)
                        self.assertEqual(doctor.returncode, 0, doctor.stderr)
                        self.assertEqual(json.loads(doctor.stdout)['checks']['credentials'], 'ok')
                        process = subprocess.Popen([sys.executable, str(root / 'ctfd-monitor.py')], env=env, cwd='/tmp', stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        lines = []
                        live = threading.Event()
                        def read():
                            for line in process.stdout:
                                lines.append(line)
                                if json.loads(line)['status'] == 'LIVE': live.set()
                        reader = threading.Thread(target=read, daemon=True)
                        reader.start()
                        try:
                            self.assertTrue(live.wait(15), ''.join(lines))
                        finally:
                            process.send_signal(signal.SIGTERM)
                            process.wait(timeout=10)
                            reader.join(5)
                            errors = process.stderr.read()
                            process.stdout.close(); process.stderr.close()
                        self.assertEqual(process.returncode, 0, errors)
                        problem = (profile.parent / config['root']).resolve() / '1_Installed_problem'
                        self.assertEqual((problem/'chall/deploy/provided.txt').read_bytes(),b'provided attachment')
                        self.assertTrue((problem/'chall/AGENTS.md').is_file())
                        for helper in ('22.sh','25.sh'):
                            self.assertTrue((problem/helper).is_file(), f'Installed monitor did not provision {helper}')
                            self.assertEqual((problem/helper).read_bytes(), (REPO/'.github/tests/fixtures/original'/helper).read_bytes())

                # The documented bare command must also work in an actual terminal.
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 60, 120, 0, 0))
                terminal = subprocess.Popen([sys.executable, str(root / 'ctfd-monitor.py')], stdin=slave, stdout=slave, stderr=slave, cwd='/tmp', env=env)
                os.close(slave)
                output = b''
                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        readable, _, _ = select.select([master], [], [], 0.2)
                        if readable:
                            try:
                                output += os.read(master, 65536)
                            except OSError:
                                break
                        if b'LIVE' in output:
                            break
                    self.assertIn(b'LIVE', output)
                    self.assertNotIn(b'CODEX WEEKLY', output)
                    self.assertNotIn(b'Traceback', output)
                finally:
                    terminal.send_signal(signal.SIGINT)
                    terminal.wait(timeout=10)
                    while select.select([master], [], [], 0.2)[0]:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError:
                            break
                        if not chunk:
                            break
                        output += chunk
                    os.close(master)
                self.assertEqual(terminal.returncode, 0)
                self.assertTrue(output.endswith(b"\x1b[0m\x1b[2J\x1b[H\x1b[?25h"), repr(output[-100:]))
                before = profile.read_bytes()
                code, transcript = interactive_install(root, [('대회 URL: ', f'http://127.0.0.1:{server.server_port}'), ('비밀번호]: ', '1'), ('CTFd 토큰: ', 'invalid-secret')], env)
                self.assertEqual(code, 1, transcript)
                self.assertEqual(profile.read_bytes(), before)
                self.assertNotIn('invalid-secret', transcript)
        finally:
            server.shutdown(); server.server_close(); worker.join()
