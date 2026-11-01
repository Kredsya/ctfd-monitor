import copy
import json
from unittest.mock import patch
from scenarios import Scenario, m

class LifecycleContracts(Scenario):
    def test_publish_unchanged_update_solve_delete_and_restart(self):
        detail = {'id':1,'name':'One','category':'misc','value':100,'description':'first','files':[]}
        self.publish([detail]); self.cycle(); self.cycle()
        detail.update(description='changed', solved_by_me=True)
        self.publish([detail]); self.cycle(); self.cycle()
        self.publish([]); self.cycle(); self.cycle()
        events = [json.loads(line)['kind'] for line in m.EVENT_FILE.read_text().splitlines()]
        self.assertEqual(events, ['NEW','UPDATED','SOLVED','DELETED'])
        self.cycle(self.new_monitor())
        self.assertEqual(len(m.EVENT_FILE.read_text().splitlines()), 4)
        self.assertTrue((m.BASE_DIR/'One/chall').is_dir())

    def test_team_only_change_is_persisted_for_restart(self):
        self.publish([]); self.cycle()
        self.ok('/api/v1/teams/me', {'id':7,'name':'Renamed','score':42})
        self.cycle()
        self.assertTrue(m.CURRENT_FILE.exists(), 'Empty contest still needs a persistent account snapshot')
        self.assertEqual(json.loads(m.CURRENT_FILE.read_text())['team']['name'], 'Renamed')

    def test_scoreboard_matching_does_not_match_two_missing_ids(self):
        rows = [{'name':'Wrong','score':999},{'account_id':7,'name':'Team','score':12}]
        self.assertEqual(self.monitor.scoreboard_team(rows, {'id':7,'name':'Team'})['name'], 'Team')

    def test_same_name_rename_and_unicode_keep_identity(self):
        self.publish([{'id':i,'name':'같은 이름 🧪','description':'x','files':[]} for i in (1,2)])
        first = self.cycle()
        dirs = {k:v['directory'] for k,v in first['challenges'].items()}
        self.assertEqual(len(set(dirs.values())), 2)
        self.publish([{'id':1,'name':'new name','description':'x','files':[]}])
        self.assertEqual(self.cycle()['challenges']['1']['directory'], dirs['1'])

    def test_attachment_name_collision_is_unique(self):
        files = self.monitor.normalize_files(['/a/x.zip','/b/x.zip','/c/x_2.zip','/d/x.zip'])
        self.assertEqual(len({f['local_name'] for f in files}), len(files))

    def test_url_token_rotation_does_not_create_update_event(self):
        challenge = self.challenge(files=['/files/a?token=first'])
        with patch.object(self.monitor, 'schedule_file'):
            for token in ('first','second'):
                challenge['files'][0]['url'] = '/files/a?token=' + token
                current={'challenges':{'1':copy.deepcopy(challenge)},'team':{'id':7,'name':'Team'}}
                self.monitor.process_snapshot(current, {})
        self.assertEqual([json.loads(line)['kind'] for line in m.EVENT_FILE.read_text().splitlines()], ['NEW'])

    def test_corrupt_state_and_partial_download_recovery_preserves_user_files(self):
        m.STATE_DIR.mkdir(parents=True, exist_ok=True)
        for file in (m.CURRENT_FILE,m.MANIFEST_FILE): file.write_text('{broken')
        deploy = m.BASE_DIR/'1_Example/chall/deploy'; deploy.mkdir(parents=True)
        (deploy/'.file.ctfd-part-dead').write_text('partial')
        (deploy/'my-code.py').write_text('keep')
        monitor = self.new_monitor()
        self.assertFalse((deploy/'.file.ctfd-part-dead').exists())
        self.assertEqual((deploy/'my-code.py').read_text(),'keep')
        self.assertEqual(monitor.manifest,{})


    def test_state_schema_matrix_recovers_without_traceback(self):
        m.STATE_DIR.mkdir(parents=True,exist_ok=True)
        for path in (m.CURRENT_FILE,m.MANIFEST_FILE,m.KOTH_FILE):
            for value in (None,[],42,'invalid'):
                with self.subTest(file=path.name,value=value):
                    path.write_text(json.dumps(value))
                    restored=self.new_monitor()
                    self.assertIsInstance(restored.state.view()['challenges'],dict)
                    path.unlink(missing_ok=True)

    def test_malformed_event_lines_do_not_discard_valid_history(self):
        m.STATE_DIR.mkdir(parents=True,exist_ok=True)
        m.EVENT_FILE.write_text('{broken\n'+json.dumps({'kind':'NEW','message':'retained','event_id':'retained'})+'\n')
        restored=self.new_monitor()
        self.assertTrue(any(event['message']=='retained' for event in restored.state.events))
