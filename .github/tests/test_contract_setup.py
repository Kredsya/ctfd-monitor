import contextlib
import io
import json
import os
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from ctfd_monitor import installer
from ctfd_monitor.client import ApiError
from ctfd_monitor.config import load_credentials, load_profile

class SetupContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        repo=Path(__file__).resolve().parents[2]
        (self.root/'helpers').mkdir()
        for name in ('22.sh','25.sh'):
            shutil.copy2(repo/'helpers'/name,self.root/'helpers'/name)

    def test_url_matrix(self):
        for given,want in [('ctf.example','https://ctf.example'),('https://ctf.example/','https://ctf.example'),('https://ctf.example/sub/','https://ctf.example/sub'),('http://127.0.0.1:8000','http://127.0.0.1:8000')]:
            with self.subTest(given=given): self.assertEqual(installer.normalize_url(given),want)
        for value in ('','file:///etc/passwd','https://u:p@host','https://host/?token=secret','https://host/#x','https://host:invalid','https://ho st'):
            with self.subTest(value=value), self.assertRaises(ValueError): installer.normalize_url(value)

    def test_credential_file_schema_and_permission_matrix(self):
        p=self.root/'credentials.json'
        for value in ([],None,{'unknown':'x'},{'token':123}):
            with self.subTest(value=value):
                p.write_text(json.dumps(value)); p.chmod(0o600)
                with self.assertRaises(ValueError): load_credentials(p)
        p.write_text('{broken')
        with self.assertRaises(ValueError): load_credentials(p)
        p.write_text('{"token":"fixture-secret"}'); p.chmod(0o644)
        with self.assertRaises(ValueError): load_credentials(p)
        p.chmod(0o600)
        self.assertEqual(load_credentials(p)['token'],'fixture-secret')
        link=self.root/'link'; link.symlink_to(p)
        with self.assertRaises(ValueError): load_credentials(link)

    def test_cancelled_setup_preserves_existing_profile(self):
        local=self.root/'.ctfd-monitor-local'; local.mkdir()
        profile=local/'competition.toml'; profile.write_text('old profile')
        with patch('builtins.input',side_effect=KeyboardInterrupt), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(self.root),130)
        self.assertEqual(profile.read_text(),'old profile')

    def test_auth_failure_does_not_save_or_echo_remote_secret(self):
        output=io.StringIO()
        with patch('builtins.input',side_effect=['https://ctf.example','1','Example CTF']), patch('getpass.getpass',return_value='fixture-secret'), patch.object(installer,'verify',side_effect=ApiError('/auth',401,'fixture-secret')), contextlib.redirect_stdout(output):
            self.assertEqual(installer.main(self.root),1)
        self.assertFalse((self.root/'.ctfd-monitor-local').exists())
        self.assertNotIn('fixture-secret',output.getvalue())

    def test_failed_profile_commit_keeps_old_profile_and_credentials(self):
        local=self.root/'.ctfd-monitor-local'; local.mkdir()
        profile=local/'competition.toml'; profile.write_text('old profile')
        old=local/'credentials-old.json'; old.write_text('old secret')
        original=installer.private_write
        writes=[]
        def fail_commit(path,text):
            writes.append(path.name)
            if path.name=='competition.toml': raise OSError('disk full')
            return original(path,text)
        with patch('builtins.input',side_effect=['https://ctf.example','1','Example CTF']), patch('getpass.getpass',return_value='new-secret'), patch.object(installer,'verify',return_value=({'id':1},'ok')), patch.object(installer,'private_write',side_effect=fail_commit), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(self.root),1)
        self.assertEqual(profile.read_text(),'old profile')
        self.assertEqual(old.read_text(),'old secret')
        self.assertEqual(list(local.glob('credentials-*.json')),[old])
        self.assertIn('competition.toml',writes, 'The failure must actually reach the commit step')

    def test_setup_must_not_report_success_with_missing_required_assets(self):
        for name in ('22.sh','25.sh'): (self.root/'helpers'/name).unlink()
        output=io.StringIO()
        with patch('builtins.input',side_effect=['https://ctf.example','1','Example CTF']), patch('getpass.getpass',return_value='fixture-secret'), patch.object(installer,'verify',return_value=({'id':1},'ok')), contextlib.redirect_stdout(output):
            self.assertNotEqual(installer.main(self.root),0,'A checkout with neither helper is incomplete')
        self.assertFalse((self.root/'.ctfd-monitor-local/competition.toml').exists())

    def test_explicit_closed_competition_can_be_saved_but_not_claimed_live(self):
        from unittest.mock import Mock
        client=Mock()
        client.request_json.return_value={'data':{'id':1,'team_id':None}}
        client.request_json_routes.side_effect=ApiError('/challenges',403,'closed','competition_closed')
        user,status=installer.verify(client)
        self.assertEqual(user['id'],1)
        self.assertIn('제한',status)

    def test_unexplained_forbidden_is_not_misreported_as_contest_start_wait(self):
        from unittest.mock import Mock
        client=Mock()
        client.request_json.return_value={'data':{'id':1}}
        client.request_json_routes.side_effect=ApiError('/challenges',403,'Your account is banned','banned')
        with self.assertRaises(ApiError): installer.verify(client)
