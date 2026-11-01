import copy
import os
import time
from unittest.mock import patch
from scenarios import Scenario, m

class ControlledStop:
    """Advance the real poll loop by responses, without waiting for wall clock time."""
    def __init__(self, monitor, transitions):
        self.monitor=monitor; self.transitions=iter(transitions); self.stopped=False; self.observed=[]
    def is_set(self): return self.stopped
    def set(self): self.stopped=True
    def wait(self, delay):
        self.observed.append((delay,copy.deepcopy(self.monitor.state.view())))
        action=next(self.transitions,None)
        if action is None: self.set()
        else: action()
        return self.stopped

class RuntimeContracts(Scenario):
    def test_server_error_backoff_and_recovery_keep_last_good_state(self):
        self.publish([{'id':1,'name':'One','files':[]}]); self.cycle()
        self.routes['/api/v1/challenges']=(503,{'success':False}, {})
        stop=ControlledStop(self.monitor,[lambda: self.publish([{'id':1,'name':'One','files':[]}])])
        self.monitor.stop=stop
        self.monitor.run()
        first,second=stop.observed
        self.assertEqual(first[1]['status'],'STALE')
        self.assertIn('1',first[1]['challenges'])
        self.assertEqual(second[1]['status'],'LIVE')
        self.assertGreater(first[0],second[0])

    def test_session_expiry_reauthenticates_next_cycle(self):
        self.publish([])
        self.routes['/api/v1/challenges']=(401,{'success':False}, {})
        stop=ControlledStop(self.monitor,[lambda:self.publish([])])
        self.monitor.stop=stop; self.monitor.run()
        self.assertGreaterEqual(sum(p=='/api/v1/users/me' for p,_ in self.requests),2)
        self.assertEqual(stop.observed[-1][1]['status'],'LIVE')

    def test_closed_contest_keeps_previously_downloaded_challenges_visible(self):
        self.publish([{'id':1,'name':'One','files':[]}]); self.cycle()
        self.routes['/api/v1/challenges']=(403,{'success':False,'code':'competition_closed'}, {})
        self.monitor.stop=ControlledStop(self.monitor,[])
        self.monitor.run()
        self.assertIn('1',self.monitor.state.challenges,'Closed competition must not erase the last visible snapshot')

    def test_empty_new_contest_is_not_an_error(self):
        self.publish([]); self.monitor.stop=ControlledStop(self.monitor,[])
        self.monitor.run()
        self.assertEqual(self.monitor.state.status,'LIVE')
        self.assertEqual(self.monitor.state.challenges,{})

    def test_absent_integrations_remain_idle_and_keep_checking(self):
        with patch.object(m.shutil,'which',return_value=None),patch.object(m.subprocess,'Popen',side_effect=AssertionError('External process started')):
            self.monitor.stop=ControlledStop(self.monitor,[])
            self.monitor.run_koth()
            self.monitor.stop=ControlledStop(self.monitor,[])
            self.monitor.run_codex_usage()
            self.assertEqual(self.monitor.state.codex_usage['status'],'ABSENT')
            self.assertEqual(len(self.monitor.stop.observed),1)

    def test_render_size_unicode_and_panel_matrix(self):
        self.monitor.state.challenges={'1':self.challenge(name='한글 🧪 e\u0301'*20)}
        for columns,rows in ((1,1),(40,10),(80,24),(120,60),(200,80)):
            with self.subTest(columns=columns,rows=rows),patch.object(m.shutil,'get_terminal_size',return_value=os.terminal_size((columns,rows))):
                rendered=m.render_screen(self.monitor.state.view())
                self.assertIsInstance(rendered,str)
                self.assertLessEqual(len(rendered.splitlines()),rows)
                self.assertNotIn('CODEX WEEKLY',rendered)

    def test_server_text_cannot_inject_terminal_clipboard_control(self):
        attack='\x1b]52;c;c2VjcmV0\x07'
        self.monitor.state.team_name=attack
        rendered=m.render_screen(self.monitor.state.view())
        self.assertNotIn(attack,rendered)
