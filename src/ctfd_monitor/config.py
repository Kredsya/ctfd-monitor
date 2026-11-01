"""Strict profile validation shared by CLI and setup diagnostics."""
import math
import tomllib
from pathlib import Path
from .koth import ADAPTERS

STRINGS = {'name', 'url', 'root', 'state', 'agents_template', 'username_env', 'password_env', 'token_env', 'contest_end', 'credentials_file'}
LEGACY_AUTOMATIC_KEYS = {'codex_usage', 'auto_extract', 'account_mode', 'max_download_bytes', 'helpers'}
INTEGERS = {'max_workers'}


def load_profile(path: Path | None) -> dict:
    config = tomllib.loads(path.read_text(encoding='utf-8')) if path else {}
    for key in LEGACY_AUTOMATIC_KEYS:
        if key in config:
            value = config[key]
            if key in {'codex_usage', 'auto_extract'} and type(value) is not bool:
                raise ValueError(f'{key} must be boolean')
            if key == 'account_mode' and value not in ('auto', 'teams', 'users'):
                raise ValueError('account_mode must be auto, teams or users')
            if key == 'helpers' and (not isinstance(value, list) or any(not isinstance(x, str) or Path(x).name != x for x in value)):
                raise ValueError('helpers must be a list of file names')
            if key == 'max_download_bytes' and (type(value) is not int or value < 1):
                raise ValueError('max_download_bytes must be a positive integer')
        config.pop(key, None)
    unknown = set(config) - STRINGS - INTEGERS - {'poll_interval', 'koth', 'koth_sources'}
    if unknown:
        raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
    for key, value in config.items():
        if key in STRINGS and not isinstance(value, str):
            raise ValueError(f'{key} must be a string')
        if key in INTEGERS and (type(value) is not int or value < 1):
            raise ValueError(f'{key} must be a positive integer')
        if key == 'poll_interval' and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ValueError('poll_interval must be a finite positive number')
    for key in ('username_env', 'password_env', 'token_env'):
        if key in config and (not config[key] or '=' in config[key] or '\x00' in config[key]):
            raise ValueError(f'{key} must name an environment variable')
    if type(config.get('koth', False)) is not bool:
        raise ValueError('koth must be boolean')
    sources = config.get('koth_sources', [])
    if not isinstance(sources, list):
        raise ValueError('koth_sources must be a list')
    seen = set()
    from urllib.parse import urlsplit
    for source in sources:
        if not isinstance(source, dict) or set(source) != {'challenge_id', 'adapter', 'url', 'max_points'}:
            raise ValueError('koth_sources entries require challenge_id, adapter, url, max_points')
        identifier = source['challenge_id']
        if type(identifier) is not int or identifier < 1 or identifier in seen:
            raise ValueError('KOTH challenge_id must be positive and unique')
        seen.add(identifier)
        if not isinstance(source['adapter'], str) or source['adapter'] not in ADAPTERS:
            raise ValueError('Unknown KOTH adapter; see src/ctfd_monitor/koth.py and .github/USAGE.md#koth')
        if not isinstance(source['url'], str):
            raise ValueError('KOTH url must be HTTP(S)')
        url = urlsplit(source['url'])
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
            raise ValueError('KOTH url must be HTTP(S) without credentials')
        _ = url.port  # Reject malformed ports at configuration time.
        maximum = source['max_points']
        if type(maximum) not in (int, float) or not math.isfinite(maximum) or maximum <= 0:
            raise ValueError('KOTH max_points must be finite and positive')
    if config.get('koth', False) and not sources:
        raise ValueError('koth=true requires koth_sources; see .github/USAGE.md#koth')
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
