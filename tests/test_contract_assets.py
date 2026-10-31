"""Original monitor contracts: mandatory helpers, usable problem workspaces."""
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from scenarios import REPO, Scenario, m

class AssetContracts(Scenario):
    def test_checkout_contains_current_user_scripts(self):
        for name in ('22.sh', '25.sh'):
            with self.subTest(name=name):
                actual = REPO / name
                self.assertTrue(actual.is_file(), f'{name} must ship in a fresh clone')
                self.assertEqual(actual.read_bytes(), (REPO / 'tests/fixtures/original' / name).read_bytes())
                self.assertTrue(os.access(actual, os.X_OK))

    def test_default_requires_both_helpers(self):
        self.profile.write_text(f'url="{self.url}"\nroot="work"\n')
        m.configure(self.profile)
        self.assertTrue({'22.sh','25.sh'}.issubset(m.HELPER_FILES))

    def test_missing_helper_is_fatal_by_default(self):
        self.profile.write_text(f'url="{self.url}"\nroot="work"\n')
        m.configure(self.profile)
        with patch.object(m, 'SCRIPT_DIR', self.root), patch.object(Path, 'home', return_value=self.root):
            with self.assertRaises(FileNotFoundError):
                m.Monitor.find_helpers()

    def test_new_problem_has_agents_file_required_by_both_scripts(self):
        deploy = self.monitor.prepare_challenge(self.challenge())
        self.assertTrue((deploy.parent / 'AGENTS.md').is_file(), 'Both helpers refuse to start without chall/AGENTS.md')
        self.assertTrue((deploy.parent / 'AGENTS.md').read_text().strip())

    def test_copy_update_permissions_and_existing_work_preserved(self):
        m.BASE_DIR.mkdir(parents=True)
        for name in ('22.sh','25.sh'):
            shutil.copy2(REPO / 'tests/fixtures/original' / name, m.BASE_DIR / name)
        with patch.object(m, 'HELPER_FILES', ('22.sh','25.sh')):
            monitor = self.new_monitor()
        challenge = self.challenge()
        deploy = monitor.prepare_challenge(challenge)
        problem = deploy.parent.parent
        (problem / 'solution.py').write_text('my work')
        for name in ('22.sh','25.sh'):
            with self.subTest(name=name):
                self.assertEqual((problem/name).read_bytes(), (m.BASE_DIR/name).read_bytes())
                self.assertTrue(os.access(problem/name, os.X_OK))
                with (m.BASE_DIR/name).open('a') as f: f.write('\n# user update\n')
        monitor.prepare_challenge(challenge)
        for name in ('22.sh','25.sh'):
            self.assertEqual((problem/name).read_bytes(), (m.BASE_DIR/name).read_bytes())
        self.assertEqual((problem/'solution.py').read_text(), 'my work')
