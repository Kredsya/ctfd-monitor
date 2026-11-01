"""Runtime decisions and display contracts for the v0.3.3 requests."""
import copy
from unittest.mock import patch
from scenarios import Scenario, m
from test_contract_runtime import ControlledStop
from test_contract_transfers import zip_bytes


class AutomaticMonitorTests(Scenario):
    def test_legacy_switches_cannot_disable_automatic_features(self):
        self.profile.write_text(self.profile.read_text()+'''
koth = false
codex_usage = false
auto_extract = false
account_mode = "users"
max_download_bytes = 1
helpers = []
''')
        config=m.load_profile(self.profile)
        for key in ('codex_usage','auto_extract','account_mode','max_download_bytes','helpers'):
            self.assertNotIn(key,config)
        self.assertFalse(config['koth'])
        m.configure(self.profile)
        self.assertEqual(m.HELPER_FILES,('22.sh','25.sh'))
        self.assertEqual(m.ACCOUNT_MODE,'auto')
        _,_,deploy=self.download(zip_bytes([('contents',b'larger than one byte')]),'automatic.zip')
        self.assertEqual((deploy/'contents').read_bytes(),b'larger than one byte')
        self.assertTrue((deploy.parent.parent/'22.sh').is_file())

    def test_koth_appears_and_disappears_while_worker_is_running(self):
        challenge=self.challenge(id=42,name='Arena',category='koth')
        source={'42':{'adapter':'generic','url':self.url+'/scores','max_points':1500}}
        stop=ControlledStop(self.monitor,[lambda:self.monitor.update_koth_challenges({'42':challenge}),lambda:self.monitor.update_koth_challenges({})])
        self.monitor.stop=stop
        with patch.object(m,'KOTH_ENABLED',True),patch.object(m,'KOTH_SOURCES',source),patch.object(self.monitor,'fetch_koth_metrics',return_value={'points':125,'score':10}) as read:
            self.monitor.run_koth()
        self.assertEqual(read.call_count,1)
        self.assertEqual([bool(view['koth']) for _,view in stop.observed],[False,True,False])
        self.assertEqual(stop.observed[1][1]['koth']['42']['status'],'LIVE')

    def test_codex_binary_and_account_availability_are_rechecked(self):
        self.monitor.stop=ControlledStop(self.monitor,[lambda:None]*3)
        with patch.object(m.shutil,'which',side_effect=[None,'/fixture/codex','/fixture/codex',None]),patch.object(self.monitor,'read_codex_weekly_usage',side_effect=[RuntimeError('login needed'),{'status':'LIVE','remaining_percent':70}]):
            self.monitor.run_codex_usage()
        self.assertEqual([view['codex_usage']['status'] for _,view in self.monitor.stop.observed],['ABSENT','ERROR','LIVE','ABSENT'])

    def test_account_mode_follows_server_membership_changes(self):
        for membership,wanted,name in ((None,'users','Player'),(7,'teams','Team'),(None,'users','Player')):
            self.ok('/api/v1/users/me',{'id':7,'name':'Player','team_id':membership})
            self.requests.clear()
            self.assertEqual(self.monitor.fetch_team()['name'],name)
            self.assertEqual(m.ACCOUNT_MODE,wanted)
            self.monitor.fetch_team_solves()
            self.assertEqual(any(path=='/api/v1/teams/me' for path,_ in self.requests),membership is not None)
            self.assertIn(f'/api/v1/{wanted}/me/solves',[path for path,_ in self.requests])

    def test_badges_last_sixty_seconds_without_countdown_text(self):
        self.assertEqual(m.BADGE_TTL,60)
        self.monitor.state.events=[{'challenge_id':1,'kind':'NEW','time':'1970-01-01T00:01:40Z','expires_at':400}]
        with patch.object(m.time,'time',return_value=160):
            self.assertIsNone(self.monitor.marker_for(1),'Old five-minute expiry must not survive an upgrade')
        for kind in ('NEW','UPDATED'):
            challenge=self.challenge(marker=kind)
            challenge.update(marker=kind,marker_expires=160)
            for now in (100,159.9,160):
                with self.subTest(kind=kind,now=now),patch.object(m.time,'time',return_value=now):
                    badge=m.marker_badge(challenge)
                    if now<160:
                        self.assertEqual(badge[0],kind)
                        self.assertNotRegex(m.ANSI_RE.sub('',m.problem_line(challenge,100)),r'\d{2}:\d{2}')
                    else:
                        self.assertIsNone(badge)

    def test_samples_older_than_120_seconds_are_dropped(self):
        with patch.object(m.time,'monotonic',return_value=100):
            sampler=m.ResourceSampler()
        sampler.samples.clear()
        sampler.samples.extend([(119.99,99,99),(120,80,80),(121,60,60),(239,20,30)])
        with patch.object(m.time,'monotonic',return_value=240):
            resources=sampler.sample()
        self.assertEqual(m.RESOURCE_RETENTION_SECONDS,120)
        self.assertTrue(all(120<=row[0]<=240 for row in resources['samples']))
        for width in (8,45,49,100):
            values=m.resource_series(resources,1,width)
            self.assertNotIn(99,values)

    def test_zero_axis_uses_upper_half_and_own_team_has_blue_background(self):
        for percent in (0,1,20,50,90.5,100):
            chart=m.resource_chart('CPU',percent,percent,[percent]*20,26,m.YELLOW)
            plain=[m.ANSI_RE.sub('',line) for line in chart]
            self.assertTrue(plain[-2].startswith('  0% └'))
            self.assertEqual(plain[-2][6:].strip(),('─' if percent==0 else '⠒' if percent<7.5 else '▀')*20)
        view=self.monitor.state.view()
        view.update(team_name='Ours',account_id=7,scoreboard=[{'account_id':1,'name':'Other','score':100,'pos':1,'solved_challenge_ids':[]},{'account_id':7,'name':'Ours','score':50,'pos':2,'solved_challenge_ids':[1]}],challenges={'1':self.challenge(solved_by_me=True)})
        rows=m.render_team_comparison(view,140)
        self.assertIn(m.OWN_TEAM_BG,next(row for row in rows if 'Ours' in row))
        self.assertIn(m.OWN_TEAM_BG,next(row for row in rows if 'US' in row))
        self.assertIn(m.OWN_TEAM_BG,next(row for row in rows if 'Example' in row))
