import time
from datetime import datetime, timedelta, timezone
from scenarios import Scenario, m


def plain(value):
    return m.ANSI_RE.sub('',value if isinstance(value,str) else '\n'.join(value))


class DisplayContracts(Scenario):
    def test_countdown_valid_missing_malformed_expired_and_naive(self):
        for value,want in (('', 'WAITING'),('not-a-date','UNAVAILABLE'),('2000-01-01T00:00:00Z','ENDED'),('2000-01-01T00:00:00','UNAVAILABLE')):
            with self.subTest(value=value):
                try: result=m.competition_countdown({'contest_end':value})[0]
                except Exception as error: self.fail(f'Malformed server time crashes rendering: {type(error).__name__}')
                self.assertEqual(result,want)
        future=(datetime.now(timezone.utc)+timedelta(days=2,hours=1)).isoformat()
        self.assertIn('2d',m.competition_countdown({'contest_end':future})[0])

    def test_transfers_show_active_done_and_error_in_both_layouts(self):
        for width in (60,120):
            for action in ('DOWNLOAD','EXTRACT'):
                for state in ('ACTIVE','DONE','ERROR'):
                    with self.subTest(width=width,action=action,state=state):
                        job=m.TransferJob(1,'Problem','data.zip',action)
                        job.state=state; job.percent=50; job.progress='50%'; job.done_at=time.monotonic() if state=='DONE' else None
                        rendered=plain(m.transfer_line(job,width))
                        self.assertIn(action,rendered)
                        self.assertIn('50%' if state=='ACTIVE' else state,rendered.replace(' 50%','50%'))

    def test_event_types_and_corrupt_timestamp_are_visible(self):
        events=[{'time':'invalid' if kind=='ERROR' else '2026-01-01T00:00:00Z','kind':kind,'message':kind+' message'} for kind in ('NEW','UPDATED','SOLVED','DELETED','ERROR')]
        text=plain(m.render_events({'events':events},120,limit=5))
        for kind in ('NEW','UPDATED','SOLVED','DELETED','ERROR'): self.assertIn(kind+' message',text)
        self.assertIn('--:--:--',text)

    def test_solved_unsolved_and_badge_expiry(self):
        first=self.challenge(name='Still open'); second=self.challenge(id=2,name='Completed',solved_by_me=True)
        first.update(marker='NEW',marker_expires=time.time()+100)
        view=self.monitor.state.view(); view.update(status='LIVE',challenges={'1':first,'2':second})
        text=plain(m.render_challenges(view,60,60))
        for expected in ('UNSOLVED  1','SOLVED  1','Still open','Completed','NEW'): self.assertIn(expected,text)
        first['marker_expires']=time.time()-1
        self.assertIsNone(m.marker_badge(first))

    def test_koth_waiting_live_stale_and_unavailable(self):
        entries=[{'id':1,'name':'Working','status':'LIVE','rank':1,'teams':4,'score':100,'points':1500},{'id':2,'name':'Old data','status':'ERROR','points':750},{'id':3,'name':'No data','status':'ERROR'},{'id':4,'name':'Pending','status':'WAITING'}]
        text=plain(m.render_koth({'koth':{str(x['id']):x for x in entries}},160))
        for expected in ('Working','STALE','UNAVAILABLE','WAITING','2250'): self.assertIn(expected,text)

    def test_comparison_handles_standard_ctfd_scoreboard(self):
        view=self.monitor.state.view()
        view.update(team_name='Ours',scoreboard=[{'account_id':1,'name':'Opponent','pos':1,'score':200},{'account_id':7,'name':'Ours','pos':2,'score':123}],challenges={})
        text=plain(m.render_team_comparison(view,160))
        self.assertRegex(text, r'#2\s+Ours')
        self.assertIn('+77',text,'Opponent 200 minus own 123 must produce +77, not +0')

    def test_resource_graph_ignores_out_of_window_samples(self):
        resources={'now':240,'samples':[(0,999,999),(121,10,20),(130,30,40),(239,50,60),(241,999,999)]}
        points=m.resource_series(resources,1,8)
        self.assertEqual(points[0],30)
        self.assertEqual(points[-1],50)
        self.assertNotIn(999,points)
