"""Deterministic, interactive configuration for a checkout."""
from __future__ import annotations

import getpass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.parse
import urllib.error
import uuid
import shutil

from .client import ApiError, CTFdClient
from .assets import validate_checkout
from . import __version__


def normalize_url(value: str) -> str:
    value = value.strip()
    if '://' not in value:
        value = 'https://' + value
    url = urllib.parse.urlsplit(value)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('대회 루트 URL을 입력하세요. 예: https://ctf.example.org')
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError('URL에 공백을 사용할 수 없습니다.')
    _ = url.port  # Validate malformed ports before sending a request.
    return value.rstrip('/')


def private_write(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.setup-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verify(client: CTFdClient) -> tuple[dict, str]:
    client.login()
    user = client.request_json('/api/v1/users/me').get('data')
    if not isinstance(user, dict) or type(user.get('id')) is not int:
        raise ValueError('계정 API 응답이 일반 CTFd 형식이 아닙니다.')
    try:
        result = client.request_json_routes(('/api/v1/challenges', '/api/v2/challenges'))
        if not isinstance(result.get('data'), list):
            raise ValueError('문제 목록 API 응답 형식이 올바르지 않습니다.')
        status = '문제 목록 조회 성공'
    except ApiError as error:
        if error.competition_unavailable:
            status = '인증 성공. 서버가 대회 기간에 따른 접근 제한을 알렸습니다. 문제 공개 여부는 아직 확인하지 못했습니다.'
        else:
            raise
    return user, status


def setup(root: Path) -> None:
    print(f'CTFd Monitor {__version__} 설치')
    print('인증 정보는 이 컴퓨터의 비공개 파일(0600)에 저장됩니다.')
    print('다시 실행하면 새 연결 검증에 성공한 뒤 기존 설정을 교체합니다.')
    url = normalize_url(input('대회 URL: '))
    mode = input('인증 방식 [1: CTFd 토큰(기본), 2: 아이디/비밀번호]: ').strip() or '1'
    if mode not in {'1', '2'}:
        raise ValueError('인증 방식은 1 또는 2를 입력하세요.')
    credentials = {'username': '', 'password': '', 'token': ''}
    if mode == '1':
        credentials['token'] = getpass.getpass('CTFd 토큰: ').strip()
        if not credentials['token']:
            raise ValueError('토큰을 입력하세요.')
    else:
        credentials['username'] = input('아이디: ').strip()
        credentials['password'] = getpass.getpass('비밀번호: ')
        if not credentials['username'] or not credentials['password']:
            raise ValueError('아이디와 비밀번호를 입력하세요.')
    client = CTFdClient(url, credentials['username'], credentials['password'], credentials['token'])
    print('인증과 API 연결을 확인합니다...')
    user, status = verify(client)
    print(status)
    validate_checkout(root)
    identity = hashlib.sha256(f"{url}:{user['id']}".encode()).hexdigest()[:12]
    local = root / '.ctfd-monitor-local'
    if local.is_symlink():
        raise ValueError('설정 디렉터리는 심볼릭 링크일 수 없습니다.')
    local.mkdir(mode=0o700, exist_ok=True)
    local.chmod(0o700)
    secret = local / f'credentials-{uuid.uuid4().hex}.json'
    private_write(secret, json.dumps(credentials, ensure_ascii=False))
    profile = {
        'name': urllib.parse.urlsplit(url).netloc,
        'url': url,
        'root': f'../workspace/{identity}',
        'credentials_file': secret.name,
        'poll_interval': 5.0,
        'max_workers': 4,
    }
    def toml_value(value):
        return json.dumps(value, ensure_ascii=False)
    try:
        private_write(local / 'competition.toml', '\n'.join(f'{key} = {toml_value(value)}' for key, value in profile.items()) + '\n')
    except BaseException:
        secret.unlink(missing_ok=True)
        raise
    # The profile replacement above is the commit point; earlier credentials stay usable on failure.
    for old in local.glob('credentials-*.json'):
        if old != secret and not old.is_symlink():
            try:
                old.unlink()
            except OSError:
                print('새 설정은 저장됐지만 이전 인증 파일을 정리하지 못했습니다. .ctfd-monitor-local/의 파일 권한을 확인하세요.')
    print('설치 완료. 실행: python3 ctfd-monitor.py')
    print(f'작업 폴더: {root / "workspace" / identity}')
    print('문제마다 22.sh(4개 창), 25.sh(10개 창), chall/AGENTS.md를 준비합니다.')
    if not shutil.which('tmux'):
        print('창 분할을 사용하려면 tmux를 설치하세요 (Ubuntu/Debian: sudo apt install tmux). 모니터는 바로 실행할 수 있습니다.')


def main(root: Path) -> int:
    try:
        setup(root)
        return 0
    except (KeyboardInterrupt, EOFError):
        print('\n설치를 취소했습니다. 기존 설정은 유지됩니다.')
        return 130
    except ApiError as error:
        # Do not echo remote response text, which may contain credentials.
        print(f'연결 검증 실패 (HTTP {error.status}). URL·인증 정보·대회 접근 권한을 확인하고 다시 실행하세요.')
        return 1
    except ValueError as error:
        print(f'설정 오류: {error}')
        return 1
    except (OSError, urllib.error.URLError):
        print('설치 실패. 네트워크 연결·설정 폴더 권한을 확인하고 다시 실행하세요.')
        return 1
