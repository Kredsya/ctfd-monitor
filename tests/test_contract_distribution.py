import os
import subprocess
import tarfile
import unittest
import zipfile
from pathlib import Path
from scenarios import REPO

class DistributionContracts(unittest.TestCase):
    def test_git_ignores_secrets_but_tracks_helpers(self):
        ignored=subprocess.run(['git','check-ignore','.ctfd-monitor-local/credentials-test.json'],cwd=REPO,capture_output=True,text=True)
        self.assertEqual(ignored.returncode,0)
        tracked=subprocess.check_output(['git','ls-files','22.sh','25.sh'],cwd=REPO,text=True).splitlines()
        self.assertEqual(set(tracked),{'22.sh','25.sh'})

    def test_sdist_contains_launcher_installer_and_required_helpers(self):
        archives=sorted((REPO/'dist').glob('ctfd_monitor-*.tar.gz'),key=lambda p:p.stat().st_mtime)
        self.assertTrue(archives,'Run python -m build before the distribution gate')
        with tarfile.open(archives[-1]) as archive:
            members=archive.getmembers()
            names={'/'.join(m.name.split('/')[1:]):m for m in members}
            for name in ('install.py','ctfd-monitor.py','22.sh','25.sh'):
                with self.subTest(name=name):
                    self.assertIn(name,names)
                    if name.endswith('.sh'):
                        self.assertTrue(names[name].mode & 0o111)
                        self.assertEqual(archive.extractfile(names[name]).read(),(REPO/'tests/fixtures/original'/name).read_bytes())
            self.assertFalse(any('.ctfd-monitor-local/' in name or name.endswith('.env') for name in names))

    def test_wheel_contains_runtime_helpers_and_no_local_secrets(self):
        wheels=sorted((REPO/'dist').glob('ctfd_monitor-*.whl'),key=lambda p:p.stat().st_mtime)
        self.assertTrue(wheels,'Run python -m build before the distribution gate')
        with zipfile.ZipFile(wheels[-1]) as wheel:
            names=wheel.namelist()
            for filename in ('22.sh','25.sh'):
                candidates=[name for name in names if name.endswith('/'+filename)]
                self.assertEqual(len(candidates),1,f'{filename} must exist in the installed package')
                if candidates:
                    self.assertEqual(wheel.read(candidates[0]),(REPO/'tests/fixtures/original'/filename).read_bytes())
            self.assertFalse(any('.ctfd-monitor-local/' in name for name in names))
