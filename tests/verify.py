#!/usr/bin/env python3
"""The ladder. See tests/verify.sh for the layers and how to run it."""
import base64, datetime, json, os, re, sys, urllib.parse, urllib.request

REPO = sys.argv[1] if len(sys.argv) > 1 else 'embabel/embabel-agent'
BASE = os.environ.get('APPLIANCE', 'http://127.0.0.1:11043').rstrip('/')
GH = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
if not GH: sys.exit('GH_TOKEN is required: L0 reads GitHub directly, and without it nothing here is ground truth')

def auth_header():
    if os.environ.get('EMBABEL_TOKEN'): return 'Bearer ' + os.environ['EMBABEL_TOKEN']
    if os.environ.get('EMBABEL_AUTH'): return 'Basic ' + base64.b64encode(os.environ['EMBABEL_AUTH'].encode()).decode()
    sys.exit('set EMBABEL_AUTH=user:pass or EMBABEL_TOKEN=...')

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': auth_header()})
    with urllib.request.urlopen(req, timeout=900) as r: return json.loads(r.read().decode())

def get(path):
    req = urllib.request.Request(BASE + path, headers={'Authorization': auth_header()})
    with urllib.request.urlopen(req, timeout=120) as r: return r.status, r.read()

def gh(path, params):
    url = 'https://api.github.com' + path + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + GH, 'Accept': 'application/vnd.github+json',
                                               'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read().decode())

def rows_of(d):
    rows = d.get('rows') or (d.get('data') or {}).get('rows') if isinstance(d.get('data'), dict) else d.get('rows') or d.get('data')
    return rows if isinstance(rows, list) else []

def view(name, args):
    d = post(f'/api/v1/admin/kg/views/{name}/run', {'args': args})
    return rows_of(d), d.get('warnings') or []

fails = []
def check(cond, label, detail=''):
    print(('ok   ' if cond else 'FAIL ') + label + (f'  [{detail}]' if detail and not cond else ''))
    if not cond: fails.append(label)

