"""Tick-centred graphs, integer KOTH display and closed-event standings."""
import copy
import re
from scenarios import Scenario, m
from test_contract_runtime import ControlledStop


class DisplayAndScoreTests(Scenario):
    def test_tick_centres_and_user_reported_46_percent(self):
        values=[0,5,10,20,30,40,46.2,50,60,80,90.5,92.5,100]
        lines=[m.ANSI_RE.sub('',s) for s in m.resource_chart('CPU',17,46.2,values,len(values)+6,m.YELLOW)]
        rows={int(line.split('%')[0]):line[6:] for line in lines[1:-1]}
        for percent in (20,40,60,80,100):
            self.assertEqual(rows[percent][values.index(percent)],'▄')
        for percent,row,glyph in ((30,20,'█'),(46.2,40,'▆'),(50,40,'█'),(50,60,' '),(90.5,100,' '),(92.5,100,'▁')):
            self.assertEqual(rows[row][values.index(percent)],glyph,(percent,row))
        self.assertEqual(rows[0][0],'─')
        self.assertEqual(rows[0][1],'⠒')
        self.assertTrue(all(cell=='▀' for cell in rows[0][2:]))
        self.assertIn('Peak  46.2%',m.resource_chart('CPU',17,46.2,values,60,m.YELLOW)[0])

    def test_koth_panel_removes_repeated_label_and_decimals_only_in_display(self):
        view={'koth':{'1':{'id':1,'name':'Arena Alpha','score':230.25,'points':1234.56,'status':'LIVE','rank':2,'teams':10},
                      '2':{'id':2,'name':'Arena Beta','score':7,'points':9,'status':'LIVE','rank':1,'teams':9}}}
        original=copy.deepcopy(view)
        for width in (109,120,180):
            rows=[m.ANSI_RE.sub('',s) for s in m.render_koth(view,width)]
            self.assertIn('KOTH · 2 ARENAS',rows[0])
            self.assertNotRegex('\n'.join(rows),r'\d+\.\d+')
            self.assertTrue(all('KOTH' not in row for row in rows[1:-1]))
            self.assertNotRegex(rows[1],r'\b230\b')
            self.assertIn('Rank',rows[1])
            self.assertIn('1235 / 1500 pt',rows[2])
            self.assertEqual(rows[1].index('Rank'),rows[4].index('Rank'))
            for token in (' / ',' pt'):
                self.assertEqual(rows[2].index(token),rows[5].index(token))
        self.assertEqual(view,original)

    def test_closed_challenges_do_not_freeze_official_koth_total(self):
        self.publish([{'id':1,'name':'Saved','value':100,'files':[]}]);self.cycle()
        self.monitor.state.koth={'42':{'points':1418,'status':'LIVE'}}
        self.ok('/api/v1/teams/me',{'id':7,'name':'Team','score':1300})
        def board(score):
            self.ok('/api/v1/scoreboard',[{'account_id':7,'name':'Team','score':score,'pos':2}])
        board(2718)
        self.routes['/api/v1/challenges']=(403,{'success':False,'code':'competition_ended'},{})
        stop=ControlledStop(self.monitor,[lambda:board(3499)])
        self.monitor.stop=stop;self.monitor.run()
        self.assertEqual([view['score'] for _,view in stop.observed],[2718,3499])
        self.assertTrue(all(view['status']=='ENDED' and '1' in view['challenges'] for _,view in stop.observed))
        self.assertEqual([delay for delay,_ in stop.observed],[m.POLL_INTERVAL,m.POLL_INTERVAL])

    def test_unavailable_board_keeps_last_total_and_explicit_total_is_authoritative(self):
        team={'id':7,'name':'Team','score':1300}
        self.monitor.state.score=2718
        for status in (403,503):
            self.routes['/api/v1/scoreboard']=(status,{'success':False},{})
            self.monitor.refresh_standings(team)
            self.assertEqual(self.monitor.state.score,2718)
        for row,want in (({'score':1300,'total_score':2718},2718),({'score':0},0)):
            self.ok('/api/v1/scoreboard',[dict(account_id=7,name='Team',pos=1,**row)])
            self.monitor.refresh_standings(team)
            self.assertEqual(self.monitor.state.score,want)
