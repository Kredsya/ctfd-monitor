"""Keep the original two-panel comparison across standard and custom CTFd APIs."""
import copy
from unittest.mock import patch
from scenarios import Scenario, m


class ComparisonTests(Scenario):
    def view(self):
        view=self.monitor.state.view()
        view.update(team_name='Ours',account_id=7,scoreboard=[
            {'account_id':1,'name':'Ahead','pos':1,'score':200,'solved_challenge_ids':[1,3]},
            {'account_id':7,'name':'Ours','pos':2,'score':123,'solved_challenge_ids':[2,3]},
            {'account_id':2,'name':'Behind','pos':3,'score':100,'solved_challenge_ids':[3]}],
            challenges={str(n):self.challenge(id=n,name=name,solved_by_me=n in (2,3))
                        for n,name in ((1,'Opponent only'),(2,'Our advantage'),(3,'Everyone solved'))})
        return view

    def test_original_panels_deltas_solve_colors_and_completed_filter(self):
        rendered='\n'.join(m.render_team_comparison(self.view(),140))
        plain=m.ANSI_RE.sub('',rendered)
        for text in ('TEAM COMPARISON','RK TEAM','ΔPT','JEOPARDY CHALLENGE','+77','-23','Opponent only','Our advantage',' │ '):
            self.assertIn(text,plain)
        self.assertNotIn('Everyone solved',plain)
        self.assertIn(m.RED_BG,rendered)
        self.assertIn(m.GREEN_BG,rendered)

    def test_configured_koth_uses_relative_points_and_keeps_jeopardy_panel(self):
        view=self.view()
        view['challenges']['42']=self.challenge(id=42,name='Arena Alpha')
        view['koth']={'42':{'name':'Arena Alpha','status':'LIVE','team_points':{'7':500,'1':800,'2':400}}}
        with patch.object(m,'KOTH_SOURCES',{'42':{'max_points':1000}}):
            rendered='\n'.join(m.render_team_comparison(view,160))
        plain=m.ANSI_RE.sub('',rendered)
        for text in ('+300','-100','+77','-23','JEOPARDY CHALLENGE','K42'):
            self.assertIn(text,plain)
        self.assertNotIn('Arena Alpha',plain) # KOTH must not appear as a jeopardy solve.
        self.assertIn(m.RED_BG,rendered)
        self.assertIn(m.GREEN_BG,rendered)

    def test_legacy_koth_columns_keep_original_labels(self):
        view=self.view()
        for row in view['scoreboard']:
            row['koth_score_detail']={name:0 for name in ('King of the Brick-Breaker','Neural Dominion','SHIFT','BATTLE')}
        view['scoreboard'][0]['koth_score_detail']['SHIFT']=50
        with patch.object(m,'KOTH_ENABLED',True),patch.object(m,'KOTH_SOURCES',{}):
            plain=m.ANSI_RE.sub('','\n'.join(m.render_team_comparison(view,140)))
        for text in ('BRK','NEU','SHF','BAT','+50','JEOPARDY CHALLENGE'):
            self.assertIn(text,plain)

    def test_unknown_solves_are_not_unsolved_or_filtered_out(self):
        view=self.view();view['scoreboard'][0].pop('solved_challenge_ids')
        plain=m.ANSI_RE.sub('','\n'.join(m.render_team_comparison(view,140)))
        self.assertIn('? = solves unavailable',plain)
        self.assertIn('Everyone solved',plain)
        # Own solve indicators also work with a standard scoreboard lacking IDs.
        view['scoreboard'][1].pop('solved_challenge_ids')
        rendered='\n'.join(m.render_team_comparison(view,140))
        self.assertIn(m.GREEN_BG,rendered)

    def test_own_account_id_wins_over_duplicate_name_and_top_four_only(self):
        view=self.view();view['scoreboard'][0]['name']='Ours'
        for n in range(4,8):view['scoreboard'].append({'account_id':n+10,'name':f'Rank {n}','pos':n,'score':10})
        plain=m.ANSI_RE.sub('','\n'.join(m.render_team_comparison(view,140)))
        self.assertRegex(plain, r'#2\s+Ours')
        self.assertIn('+77',plain)
        self.assertIn('Rank 5',plain)
        self.assertNotIn('Rank 6',plain)

    def test_narrow_layout_keeps_both_sections_and_stays_within_width(self):
        for width in (32,40,80,109,120,160):
            with self.subTest(width=width):
                lines=m.render_team_comparison(self.view(),width)
                plain=m.ANSI_RE.sub('','\n'.join(lines))
                self.assertIn('RK TEAM',plain)
                self.assertIn('JEOPARDY CHALLENGE',plain)
                self.assertTrue(all(m.display_width(line)<=width for line in lines))

    def test_public_solves_cache_refresh_and_forbidden_are_distinct(self):
        rows=self.view()['scoreboard']
        for row in rows:row.pop('solved_challenge_ids')
        self.ok('/api/v1/teams/1/solves',[{'challenge_id':1}])
        self.ok('/api/v1/teams/2/solves',[])
        with patch.object(m,'ACCOUNT_MODE','teams'):
            first=copy.deepcopy(rows);self.monitor.enrich_comparison_solves(first,{'id':7})
            self.assertEqual(first[0]['solved_challenge_ids'],[1])
            self.assertEqual(first[2]['solved_challenge_ids'],[])
            self.monitor.enrich_comparison_solves(copy.deepcopy(rows),{'id':7})
            self.assertEqual(sum('/solves' in path for path,_ in self.requests),2)
            self.routes['/api/v1/teams/1/solves']=(403,{'success':False},{})
            self.monitor.comparison_solves_cache.clear()
            denied=copy.deepcopy(rows);self.monitor.enrich_comparison_solves(denied,{'id':7})
            self.assertNotIn('solved_challenge_ids',denied[0])
            self.assertEqual(denied[2]['solved_challenge_ids'],[])

    def test_user_mode_and_full_scoreboard_do_not_use_team_routes(self):
        rows=self.view()['scoreboard'];self.ok('/api/v1/users/1/solves',[{'challenge':{'id':2}}])
        with patch.object(m,'ACCOUNT_MODE','users'):
            self.monitor.enrich_comparison_solves(rows,{'id':7})
            self.assertFalse(self.requests)
            rows[0].pop('solved_challenge_ids')
            self.monitor.enrich_comparison_solves(rows,{'id':7})
        self.assertEqual(rows[0]['solved_challenge_ids'],[2])
        self.assertEqual([p for p,_ in self.requests],['/api/v1/users/1/solves'])