# ---- The window: fixed before anything is read, and it ends two hours ago so a run that is
# still in progress, or one created between two reads, cannot move a figure.
NOW = datetime.datetime.now(datetime.timezone.utc)
SINCE = (NOW - datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
UNTIL = (NOW - datetime.timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
print(f'window {SINCE} .. {UNTIL} (exclusive) on {REPO}')

# ---- L0: GitHub itself.
def secs(a, b):
    fa = datetime.datetime.strptime(a, '%Y-%m-%dT%H:%M:%SZ'); fb = datetime.datetime.strptime(b, '%Y-%m-%dT%H:%M:%SZ')
    return int((fb - fa).total_seconds())
def label(run):
    return 'dynamic: ' + run['path'].split('/')[1] if run['path'].startswith('dynamic/') else run['name']
runs = []
page = 1
while True:
    d = gh(f'/repos/{REPO}/actions/runs', {'created': f'{SINCE}..{UNTIL}', 'per_page': 100, 'page': page})
    batch = d.get('workflow_runs', [])
    runs += [r for r in batch if SINCE <= r['created_at'] < UNTIL]   # the range filter is inclusive; the views' until is exclusive
    if len(batch) < 100 or page >= 10: break
    page += 1
L0 = {
    'runs': len(runs),
    'completed': sum(1 for r in runs if r['status'] == 'completed'),
    'failed': sum(1 for r in runs if r['conclusion'] == 'failure'),
    'succeeded': sum(1 for r in runs if r['conclusion'] == 'success'),
    'passedOnRetry': sum(1 for r in runs if r['conclusion'] == 'success' and r['run_attempt'] > 1),
}
completed = [r for r in runs if r['status'] == 'completed']
durations = sorted(((secs(r['run_started_at'], r['updated_at']), r['id']) for r in completed), reverse=True)
L0['slowestSeconds'], L0['slowestRunId'] = durations[0] if durations else (None, None)
L0['slowestCreatedAt'] = next((r['created_at'] for r in completed if r['id'] == L0['slowestRunId']), SINCE)
per_wf = {}
for r in completed:
    w = per_wf.setdefault(label(r), {'runs': 0, 'failed': 0})
    w['runs'] += 1; w['failed'] += 1 if r['conclusion'] == 'failure' else 0
L0['workflows'] = {k: (v['runs'], v['failed']) for k, v in per_wf.items()}
days = {}
for r in runs:
    d0 = days.setdefault(r['created_at'][:10], [0, 0]); d0[0] += 1; d0[1] += 1 if r['conclusion'] == 'failure' else 0
L0['days'] = days
print('L0', json.dumps({k: v for k, v in L0.items() if k not in ('workflows', 'days')}))
check(L0['runs'] > 0, 'L0: the window holds runs (a repository with none cannot verify anything)')

# ---- L1: the traversal, through the engine, same window.
d = post('/api/v1/admin/kg/execute', {'cypher': f"""
  MATCH (r:GitHubRepository {{full_name: '{REPO}'}})-[:HAS_WORKFLOW_RUN]->(run:WorkflowRun)
  WHERE run.created_at >= '{SINCE}' AND run.created_at < '{UNTIL}'
  RETURN count(run) AS n, sum(CASE WHEN run.conclusion = 'failure' THEN 1 ELSE 0 END) AS failed"""})
r1 = rows_of(d)
check(bool(r1) and r1[0]['n'] == L0['runs'], 'L1: traversal run count == GitHub', f'{r1} vs {L0["runs"]}')
check(bool(r1) and r1[0]['failed'] == L0['failed'], 'L1: traversal failed count == GitHub')
check(not any('PARTIAL' in w for w in (d.get('warnings') or [])), 'L1: no PARTIAL warning (the since literal pushed down)')

# ---- L2: every view, the same window, exact.
W = {'repo': REPO, 'since': SINCE, 'until': UNTIL}
rows, warns = view('ActionsRunCount', W)
check(rows and rows[0]['runs'] == L0['runs'] and rows[0]['failed'] == L0['failed'] and rows[0]['completed'] == L0['completed']
      and rows[0]['succeeded'] == L0['succeeded'], 'L2: ActionsRunCount == GitHub', f'{rows[:1]} vs {L0}')
rows, _ = view('ActionsRecentRuns', dict(W, limit=2000))
ids = [r['runId'] for r in rows]
check(len(ids) == L0['runs'] and len(set(ids)) == len(ids), 'L2: ActionsRecentRuns lists every run once (dedupe by id)', f'{len(ids)} rows, {len(set(ids))} distinct vs {L0["runs"]}')
rows, _ = view('ActionsSlowestRuns', dict(W, limit=3))
check(rows and rows[0]['runSeconds'] == L0['slowestSeconds'] and rows[0]['runId'] == L0['slowestRunId'],
      'L2: ActionsSlowestRuns top == GitHub (seconds and id)', f'{rows[:1]} vs {L0["slowestSeconds"]}/{L0["slowestRunId"]}')
rows, _ = view('ActionsWorkflowSummary', W)
got = {r['workflow']: (r['runs'], r['failed']) for r in rows}
check(got == L0['workflows'], 'L2: ActionsWorkflowSummary per-workflow (runs, failed) == GitHub', f'{got} vs {L0["workflows"]}')
rows, _ = view('ActionsFailedRuns', dict(W, limit=2000))
check(len(rows) == L0['failed'] and all(r['runId'] for r in rows), 'L2: ActionsFailedRuns count == GitHub failed', f'{len(rows)} vs {L0["failed"]}')
rows, _ = view('ActionsPassedOnRetry', dict(W, limit=2000))
check(len(rows) == L0['passedOnRetry'], 'L2: ActionsPassedOnRetry count == GitHub', f'{len(rows)} vs {L0["passedOnRetry"]}')
rows, _ = view('ActionsDailyRuns', W)
gotd = {r['day']: [r['runs'], r['failed']] for r in rows}
check(gotd == L0['days'], 'L2: ActionsDailyRuns per-day (runs, failed) == GitHub', f'{gotd} vs {L0["days"]}')
if L0['slowestRunId']:
    jobs0 = gh(f'/repos/{REPO}/actions/runs/{L0["slowestRunId"]}/jobs', {'filter': 'all', 'per_page': 100})['jobs']
    rows, warns = view('ActionsRunJobs', {'repo': REPO, 'runId': L0['slowestRunId'], 'since': L0['slowestCreatedAt']})
    check(sorted(r['jobId'] for r in rows) == sorted(j['id'] for j in jobs0), 'L2: ActionsRunJobs job ids == GitHub jobs of the slowest run', f'{len(rows)} vs {len(jobs0)}')
    exp_failed = {j['id']: [s['name'] for s in j['steps'] if s['conclusion'] == 'failure'] for j in jobs0}
    check(all(r['failedSteps'] == exp_failed.get(r['jobId']) for r in rows), 'L2: ActionsRunJobs failed steps == GitHub step conclusions')
rows, warns = view('ActionsWorkflows', {'repo': REPO})
wf0 = gh(f'/repos/{REPO}/actions/workflows', {'per_page': 100})
check(len(rows) == wf0['total_count'], 'L2: ActionsWorkflows count == GitHub', f'{len(rows)} vs {wf0["total_count"]}')

# ---- L2 fleet: every followed repository's watched branch, latest completed run per workflow, from GitHub directly.
watch_rows, _ = view('ActionsWatchlist', {})
check(any(w['repo'] == REPO for w in watch_rows), f'L2: ActionsWatchlist follows {REPO} (the fixture the fleet checks need)', f'{[w["repo"] for w in watch_rows]}')
SINCE14 = (NOW - datetime.timedelta(days=14)).strftime('%Y-%m-%dT%H:%M:%SZ')
fleet0 = {}
for w in watch_rows:
    page = 1; branch_runs = []
    while True:
        d = gh(f"/repos/{w['repo']}/actions/runs", {'branch': w['branch'], 'created': f'>={SINCE14}', 'per_page': 100, 'page': page})
        batch = d.get('workflow_runs', []); branch_runs += batch
        if len(batch) < 100 or page >= 10: break
        page += 1
    latest = {}
    for r in sorted(branch_runs, key=lambda r: r['created_at'], reverse=True):
        if r['status'] != 'completed': continue
        k = label(r)
        if k not in latest: latest[k] = r['conclusion']
    for k, concl in latest.items(): fleet0[(w['repo'], k)] = concl
rows, warns = view('ActionsBrokenMains', {'since': SINCE14, 'all': True})
got = {(r['repo'], r['workflow']): r['latestConclusion'] for r in rows}
check(got == fleet0, 'L2: ActionsBrokenMains (all=true) latest conclusion per repo+workflow == GitHub', f'{got} vs {fleet0}')
rows_red, _ = view('ActionsBrokenMains', {'since': SINCE14})
check(sorted((r['repo'], r['workflow']) for r in rows_red) == sorted(k for k, c in fleet0.items() if c != 'success'), 'L2: ActionsBrokenMains (default) lists exactly the non-success ones')
pr0 = {}
for w in watch_rows:
    page = 1; prs = []
    while True:
        d = gh(f"/repos/{w['repo']}/actions/runs", {'event': 'pull_request', 'created': f'{SINCE}..{UNTIL}', 'per_page': 100, 'page': page})
        batch = d.get('workflow_runs', []); prs += [r for r in batch if SINCE <= r['created_at'] < UNTIL]
        if len(batch) < 100 or page >= 10: break
        page += 1
    latest = {}
    for r in sorted(prs, key=lambda r: r['created_at'], reverse=True):
        if r['status'] != 'completed': continue
        k = (r['head_branch'], label(r))
        if k not in latest: latest[k] = r['conclusion']
    for (b, wf), concl in latest.items():
        if concl == 'failure': pr0[(w['repo'], b, wf)] = concl
rows, warns = view('ActionsBrokenPullRequests', {'since': SINCE, 'until': UNTIL, 'limit': 1000}) if False else view('ActionsBrokenPullRequests', {'since': SINCE, 'limit': 1000})
got_pr = set((r['repo'], r['branch'], r['workflow']) for r in rows if r['failedAt'] < UNTIL)
check(got_pr == set(pr0), 'L2: ActionsBrokenPullRequests == GitHub (latest PR-branch run failed), window-bounded', f'{sorted(got_pr)} vs {sorted(pr0)}')

# ---- L2b: the model-backed views run and stay grounded.
rows, warns = view('ActionsBriefing', dict(W, runs=5))
brief = rows[0]['briefing'] if rows else ''
check(len(brief) > 150 and not brief.startswith('UNAVAILABLE'), 'L2: ActionsBriefing composes prose', brief[:80])
named = [k for k in L0['workflows'] if k in brief]
check(len(named) >= 1, 'L2: ActionsBriefing names at least one workflow that exists in the window', f'{named}')
rows, warns = view('ActionsFailureThemes', dict(W, runs=6, count=4))
if L0['failed'] > 0:
    themes = rows[0]['themes'] if rows else None
    check(isinstance(themes, list) and 1 <= len(themes) <= 4, 'L2: ActionsFailureThemes returns 1..count themes when there are failures', f'{themes}')
else:
    print('SKIP L2: ActionsFailureThemes (no failures in window)')

# ---- L3: the battery.
try:
    import yaml
except ImportError:
    sys.exit('pip install pyyaml (the battery is YAML)')
schema_status, schema_raw = get('/api/v1/admin/kg/schema')
schema_text = schema_raw.decode(errors='replace')
declared = set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', schema_text))
def ask(q):
    d = post('/api/v1/admin/kg/ask', {'question': q})
    return rows_of(d), d.get('cypher') or d.get('query') or '', d
def top_figure(rows, column):
    for r in rows:
        v = r.get(column)
        if isinstance(v, (int, float, str)) and v != '': return v
    return None
def figures(rows):
    out = set()
    for r in rows:
        for k, v in r.items():
            if isinstance(v, (int, float)) and not k.lower().endswith('id'): out.add(round(float(v), 1))
    return out
battery = yaml.safe_load(open('tests/questions.yml'))
for entry in battery:
    q = entry['question'].replace('{repo}', REPO).replace('{slowestRunId}', str(L0['slowestRunId']))
    exp = entry.get('expect', {})
    if entry.get('adversarial'):
        for i in range(3):
            try:
                rows, cypher, d = ask(q)
            except Exception as e:
                print(f'ok   L3 adversarial "{q}" #{i+1}: refused ({str(e)[:60]})'); continue
            props = set(re.findall(r'\.([A-Za-z_][A-Za-z0-9_]*)', cypher))
            unknown = [p for p in props if p not in declared]
            check(not rows or not unknown, f'L3 adversarial "{q}" #{i+1}: no rows, or only declared properties', f'rows={len(rows)} unknown={unknown} cypher={cypher[:120]}')
        continue
    try:
        rows, cypher, d = ask(q)
    except Exception as e:
        check(False, f'L3 "{q}"', str(e)[:120]); continue
    if 'matchesView' in exp:
        mv = exp['matchesView']
        vrows, _ = view(mv['name'], dict({'repo': REPO}, **mv.get('args', {})))
        want = top_figure(vrows, mv['column'])
        for attempt in range(2):   # generation is stochastic: a figure that matches once in two is not stable
            if attempt: rows, cypher, d = ask(q)
            if isinstance(want, str):
                got_s = set(str(x) for r in rows for x in r.values() if isinstance(x, str))
                check(want in got_s, f'L3 "{q}" #{attempt+1} == {mv["name"]}.{mv["column"]}', f'want {want} in {sorted(got_s)[:8]} cypher={cypher[:140]}')
                continue
            got = figures(rows)
            check(want is not None and round(float(want), 1) in got, f'L3 "{q}" #{attempt+1} == {mv["name"]}.{mv["column"]}', f'want {want} in {sorted(got)[:12]} cypher={cypher[:140]}')
    elif exp.get('nonEmpty'):
        check(len(rows) > 0, f'L3 "{q}" non-empty', f'cypher={cypher[:140]}')
    else:
        check(len(rows) >= int(exp.get('minRows', 0)), f'L3 "{q}" runs', f'rows={len(rows)}')

# ---- L5: the app is served.
try:
    st, body = get('/apps/github-actions/ci-health.html')
    check(st == 200 and b'ci-health' in body, 'L5: app ci-health served at /apps/github-actions/ci-health.html')
except Exception as e:
    check(False, 'L5: app ci-health served', str(e)[:80])

print('\n' + ('DRIFT DETECTED: ' + '; '.join(fails) if fails else 'ALL CHECKS PASS'))
sys.exit(1 if fails else 0)
