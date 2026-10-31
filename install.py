#!/usr/bin/env python3
"""Interactive setup; standard library only, no package installation required."""
import sys
from pathlib import Path

if __name__ == '__main__':
    if sys.version_info < (3, 12) or sys.platform != 'linux':
        print('Linux와 Python 3.12 이상이 필요합니다.', file=sys.stderr)
        raise SystemExit(1)
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / 'src'))
    from ctfd_monitor.installer import main
    raise SystemExit(main(root))
