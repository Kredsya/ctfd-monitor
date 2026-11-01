import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from ctfd_monitor.config import load_profile
from ctfd_monitor.client import CTFdClient, ApiError
from ctfd_monitor import app

spec=importlib.util.spec_from_file_location('lab_runner',Path(__file__).resolve().parents[1]/'lab.py')
lab=importlib.util.module_from_spec(spec); spec.loader.exec_module(lab)

class LabTests(unittest.TestCase):
    def test_scores_ties_zero_and_integer_awards(self):
        self.assertEqual(lab.standings({'2':10,'1':10,'3':5}),[
            dict(team_id=1,raw_score=10,points=1500,rank=1),dict(team_id=2,raw_score=10,points=1500,rank=1),dict(team_id=3,raw_score=5,points=750,rank=3)])
        self.assertTrue(all(r['points']==0 for r in lab.standings({'1':0,'2':0})))
        self.assertEqual(lab.standings({'1':7,'2':3})[1]['points'],642)

    def test_source_validation_and_classification(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p.toml'
            valid='[[koth_sources]]\nchallenge_id=42\nadapter="generic"\nurl="http://localhost:8001/api/games/42"\nmax_points=1500\n'
            p.write_text(valid)
            source=load_profile(p)['koth_sources'][0]
            with patch.object(app,'KOTH_SOURCES',{'42':source}):
                self.assertTrue(app.is_koth_challenge({'id':42,'type':'standard','category':'Web'}))
                self.assertFalse(app.is_koth_challenge({'id':43,'type':'standard'}))
            for broken in (valid+valid, valid.replace('1500','nan'),valid.replace('generic','unknown'),valid.replace('http://localhost','file:///tmp'),valid.replace('42','true')):
                p.write_text(broken)
                with self.assertRaises(ValueError): load_profile(p)

    def test_stock_period_messages_and_generic_forbidden(self):
        measured=json.loads((Path(__file__).parent/'fixtures/stock_ctfd_period.json').read_text())
        current=dict(measured['before']['body'])
        self.assertEqual(measured['before']['status'],403)
        self.assertEqual(measured['after']['status'],403)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def do_GET(self):
                self.send_response(403); self.end_headers(); self.wfile.write(json.dumps(current).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        client=CTFdClient(f'http://127.0.0.1:{server.server_port}','','','test')
        try:
            for message,path,expected in [('Local monitor lab has not started yet','/api/v1/challenges','competition_not_started'),('Local monitor lab has ended','/api/v1/challenges/1','competition_ended'),('Forbidden','/api/v1/challenges',''),('Local monitor lab has ended','/api/v1/users/me',''),('User has ended access','/api/v1/challenges','')]:
                current['message']=message
                with self.assertRaises(ApiError) as caught: client.request_json(path)
                self.assertEqual(caught.exception.code,expected)
                self.assertEqual(caught.exception.competition_unavailable,bool(expected))
        finally: server.shutdown();server.server_close();thread.join()

    def test_generic_uses_team_id_and_never_sends_credentials(self):
        captured=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def do_GET(self):
                captured.append(dict(self.headers)); self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'round':2,'teams':[{'team_id':9,'raw_score':2},{'team_id':7,'raw_score':1}]}).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            from unittest.mock import Mock
            monitor=object.__new__(app.Monitor);monitor.client=Mock()
            monitor.client.request_json.return_value={'data':{'id':7,'name':'irrelevant'}}
            result=monitor.refresh_generic_koth({'url':f'http://127.0.0.1:{server.server_port}','max_points':1500})
            self.assertEqual(result['points'],750);self.assertEqual(result['rank'],2)
            self.assertNotIn('Authorization',captured[0]);self.assertNotIn('Cookie',captured[0])
        finally: server.shutdown();server.server_close();thread.join()

    def test_password_login_closed_redirect_verifies_authenticated_user(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def do_GET(self):
                if self.path=='/login':
                    self.send_response(200);self.end_headers();self.wfile.write(b'<input name="nonce" value="local">')
                elif self.path=='/challenges':
                    self.send_response(403);self.end_headers();self.wfile.write(b'Local lab has not started yet')
                elif self.path=='/api/v1/users/me' and self.headers.get('Cookie')=='session=accepted':
                    self.send_response(200);self.end_headers();self.wfile.write(b'{"success":true,"data":{"id":7,"name":"test"}}')
                else:
                    self.send_response(403);self.end_headers();self.wfile.write(b'{"message":"Forbidden"}')
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length',0)))
                if self.path=='/api/v2/auth/login':
                    self.send_response(404);self.end_headers();return
                self.send_response(302);self.send_header('Location','/challenges')
                if b'password=correct' in body:self.send_header('Set-Cookie','session=accepted; Path=/')
                self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}'
            self.assertEqual(CTFdClient(url,'test','correct').login()['user']['id'],7)
            with self.assertRaises(ApiError):CTFdClient(url,'test','wrong').login()
        finally:server.shutdown();server.server_close();thread.join()

    def test_port_collision_reports_options_without_stopping_owner(self):
        import argparse
        import socket
        with socket.socket() as owner:
            owner.bind(('127.0.0.1',0));owner.listen()
            runner=object.__new__(lab.Lab)
            runner.args=argparse.Namespace(port=owner.getsockname()[1],koth_port=1)
            with self.assertRaisesRegex(RuntimeError,'--port / --koth-port'):
                runner.start()
            self.assertGreater(owner.fileno(),-1)

    def test_failed_sync_keeps_desired_result_for_retry(self):
        import argparse
        import random
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            runner=object.__new__(lab.Lab)
            runner.directory=Path(d);runner.args=argparse.Namespace(seed=2026)
            runner.operation_lock=threading.RLock();runner.rng=random.Random(2026)
            runner.games={'42':{'challenge_id':42,'round':1,'scores':{'7':0,'9':0}}}
            runner.control=Mock(side_effect=RuntimeError('Award write unavailable'))
            runner.event=Mock()
            with self.assertRaisesRegex(RuntimeError,'Award write unavailable'):
                runner.koth('set',challenge=42,team=7,score=800)
            self.assertTrue(runner.sync_pending)
            self.assertEqual(json.loads((Path(d)/'koth.json').read_text())['42']['scores']['7'],800)
            rows=[{'team_id':7,'name':'lab-koth-42','value':1500},{'team_id':9,'name':'lab-koth-42','value':0}]
            runner.status={'teams':[{'id':7,'score':1500},{'id':9,'score':0}], 'awards':rows}
            runner.control=Mock()
            runner.client=Mock();runner.client.return_value.request_json.return_value={'data':[{'account_id':7,'score':1500}]}
            runner.sync()
            self.assertFalse(runner.sync_pending)
            self.assertEqual(runner.games['42']['scores']['7'],800)

    def test_configured_comparison_and_maximum_use_sources(self):
        sources={'42':{'max_points':1000},'43':{'max_points':500}}
        view={'team_name':'Us','scoreboard':[{'account_id':7,'name':'Us','score':900,'pos':1},{'account_id':9,'name':'Other','score':800,'pos':2}],
              'challenges':{'42':{'id':42,'name':'Alpha'},'43':{'id':43,'name':'Beta'}},
              'koth':{'42':{'id':42,'name':'Alpha','points':500,'score':50,'team_points':{'7':500,'9':800},'status':'LIVE'}}}
        with patch.object(app,'KOTH_SOURCES',sources):
            display='\n'.join(app.render_team_comparison(view,120))
            self.assertIn('Alpha',display);self.assertIn('Beta',display);self.assertNotIn('BRK',display)
            koth='\n'.join(app.render_koth(view,120))
            self.assertIn('/ 1000 pt',koth)
