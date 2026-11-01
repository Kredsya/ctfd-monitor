"""Behavior checks traced to the original user's monitor requirements."""
import json
import threading
from unittest.mock import patch
from scenarios import Scenario, m


class RecoveryAudit(Scenario):
    def test_hint_update_keeps_raw_versions_and_does_not_repeat_events(self):
        detail = {'id':1, 'name':'Problem', 'category':'misc', 'description':'description', 'hints':[]}
        self.publish([detail]); self.cycle()
        detail['hints'] = [{'id':3, 'content':'new hint'}]
        self.publish([detail]); self.cycle(); self.cycle()
        events = self.monitor.state.view()['events']
        updates = [event for event in events if event['kind'] == 'UPDATED']
        self.assertEqual(len(updates), 1)
        self.assertIn('hint', updates[0]['message'])
        snapshots = [json.loads(p.read_text()) for p in m.SNAPSHOT_DIR.glob('*.json')]
        self.assertTrue(any(x['challenge_details'][0]['hints'] == [] for x in snapshots))
        self.assertTrue(any(x['challenge_details'][0]['hints'] == detail['hints'] for x in snapshots))

    def test_solver_name_and_newest_first_survive_restart(self):
        detail = {'id':1, 'name':'Problem', 'category':'misc', 'description':'', 'solved_by_me':False}
        self.publish([detail]); self.cycle()
        self.ok('/api/v1/teams/me/solves', [{'challenge_id':1, 'user':{'name':'Player A'}}])
        detail['solved_by_me'] = True
        self.publish([detail]); self.cycle()
        restarted = self.new_monitor()
        view = restarted.state.view()
        self.assertEqual(view['events'][-1]['message'], 'Player A solves Problem')
        text = m.ANSI_RE.sub('', '\n'.join(m.render_events(view, 120)))
        self.assertLess(text.index('Player A solves Problem'), text.index('Problem released'))

    def test_downloads_are_concurrent_and_all_active_jobs_visible(self):
        entered = [threading.Event(), threading.Event()]
        release = threading.Event()
        challenge = self.challenge(files=['/files/one.bin', '/files/two.bin'])
        deploy = self.monitor.prepare_challenge(challenge)
        def response(index):
            def handler(_):
                entered[index].set()
                release.wait(5)
                return 200, b'payload', {}
            return handler
        for index, file in enumerate(challenge['files']):
            self.routes[file['url']] = response(index)
        try:
            for file in challenge['files']:
                self.monitor.schedule_file(challenge, file, deploy, False)
            self.assertTrue(all(event.wait(3) for event in entered), 'Transfers must overlap')
            view = self.monitor.state.view()
            self.assertEqual(len([job for job in view['jobs'] if job.state == 'ACTIVE']), 2)
            text = m.ANSI_RE.sub('', '\n'.join(m.render_transfers(view, 120)))
            for name in ('one.bin', 'two.bin'):
                self.assertIn(name, text)
        finally:
            release.set()
            self.monitor.executor.shutdown(wait=True)
        self.assertEqual((deploy/'one.bin').read_bytes(), b'payload')
        self.assertEqual((deploy/'two.bin').read_bytes(), b'payload')

    def test_done_visible_five_seconds_then_idle_download_panel_hidden(self):
        self.monitor.state.status = 'LIVE'
        job = m.TransferJob(1, 'Problem', 'file', 'DOWNLOAD')
        self.monitor.state.add_job(job)
        with patch.object(m.time, 'monotonic', return_value=100):
            self.monitor.state.finish_job(job)
        with patch.object(m.time, 'monotonic', return_value=104.99):
            self.assertEqual(len(self.monitor.state.view()['jobs']), 1)
        with patch.object(m.time, 'monotonic', return_value=105):
            view = self.monitor.state.view()
            self.assertEqual(view['jobs'], [])
            self.assertEqual(m.render_transfers(view, 120), [])
