#!/usr/bin/env python3
"""Run the checked-out monitor with the installer-generated profile."""
import sys
from pathlib import Path


def main():
    if sys.version_info < (3, 12) or sys.platform != 'linux':
        print('Linux와 Python 3.12 이상이 필요합니다.', file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / 'src'))
    if '--config' not in sys.argv and not any(arg.startswith('--config=') for arg in sys.argv):
        if not any(arg in ('--help', '-h', '--version') for arg in sys.argv):
            profile = root / '.ctfd-monitor-local' / 'competition.toml'
            if not profile.is_file():
                print('먼저 python3 install.py를 실행하세요.', file=sys.stderr)
                return 1
            sys.argv.extend(['--config', str(profile)])
    from ctfd_monitor.app import entrypoint
    return entrypoint()


if __name__ == '__main__':
    raise SystemExit(main())
