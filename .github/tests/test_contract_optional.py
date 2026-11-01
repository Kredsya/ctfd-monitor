import json
import os
from unittest.mock import patch
from scenarios import Scenario, m

class OptionalContracts(Scenario):
    def test_unknown_koth_is_visible_as_error_without_breaking_monitor(self):
        challenge=self.challenge(id=987,type='koth_challenge',category='koth')
        self.monitor.koth_challenges={'987':challenge}
        self.monitor.refresh_koth()
        self.assertEqual(self.monitor.state.koth['987']['status'],'ERROR')
        self.assertTrue(m.KOTH_FILE.is_file())

    def test_koth_projection_boundaries(self):
        for score,leader,expected in ((0,0,0),(0,10,0),(5,10,m.KOTH_MAX_POINTS/2),(20,10,m.KOTH_MAX_POINTS)):
            with self.subTest(score=score,leader=leader): self.assertEqual(m.Monitor.projected_points(score,leader),expected)

    def test_codex_missing_binary_is_reported(self):
        with patch.object(m.shutil,'which',return_value=None), self.assertRaises(RuntimeError):
            m.Monitor.read_codex_weekly_usage()

    def test_codex_response_parsing_uses_longest_window_and_terminates_child(self):
        binary=self.root/'codex-fixture'
        response={'id':1,'result':{'rateLimits':{'primary':{'windowDurationMins':300,'usedPercent':90},'secondary':{'windowDurationMins':10080,'usedPercent':25}}}}
        binary.write_text('#!/usr/bin/env python3\nimport sys,json,time\nsys.stdin.readline(); sys.stdin.readline()\nprint('+repr(json.dumps(response))+',flush=True)\ntime.sleep(30)\n')
        binary.chmod(0o755)
        with patch.object(m.shutil,'which',return_value=str(binary)):
            result=m.Monitor.read_codex_weekly_usage()
        self.assertEqual(result['remaining_percent'],75)
        self.assertEqual(result['window_minutes'],10080)

    def test_koth_adapter_success_response_matrix(self):
        challenge=self.challenge(koth_url='https://koth.invalid')
        with patch.object(self.monitor,'koth_json',return_value={'teams':[{'name':'Leader','koth':100},{'name':'Ours','koth':50,'normalized_score':750,'rank':2}]}):
            metrics=self.monitor.refresh_neural_koth(challenge,'Ours')
            self.assertEqual((metrics['rank'],metrics['score'],metrics['points']),(2,50,750))
        with patch.object(self.monitor,'koth_json',return_value={'rank':2,'teams':4,'accumulated_score':50,'first_rank_team_score':100,'score':750,'matches_played':3}):
            metrics=self.monitor.refresh_shift_koth(challenge)
            self.assertEqual((metrics['rank'],metrics['score'],metrics['points'],metrics['rounds']),(2,50,750,3))
        with patch.object(self.monitor,'koth_json',return_value={'standings':{'teams':[{'points':100},{'points':50,'is_self':True,'rank':2,'scored_games':3}]}}):
            metrics=self.monitor.refresh_battle_koth(challenge)
            self.assertEqual((metrics['rank'],metrics['score'],metrics['points'],metrics['rounds']),(2,50,750,3))

    def test_brick_koth_pagination_and_round_aggregation(self):
        challenge=self.challenge(koth_url='https://koth.invalid')
        def response(challenge,url):
            if url.endswith('/api/client-state'): return {'leaderboard_rounds':[1,2]}
            if 'page=1' in url: return {'pages':2,'leaderboard':[{'team':'Leader','metrics':{'score':100}}]}
            return {'leaderboard':[{'team':'Ours','metrics':{'score':25}}]}
        with patch.object(self.monitor,'koth_json',side_effect=response):
            result=self.monitor.refresh_brick_koth(challenge,'Ours')
        self.assertEqual((result['rank'],result['score'],result['leader_score'],result['points']),(2,50,200,375))
