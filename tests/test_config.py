import tempfile
import unittest
from pathlib import Path
from ctfd_monitor.config import load_profile

class ConfigTests(unittest.TestCase):
    def test_invalid_types_and_unknown_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'profile.toml'
            for content in ('url=1', 'poll_interval=true', 'poll_interval=nan', 'max_workers=1.5', 'max_workers=true', 'root=[]', 'koth="false"', 'token_env=""', 'account_mode="bad"', 'typo=1'):
                with self.subTest(content=content):
                    p.write_text(content)
                    with self.assertRaises(ValueError):
                        load_profile(p)
