"""Optional KOTH extension point for an LLM customizing a competition.

Default: disabled. Set `koth = true` plus [[koth_sources]] in the profile.
Start here when asked to add a KOTH screen. Full recipe: .github/USAGE.md#koth.
Profile example (koth must be a top-level key, before the array of tables):
    koth = true
    [[koth_sources]]
    challenge_id = 42
    adapter = "generic"
    url = "https://scores.example.org/standings.json"
    max_points = 1000

1. Inspect the competition's documented API/fixture and scoring rules.
2. Add an adapter(source, account_id) below and register it in ADAPTERS.
   The adapter owns its requests; no CTFd credentials/client are passed here.
3. Return rank, teams, score, leader_score, points, max_points, team_points.
   team_points maps str(CTFd account ID) -> awarded/projected points, not raw scores.
   Missing accounts stay unknown. Never infer identity from names or problem IDs.
4. app.py fetch_koth_metrics/refresh_koth handles polling and stale/error states.
   render_koth/render_team_comparison already render the normalized result.
   Official scoreboard totals remain authoritative; never add these points twice.
5. Test default-off, configured-on, errors, recovery, comparison, and packaging.
   See .github/tests/test_koth_extension.py and test_koth_layout.py.

The built-in generic adapter is an EXAMPLE protocol, not a universal CTFd API:
{"teams": [{"team_id": 7, "raw_score": 20}], "round": 1}
Its explicit rule is floor(max_points * raw_score / leader_score), zero if all
scores are zero. Other scoring rules require another adapter, not guesses.
"""
import json
import math
import urllib.request


def generic(source: dict, account_id: int) -> dict:
    request = urllib.request.Request(source['url'], headers={'Accept': 'application/json'})
    # A fresh opener has no CTFd cookie jar or token, including on redirects.
    with urllib.request.build_opener().open(request, timeout=20) as response:
        value = json.load(response)
    if not isinstance(value, dict) or not isinstance(value.get('teams'), list):
        raise ValueError('Invalid generic KOTH standings')
    scores = {}
    for row in value['teams']:
        if not isinstance(row, dict):
            raise ValueError('Invalid generic KOTH row')
        identifier, raw = row.get('team_id'), row.get('raw_score')
        if type(identifier) is not int or identifier < 1 or identifier in scores:
            raise ValueError('Invalid or duplicate KOTH account ID')
        if type(raw) not in (int, float) or not math.isfinite(raw) or raw < 0:
            raise ValueError('Invalid generic KOTH score')
        scores[identifier] = float(raw)
    leader = max(scores.values(), default=0)
    maximum = float(source['max_points'])
    table = {str(key): math.floor(maximum * (raw / leader)) if leader else 0
             for key, raw in scores.items()}
    own = scores.get(account_id)
    return {'rank': 1 + sum(raw > own for raw in scores.values()) if own is not None else None,
            'teams': len(scores), 'score': own, 'leader_score': leader,
            'points': table.get(str(account_id)), 'rounds': value.get('round'),
            'team_points': table, 'max_points': maximum}


ADAPTERS = {'generic': generic}


def fetch(source: dict, account_id: int) -> dict:
    """Dispatch an explicitly configured adapter and validate its display contract."""
    result = ADAPTERS[source['adapter']](source, account_id)
    required = {'rank', 'teams', 'score', 'leader_score', 'points', 'team_points', 'max_points'}
    if not isinstance(result, dict) or not required.issubset(result):
        raise ValueError('KOTH adapter did not return the normalized display fields')
    for key in ('score', 'leader_score', 'points'):
        value = result[key]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError(f'Invalid KOTH {key}')
    if result['max_points'] != source['max_points']:
        raise ValueError('KOTH max_points must match the configured scoring scale')
    if type(result['teams']) is not int or result['teams'] < 0:
        raise ValueError('Invalid KOTH team count')
    if result['rank'] is not None and (type(result['rank']) is not int or not 1 <= result['rank'] <= result['teams']):
        raise ValueError('Invalid KOTH rank')
    points = result['team_points']
    if not isinstance(points, dict) or any(
        not isinstance(key, str) or not key.isdigit() or int(key) < 1
        or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= source['max_points']
        for key, value in points.items()
    ):
        raise ValueError('Invalid KOTH team_points')
    if result['points'] != points.get(str(account_id)):
        raise ValueError('KOTH own points must match team_points')
    return result
