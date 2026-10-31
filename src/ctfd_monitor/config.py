"""Strict profile validation shared by CLI and setup diagnostics."""
import math
import tomllib
from pathlib import Path

STRINGS = {'name', 'url', 'root', 'state', 'agents_template', 'username_env', 'password_env', 'token_env', 'contest_end', 'account_mode', 'credentials_file'}
BOOLEANS = {'koth', 'codex_usage', 'auto_extract'}
INTEGERS = {'max_workers', 'max_download_bytes'}


def load_profile(path: Path | None) -> dict:
    config = tomllib.loads(path.read_text(encoding='utf-8')) if path else {}
    unknown = set(config) - STRINGS - BOOLEANS - INTEGERS - {'poll_interval', 'helpers'}
    if unknown:
        raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
    for key, value in config.items():
        if key in STRINGS and not isinstance(value, str):
            raise ValueError(f'{key} must be a string')
        if key in BOOLEANS and type(value) is not bool:
            raise ValueError(f'{key} must be boolean')
        if key in INTEGERS and (type(value) is not int or value < 1):
            raise ValueError(f'{key} must be a positive integer')
        if key == 'poll_interval' and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ValueError('poll_interval must be a finite positive number')
    if config.get('account_mode', 'auto') not in {'auto', 'teams', 'users'}:
        raise ValueError('account_mode must be auto, teams or users')
    for key in ('username_env', 'password_env', 'token_env'):
        if key in config and (not config[key] or '=' in config[key] or '\x00' in config[key]):
            raise ValueError(f'{key} must name an environment variable')
    return config


def load_credentials(path: Path) -> dict:
    """Read installer credentials only from a private regular file."""
    import json
    import os
    import stat
    if path.is_symlink():
        raise ValueError('credentials_file must not be a symlink')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('credentials_file must be owned by the current user with permissions 0600')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) - {'username', 'password', 'token'}:
        raise ValueError('Invalid credentials file')
    if any(not isinstance(value, str) for value in data.values()):
        raise ValueError('Credential values must be strings')
    return data
