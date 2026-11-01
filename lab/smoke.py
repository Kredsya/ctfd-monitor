"""Real Docker + product monitor integration; shared menu controls, fixed seed."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


def eventually(check, timeout=45):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        value = check()
        if value: return value
        time.sleep(.3)
    raise AssertionError('Timed out waiting for '+str(check))


def smoke(lab):
    root = Path(__file__).resolve().parents[1]
    processes = []
    observations = {}
    def raw_closed(label):
        request=urllib.request.Request(lab.url+'/api/v1/challenges',headers={'Authorization':'Token '+lab.credentials['tokens']['lab-0-0'],'Content-Type':'application/json'})
        try: urllib.request.urlopen(request)
        except urllib.error.HTTPError as e:
            body=json.loads(e.read()); observations[label]={'status':e.code,'body':body}
            print(label,observations[label],flush=True)
            assert e.code==403
        else: raise AssertionError('Closed challenges accessible')
    def launch(mode):
        output=open(lab.directory/f'{mode}-monitor.log','w')
        env={k:v for k,v in os.environ.items() if not k.startswith('CTFD_MONITOR_')}
        p=subprocess.Popen([sys.executable,str(root/'ctfd-monitor.py'),'--config',str(lab.directory/f'{mode}.toml'),'--headless','run'],stdout=output,stderr=subprocess.STDOUT,env=env)
        processes.append((p,output)); return p
    def state(mode):
        lines=(lab.directory/f'{mode}-monitor.log').read_text().splitlines()
        for line in reversed(lines):
            try: return json.loads(line)
            except ValueError: pass
        return {}
    def file(mode,name):
        p=lab.directory/f'{mode}-state'/name
        return json.loads(p.read_text()) if p.exists() else {}
    try:
        raw_closed('before')
        for token in (lab.credentials['expired'], 'ctfd_invalid_local_only'):
            from ctfd_monitor.client import CTFdClient, ApiError
            try: CTFdClient(lab.url,'','',token).login()
            except ApiError as error: assert error.status == 401
            else: raise AssertionError('Invalid token accepted')
        try: lab.client().request_json('/api/v1/challenges/attempt',method='POST',payload={'challenge_id':1,'submission':'flag{local_01}'})
        except ApiError as error: assert error.competition_unavailable
        else: raise AssertionError('Closed submission accepted')
        for mode in ('token','password'):
            client=lab.client() if mode=='token' else __import__('ctfd_monitor.client',fromlist=['CTFdClient']).CTFdClient(lab.url,'lab-0-0',lab.credentials['password'])
            client.login(); launch(mode)
            eventually(lambda: state(mode).get('status') in ('PRE-START','UNAVAILABLE'))
        lab.set_time('start')
        lab.set_time('remaining',seconds=1800)
        assert abs(lab.status['end']-time.time()-1800)<5
        for mode in ('token','password'):
            eventually(lambda: state(mode).get('status')=='LIVE')
            eventually(lambda: len(file(mode,'current.json').get('challenges',{}))==15)
            workspace=lab.directory/f'{mode}-workspace'
            eventually(lambda: len(list(workspace.glob('*/chall/AGENTS.md')))>=15)
            eventually(lambda: len(list(workspace.glob('*/22.sh')))>=15)
            eventually(lambda: len(list(workspace.glob('*/chall/deploy/*.zip')))>0)
            eventually(lambda: len(file(mode,'koth.json').get('entries',{}))==3)
        protected = lab.directory/'token-workspace'/'user-notes.txt'
        protected.write_text('Keep these notes')
        lab.reset(); lab.set_time('start')
        lab.submit(name='lab-0-0',challenge=1); lab.submit(name='lab-0-1',challenge=2); lab.submit(opponent=True); lab.submit(wrong=True)
        assert len(lab.client().request_json('/api/v1/teams/me/solves')['data'])==2
        lab.change(3,description='Smoke changed',hint='smoke hint',files='replace')
        eventually(lambda: file('token','current.json').get('challenges',{}).get('3',{}).get('description')=='Smoke changed')
        lab.change(3,state='hidden')
        eventually(lambda: '3' not in file('token','current.json').get('challenges',{}))
        lab.change(3,state='visible')
        eventually(lambda: '3' in file('token','current.json').get('challenges',{}))
        lab.change(3,files='add')
        eventually(lambda: len(file('token','current.json').get('challenges',{}).get('3',{}).get('files',[]))==2)
        lab.change(3,files='delete')
        eventually(lambda: not file('token','current.json').get('challenges',{}).get('3',{}).get('files'))
        lab.publish('Smoke newly released challenge')
        new_id=lab.status['challenges'][-1]['id']
        eventually(lambda: str(new_id) in file('token','current.json').get('challenges',{}))
        lab.change(new_id,state='hidden')
        eventually(lambda: str(new_id) not in file('token','current.json').get('challenges',{}))
        for _ in range(3): lab.koth('round')
        assert len(lab.status['awards'])==18
        eventually(lambda: all(file('token','koth.json').get('entries',{}).get(k,{}).get('rounds')==g['round'] for k,g in lab.games.items()))
        rows=lab.client().request_json('/api/v1/scoreboard')['data']
        for row in rows:
            awards=sum(a['value'] for a in lab.status['awards'] if a['team_id']==row['account_id'])
            solves=lab.client().request_json(f"/api/v1/teams/{row['account_id']}/solves")['data']
            assert row['score']==awards+sum(s['challenge']['value'] for s in solves)
        eventually(lambda: state('token').get('score')==next(r['score'] for r in rows if r['name']=='Our team'))
        lab.fault('ctfd','delay')
        began=time.monotonic(); lab.client(proxy=True).request_json('/api/v1/scoreboard')
        assert time.monotonic()-began >= 2.5
        lab.fault('ctfd','normal')
        for fault in ('offline','429','503'):
            lab.fault('ctfd',fault)
            eventually(lambda: state('token').get('status')=='STALE')
            lab.fault('ctfd','normal')
            eventually(lambda: state('token').get('status')=='LIVE',timeout=75)
        lab.fault('koth','503')
        eventually(lambda: any(e.get('status')=='ERROR' for e in file('token','koth.json').get('entries',{}).values()))
        lab.fault('koth','normal')
        eventually(lambda: all(e.get('status')=='LIVE' for e in file('token','koth.json').get('entries',{}).values()))
        old=lab.credentials['tokens']['lab-0-0']; lab.token(revoke=True)
        eventually(lambda: state('token').get('status')=='STALE')
        lab.token()
        # Restart monitor so new credential file is loaded.
        for p,out in processes: p.send_signal(signal.SIGINT); p.wait(timeout=40); out.close()
        processes.clear(); launch('token')
        eventually(lambda: state('token').get('status')=='LIVE')
        lab.set_time('end'); raw_closed('after')
        eventually(lambda: state('token').get('status')=='ENDED')
        # KOTH awards can change while the challenges endpoint remains closed.
        # The header must follow the official combined total without adding it twice.
        own=next(t for t in lab.status['teams'] if t['name']=='Our team')
        previous=state('token')['score']
        lab.koth('set',team=own['id'],score=0 if any(a['value'] for a in lab.status['awards'] if a['team_id']==own['id']) else 100000)
        board=lab.client().request_json('/api/v1/scoreboard')['data']
        expected=next(row['score'] for row in board if row['account_id']==own['id'])
        assert expected != previous
        eventually(lambda: state('token').get('status')=='ENDED' and state('token').get('score')==expected)
        assert len(file('token','current.json')['challenges'])==15
        before=json.loads((lab.directory/'credentials.json').read_text())
        for p,out in processes: p.send_signal(signal.SIGINT); p.wait(timeout=40); out.close()
        processes.clear()
        lab.docker('restart',lab.name); lab.refresh_backend(); lab.wait_ready(); lab.set_time('closed'); lab.sync()
        assert before==json.loads((lab.directory/'credentials.json').read_text())
        assert len(lab.status['awards'])==18
        launch('token'); eventually(lambda: state('token').get('status')=='PRE-START')
        assert len(file('token','current.json')['challenges'])==15
        assert protected.read_text() == 'Keep these notes'
        lab.reset()
        assert all(a['value']==0 for a in lab.status['awards'])
        assert lab.client().request_json('/api/v1/teams/me/solves')['data']==[]
        (lab.directory/'stock-responses.json').write_text(json.dumps(observations,indent=2))
        print('SMOKE PASSED: real CTFd, both monitor profiles, submissions, files, KOTH, faults, auth, restart, reset',flush=True)
    finally:
        for p,out in processes:
            if p.poll() is None: p.send_signal(signal.SIGINT); p.wait(timeout=40)
            out.close()
