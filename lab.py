#!/usr/bin/env python3
"""Persistent, loopback-only official CTFd lab. Python 3.12+, Docker required."""
from __future__ import annotations
import argparse
import fcntl
import html
import json
import os
from pathlib import Path
import random
import secrets
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'src'))
from ctfd_monitor.client import CTFdClient, ApiError
IMAGE = 'ctfd/ctfd:3.8.9@sha256:84aff1e50b6a6f931b5da90c6f5b7c623ba4583217a9b00e9d4c1b7c53b9739f'


def standings(scores, maximum=1500):
    leader = max(scores.values(), default=0)
    ordered = sorted(scores, key=lambda key: (-scores[key], int(key)))
    return [dict(team_id=int(key), raw_score=scores[key], points=int(maximum*scores[key]/leader) if leader else 0,
                 rank=1+sum(value > scores[key] for value in scores.values())) for key in ordered]


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


class Lab:
    def __init__(self, args):
        self.args = args
        self.directory = args.data.resolve(); self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = open(self.directory/'lock', 'w')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.prefix = ['docker']
        if subprocess.run(self.prefix+['info'], capture_output=True).returncode:
            self.prefix = ['sudo','-n','docker']
        self.docker('info')
        self.name = 'ctfd-lab-'+__import__('hashlib').sha256(str(self.directory).encode()).hexdigest()[:12]
        self.url = f'http://localhost:{args.port}'
        self.faults = {'ctfd':'normal','koth':'normal'}
        self.servers = []; self.running = False; self.started = False
        self.sync_pending = False; self.retry_stop = threading.Event(); self.retry_thread = None
        self.auto_stop = threading.Event(); self.auto_thread = None; self.operation_lock = threading.RLock()
        self.rng = random.Random(args.seed); self.last = 'Ready'; self.mode = 'closed'
        path = self.directory/'credentials.json'
        if path.exists(): self.credentials = json.loads(path.read_text())
        else:
            self.credentials = {'password':secrets.token_urlsafe(18), 'tokens':{f'lab-{n}-{m}':'ctfd_'+secrets.token_hex(32) for n in range(6) for m in range(2 if n == 0 else 1)}, 'expired':'ctfd_'+secrets.token_hex(32)}
            save(path,self.credentials)
        path = self.directory/'koth.json'
        self.games = json.loads(path.read_text()) if path.exists() else {}

    def docker(self,*args,**kwargs):
        result = subprocess.run(self.prefix+list(args),capture_output=True,text=True,timeout=180,**kwargs)
        if result.returncode: raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout

    def control(self,action,**data):
        with self.operation_lock:
            output = self.docker('exec','-i',self.name,'python','/opt/lab/control.py',input=json.dumps({'action':action,'data':data}))
            self.status = json.loads(output.split('LAB_RESULT=')[-1])
            return self.status

    def client(self,name='lab-0-0',proxy=False):
        return CTFdClient(self.url if proxy else self.backend, '', '', self.credentials['tokens'][name])

    def start(self):
        # Reserve the public ports before starting anything; never kill port owners.
        reserved = []
        try:
            for port in (self.args.port,self.args.koth_port):
                s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); reserved.append(s)
                try: s.bind(('127.0.0.1',port))
                except OSError as error: raise RuntimeError(f'Port {port} unavailable: {error}. Use --port / --koth-port.') from error
        finally:
            for s in reserved: s.close()
        existing = subprocess.run(self.prefix+['inspect',self.name],capture_output=True).returncode == 0
        if existing:
            label = self.docker('inspect','--format','{{index .Config.Labels "ctfd-monitor.lab"}}',self.name).strip()
            if label != 'true': raise RuntimeError(f'Container name already belongs to another service: {self.name}')
            self.docker('start',self.name)
        else:
            self.docker('image','inspect',IMAGE)  # pinned image may need pulling below
            (self.directory/'uploads').mkdir(exist_ok=True)
            self.docker('run','-d','--name',self.name,'--label','ctfd-monitor.lab=true','-p','127.0.0.1::8000',
                        '-v',f'{self.directory}:/var/lab','-v',f'{self.directory}/uploads:/var/uploads','-v',f'{ROOT}/lab:/opt/lab:ro',
                        '-e','DATABASE_URL=sqlite:////var/lab/ctfd.db','-e','UPLOAD_FOLDER=/var/uploads',
                        '-e',f"SECRET_KEY={self.credentials['password']}",'-e','WORKERS=1',IMAGE)
        self.started = True
        self.refresh_backend()
        self.wait_ready()
        self.control('seed',**self.credentials,koth_url=f'http://localhost:{self.args.koth_port}')
        self.set_time('closed')
        for c in self.status['challenges']:
            if c['category'] != 'Arena': continue
            self.games.setdefault(str(c['id']), {'challenge_id':c['id'],'name':c['name'],'round':1,'updated_at':time.time(),'scores':{str(t['id']):0 for t in self.status['teams']}})
        self.persist_games(); self.sync()
        self.serve('ctfd', self.args.port); self.serve('koth',self.args.koth_port)
        self.profiles(); self.running = True
        self.retry_thread = threading.Thread(target=self.retry_sync,daemon=True); self.retry_thread.start()

    def refresh_backend(self):
        port = self.docker('port',self.name,'8000/tcp').strip().rsplit(':',1)[1]
        self.backend = f'http://127.0.0.1:{port}'

    def wait_ready(self):
        for _ in range(90):
            try:
                with urllib.request.urlopen(self.backend+'/login',timeout=2) as r:
                    if r.status == 200: return
            except OSError: pass
            time.sleep(1)
        raise RuntimeError('CTFd readiness timed out')

    def event(self,action,data,result):
        record = dict(time=time.time(),action=action,data=data,result=result,seed=self.args.seed)
        with open(self.directory/'events.jsonl','a') as f: f.write(json.dumps(record,ensure_ascii=False)+'\n')
        self.last = str(result)

    def set_time(self,mode,seconds=3600):
        if mode == 'remaining' and self.mode not in ('start','remaining'): raise ValueError('Start the contest before changing remaining time')
        if mode in ('start','remaining') and seconds <= 0: raise ValueError('Seconds must be positive')
        self.control('time',mode=mode,seconds=seconds)
        # Check the actual HTTP response after cache invalidation.
        try:
            self.client().request_json('/api/v1/challenges')
            if mode not in ('start','remaining'): raise AssertionError('Closed challenge list still accessible')
        except ApiError as e:
            if mode in ('start','remaining'): raise
            expected = 'competition_ended' if mode == 'end' else 'competition_not_started'
            if e.status != 403 or e.code != expected: raise
        self.mode = mode
        self.event('time',dict(mode=mode,seconds=seconds),'verified')

    def persist_games(self): save(self.directory/'koth.json',self.games)

    def sync(self):
        rows = [dict(challenge_id=g['challenge_id'],**row) for g in self.games.values() for row in standings(g['scores'])]
        self.control('awards',rows=rows)
        expected = {(r['team_id'],f"lab-koth-{r['challenge_id']}"):r['points'] for r in rows}
        actual = {(a['team_id'],a['name']):a['value'] for a in self.status['awards']}
        assert all(actual[k] == v for k,v in expected.items())
        board = self.client().request_json('/api/v1/scoreboard')['data']
        expected_scores = {t['id']:t['score'] for t in self.status['teams']}
        assert all(row['score'] == expected_scores[row['account_id']] for row in board), 'Official scoreboard has stale totals'
        self.sync_pending = False
        self.event('sync',{'rows':len(rows)},'verified')
        return board

    def koth(self,mode='random',challenge=None,team=None,score=0):
        if mode not in ('random','round','set'): raise ValueError('Unknown KOTH operation')
        if challenge is not None and str(challenge) not in self.games: raise ValueError('Unknown KOTH challenge')
        if type(score) is not int or score < 0: raise ValueError('Score must be a nonnegative integer')
        if team is not None and str(team) not in next(iter(self.games.values()))['scores']: raise ValueError('Unknown team ID')
        with self.operation_lock:
            selected = [self.games[str(challenge)]] if challenge else list(self.games.values())
            for game in selected:
                if mode == 'round': game['round'] += 1
                for key in game['scores']:
                    if team is not None and int(key) != int(team): continue
                    game['scores'][key] = self.rng.randrange(1001) if mode in ('random','round') else int(score)
                game['updated_at'] = time.time()
            self.sync_pending = True
            self.persist_games()  # durable result first, retry sync after failure/restart
            self.event('koth-pending', {'games':selected}, 'saved; awaiting official Award sync')
            self.sync(); self.event('koth',dict(mode=mode,challenge=challenge,team=team,score=score),'verified')

    def retry_sync(self):
        while not self.retry_stop.wait(5):
            if self.sync_pending:
                try:
                    with self.operation_lock: self.sync()
                except Exception as error: self.event('sync-error',{},str(error))

    def submit(self,name=None,challenge=None,wrong=False,opponent=False):
        name = name or self.rng.choice([u['name'] for u in self.status['users'] if u['team_id'] and (u['name'].startswith('lab-0-') != opponent)])
        client = self.client(name)
        solved = {r['challenge_id'] for r in client.request_json('/api/v1/teams/me/solves')['data']}
        candidates = [c for c in [c for c in self.status['challenges'] if c['id'] not in {g['challenge_id'] for g in self.games.values()}] if c['state']=='visible' and (wrong or c['id'] not in solved)]
        if challenge is None:
            if not candidates: raise ValueError('No unsolved visible challenges for this team')
            challenge = self.rng.choice(candidates)['id']
        index = int(challenge)
        if str(index) in self.games: raise ValueError('KOTH has no flag submissions')
        self.event('submit-attempt',dict(user=name,challenge=challenge,wrong=wrong),'sending to official CTFd')
        result = client.request_json('/api/v1/challenges/attempt', method='POST',payload={'challenge_id':int(challenge),'submission':'wrong' if wrong else f'flag{{local_{index:02d}}}'})
        status = result['data']['status']
        if status != ('incorrect' if wrong else 'correct'): raise RuntimeError(f'Submission rejected: {result}')
        self.event('submit',dict(user=name,challenge=challenge,wrong=wrong),result)
        return result

    def fault(self, service, mode):
        if service not in self.faults or mode not in ('normal','offline','delay','429','503'):
            raise ValueError('Invalid fault')
        self.faults[service] = mode
        self.event('fault', {'service':service,'mode':mode}, 'enabled')

    def publish(self, name):
        if not name.strip(): raise ValueError('Challenge name is required')
        self.control('new', name=name)
        identifier = self.status['challenges'][-1]['id']
        detail = self.client().request_json(f'/api/v1/challenges/{identifier}')['data']
        assert detail['name'] == name
        self.event('publish', {'id':identifier,'name':name}, 'verified')

    def change(self,challenge,**changes):
        if changes.get('files', 'add') not in ('add','replace','delete'): raise ValueError('Unknown attachment operation')
        self.control('challenge',id=int(challenge),**changes)
        if self.mode in ('start','remaining'):
            listed = self.client().request_json('/api/v1/challenges')['data']
            visible = any(c['id']==int(challenge) for c in listed)
            current = next(c for c in self.status['challenges'] if c['id']==int(challenge))
            assert visible == (current['state']=='visible')
            if visible:
                detail = self.client().request_json(f'/api/v1/challenges/{challenge}')['data']
                if 'description' in changes: assert detail['description']==changes['description']
                assert len(detail['files']) == len(current['files'])
                for location in detail['files']:
                    with self.client().open_file(location) as response:
                        assert response.status == 200
                        response.read()
        self.event('challenge',dict(id=challenge,**changes),'verified')

    def token(self,revoke=False):
        token = '' if revoke else 'ctfd_'+secrets.token_hex(32)
        self.control('token',name='lab-0-0',token=token,expired=self.credentials['expired'])
        self.credentials['tokens']['lab-0-0']=token
        save(self.directory/'credentials.json',self.credentials); self.profiles()
        self.event('token',{'revoked':revoke},'updated')

    def profiles(self):
        sources = ''.join(f'\n[[koth_sources]]\nchallenge_id = {g["challenge_id"]}\nadapter = "generic"\nurl = "http://localhost:{self.args.koth_port}/api/games/{g["challenge_id"]}"\nmax_points = 1500\n' for g in self.games.values())
        for mode in ('token','password'):
            credentials = {'token':self.credentials['tokens']['lab-0-0']} if mode=='token' else {'username':'lab-0-0','password':self.credentials['password']}
            save(self.directory/f'{mode}-credentials.json', credentials)
            text = f'name = "Local lab {mode}"\nurl = "{self.url}"\nroot = "{mode}-workspace"\nstate = "{mode}-state"\ncredentials_file = "{mode}-credentials.json"\npoll_interval = 1\nkoth = true\n'+sources
            (self.directory/f'{mode}.toml').write_text(text)

    def serve(self,kind,port):
        lab = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def handle_request(self):
                fault = lab.faults[kind]
                if fault=='offline': self.connection.close(); return
                if fault=='delay': time.sleep(3)
                if fault in ('429','503'):
                    self.send_response(int(fault)); self.send_header('Retry-After','2'); self.end_headers(); self.wfile.write(b'{"success":false,"message":"lab injected fault"}'); return
                if kind=='koth':
                    with lab.operation_lock:
                        games = {k:dict(challenge_id=g['challenge_id'],name=g['name'],round=g['round'],updated_at=g['updated_at'],teams=standings(g['scores'])) for k,g in lab.games.items()}
                    if self.path.startswith('/api/games/'):
                        game = games.get(self.path.rsplit('/',1)[-1])
                        self.send_response(200 if game else 404); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(game).encode()); return
                    selected = self.path.strip('/')
                    content = '<h1>Local KOTH</h1>'+''.join(f'<h2><a href="/{key}">{html.escape(g["name"])}</a> / round {g["round"]}</h2><pre>{html.escape(json.dumps(g["teams"],indent=2))}</pre>' for key,g in games.items() if not selected or selected==key)
                    self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(content.encode()); return
                body = self.rfile.read(int(self.headers.get('Content-Length',0))) or None
                headers = {k:v for k,v in self.headers.items() if k.lower() not in ('host','connection','accept-encoding')}
                request = urllib.request.Request(lab.backend+self.path,data=body,headers=headers,method=self.command)
                # No redirects: browser must retain localhost origin and cookies.
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self,*a,**k): return None
                try:
                    try: response = urllib.request.build_opener(NoRedirect).open(request,timeout=30)
                    except urllib.error.HTTPError as error: response = error
                    with response:
                        content = response.read(); self.send_response(response.code)
                        for key,value in response.headers.items():
                            if key.lower() not in ('transfer-encoding','connection','content-length','server','date'):
                                if key.lower()=='location': value=value.replace(lab.backend,lab.url)
                                self.send_header(key,value)
                        self.send_header('Content-Length',str(len(content))); self.end_headers(); self.wfile.write(content)
                except OSError: self.send_error(502)
            do_GET = do_POST = do_PATCH = do_DELETE = handle_request
        server = ThreadingHTTPServer(('127.0.0.1',port),Handler); server.daemon_threads=True
        self.servers.append(server); threading.Thread(target=server.serve_forever,daemon=True).start()

    def automatic(self):
        while not self.auto_stop.wait(5):
            try:
                with self.operation_lock:
                    if self.rng.choice([True,False]): self.submit(opponent=self.rng.choice([True,False]))
                    else: self.koth('round')
            except Exception as error: self.event('automatic',{},str(error))

    def stop_auto(self):
        self.auto_stop.set()
        if self.auto_thread: self.auto_thread.join(timeout=35)
        self.auto_thread = None

    def reset(self):
        self.stop_auto(); self.control('reset'); self.koth('set',score=0); self.set_time('closed')

    def display(self):
        print(f'\nCTFd {self.url} [{self.mode}] remaining={max(0,int(self.status["end"])-int(time.time()))}s | KOTH http://localhost:{self.args.koth_port}')
        print(f"Test lab-0-0 / lab-0-1 password: {self.credentials['password']}\nToken: {self.credentials['tokens']['lab-0-0']}\nExpired token: {self.credentials['expired']}\nAdmin lab-admin / {self.credentials['password']}")
        for mode in ('token','password'):
            print(f'{mode}: env -u CTFD_MONITOR_URL -u CTFD_MONITOR_ROOT -u CTFD_MONITOR_STATE -u CTFD_MONITOR_TOKEN -u CTFD_MONITOR_USER -u CTFD_MONITOR_PASSWORD {shlex.quote(sys.executable)} {shlex.quote(str(ROOT/"ctfd-monitor.py"))} --config {shlex.quote(str(self.directory/(mode+".toml")))}')
        try:
            board = self.client().request_json('/api/v1/scoreboard')['data']
            scores = {row['account_id']:row['score'] for row in board}
            for team in self.status['teams']:
                total = scores.get(team['id'], 0)
                koth = sum(a['value'] for a in self.status['awards'] if a['team_id']==team['id'])
                print(f"{team['name']}: total={total} normal={total-koth} KOTH={koth}")
        except Exception as e: print(f'Scoreboard: {e}')
        print('Teams: '+', '.join(f"{t['id']}={t['name']}" for t in self.status['teams']))
        print('Challenges: '+', '.join(f"{c['id']}={c['name']} ({c['state']})" for c in self.status['challenges']))
        print(f'Last: {self.last} | auto={bool(self.auto_thread)} | faults={self.faults}')

    def menu(self):
        print('Commands: start [seconds], close, end, remaining seconds, solve [user challenge], opponent, wrong,\nnew name, show id, hide id, describe id text, hint id text, files id add|replace|delete,\nkoth random|round|zero|sync|set [challenge team score], fault ctfd|koth normal|offline|delay|429|503,\ntoken renew|revoke, auto start|stop, status, reset, quit')
        while True:
            self.display()
            parts = []
            try:
                parts = shlex.split(input('lab> '))
                if not parts: continue
                command,*args = parts
                if command=='quit': return
                if command in ('start','close','end','remaining'): self.set_time('closed' if command=='close' else command,int(args[0]) if args else 3600)
                elif command in ('solve','opponent','wrong'): self.submit(args[0] if args else None,int(args[1]) if len(args)>1 else None,wrong=command=='wrong',opponent=command=='opponent')
                elif command in ('show','hide'): self.change(args[0],state='visible' if command=='show' else 'hidden')
                elif command in ('describe','hint'): self.change(args[0],**{'description' if command=='describe' else 'hint':' '.join(args[1:])})
                elif command=='files': self.change(args[0],files=args[1])
                elif command=='koth' and args[0]=='sync': self.sync()
                elif command=='koth': self.koth('set' if args[0]=='zero' else args[0],*(int(x) for x in args[1:]))
                elif command=='fault': self.fault(args[0],args[1])
                elif command=='new': self.publish(' '.join(args))
                elif command=='token':
                    if args[0] not in ('renew','revoke'): raise ValueError('Use token renew or token revoke')
                    self.token(revoke=args[0]=='revoke')
                elif command=='auto':
                    if args[0]=='start' and not self.auto_thread:
                        self.auto_stop.clear(); self.auto_thread=threading.Thread(target=self.automatic,daemon=True); self.auto_thread.start()
                    elif args[0]=='stop': self.stop_auto()
                elif command=='reset':
                    if input('Type RESET to erase solves and scores: ')=='RESET': self.reset()
                elif command=='status': print(json.dumps(self.control('status'),ensure_ascii=False,indent=2))
                else: raise ValueError('Unknown command')
            except (ValueError,IndexError,RuntimeError,ApiError,AssertionError) as error:
                self.event('error',{'command':parts},str(error)); print(f'FAILED: {error}')

    def close(self):
        self.stop_auto()
        self.retry_stop.set()
        if self.retry_thread: self.retry_thread.join(timeout=35)
        for server in self.servers: server.shutdown(); server.server_close()
        if self.started: self.docker('stop',self.name)
        self.lock.close()


def main():
    if sys.version_info < (3, 12):
        raise SystemExit('Python 3.12 or newer is required')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8000); parser.add_argument('--koth-port',type=int,default=8001)
    parser.add_argument('--data',type=Path,default=ROOT/'.ctfd-lab'); parser.add_argument('--seed',type=int,default=2026)
    parser.add_argument('--scenario',choices=['smoke'])
    args = parser.parse_args()
    lab = None
    try:
        print('Preparing pinned official CTFd and local KOTH; data will be retained.',flush=True)
        lab = Lab(args)
        try: lab.docker('image','inspect',IMAGE)
        except RuntimeError: lab.docker('pull',IMAGE)
        lab.start()
        if args.scenario:
            from lab.smoke import smoke
            smoke(lab)
        else: lab.menu()
    except (KeyboardInterrupt,EOFError): print('\nStopping lab; data retained.')
    finally:
        if lab: lab.close()

if __name__=='__main__': main()
