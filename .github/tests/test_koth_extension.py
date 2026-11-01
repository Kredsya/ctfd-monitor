"""v0.4 opt-in boundary and portable adapter contract; fixtures use no real accounts."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from scenarios import Scenario, m
from ctfd_monitor import koth


class KothExtensionTests(Scenario):
    def source(self):
        return {'challenge_id':42, 'adapter':'generic', 'url':self.url+'/scores', 'max_points':1000}

    def enable(self):
        self.profile.write_text(f'url="{self.url}"\nroot="work"\nkoth=true\n[[koth_sources]]\nchallenge_id=42\nadapter="generic"\nurl="{self.url}/scores"\nmax_points=1000\n')
        m.configure(self.profile)
        return self.new_monitor()

    def scores(self, rows):
        self.routes['/scores']=(200, {'teams':rows, 'round':3}, {})

    def test_import_defaults_are_disabled(self):
        # A fresh process checks the module default independently of configure().
        result=subprocess.run([sys.executable,'-c','from ctfd_monitor import app; assert app.KOTH_ENABLED is False'],env=dict(os.environ,PYTHONPATH=str(Path(m.__file__).resolve().parents[1])),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_default_off_ignores_metadata_sources_and_cached_state(self):
        source=self.source()
        m.STATE_DIR.mkdir(parents=True,exist_ok=True)
        cached={'entries':{'7':{'name':'Old arena','status':'LIVE','points':100,'source':source}}}
        m.KOTH_FILE.write_text(json.dumps(cached))
        previous_bytes=m.KOTH_FILE.read_bytes()
        with patch.object(m,'KOTH_SOURCES',{'7':source}):
            monitor=self.new_monitor()
            self.routes['/files/arena.txt']=(200,b'provided',{})
            self.publish([{'id':i,'name':f'Problem {i}','category':'koth','type':'koth_challenge','koth_url':self.url+'/scores','launch_url':'/launch','value':100,'files':['/files/arena.txt'] if i==7 else []} for i in (7,9,16,17)])
            self.cycle(monitor)
            monitor.executor.shutdown(wait=True)
            self.assertEqual((m.BASE_DIR/"Problem_7/chall/deploy/arena.txt").read_bytes(),b"provided")
            with patch.object(monitor,'fetch_koth_metrics',side_effect=AssertionError('Disabled KOTH performed I/O')):
                monitor.refresh_koth();monitor.run_koth()
            self.assertEqual(monitor.state.koth,{})
            self.assertEqual(monitor.koth_challenges,{})
            self.assertFalse(m.is_koth_challenge({'id':7,'category':'koth'}))
            view=monitor.state.view()
            view['koth']={'7':cached['entries']['7']}
            self.assertEqual(m.render_koth(view,120),[])
            self.assertEqual(m.render_koth_compact(view,120),[])
            text=m.ANSI_RE.sub('',m.render_screen(view))
            self.assertIn('Problem',text)
            self.assertIn('Challenges  0/4',text)
            self.assertNotIn('ARENAS',text)
            self.assertNotIn('/scores',[path for path,_ in self.requests])
        self.assertEqual(m.KOTH_FILE.read_bytes(),previous_bytes)

    def test_explicit_enable_fetch_comparison_failure_recovery_and_restart(self):
        monitor=self.enable()
        self.publish([{'id':42,'name':'Arena','category':'misc','type':'standard','value':100}])
        self.ok('/api/v1/scoreboard',[{'account_id':9,'name':'Rival','score':900,'pos':1},{'account_id':7,'name':'Team','score':700,'pos':2}])
        self.scores([{'team_id':9,'raw_score':10},{'team_id':7,'raw_score':5}])
        self.cycle(monitor);monitor.refresh_koth()
        entry=monitor.state.koth['42']
        self.assertEqual((entry['points'],entry['rank'],entry['max_points']),(500,2,1000))
        self.assertEqual(entry['team_points'],{'9':1000,'7':500})
        self.assertEqual(monitor.state.score,700, 'Never add projected KOTH to the official total')
        self.assertIn('+500.00',m.ANSI_RE.sub('','\n'.join(m.render_team_comparison(monitor.state.view(),140))))
        self.assertNotIn('Arena','\n'.join(m.challenge_lines([c for c in monitor.state.challenges.values() if not m.is_koth_challenge(c)],50)))
        self.routes['/scores']=(503,{}, {})
        monitor.refresh_koth()
        self.assertEqual(monitor.state.koth['42']['status'],'ERROR')
        self.assertEqual(monitor.state.koth['42']['points'],500)
        self.scores([{'team_id':9,'raw_score':10},{'team_id':7,'raw_score':10}])
        monitor.refresh_koth();self.assertEqual(monitor.state.koth['42']['points'],1000)
        restarted=self.new_monitor();self.assertEqual(restarted.state.koth['42']['points'],1000)
        changed=dict(m.KOTH_SOURCES['42'],max_points=500)
        with patch.object(m,'KOTH_SOURCES',{'42':changed}):
            self.assertIsNone(self.new_monitor().state.koth['42']['points'])
        monitor.update_koth_challenges({})
        self.assertEqual(monitor.state.koth,{})
        # Neither the adapter endpoint nor redirects share the CTFd auth headers.
        for path,headers in self.requests:
            if path=='/scores':
                self.assertNotIn('Authorization',headers);self.assertNotIn('Cookie',headers)

    def test_generic_zero_ties_missing_accounts_and_invalid_responses(self):
        for rows,points,rank in (([],None,None),([{'team_id':7,'raw_score':0}],0,1),
            ([{'team_id':7,'raw_score':10},{'team_id':8,'raw_score':10}],1000,1),
            ([{'team_id':8,'raw_score':10}],None,None)):
            self.scores(rows);result=koth.fetch(self.source(),7)
            self.assertEqual((result['points'],result['rank']),(points,rank))
        for rows in ([{}],[{'team_id':True,'raw_score':0}],[{'team_id':7,'raw_score':-1}],
                     [{'team_id':7,'raw_score':float('nan')}],[{'team_id':7,'raw_score':False}],
                     [{'team_id':7,'raw_score':1}]*2,['bad']):
            with self.subTest(rows=rows):
                self.scores(rows)
                with self.assertRaises(ValueError):koth.fetch(self.source(),7)

    def test_config_requires_explicit_enable_and_rejects_removed_adapters(self):
        monitor=self.enable()
        text=self.profile.read_text()
        self.profile.write_text(text.replace('koth=true','koth=false'))
        m.configure(self.profile);self.assertFalse(m.KOTH_ENABLED)
        self.profile.write_text(text.replace('koth=true\n',''))
        m.configure(self.profile);self.assertFalse(m.KOTH_ENABLED)
        for adapter in ('brick','neural','shift','battle','unknown'):
            self.profile.write_text(text.replace('adapter="generic"',f'adapter="{adapter}"'))
            with self.assertRaisesRegex(ValueError,'koth.py'):m.configure(self.profile)
        self.profile.write_text(f'url="{self.url}"\nkoth=true\n')
        with self.assertRaisesRegex(ValueError,'koth_sources'):m.configure(self.profile)
        self.profile.write_text(f'url="{self.url}"\nkoth="yes"\n')
        with self.assertRaisesRegex(ValueError,'boolean'):m.configure(self.profile)

    def test_new_adapter_registers_without_changing_monitor_dispatch(self):
        result={'rank':1,'teams':1,'score':17,'leader_score':17,'points':1000,'team_points':{'7':1000},'max_points':1000}
        with patch.dict(koth.ADAPTERS,{'custom':lambda source,account:copy.deepcopy(result)}):
            source=dict(self.source(),adapter='custom')
            self.assertEqual(koth.fetch(source,7),result)
            for key,value in (('points',42),('rank',0),('max_points',1500),('teams',-1),('team_points',{'7':float('inf')})):
                with self.subTest(key=key),patch.dict(koth.ADAPTERS,{'custom':lambda source,account:dict(result,**{key:value})}):
                    with self.assertRaises(ValueError):koth.fetch(source,7)
