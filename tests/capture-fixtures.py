#!/usr/bin/env python3
"""Capture the browser harness's fixtures from a LIVE appliance — never hand-write them.

    EMBABEL_AUTH=user:pass APPLIANCE=http://127.0.0.1:11043 python3 tests/capture-fixtures.py [owner/repo]

Saves under tests/fixtures/: the served app (app.html), the world's contracts, and every
view envelope the app's scripts request, keyed exactly as the runtime keys them
(`view:<name>:<sorted args json>`), all computed at ONE instant (`capturedAt`) that the
harness freezes Date.now() to, so the app's own `since` arithmetic reproduces the keys.
Also the ask envelope for one question and the invocation Cypher of every view.
Re-run after any change to a view or to the app's calls; the harness failing on a
re-capture is the harness working.
"""
import base64, datetime, json, os, sys, urllib.request

REPO = sys.argv[1] if len(sys.argv) > 1 else 'embabel/embabel-agent'
BASE = os.environ.get('APPLIANCE', 'http://127.0.0.1:11043').rstrip('/')
HERE = os.path.dirname(os.path.abspath(__file__)); FX = os.path.join(HERE, 'fixtures')
NOW = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
NOW_MS = int(NOW.timestamp() * 1000)
def iso(ms): return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
DAYS = 7
SINCE = iso(NOW_MS - DAYS * 86400000); SINCE30 = iso(NOW_MS - 30 * 86400000)

def auth():
    if os.environ.get('EMBABEL_TOKEN'): return 'Bearer ' + os.environ['EMBABEL_TOKEN']
    if os.environ.get('EMBABEL_AUTH'): return 'Basic ' + base64.b64encode(os.environ['EMBABEL_AUTH'].encode()).decode()
    sys.exit('set EMBABEL_AUTH=user:pass or EMBABEL_TOKEN=...')
def req(path, body=None):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', 'Authorization': auth()})
    with urllib.request.urlopen(r, timeout=900) as resp: return resp.read()
def key(name, args): return 'view:' + name + ':' + json.dumps(dict(sorted(args.items())), separators=(',', ':'))

open(os.path.join(FX, 'app.html'), 'wb').write(req('/apps/github-actions/ci-health.html'))
open(os.path.join(FX, 'contracts.json'), 'wb').write(req('/api/v1/apps-runtime/v1/contracts'))

# The calls the app's scripts make at load, with the arguments they send for this instant.
SINCE14 = iso(NOW_MS - 14 * 86400000)
CALLS = [
    ('ActionsWatchlist', {}),
    ('ActionsBrokenMains', {'since': SINCE14, 'all': True}),
    ('ActionsBrokenPullRequests', {'since': SINCE, 'limit': 100}),
    ('ActionsRunCount', {'repo': REPO, 'since': SINCE}),
    ('ActionsSlowestRuns', {'repo': REPO, 'since': SINCE, 'limit': 1}),
    ('ActionsWorkflowSummary', {'repo': REPO, 'since': SINCE}),
    ('ActionsDailyRuns', {'repo': REPO, 'since': SINCE}),
    ('ActionsSlowestRuns', {'repo': REPO, 'since': SINCE, 'limit': 15}),
    ('ActionsFailedRuns', {'repo': REPO, 'since': SINCE, 'limit': 50}),
    ('ActionsFailingSteps', {'repo': REPO, 'since': SINCE, 'runs': 25}),
    ('ActionsSlowestJobs', {'repo': REPO, 'since': SINCE, 'runs': 8, 'limit': 10}),
    ('ActionsPassedOnRetry', {'repo': REPO, 'since': SINCE30, 'limit': 30}),
    ('ActionsFlakyJobs', {'repo': REPO, 'since': SINCE30, 'runs': 20}),
    ('ActionsFailureThemes', {'repo': REPO, 'since': SINCE, 'runs': 20, 'count': 5}),
    ('ActionsBriefing', {'repo': REPO, 'since': SINCE, 'runs': 15}),
    # the views explorer runs a view with the form's defaults; repo/since prefilled, until cleared
    ('ActionsRunCount', {'repo': REPO, 'days': 7, 'since': SINCE}),
]
envelopes = {}
for name, args in CALLS:
    env = json.loads(req(f'/api/v1/views/{name}/invoke', {'args': args}))
    envelopes[key(name, args)] = env
    rows = env.get('data') if isinstance(env.get('data'), list) else (env.get('data') or {}).get('rows') or env.get('rows') or []
    print(f'captured {name} {json.dumps(args)} -> {len(rows)} rows, {env.get("status")}/{env.get("outcome")}')
# The jobs of the first slowest run, as clicking that row requests them (since = its createdAt).
slow = envelopes[key('ActionsSlowestRuns', {'repo': REPO, 'since': SINCE, 'limit': 15})]
srows = slow.get('data') if isinstance(slow.get('data'), list) else (slow.get('data') or {}).get('rows') or []
if srows:
    args = {'repo': REPO, 'runId': srows[0]['runId'], 'since': srows[0]['createdAt']}
    envelopes[key('ActionsRunJobs', args)] = json.loads(req('/api/v1/views/ActionsRunJobs/invoke', {'args': args}))
    print('captured ActionsRunJobs for run', srows[0]['runId'])
json.dump({'capturedAt': NOW_MS, 'repo': REPO, 'since': SINCE, 'envelopes': envelopes}, open(os.path.join(FX, 'envelopes.json'), 'w'), indent=1)

ask = json.loads(req('/api/v1/admin/kg/ask', {'question': f'which workflow in {REPO} fails most often'}))
json.dump(ask, open(os.path.join(FX, 'ask.json'), 'w'), indent=1)
print('captured ask ->', len(ask.get('rows') or []), 'rows')
inv = {}
for v in json.load(open(os.path.join(FX, 'contracts.json')))['views']:
    if v.get('realm') == 'github-actions':
        args = {k: val for k, val in {'repo': REPO, 'since': SINCE}.items() if k in (v.get('params') or {})}
        inv[v['name']] = json.loads(req(f"/api/v1/admin/kg/views/{v['name']}/invocation", {'args': args}))
json.dump(inv, open(os.path.join(FX, 'invocations.json'), 'w'), indent=1)
print('captured', len(inv), 'invocations; capturedAt', NOW_MS, SINCE)
