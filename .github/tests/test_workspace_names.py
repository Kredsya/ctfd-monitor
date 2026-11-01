import contextlib
import io
from unittest.mock import patch
from ctfd_monitor import installer
from scenarios import Scenario, m, REPO


class WorkspaceNames(Scenario):
    def test_names_without_ids_and_collision_suffixes_are_stable(self):
        self.publish([{'id':912,'name':'같은 문제'},{'id':5,'name':'같은 문제'},
                      {'id':71,'name':'같은_문제_2'},{'id':6,'name':'같은/문제'}])
        first=self.cycle()['challenges']
        names={key:value['directory'] for key,value in first.items()}
        self.assertEqual(names,{'912':'같은_문제','5':'같은_문제_2','71':'같은_문제_2_2','6':'같은_문제_3'})
        for key,name in names.items():
            (m.BASE_DIR/name/'solution.py').write_text(key)
        self.publish([{'id':6,'name':'renamed'},{'id':71,'name':'changed'},
                      {'id':5,'name':'same'},{'id':912,'name':'different'}])
        second=self.cycle(self.new_monitor())['challenges']
        self.assertEqual({key:value['directory'] for key,value in second.items()},names)
        for key,name in names.items():
            self.assertEqual((m.BASE_DIR/name/'solution.py').read_text(),key)

    def test_existing_untracked_and_casefold_paths_are_not_reused(self):
        (m.BASE_DIR/'Example').mkdir(parents=True)
        (m.BASE_DIR/'Example'/'user.txt').write_text('keep')
        self.assertEqual(self.challenge(id=1,name='example')['directory'],'example_2')
        self.assertEqual(self.challenge(id=2,name='EXAMPLE')['directory'],'EXAMPLE_3')
        self.assertEqual((m.BASE_DIR/'Example/user.txt').read_text(),'keep')

    def test_reserved_and_shell_names_remain_within_workspace(self):
        for index,name in enumerate(('.ctfd-monitor','..','../../bad','$(touch x)', '`pwd`', '가'*200),1):
            with self.subTest(name=name):
                value=self.challenge(id=index,name=name)['directory']
                self.assertFalse(value.startswith('.'))
                self.assertLessEqual(len(value.encode()),240)
                self.assertTrue((m.BASE_DIR/value).resolve().is_relative_to(m.BASE_DIR.resolve()))
                for unsafe in '/\\$`"':self.assertNotIn(unsafe,value)

    def test_missing_names_do_not_expose_ids(self):
        self.assertEqual(self.challenge(id=9876,name="")["directory"], "Unnamed_challenge")
        self.assertEqual(self.challenge(id=6543,name="")["directory"], "Unnamed_challenge_2")

    def test_saved_legacy_problem_paths_are_preserved(self):
        old=self.challenge();old['directory']='1_Example'
        self.monitor.previous={'challenges':{'1':old}}
        self.assertEqual(self.challenge()['directory'],'1_Example')

    def test_installer_uses_entered_contest_name(self):
        import shutil
        (self.root/'helpers').mkdir()
        for name in ('22.sh','25.sh'):
            shutil.copy2(REPO/'helpers'/name,self.root/'helpers'/name)
        with patch('builtins.input',side_effect=[self.url,'1','ACDC 2026 / Finals']),patch('getpass.getpass',return_value='fixture-token'),patch.object(installer,'verify',return_value=({'id':7},'ok')),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(self.root),0)
        from ctfd_monitor.config import load_profile
        profile=load_profile(self.root/'.ctfd-monitor-local/competition.toml')
        self.assertEqual(profile['name'],'ACDC 2026 / Finals')
        self.assertEqual(profile['root'],'../workspace/ACDC_2026___Finals')

    def test_directory_identity_survives_before_first_snapshot_is_saved(self):
        challenge=self.challenge(id=987,name='First download')
        deploy=self.monitor.prepare_challenge(challenge)
        (deploy/'solution.py').write_text('keep work')
        self.assertFalse(m.CURRENT_FILE.exists())
        restored=self.new_monitor()
        same=restored.normalize_challenge({'id':987},{'id':987,'name':'First download'})
        self.assertEqual(same['directory'],'First_download')
        self.assertEqual(restored.prepare_challenge(same),deploy)
        self.assertEqual((deploy/'solution.py').read_text(),'keep work')
        self.assertFalse((m.BASE_DIR/'First_download_2').exists())

    def test_failed_directory_mapping_write_retries_without_suffix(self):
        with patch.object(m,'atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.challenge(id=89,name='Retry')
        self.assertNotIn('89',self.monitor.challenge_directories)
        self.assertEqual(self.challenge(id=89,name='Retry')['directory'],'Retry')
        self.assertTrue(m.DIRECTORIES_FILE.is_file())
