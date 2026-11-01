import os
import subprocess
import tarfile
import unittest
import zipfile
import tempfile
import sys
from pathlib import Path
from scenarios import REPO

class DistributionContracts(unittest.TestCase):
    def test_installed_wheel_provisions_workspace_without_checkout(self):
        wheel=max((REPO/'dist').glob('ctfd_monitor-*.whl'),key=lambda p:p.stat().st_mtime)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            installed=root/'installed'
            result=subprocess.run([sys.executable,'-m','pip','install','--no-deps','--no-compile','--target',str(installed),str(wheel)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)
            (root/'competition.toml').write_text('url="https://fixture.invalid"\nroot="work"\n')
            code='''
from pathlib import Path
import threading
from ctfd_monitor import app
app.configure(Path('competition.toml'))
monitor=app.Monitor(app.SharedState(),threading.Event())
try:
    detail={'id':1,'name':'Wheel problem','description':'supplied description'}
    monitor.prepare_challenge(monitor.normalize_challenge(detail,detail))
    print(app.__version__)
finally:
    monitor.executor.shutdown()
'''
            env={k:v for k,v in os.environ.items() if not k.startswith('CTFD_MONITOR_')}
            env['PYTHONPATH']=str(installed)
            result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            problem=root/'work/1_Wheel_problem'
            self.assertTrue((problem/'chall/AGENTS.md').is_file())
            self.assertIn('supplied description',(problem/'chall/README.md').read_text())
            for name in ('22.sh','25.sh'):
                self.assertEqual((problem/name).read_bytes(),(REPO/name).read_bytes())
                self.assertTrue(os.access(problem/name,os.X_OK))

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
            for name in ('install.py','ctfd-monitor.py','22.sh','25.sh','lab.py','lab/__init__.py','lab/control.py','lab/smoke.py','setup.py','README.md'):
                with self.subTest(name=name):
                    self.assertIn(name,names)
                    if name.endswith('.sh'):
                        self.assertTrue(names[name].mode & 0o111)
                        self.assertEqual(archive.extractfile(names[name]).read(),(REPO/'.github/tests/fixtures/original'/name).read_bytes())
            self.assertFalse(any('.ctfd-monitor-local/' in name or '.ctfd-lab/' in name or name.endswith(('.env','.db')) for name in names))
            self.assertFalse(any(name.startswith(('docs/', 'examples/', 'tests/', '.github/')) or name == 'RELEASE-NOTES.md' for name in names))
            for helper in ('22.sh', '25.sh'):
                self.assertNotIn('src/ctfd_monitor/' + helper, names)

    def test_wheel_contains_runtime_helpers_and_no_local_secrets(self):
        wheels=sorted((REPO/'dist').glob('ctfd_monitor-*.whl'),key=lambda p:p.stat().st_mtime)
        self.assertTrue(wheels,'Run python -m build before the distribution gate')
        with zipfile.ZipFile(wheels[-1]) as wheel:
            names=wheel.namelist()
            for filename in ('22.sh','25.sh'):
                candidates=[name for name in names if name.endswith('/'+filename)]
                self.assertEqual(len(candidates),1,f'{filename} must exist in the installed package')
                if candidates:
                    self.assertEqual(wheel.read(candidates[0]),(REPO/'.github/tests/fixtures/original'/filename).read_bytes())
            self.assertFalse(any('.ctfd-monitor-local/' in name for name in names))
