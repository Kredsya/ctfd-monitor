"""Original dashboard features must survive resizing and ranking changes."""
import os
import re
from unittest.mock import patch
from scenarios import Scenario, m


class UIPreservationTests(Scenario):
    def test_header_keeps_countdown_without_label(self):
        with patch.object(m,'competition_countdown',return_value=('01:23:45',m.CYAN)),patch.object(m.shutil,'get_terminal_size',return_value=os.terminal_size((120,61))):
            text=m.ANSI_RE.sub('',m.render_screen(self.view(),self.resources()))
        self.assertIn('01:23:45',text)
        self.assertIn('LIVE',text)
        self.assertNotIn('TIME REMAINING',text)
        self.assertNotIn('TIME REAMINING',text)

    def test_resource_peak_matches_visible_bars_including_spikes_and_expiry(self):
        for width in (109,120,180):
            for now in (240,241,360,361):
                with self.subTest(width=width,now=now):
                    resources={'now':now,'cpu':100,'memory':100,
                        'samples':[(110,99,99),(200,10,30),(201,90.5,32.8),(202,10,30),(239,6.5,31.2),(400,100,100)]}
                    with patch.object(m,'resource_chart',wraps=m.resource_chart) as chart:
                        lines=m.render_resources(resources,width)
                    for call in chart.call_args_list:
                        title,current,peak,values,column_width,*_=call.args
                        self.assertEqual(peak,max((v for v in values if v is not None),default=None))
                        self.assertNotIn(99,values)
                        self.assertNotIn(100,values)
                        if now<300:
                            self.assertEqual(peak,90.5 if title=='CPU' else 32.8)
                        else:
                            self.assertIsNone(peak)
                    if now<300:
                        # The 80% cell spans 70–90%; a 90.5% spike fills it.
                        top=m.ANSI_RE.sub('',lines[3]).split('80% ┤',2)[1]
                        self.assertTrue(any(c in top for c in '▁▂▃▄▅▆▇█'))

    def test_codex_detected_usage_is_visible_without_profile_toggle(self):
        view=self.view(count=80)
        view['codex_usage']={'status':'LIVE','remaining_percent':0,'credits_balance':'23.50','competition_start_credits':'100'}
        for cols,rows in ((109,54),(120,61),(80,24)):
            with self.subTest(cols=cols,rows=rows),patch.object(m.shutil,'get_terminal_size',return_value=os.terminal_size((cols,rows))):
                screen=m.ANSI_RE.sub('',m.render_screen(view,self.resources()))
                for text in ('CODEX WEEKLY','0% REMAINING','CREDITS 100.00 → 23.50','CPU','MEMORY'):
                    self.assertIn(text,screen)
                self.assertLessEqual(len(screen.splitlines()),rows)

    def test_codex_waiting_error_stale_and_credits_are_distinct(self):
        for usage,expected in (({'status':'WAITING'},'WAITING'),
                               ({'status':'ERROR'},'UNAVAILABLE'),
                               ({'status':'ERROR','remaining_percent':25},'STALE'),
                               ({'status':'LIVE','remaining_percent':75},'75% REMAINING'),
                               ({'status':'LIVE','remaining_percent':0,'credits_unlimited':True},'CREDITS UNLIMITED')):
            with self.subTest(usage=usage):
                self.assertIn(expected,m.ANSI_RE.sub('',m.codex_usage_line(usage,116)))

    def test_category_spacing_stays_consistent_across_screen_heights(self):
        view=self.view(count=12)
        for n,challenge in enumerate(view['challenges'].values()):
            challenge['solved']=True
            challenge['category']='Alpha' if n<6 else 'Beta'
        for rows in (54,60,70,90):
            with self.subTest(rows=rows),patch.object(m.shutil,'get_terminal_size',return_value=os.terminal_size((120,rows))):
                screen=m.ANSI_RE.sub('',m.render_screen(view,self.resources()))
                lines=screen.splitlines()
                # Inspect the solved (right-hand) panel, including crowded layouts.
                categories=[i for i,line in enumerate(lines) if 'BETA (' in line]
                self.assertTrue(categories)
                for index in categories:
                    right=lines[index-1][61:].strip()
                    self.assertEqual(right,'│'+(' ' * (len(right)-2))+'│')

    def view(self, rank=2, count=16):
        view=self.monitor.state.view()
        rows=[{'account_id':n,'name':f'Team {n}','score':1000-n*10,'pos':n,'solved_challenge_ids':[]} for n in range(1,9)]
        rows[rank-1]['name']='Ours'
        view.update(status='LIVE',team_name='Ours',account_id=rank,scoreboard=rows,
                    challenges={str(n):self.challenge(id=n,name=f'Problem {n}',category=f'Category {n%6}') for n in range(1,count+1)})
        for n in (101,102,103):
            view['challenges'][str(n)]=self.challenge(id=n,name=f'KOTH {n}',category='koth')
        view['koth']={str(n):{'id':n,'name':f'KOTH {n}','status':'LIVE','score':100,'points':1000,
                              'team_points':{str(t):1500-100*t for t in range(1,9)}} for n in (101,102,103)}
        return view

    def resources(self):
        return {'now':240,'cpu':45,'memory':60,'cpu_cores':8,'used_gib':9,'total_gib':16,
                'samples':[(t,20+t%60,50+t%30) for t in range(120,241)]}

    def test_own_row_and_jeopardy_column_follow_rank(self):
        for rank in (1,2,3,4,5,8):
            with self.subTest(rank=rank):
                view=self.view(rank)
                plain=m.ANSI_RE.sub('','\n'.join(m.render_team_comparison(view,180)))
                ranking=[int(x) for x in re.findall(r'^│ #(\d+)\s',plain,re.M)]
                self.assertEqual(ranking,sorted(ranking))
                self.assertIn(rank,ranking)
                self.assertEqual(len(ranking),5)
                header=next(line for line in plain.splitlines() if 'JEOPARDY CHALLENGE' in line)
                cells=re.findall(r'#\d+|US',header.split('JEOPARDY CHALLENGE',1)[1])
                self.assertEqual(cells,['US' if n==rank else f'#{n}' for n in ranking])

    def test_graphs_and_koth_comparison_survive_crowded_supported_screen(self):
        sources={str(n):{'max_points':1500} for n in (101,102,103)}
        for cols,rows in ((106,61),(109,54),(120,60),(180,70)):
            for count in (16,80):
                with self.subTest(cols=cols,rows=rows,count=count),patch.object(m,'KOTH_SOURCES',sources),patch.object(m.shutil,'get_terminal_size',return_value=os.terminal_size((cols,rows))):
                    screen=m.ANSI_RE.sub('',m.render_screen(self.view(count=count),self.resources()))
                    for label in ('SYSTEM RESOURCES','CPU','MEMORY','100% ┤','0% └','2m ago','TEAM COMPARISON','KOTH 101','KOTH 102','KOTH 103'):
                        self.assertIn(label,screen)
                    self.assertLessEqual(len(screen.splitlines()),rows)
                    self.assertTrue(all(m.display_width(line)<=cols for line in screen.splitlines()))

    def test_small_screen_retains_two_history_graphs(self):
        with patch.object(m.shutil,'get_terminal_size',return_value=os.terminal_size((80,24))):
            screen=m.ANSI_RE.sub('',m.render_screen(self.view(count=80),self.resources()))
        for label in ('SYSTEM RESOURCES','CPU','MEMORY'):
            self.assertIn(label,screen)
        graph_lines=[line for line in screen.splitlines() if 'CPU' in line or 'MEMORY' in line]
        self.assertEqual(len(graph_lines),2)
        self.assertTrue(all(any(char in line for char in '▁▂▃▄▅▆▇█') for line in graph_lines))

    def test_original_warning_threshold_and_extreme_sizes(self):
        for cols,rows,width_warning,height_warning in ((109,54,False,False),(108,54,True,False),(109,53,False,True),(106,61,True,False),(80,24,True,True)):
            with self.subTest(cols=cols,rows=rows):
                warning=m.terminal_size_warning_overlays(cols,rows)
                self.assertEqual('WIDTH TOO SMALL' in warning,width_warning)
                self.assertEqual('HEIGHT TOO SMALL' in warning,height_warning)
        self.assertIn('!',m.terminal_size_warning_overlays(1,1))

    def test_comparison_palette_is_muted_and_not_bold(self):
        for ours,theirs in ((True,False),(False,True)):
            cell=m.comparison_status_cell(ours,theirs)
            self.assertNotIn(m.BOLD,cell)
            self.assertIn('48;2;',cell)
            self.assertNotIn(m.RED,cell)
            self.assertNotIn(m.GREEN,cell)

    def test_koth_scores_and_decimal_deltas_are_not_truncated(self):
        view=self.view()
        sources={str(n):{'max_points':1500} for n in (101,102,103)}
        for entry in view['koth'].values():
            entry.update(name='Long arena title that must yield space to scores',score=1234567.89,points=1234.56,rank=2,teams=100)
            entry['team_points']['1']=1234.56
            entry['team_points']['2']=1000
            entry['team_points']['3']=999.25
        for width in (109,110,120,180):
            with self.subTest(width=width),patch.object(m,'KOTH_SOURCES',sources):
                lines=m.render_koth(view,width)
                text=m.ANSI_RE.sub('','\n'.join(lines))
                self.assertNotIn('1234568',text)
                self.assertEqual(text.count('1235 / 1500 pt'),3)
                self.assertNotIn('PROJECTED',text)
                self.assertTrue(all(m.display_width(line)<=width for line in lines))
                comparison=m.render_team_comparison(view,width)
                text=m.ANSI_RE.sub('','\n'.join(comparison))
                self.assertEqual(text.count('+234.56'),3)
                self.assertEqual(text.count('-0.75'),3)
                self.assertNotIn('TOP 4',text)
                self.assertNotIn('OUR ACTUAL',text)
                self.assertTrue(all(m.display_width(line)<=width for line in comparison))

    def test_koth_columns_align_across_digit_counts_and_statuses(self):
        entries={str(n):{'id':n,'name':f'경기 {n}','status':status,'score':score,
                        'points':points,'rank':rank,'teams':teams}
                 for n,(score,points,rank,teams,status) in enumerate((
                     (1,0,1,8,'LIVE'),(999.99,9.99,10,100,'LIVE'),
                     (1000,100,2,100,'LIVE'),(1234567.89,1500,100,100,'LIVE'),
                     (-123.45,999.99,3,8,'ERROR'),(None,None,None,None,'ERROR'),
                     (None,None,None,None,'WAITING')),1)}
        sources={key:{'max_points':20000 if key=='2' else 1500} for key in entries}
        for width in (109,110,120,180):
            with self.subTest(width=width),patch.object(m,'KOTH_SOURCES',sources):
                lines=m.render_koth({'koth':entries},width)
                rows=[m.ANSI_RE.sub('',line) for line in lines[1:-1]]
                self.assertEqual(len(rows),len(entries))
                for token in ('Rank ', ' / ', ' pt'):
                    columns=[m.display_width(row[:row.index(token)]) for row in rows]
                    self.assertEqual(len(set(columns)),1,(token,columns))
                bars=[re.search('[█░]+',row) for row in rows]
                self.assertTrue(all(bars))
                self.assertEqual(len({m.display_width(row[:bar.start()]) for row,bar in zip(rows,bars)}),1)
                self.assertEqual(len({len(bar[0]) for bar in bars}),1)
                for row,entry in zip(rows,entries.values()):
                    self.assertIn(entry['name'],row)
                    if entry['points'] is not None:
                        self.assertIn(f"{entry['points']:.0f} /",row)
                self.assertTrue(all(m.display_width(line)<=width for line in lines))
