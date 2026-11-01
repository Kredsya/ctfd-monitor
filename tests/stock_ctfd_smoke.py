"""Read-only client checks against an isolated official CTFd image.

Run: PYTHONPATH=src python3 tests/stock_ctfd_smoke.py [--sudo]
Docker is required only for this developer test, never for monitor installation.
"""
import argparse
import subprocess
import time
import urllib.request
import uuid

from ctfd_monitor.client import ApiError, CTFdClient
from ctfd_monitor.installer import verify

IMAGE = 'ctfd/ctfd:3.8.9@sha256:84aff1e50b6a6f931b5da90c6f5b7c623ba4583217a9b00e9d4c1b7c53b9739f'
SEED = '''
from datetime import datetime, timedelta
from CTFd import create_app
from CTFd.models import db, Users, Challenges, UserTokens
from CTFd.utils import set_config
app=create_app()
with app.app_context():
    for key,value in {'setup':True,'ctf_name':'Monitor smoke test','user_mode':'users','challenge_visibility':'private','score_visibility':'public','account_visibility':'public'}.items():
        set_config(key,value)
    user=Users(name='monitor-test',email='monitor@example.invalid',password='local-test-password',verified=True)
    db.session.add(user)
    db.session.commit()
    db.session.add(UserTokens(user_id=user.id,value='ctfd_local_smoke_test_only'))
    set_config('start', 1)
    set_config('end', 1893456000)
    db.session.add(UserTokens(user_id=user.id,value='ctfd_expired_fixture_only',expiration=datetime.utcnow()-timedelta(days=1)))
    db.session.add(Challenges(name='Smoke',description='Read-only test challenge',category='misc',value=100,type='standard',state='visible'))
    db.session.commit()
'''

TEAM_SEED = """
from CTFd import create_app
from CTFd.models import db, Users, Teams
from CTFd.utils import set_config
app=create_app()
with app.app_context():
    set_config('user_mode', 'teams')
    set_config('end', 1893459600)
    team=Teams(name='Monitor team',email='team@example.invalid',password='local-test-password')
    db.session.add(team)
    db.session.flush()
    user=Users.query.filter_by(name='monitor-test').one()
    user.team_id=team.id
    db.session.commit()
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sudo', action='store_true')
    args = parser.parse_args()
    prefix = ['sudo', '-n', 'docker'] if args.sudo else ['docker']
    name = 'ctfd-monitor-smoke-' + uuid.uuid4().hex[:12]
    def docker(*args, **kwargs):
        return subprocess.run(prefix + list(args), check=True, capture_output=True, text=True, **kwargs).stdout
    try:
        docker('run', '-d', '--name', name, '-p', '127.0.0.1::8000', '-e', 'DATABASE_URL=sqlite:////tmp/monitor-test.db', '-e', 'SECRET_KEY=monitor-local-test-only', '-e', 'WORKERS=1', IMAGE, timeout=180)
        port = docker('port', name, '8000/tcp').strip().rsplit(':', 1)[1]
        url = 'http://127.0.0.1:' + port
        for _ in range(60):
            try:
                with urllib.request.urlopen(url + '/setup', timeout=2) as response:
                    if response.status == 200: break
            except (OSError, TimeoutError):
                time.sleep(1)
        else:
            raise RuntimeError('Stock CTFd did not become ready')
        docker('exec', '-i', name, 'python', '-', input=SEED, timeout=30)
        for mode in ('token', 'password'):
            client = CTFdClient(url, 'monitor-test' if mode == 'password' else '', 'local-test-password' if mode == 'password' else '', 'ctfd_local_smoke_test_only' if mode == 'token' else '')
            assert client.fetch_contest_end() == '2030-01-01T00:00:00+00:00'
            user, status = verify(client)
            assert client.fetch_contest_end() == '2030-01-01T00:00:00+00:00'
            assert user['name'] == 'monitor-test'
            assert client.request_json('/api/v1/challenges/1')['data']['name'] == 'Smoke'
            assert isinstance(client.request_json('/api/v1/users/me/solves')['data'], list)
            print(mode + ': authentication, challenge list/detail and solves passed')
        for bad_token in ('ctfd_invalid_fixture_only','ctfd_expired_fixture_only'):
            try:
                CTFdClient(url, '', '', bad_token).login()
            except ApiError as error:
                assert error.status == 401
            else:
                raise AssertionError('Invalid/expired token was accepted')
        try:
            CTFdClient(url, 'monitor-test', 'wrong-password').login()
        except ApiError as error:
            assert error.status == 401
        else:
            raise AssertionError('Invalid password was accepted')
        print('invalid token, expired token and invalid password rejected')
        docker('exec', '-i', name, 'python', '-', input=TEAM_SEED, timeout=30)
        docker('restart', name, timeout=30)
        port = docker('port', name, '8000/tcp').strip().rsplit(':', 1)[1]
        url = 'http://127.0.0.1:' + port
        for _ in range(60):
            try:
                with urllib.request.urlopen(url + '/login', timeout=2) as response:
                    if response.status == 200: break
            except (OSError, TimeoutError):
                time.sleep(1)
        else:
            raise RuntimeError('Stock CTFd did not restart')
        for mode in ('token', 'password'):
            client = CTFdClient(url, 'monitor-test' if mode == 'password' else '', 'local-test-password' if mode == 'password' else '', 'ctfd_local_smoke_test_only' if mode == 'token' else '')
            assert client.fetch_contest_end() == '2030-01-01T01:00:00+00:00'
            user, _ = verify(client)
            assert user['team_id']
            assert client.request_json('/api/v1/teams/me')['data']['name'] == 'Monitor team'
            assert isinstance(client.request_json('/api/v1/teams/me/solves')['data'], list)
            assert client.fetch_contest_end() == '2030-01-01T01:00:00+00:00'
            print('teams/' + mode + ': account detection, team profile and solves passed')
        print('stock public deadline: token/password, before/after login, and changed end passed')
    finally:
        subprocess.run(prefix + ['rm', '-f', name], capture_output=True)


if __name__ == '__main__':
    main()
