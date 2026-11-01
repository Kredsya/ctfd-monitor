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
                actual = REPO / 'helpers' / name
                self.assertTrue(actual.is_file(), f'{name} must ship in a fresh clone')
                self.assertEqual(actual.read_bytes(), (REPO / '.github/tests/fixtures/original' / name).read_bytes())
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
            shutil.copy2(REPO / '.github/tests/fixtures/original' / name, m.BASE_DIR / name)
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

    def test_original_user_instructions_and_dynamic_category(self):
        original = (REPO / '.github/tests/fixtures/original/AGENTS.md').read_text()
        for category in ('web', 'Cryptography', 'pwnable', '리버싱'):
            with self.subTest(category=category):
                challenge = self.challenge(name='문제 {name}', category=category, description='설명 {literal}\nsecond line')
                deploy = self.monitor.prepare_challenge(challenge)
                expected = original.replace('<문제 제목>', challenge['name']).replace('<web, crypto, pwnable, 등등>', category).replace('<문제 설명>', challenge['description']).replace('너는 Cryptography 분야의 천재이다.', f'너는 {category} 분야의 천재이다.')
                expected = expected.replace('## Role', '## Files\n문제에서 제공된 파일은 `./deploy/` 디렉토리에 있다.\n\n## Role')
                self.assertEqual((deploy.parent / 'AGENTS.md').read_text(), expected)
                self.monitor.previous = {'challenges': {'1': challenge}}

    def test_legacy_generated_instructions_migrate_with_backup(self):
        from ctfd_monitor.assets import LEGACY_DEFAULT_AGENTS
        challenge = self.challenge()
        deploy = self.monitor.prepare_challenge(challenge)
        agents = deploy.parent / 'AGENTS.md'
        legacy = LEGACY_DEFAULT_AGENTS + f"\nLatest problem description: {deploy.parent / 'README.md'}\n"
        agents.write_text(legacy)
        self.monitor.prepare_challenge(challenge)
        self.assertIn('너는 misc 분야의 천재이다.', agents.read_text())
        self.assertEqual([p.read_text() for p in m.ARCHIVE_DIR.glob('1/*/AGENTS.md')], [legacy])
        self.monitor.prepare_challenge(challenge)
        self.assertEqual(len(list(m.ARCHIVE_DIR.glob('1/*/AGENTS.md'))), 1)

    def test_generated_description_refresh_after_restart_preserves_user_edits(self):
        self.publish([{'id':1,'name':'First','category':'web','description':'old'}])
        current = self.cycle()
        agents = m.BASE_DIR / current['challenges']['1']['directory'] / 'chall/AGENTS.md'
        restarted = self.new_monitor()
        self.publish([{'id':1,'name':'Renamed','category':'crypto','description':'new'}])
        self.cycle(restarted)
        self.assertIn('# Renamed\n분야: crypto\n\n## description\nnew', agents.read_text())
        edited = agents.read_text() + '\nMy solution notes\n'
        agents.write_text(edited)
        self.publish([{'id':1,'name':'Third','description':'latest'}])
        self.cycle(restarted)
        self.assertEqual(agents.read_text(), edited)
        self.assertIn('latest', (agents.parent/'README.md').read_text())

    def test_edited_legacy_and_custom_template_are_preserved_exactly(self):
        from ctfd_monitor.assets import LEGACY_DEFAULT_AGENTS
        deploy = self.monitor.prepare_challenge(self.challenge())
        agents = deploy.parent/'AGENTS.md'
        edited = LEGACY_DEFAULT_AGENTS + '\nuser notes'
        agents.write_text(edited)
        self.monitor.prepare_challenge(self.challenge())
        self.assertEqual(agents.read_text(), edited)
        agents.unlink()
        template = self.root/'custom.txt'; template.write_text('custom {category}\n')
        with patch.object(m, 'AGENTS_TEMPLATE', template):
            self.monitor.prepare_challenge(self.challenge())
        self.assertEqual(agents.read_text(), template.read_text())
