"""Runs only inside the pinned CTFd container; local administrative controls."""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, '/opt/CTFd')
from CTFd import create_app
from CTFd.models import db, Users, Teams, Challenges, Flags, ChallengeFiles, UserTokens, Awards, Hints, Solves, Fails
from CTFd.utils import set_config, get_config
from CTFd.cache import clear_standings, clear_challenges, clear_all_user_sessions

app = create_app()
request = json.load(sys.stdin)
with app.app_context():
    action = request['action']
    data = request.get('data', {})
    if action == 'seed':
        for key, value in dict(setup=True, ctf_name='Local monitor lab', user_mode='teams', challenge_visibility='private', score_visibility='public', account_visibility='public', registration_visibility='private', team_size=10).items():
            set_config(key, value)
        if not Users.query.filter_by(name='lab-admin').first():
            admin = Users(name='lab-admin', email='admin@lab.invalid', password=data['password'], type='admin', verified=True)
            db.session.add(admin)
            for n in range(6):
                team = Teams(name='Our team' if n == 0 else f'Opponent {n}', email=f'team{n}@lab.invalid', password=data['password'])
                db.session.add(team)
                db.session.flush()
                for member in range(2 if n == 0 else 1):
                    user = Users(name=f'lab-{n}-{member}', email=f'user{n}-{member}@lab.invalid', password=data['password'], verified=True, team_id=team.id)
                    db.session.add(user)
                    db.session.flush()
                    db.session.add(UserTokens(user_id=user.id, value=data['tokens'][user.name]))
            db.session.flush()
            user = Users.query.filter_by(name='lab-0-0').one()
            db.session.add(UserTokens(user_id=user.id, value=data['expired'], expiration=datetime.utcnow()-timedelta(days=1)))
            for n in range(15):
                category = ['Web', 'Pwn', 'Reversing', 'Crypto', 'Forensics', 'Misc'][n//2] if n < 12 else 'Arena'
                flag = f'flag{{local_{n+1:02d}}}'
                challenge = Challenges(name=f'{category} {n%2+1}' if n < 12 else f'KOTH {n-11}', description=f'Local practice. Submit `{flag}`.' if n < 12 else 'Local KOTH standings: http://localhost:8001', category=category, value=100 if n < 12 else 0, type='standard', state='visible')
                db.session.add(challenge)
                db.session.flush()
                if n < 12:
                    db.session.add(Flags(challenge_id=challenge.id, type='static', content=flag, data=''))
                    import io, zipfile, tarfile
                    folder = Path('/var/uploads') / f'lab-{challenge.id}'
                    folder.mkdir(parents=True, exist_ok=True)
                    names = ['readme.txt', '추가자료.txt'] if n%4 == 1 else ['자료.txt' if n%4 == 0 else 'bundle.zip' if n%4 == 2 else 'bundle.tar']
                    for name in names:
                        path = folder/name
                        content = f'{challenge.name}\n{flag}\n'.encode()
                        if name.endswith('.zip'):
                            with zipfile.ZipFile(path, 'w') as z: z.writestr('readme.txt', content)
                        elif name.endswith('.tar'):
                            with tarfile.open(path, 'w') as t:
                                info = tarfile.TarInfo('readme.txt'); info.size = len(content); t.addfile(info, io.BytesIO(content))
                        else: path.write_bytes(content)
                        db.session.add(ChallengeFiles(challenge_id=challenge.id, type='challenge', location=f'lab-{challenge.id}/{name}'))
            db.session.commit()
        for challenge in Challenges.query.filter_by(category='Arena'):
            challenge.description = f"Local KOTH standings: {data['koth_url']}/{challenge.id}"
        db.session.commit()
        user = Users.query.filter_by(name='lab-0-0').one()
        if not UserTokens.query.filter_by(value=data['expired']).first():
            db.session.add(UserTokens(user_id=user.id,value=data['expired'],expiration=datetime.utcnow()-timedelta(days=1)))
            db.session.commit()
    elif action == 'time':
        now = int(time.time())
        mode = data['mode']
        set_config('start', now-60 if mode in ('start','end','remaining') else now+86400)
        set_config('end', now-1 if mode == 'end' else now+int(data.get('seconds',3600)) if mode in ('start','remaining') else now+90000)
    elif action == 'new':
        challenge = Challenges(name=data.get('name','New local challenge'), description='New local practice challenge', category='Misc', value=100, type='standard', state='visible')
        db.session.add(challenge); db.session.flush()
        flag = f'flag{{local_{challenge.id:02d}}}'
        challenge.description = f'Submit `{flag}`.'
        db.session.add(Flags(challenge_id=challenge.id, type='static', content=flag, data=''))
        db.session.commit()
    elif action == 'challenge':
        c = db.session.get(Challenges, int(data['id']))
        if not c: raise ValueError('Unknown challenge')
        for key in ('state','description'): 
            if key in data: setattr(c, key, data[key])
        if 'hint' in data: db.session.add(Hints(challenge_id=c.id, content=data['hint'], cost=0))
        if data.get('files') in ('replace','delete'):
            for f in ChallengeFiles.query.filter_by(challenge_id=c.id).all():
                (Path('/var/uploads')/f.location).unlink(missing_ok=True); db.session.delete(f)
        if data.get('files') in ('add','replace'):
            location = f'lab-{c.id}/update-{time.time_ns()}.txt'
            path = Path('/var/uploads')/location; path.parent.mkdir(exist_ok=True); path.write_text(data.get('content','Updated local attachment'))
            db.session.add(ChallengeFiles(challenge_id=c.id, type='challenge', location=location))
        db.session.commit()
    elif action == 'awards':
        for row in data['rows']:
            name = f"lab-koth-{row['challenge_id']}"
            matches = Awards.query.filter_by(team_id=row['team_id'], name=name).all()
            award = matches[0] if matches else Awards(team_id=row['team_id'], name=name, value=0)
            for duplicate in matches[1:]: db.session.delete(duplicate)
            award.value = row['points']; db.session.add(award)
        db.session.commit()
    elif action == 'token':
        user = Users.query.filter_by(name=data['name']).one()
        UserTokens.query.filter_by(user_id=user.id).filter(UserTokens.value != data['expired']).delete()
        if data.get('token'): db.session.add(UserTokens(user_id=user.id, value=data['token']))
        db.session.commit()
    elif action == 'reset':
        for model in (Solves, Fails, Awards): model.query.delete()
        db.session.commit()
    elif action != 'status': raise ValueError(action)
    clear_standings()
    clear_challenges()
    clear_all_user_sessions()
    result = {'teams':[{'id':t.id,'name':t.name,'score':sum(db.session.get(Challenges, solve.challenge_id).value for solve in Solves.query.filter_by(team_id=t.id)) + sum(award.value for award in Awards.query.filter_by(team_id=t.id))} for t in Teams.query.order_by(Teams.id)], 'users':[{'id':u.id,'name':u.name,'team_id':u.team_id} for u in Users.query.order_by(Users.id)], 'challenges':[{'id':c.id,'name':c.name,'category':c.category,'state':c.state,'description':c.description,'files':[f.location for f in ChallengeFiles.query.filter_by(challenge_id=c.id)]} for c in Challenges.query.order_by(Challenges.id)], 'start':get_config('start'),'end':get_config('end'), 'awards':[{'team_id':a.team_id,'name':a.name,'value':a.value} for a in Awards.query.all()]}
    print('LAB_RESULT='+json.dumps(result))
