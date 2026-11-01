"""Product-level boundaries added while repairing the failed v0.2 contracts."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ctfd_monitor import installer
from scenarios import Scenario, REPO, m
from test_contract_transfers import zip_bytes
from test_contract_runtime import ControlledStop


class WorkspaceReleaseContracts(Scenario):
    def test_remote_title_cannot_become_worker_shell_substitution(self):
        challenge=self.challenge(name='한글 $(touch marker) `touch marker` "quoted" \\ name')
        for character in ('$', '`', '"', '\\'):
            self.assertNotIn(character,challenge['directory'])
        self.assertIn('한글',challenge['directory'])
        deploy=self.monitor.prepare_challenge(challenge)
        self.assertTrue((deploy.parent/'README.md').is_file())

    def test_failed_reextraction_replaces_previous_complete_status(self):
        challenge,file,deploy=self.download(zip_bytes([('data',b'original')]),'data.zip')
        self.assertEqual(self.monitor.manifest['1/data.zip']['extraction']['status'],'complete')
        (deploy/'data.zip').write_bytes(zip_bytes([('../escape',b'invalid')]))
        self.monitor.apply_extraction(challenge,file,deploy/'data.zip',deploy)
        self.assertEqual((deploy/'data').read_bytes(),b'original')
        self.assertEqual(self.monitor.manifest['1/data.zip']['extraction']['status'],'error')
        self.assertEqual(json.loads(m.MANIFEST_FILE.read_text())['1/data.zip']['extraction']['status'],'error')

    def test_probe_reports_required_access_failure_with_nonzero_exit(self):
        self.publish([])
        for status in (200,403,503):
            with self.subTest(status=status):
                if status != 200:
                    self.routes['/api/v1/challenges']=(status,{'success':False,'code':'blocked'}, {})
                output=io.StringIO()
                with contextlib.redirect_stdout(output): code=m.diagnose(True)
                self.assertEqual(code,0 if status==200 else 1)
                report=json.loads(output.getvalue())
                self.assertEqual(report['checks']['login'],'ok')
                self.assertEqual(report['checks']['challenges']=='ok',status==200)

    def test_custom_instructions_survive_description_refresh(self):
        template=self.root/'instructions.md'; template.write_text('User custom rules')
        with patch.object(m,'AGENTS_TEMPLATE',template):
            deploy=self.monitor.prepare_challenge(self.challenge())
        instructions=deploy.parent/'AGENTS.md'
        self.assertIn('User custom rules',instructions.read_text())
        instructions.write_text('In-progress instructions')
        self.monitor.prepare_challenge(self.challenge(description='new problem description'))
        self.assertEqual(instructions.read_text(),'In-progress instructions')
        self.assertIn('new problem description',(deploy.parent/'README.md').read_text())

    def test_default_checkout_helpers_override_packaged_copy(self):
        package=self.root/'clone/src/ctfd_monitor'; package.mkdir(parents=True)
        for name in ('22.sh','25.sh'):
            (package/name).write_text('packaged')
            (package.parent.parent/name).write_text('user modified checkout')
        with patch.object(m,'SCRIPT_DIR',package),patch.object(m,'HELPER_FILES',('22.sh','25.sh')):
            found=m.Monitor.find_helpers()
        self.assertEqual({p.read_text() for p in found.values()},{'user modified checkout'})

    def test_preflight_rejects_entire_archive_before_publishing(self):
        for name in ('data.zip','link/escape','directory'):
            with self.subTest(name=name):
                deploy=self.monitor.prepare_challenge(self.challenge())
                outside=self.root/'outside'; outside.mkdir(exist_ok=True)
                (deploy/'link').unlink(missing_ok=True)
                (deploy/'link').symlink_to(outside)
                (deploy/'directory').mkdir(exist_ok=True)
                self.download(zip_bytes([('aaa-valid',b'must not publish'),(name,b'invalid')]),'data.zip')
                self.assertFalse((deploy/'aaa-valid').exists())
                self.assertEqual(self.monitor.state.jobs[-1].state,'ERROR')

    def test_restart_stays_stale_until_server_success(self):
        self.publish([{'id':1,'name':'Saved','files':[]}]); self.cycle()
        restarted=self.new_monitor()
        self.assertEqual(restarted.state.status,'STALE')
        self.assertIn('1',restarted.state.challenges)
        self.cycle(restarted)
        self.assertEqual(restarted.state.status,'LIVE')

    def test_banned_response_never_looks_like_pre_start(self):
        self.publish([{'id':1,'name':'Saved','files':[]}]); self.cycle()
        self.routes['/api/v1/challenges']=(403,{'success':False,'code':'banned','message':'Your ban started yesterday'}, {})
        self.monitor.stop=ControlledStop(self.monitor,[]); self.monitor.run()
        self.assertEqual(self.monitor.state.status,'STALE')
        self.assertIn('1',self.monitor.state.challenges)
        self.assertTrue(any('banned' in event['message'] or 'ban started' in event['message'] for event in self.monitor.state.events))

    def test_standard_scoreboard_omits_unavailable_acdc_metrics(self):
        view=self.monitor.state.view()
        view.update(team_name='Ours',scoreboard=[{'name':'Other','pos':1,'score':150},{'name':'Ours','pos':2,'score':100}])
        rendered='\n'.join(m.render_team_comparison(view,120))
        self.assertIn('+50',rendered)
        for unsupported in ('BRK','NEU','SHF','BAT'):
            self.assertNotIn(unsupported,rendered)
        self.assertIn('JEOPARDY CHALLENGE',rendered)

    def test_terminal_controls_and_width_bounds(self):
        for attack in ('\x1b]52;c;payload\x07','\x1b[2J','\x1b[1;1H','\x1bPpayload\x1b\\','\x9b2J','\r\nINJECTED'):
            self.monitor.state.team_name=attack
            for columns,rows in ((1,1),(3,3),(40,10),(80,24)):
                with self.subTest(attack=repr(attack),columns=columns),patch.object(m.shutil,'get_terminal_size',return_value=os.terminal_size((columns,rows))):
                    rendered=m.render_screen(self.monitor.state.view())
                    plain=m.ANSI_RE.sub('',rendered)
                    self.assertNotIn('\x1b',plain)
                    self.assertNotIn('\x9b',plain)
                    self.assertLessEqual(len(rendered.splitlines()),rows)
                    self.assertTrue(all(m.display_width(line)<=columns for line in rendered.splitlines()))


class SetupReleaseContracts(unittest.TestCase):
    def test_old_secret_cleanup_failure_does_not_claim_committed_setup_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('22.sh','25.sh'): shutil.copy2(REPO/name,root/name)
            local=root/'.ctfd-monitor-local'; local.mkdir()
            old=local/'credentials-old.json'; old.write_text('old secret')
            unlink=Path.unlink
            def deny_old(path,*args,**kwargs):
                if path==old: raise PermissionError('cleanup denied')
                return unlink(path,*args,**kwargs)
            output=io.StringIO()
            with patch('builtins.input',side_effect=['https://ctf.example','1']),patch('getpass.getpass',return_value='fixture-secret'),patch.object(installer,'verify',return_value=({'id':1},'ok')),patch.object(Path,'unlink',deny_old),contextlib.redirect_stdout(output):
                self.assertEqual(installer.main(root),0)
            self.assertTrue((local/'competition.toml').is_file())
            self.assertTrue(old.is_file())
            self.assertIn('설치 완료',output.getvalue())
            self.assertIn('정리하지 못했습니다',output.getvalue())
            self.assertNotIn('fixture-secret',output.getvalue())

    def test_each_incomplete_helper_keeps_old_configuration(self):
        for name in ('22.sh','25.sh'):
            for damage in ('missing','empty','not executable'):
                with self.subTest(name=name,damage=damage),tempfile.TemporaryDirectory() as directory:
                    root=Path(directory)
                    for helper in ('22.sh','25.sh'): shutil.copy2(REPO/helper,root/helper)
                    broken=root/name
                    if damage=='missing': broken.unlink()
                    elif damage=='empty': broken.write_bytes(b'')
                    else: broken.chmod(0o600)
                    local=root/'.ctfd-monitor-local'; local.mkdir()
                    profile=local/'competition.toml'; profile.write_text('old config')
                    output=io.StringIO()
                    with patch('builtins.input',side_effect=['https://ctf.example','1']),patch('getpass.getpass',return_value='fixture-secret'),patch.object(installer,'verify',return_value=({'id':1},'ok')),contextlib.redirect_stdout(output):
                        self.assertEqual(installer.main(root),1)
                    self.assertIn(name,output.getvalue())
                    self.assertNotIn('설치 완료',output.getvalue())
                    self.assertEqual(profile.read_text(),'old config')
