#!/usr/bin/env python3
"""Run every view of realm-github-actions against a live appliance and require rows.

    export EMBABEL_AUTH=user:pass      # or EMBABEL_TOKEN=... for bearer auth
    python3 scripts/test-views.py http://127.0.0.1:11043 [owner/repo]

Calls the host's own endpoint (POST /api/v1/admin/kg/views/{name}/run) — never a
re-implementation of it — with real parameters, prints every warning, and exits nonzero if a
view that should have rows has none or any view errors. Views listed in MAY_BE_EMPTY may
return zero rows, each with the reason. This is the smoke half; tests/verify.sh is the
reconciliation against GitHub itself.
"""
import base64, datetime, json, os, sys, urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:11043').rstrip('/')
REPO = sys.argv[2] if len(sys.argv) > 2 else 'embabel/embabel-agent'
NOW = datetime.datetime.now(datetime.timezone.utc)
SINCE = (NOW - datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
SINCE30 = (NOW - datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')

def auth_header():
    if os.environ.get('EMBABEL_TOKEN'):
        return 'Bearer ' + os.environ['EMBABEL_TOKEN']
    if os.environ.get('EMBABEL_AUTH'):
        return 'Basic ' + base64.b64encode(os.environ['EMBABEL_AUTH'].encode()).decode()
    sys.exit('set EMBABEL_AUTH=user:pass or EMBABEL_TOKEN=... (the appliance refuses anonymous admin calls)')

def run_view(name, params):
    req = urllib.request.Request(f'{BASE}/api/v1/admin/kg/views/{name}/run',
                                 data=json.dumps({'args': params}).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': auth_header()})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode())
    rows = d.get('rows') or (d.get('data') or {}).get('rows') or d.get('data') or []
    return rows if isinstance(rows, list) else [], d.get('warnings') or [], d

VIEWS = {
    'ActionsWatchlist':       {},
    'ActionsBrokenMains':     {'since': SINCE, 'all': True},
    'ActionsBrokenPullRequests': {'since': SINCE30},
    'ActionsRunCount':        {'repo': REPO, 'since': SINCE},
    'ActionsRunTime':         {'repo': REPO, 'since': SINCE},
    'ActionsByActor':         {'repo': REPO, 'since': SINCE},
    'ActionsRecentRuns':      {'repo': REPO, 'since': SINCE, 'limit': 50},
    'ActionsWorkflowSummary': {'repo': REPO, 'since': SINCE},
    'ActionsSlowestRuns':     {'repo': REPO, 'since': SINCE, 'limit': 5},
    'ActionsFailedRuns':      {'repo': REPO, 'since': SINCE30},
    'ActionsDailyRuns':       {'repo': REPO, 'since': SINCE},
    'ActionsPassedOnRetry':   {'repo': REPO, 'since': SINCE30},
    'ActionsWorkflows':       {'repo': REPO},
    'ActionsSlowestJobs':     {'repo': REPO, 'since': SINCE, 'runs': 3, 'limit': 5},
    'ActionsFailingSteps':    {'repo': REPO, 'since': SINCE30, 'runs': 10},
    'ActionsFlakyJobs':       {'repo': REPO, 'since': SINCE30, 'runs': 10},
    'ActionsFailureThemes':   {'repo': REPO, 'since': SINCE30, 'runs': 8, 'count': 4},
    'ActionsBriefing':        {'repo': REPO, 'since': SINCE, 'runs': 5},
    # ActionsRunJobs is run with the slowest run found by ActionsSlowestRuns (below).
}
MAY_BE_EMPTY = {
    'ActionsWatchlist':       'nothing followed yet — follow a repository from the app or with gateway.repository.createEntry on ActionsWatch',
    'ActionsBrokenMains':     'nothing followed, or no completed run on a watched branch in the window',
    'ActionsBrokenPullRequests': 'no pull-request branch is red across the followed repositories',
    'ActionsFailedRuns':    'a repository whose last 30 days are all green is honestly empty',
    'ActionsPassedOnRetry': 'a repository nobody re-ran is honestly empty',
    'ActionsFailingSteps':  'no failed runs in the window means no failing steps',
    'ActionsFlakyJobs':     'no run passed on retry, so no job flaked',
    'ActionsFailureThemes': 'no failures to theme',
}

fail = False
slowest = None
for name, params in VIEWS.items():
    try:
        rows, warnings, envelope = run_view(name, params)
    except Exception as e:
        print(f'FAIL {name}: {e}'); fail = True; continue
    for w in warnings:
        print(f'  warn {name}: {w[:200]}')
    unavailable = any(isinstance(v, str) and v.startswith('UNAVAILABLE') for r in rows for v in r.values())
    if (not rows or unavailable) and name not in MAY_BE_EMPTY:
        print(f'FAIL {name}: {"UNAVAILABLE" if unavailable else "0 rows"} with params {params}'); fail = True
    elif not rows:
        print(f'ok   {name}: 0 rows ({MAY_BE_EMPTY[name]})')
    else:
        print(f'ok   {name}: {len(rows)} rows')
    if name == 'ActionsSlowestRuns' and rows:
        slowest = rows[0].get('runId')

if slowest:
    try:
        rows, warnings, _ = run_view('ActionsRunJobs', {'repo': REPO, 'runId': int(slowest)})
        for w in warnings: print(f'  warn ActionsRunJobs: {w[:200]}')
        if not rows: print(f'FAIL ActionsRunJobs: 0 jobs for run {slowest}'); fail = True
        else: print(f'ok   ActionsRunJobs: {len(rows)} jobs for run {slowest}')
    except Exception as e:
        print(f'FAIL ActionsRunJobs: {e}'); fail = True
else:
    print('FAIL ActionsRunJobs: no slowest run to open'); fail = True

# Invariants a static read cannot check.
try:
    rows, _, _ = run_view('ActionsSlowestRuns', {'repo': REPO, 'since': SINCE, 'limit': 20})
    secs = [r['runSeconds'] for r in rows]
    if secs != sorted(secs, reverse=True): print('FAIL ActionsSlowestRuns: not sorted slowest first'); fail = True
    if any(s is None or s < 0 for s in secs): print('FAIL ActionsSlowestRuns: a completed run with no or negative run time'); fail = True
    rows, _, _ = run_view('ActionsWorkflowSummary', {'repo': REPO, 'since': SINCE})
    for r in rows:
        if r['failed'] + r['succeeded'] + r['cancelled'] > r['runs']:
            print(f'FAIL ActionsWorkflowSummary: conclusions exceed runs for {r["workflow"]}'); fail = True
        if not (0 <= r['failureRatePct'] <= 100):
            print(f'FAIL ActionsWorkflowSummary: failure rate out of range for {r["workflow"]}'); fail = True
    print('ok   invariants')
except Exception as e:
    print(f'FAIL invariants: {e}'); fail = True

print('DRIFT DETECTED' if fail else 'ALL VIEWS PASS')
sys.exit(1 if fail else 0)
