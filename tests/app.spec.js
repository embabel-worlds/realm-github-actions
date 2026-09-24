/* The browser harness for apps/CI-Health.html — Playwright against the installed Chrome.
 * The app's real bytes run; the two runtime scripts are replaced by a stub that answers from
 * envelopes CAPTURED live by tests/capture-fixtures.py, keyed as the runtime keys them.
 * Date.now() is frozen to the capture instant so the app's own `since` arithmetic reproduces
 * the keys. Any call with no fixture throws loudly. Run: npm run test:app */
const { test, expect } = require('@playwright/test');
const fs = require('fs'); const path = require('path');

const FX = path.join(__dirname, 'fixtures');
const fixtures = JSON.parse(fs.readFileSync(path.join(FX, 'envelopes.json'), 'utf8'));
const contracts = JSON.parse(fs.readFileSync(path.join(FX, 'contracts.json'), 'utf8'));
const askEnvelope = JSON.parse(fs.readFileSync(path.join(FX, 'ask.json'), 'utf8'));
const invocations = JSON.parse(fs.readFileSync(path.join(FX, 'invocations.json'), 'utf8'));
const ORIGIN = 'http://ci-health.test';
const rowsOf = (env) => Array.isArray(env.data) ? env.data : (env.data && env.data.rows) || env.rows || [];
const key = (name, args) => 'view:' + name + ':' + JSON.stringify(Object.fromEntries(Object.entries(args || {}).sort()));
const fx = (name, args) => { const e = fixtures.envelopes[key(name, args)]; if (!e) throw new Error('no fixture ' + key(name, args)); return e; };

function stubScript(envelopes, opts) {
  opts = opts || {};
  return `
  Date.now = function () { return ${fixtures.capturedAt}; };
  window.embabel = (function () {
    var fx = ${JSON.stringify(envelopes)};
    var delayFor = ${JSON.stringify(opts.delay || {})};
    function key(kind, id, args) { var o = {}; Object.keys(args || {}).sort().forEach(function (k) { o[k] = args[k]; }); return kind + ':' + id + ':' + JSON.stringify(o); }
    function invoke(kind) { return function (id, args) {
      var k = key(kind, id, args); var env = fx[k];
      if (!env) return Promise.reject(new Error('NO FIXTURE for ' + k));
      var p = env.status === 'FAILED' ? Promise.reject(Object.assign(new Error((env.error && env.error.message) || 'failed'), env.error || {})) : Promise.resolve(env);
      var d = delayFor[id]; return d ? new Promise(function (r) { setTimeout(r, d); }).then(function () { return p; }) : p; }; }
    var esc = function (v) { return String(v == null ? '' : v).replace(/[&<>'"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]; }); };
    return {
      views: { invoke: invoke('view') }, lenses: { invoke: invoke('lens') },
      contracts: function () { return ${JSON.stringify(contracts)}; },
      html: { escape: esc },
      format: { number: function (v) { return v == null ? '' : Number(v).toLocaleString(); }, date: function (v) { return v == null ? '' : new Date(v).toLocaleDateString(); }, currency: function (v, c) { return v == null ? '' : Number(v).toLocaleString(undefined, { style: 'currency', currency: c || 'USD' }); } },
      manifest: { read: function () { return null; }, preflight: function () { return Promise.resolve({ ok: true }); }, ready: Promise.resolve() },
      progress: { subscribe: function () { return function () {}; }, label: function () {} },
      cache: { invalidate: function () {}, clear: function () {} },
      EmbabelError: Error,
    };
  })();
  window.gateway = new Proxy({}, { get: function (_, ns) { return new Proxy({}, { get: function (_, m) { return function () { return Promise.reject(new Error('NO FIXTURE for gateway.' + String(ns) + '.' + String(m))); }; } }); } });`;
}
function pageHtml(envelopes, opts) {
  return fs.readFileSync(path.join(FX, 'app.html'), 'utf8')
    .replace(/<script src="\/api\/v1\/apps-runtime[^"]*"><\/script>\s*/g, '')
    .replace(/<link rel="stylesheet" href="\/api\/v1\/apps-runtime[^"]*">\s*/g, '')
    .replace('</head>', '<script>' + stubScript(envelopes, opts) + '</script></head>');
}
async function open(page, envelopes, opts) {
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route(ORIGIN + '/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/app.html') return route.fulfill({ status: 200, contentType: 'text/html', body: pageHtml(envelopes, opts) });
    if (url.pathname === '/api/v1/admin/kg/ask') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(askEnvelope) });
    const m = url.pathname.match(/^\/api\/v1\/admin\/kg\/views\/([^/]+)\/invocation$/);
    if (m) { const inv = invocations[decodeURIComponent(m[1])]; return inv ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(inv) }) : route.fulfill({ status: 404, body: '' }); }
    return route.fulfill({ status: 404, body: 'no route for ' + url.pathname });
  });
  await page.goto(ORIGIN + '/app.html');
  return errors;
}
const REPO = fixtures.repo, SINCE = fixtures.since;
const SINCE14 = new Date(fixtures.capturedAt - 14 * 86400000).toISOString().replace(/\.\d{3}Z$/, 'Z');
const SINCE30 = new Date(fixtures.capturedAt - 30 * 86400000).toISOString().replace(/\.\d{3}Z$/, 'Z');

test('renders every panel from the fixtures, drives every path, no console errors', async ({ page }) => {
  const errors = await open(page, fixtures.envelopes);
  // the picker: every followed repository listed, filter narrows, choosing swaps the scope
  const watch = rowsOf(fx('ActionsWatchlist', {}));
  await expect(page.locator('#repoLabel')).toHaveText(REPO);
  await page.click('#repoBtn');
  await expect(page.locator('#repoList .opt')).toHaveCount(watch.length);
  await page.fill('#repoFilter', 'zzz-no-such-repo');
  await expect(page.locator('#repoList .opt')).toHaveCount(0);
  await page.fill('#repoFilter', 'not-followed/example');
  await expect(page.locator('#followBtn')).toBeVisible();
  await page.fill('#repoFilter', REPO.split('/')[1].slice(0, 6));
  expect(await page.locator('#repoList .opt').count()).toBeGreaterThan(0);
  await page.keyboard.press('Escape');
  await expect(page.locator('#repoMenu')).toBeHidden();
  // the fleet: a card per followed repository, broken mains and PRs from the fixtures
  await page.click('nav [data-tab="fleet"]');
  await expect(page.locator('#p-fleet .repo-card')).toHaveCount(watch.length);
  const mains = rowsOf(fx('ActionsBrokenMains', { since: SINCE14, all: true }));
  await expect(page.locator('#p-fleet [data-broken-main]')).toHaveCount(mains.filter((m) => m.latestConclusion !== 'success').length);
  await expect(page.locator('#p-fleet [data-broken-pr]')).toHaveCount(rowsOf(fx('ActionsBrokenPullRequests', { since: SINCE, limit: 100 })).length);
  await page.click('#p-fleet .repo-card[data-fleet-repo="' + REPO + '"]');
  await expect(page.locator('#p-overview')).toHaveClass(/on/);
  // headline
  await expect(page.locator('#tiles .tile')).toHaveCount(6);
  const count = rowsOf(fx('ActionsRunCount', { repo: REPO, since: SINCE }))[0];
  await expect(page.locator('#verdict .big')).toContainText(count.runs + ' runs in the last 7 days, ' + count.failed + ' failed');
  // overview
  await expect(page.locator('#p-overview tbody tr')).toHaveCount(rowsOf(fx('ActionsWorkflowSummary', { repo: REPO, since: SINCE })).length);
  await expect(page.locator('#p-overview .bar')).toHaveCount(rowsOf(fx('ActionsDailyRuns', { repo: REPO, since: SINCE })).length);
  // what broke main: one row per red workflow, or the green note
  const broke = rowsOf(fx('ActionsWhatBroke', { repo: REPO, branch: 'main' }));
  if (broke.length) await expect(page.locator('#whatBroke [data-what-broke]')).toHaveCount(broke.length);
  else await expect(page.locator('#whatBroke .empty')).toContainText('green');
  // runs + drill into the first slowest run's jobs
  await page.click('nav [data-tab="runs"]');
  await expect(page.locator('#p-runs')).toHaveClass(/on/);
  const slowest = rowsOf(fx('ActionsSlowestRuns', { repo: REPO, since: SINCE, limit: 15 }));
  const failed = rowsOf(fx('ActionsFailedRuns', { repo: REPO, since: SINCE, limit: 50 }));
  await expect(page.locator('#p-runs tr.pick')).toHaveCount(slowest.length + failed.length);
  await page.locator('#p-runs tr.pick').first().click();
  const jobs = rowsOf(fx('ActionsRunJobs', { repo: REPO, runId: slowest[0].runId }));
  await expect(page.locator('#drawer tbody tr')).toHaveCount(jobs.length);
  await expect(page.locator('#drawer h3').first()).toContainText('Run ' + slowest[0].runId);
  // a failed run offers "How to fix this", and the lens's hint renders with its sources and error lines
  await page.locator('#p-runs tr.pick[data-run="' + failed[0].runId + '"]').first().click();
  await expect(page.locator('#fixGo')).toBeVisible();
  await page.click('#fixGo');
  const lensKey = 'lens:resolve-failure:' + JSON.stringify(Object.fromEntries(Object.entries({ repo: REPO, runId: failed[0].runId }).sort()));
  const lensEnv = fixtures.envelopes[lensKey]; const lensJobs = (lensEnv && lensEnv.data && lensEnv.data.jobs) || [];
  await expect(page.locator('#fixOut [data-resolution]')).toHaveCount(lensJobs.length);
  if (lensJobs.length) { await expect(page.locator('#fixOut .prose').first()).toContainText(lensJobs[0].hint.slice(0, 30)); await expect(page.locator('#fixOut pre').first()).toContainText((lensJobs[0].errorLines[0] || '').slice(0, 20)); }
  // failures
  await page.click('nav [data-tab="failures"]');
  const tables = page.locator('#p-failures table');
  await expect(tables.nth(0).locator('tbody tr')).toHaveCount(rowsOf(fx('ActionsFailingSteps', { repo: REPO, since: SINCE, runs: 10 })).length);
  await expect(tables.nth(1).locator('tbody tr')).toHaveCount(rowsOf(fx('ActionsSlowestJobs', { repo: REPO, since: SINCE, runs: 5, limit: 10 })).length);
  // flaky (30-day window regardless of the picker)
  await page.click('nav [data-tab="flaky"]');
  const ft = page.locator('#p-flaky table');
  await expect(ft.nth(0).locator('tbody tr')).toHaveCount(rowsOf(fx('ActionsFlakyJobs', { repo: REPO, since: SINCE30, runs: 10 })).length);
  await expect(ft.nth(1).locator('tbody tr')).toHaveCount(rowsOf(fx('ActionsPassedOnRetry', { repo: REPO, since: SINCE30, limit: 30 })).length);
  // reading: lazy, on click
  await page.click('nav [data-tab="insight"]');
  await expect(page.locator('#themesOut')).toBeEmpty();
  await page.click('#themesGo');
  const themes = rowsOf(fx('ActionsFailureThemes', { repo: REPO, since: SINCE, runs: 10, count: 5 }))[0].themes;
  await expect(page.locator('#themesOut li')).toHaveCount(themes.length);
  await page.click('#briefGo');
  await expect(page.locator('#briefOut .prose')).toContainText(rowsOf(fx('ActionsBriefing', { repo: REPO, since: SINCE, runs: 10 }))[0].briefing.slice(0, 40));
  // views explorer: every realm view listed, one run through the generated form, Cypher read back
  await page.click('nav [data-tab="views"]');
  const realmViews = contracts.views.filter((v) => v.realm === 'github-actions');
  await expect(page.locator('#vlist button[data-view="ActionsBrokenMains"]')).toHaveCount(1);
  await expect(page.locator('#vlist button')).toHaveCount(realmViews.length);
  await page.click('#vlist button[data-view="ActionsRunCount"]');
  await expect(page.locator('#vpane input[data-key="repo"]')).toHaveValue(REPO);
  await expect(page.locator('#vpane input[data-key="since"]')).toHaveValue(SINCE);
  await page.click('#vrun');
  await expect(page.locator('#vout tbody tr')).toHaveCount(1);
  await expect(page.locator('#vout tbody td').first()).toHaveText(String(count.runs));
  await expect(page.locator('#vcy pre')).toContainText('MATCH (r:GitHubRepository');
  // ask in words: a claimed phrasing is routed to the verified view (no model call)
  await page.fill('#q', 'which workflow in ' + REPO + ' fails most often');
  await page.click('#askGo');
  await expect(page.locator('#answer tbody tr')).toHaveCount(rowsOf(fx('ActionsWorkflowSummary', { repo: REPO, since: SINCE })).length);
  await expect(page.locator('#answer .meta')).toContainText('answered by the view');
  await page.fill('#q', 'what is the average build time');
  await page.click('#askGo');
  await expect(page.locator('#answer .meta')).toContainText('ActionsRunTime');
  // a question about data the realm does not hold is answered plainly, no model call
  await page.fill('#q', 'who made the most commits');
  await page.click('#askGo');
  await expect(page.locator('#answer .note.bad')).toContainText('does not hold commits');
  await page.click('#nearestGo');
  await expect(page.locator('#answer .meta')).toContainText('ActionsByActor');
  // an unclaimed question goes to the model, labelled, Cypher shown
  await page.fill('#q', 'which branch has the most runs');
  await page.click('#askGo');
  await expect(page.locator('#answer .note')).toContainText('No saved view answers this');
  await expect(page.locator('#answer details pre')).toContainText('MATCH');
  // the badge, visible and inside the viewport
  const badge = page.locator('#embabel-badge');
  await expect(badge).toBeVisible();
  expect((await badge.textContent()).trim().length).toBeGreaterThan(0);
  expect(await badge.locator('a').getAttribute('href')).toContain('embabel.com');
  const box = await badge.boundingBox(); const vp = page.viewportSize();
  expect(box.y + box.height).toBeLessThanOrEqual(vp.height + 1); expect(box.y).toBeGreaterThanOrEqual(0);
  // how it works: link present, section reveals, every view read back
  await page.click('#howLink');
  await expect(page.locator('#how')).toBeVisible();
  await expect(page.locator('#howViews .view')).toHaveCount(realmViews.length);
  await expect(page.locator('#howViews .view pre').first()).toContainText('MATCH');
  expect(errors).toEqual([]);
});

test('forced failures are loud: a FAILED envelope and an empty-with-warning envelope', async ({ page }) => {
  const env = JSON.parse(JSON.stringify(fixtures.envelopes));
  const kSummary = key('ActionsWorkflowSummary', { repo: REPO, since: SINCE });
  env[kSummary] = { status: 'FAILED', outcome: 'FAILED', error: { code: 'EXECUTION_FAILED', message: 'GitHub answered 401: the token cannot read this repository' } };
  const kDaily = key('ActionsDailyRuns', { repo: REPO, since: SINCE });
  env[kDaily] = { status: 'SUCCEEDED', outcome: 'OK', outputType: 'rows', data: [], warnings: ['PARTIAL_RESULT: producer runsByRepo truncated at 1000 (page cap 10)'] };
  const kFailed = key('ActionsFailedRuns', { repo: REPO, since: SINCE, limit: 50 });
  env[kFailed] = { status: 'SUCCEEDED', outcome: 'OK', outputType: 'rows', data: [] };
  const kMains = key('ActionsBrokenMains', { since: SINCE14, all: true });
  env[kMains] = { status: 'SUCCEEDED', outcome: 'OK', outputType: 'rows', data: rowsOf(fixtures.envelopes[kMains]).map((m) => Object.assign({}, m, { latestConclusion: 'success' })) };
  const errors = await open(page, env);
  await page.click('nav [data-tab="fleet"]');
  await expect(page.locator('#p-fleet [data-broken-main]')).toHaveCount(0);
  await expect(page.locator('#p-fleet')).toContainText('green on its latest run');
  await page.click('nav [data-tab="overview"]');
  await expect(page.locator('#p-overview .note.bad')).toContainText('could not be read');
  await expect(page.locator('#p-overview .note.bad')).toContainText('401');
  await page.click('nav [data-tab="runs"]');
  await expect(page.locator('#p-runs .empty')).toContainText('Green, not broken');
  expect(errors).toEqual([]);
});

test('an empty watchlist sends you to the fleet and says how to follow', async ({ page }) => {
  const env = JSON.parse(JSON.stringify(fixtures.envelopes));
  env[key('ActionsWatchlist', {})] = { status: 'SUCCEEDED', outcome: 'OK', outputType: 'rows', data: [] };
  env[key('ActionsBrokenMains', { since: SINCE14, all: true })] = { status: 'SUCCEEDED', outcome: 'OK', outputType: 'rows', data: [] };
  env[key('ActionsBrokenPullRequests', { since: SINCE, limit: 100 })] = { status: 'SUCCEEDED', outcome: 'OK', outputType: 'rows', data: [] };
  const errors = await open(page, env);
  await expect(page.locator('#p-fleet')).toHaveClass(/on/);
  await expect(page.locator('#p-fleet .empty').first()).toContainText('type owner/repo to follow');
  await expect(page.locator('#verdict')).toContainText('Pick a repository');
  expect(errors).toEqual([]);
});

test('an empty-with-warning panel says partial, never a bare zero', async ({ page }) => {
  const env = JSON.parse(JSON.stringify(fixtures.envelopes));
  const kDaily = key('ActionsDailyRuns', { repo: REPO, since: SINCE });
  env[kDaily] = { status: 'SUCCEEDED', outcome: 'OK', outputType: 'rows', data: [], warnings: ['PARTIAL_RESULT: producer runsByRepo truncated at 1000 (page cap 10)'] };
  const errors = await open(page, env);
  await expect(page.locator('#p-overview .note', { hasText: 'Partial answer' })).toHaveCount(1);
  await expect(page.locator('#p-overview .empty', { hasText: 'No runs in the window' })).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('controls respond at once while a call is in flight, and a second click is not dropped', async ({ page }) => {
  const errors = await open(page, fixtures.envelopes, { delay: { ActionsFailedRuns: 400, ActionsWorkflowSummary: 400 } });
  await page.click('nav [data-tab="runs"]');
  await expect(page.locator('#p-runs')).toHaveClass(/on/, { timeout: 100 });
  await page.click('nav [data-tab="failures"]');
  await expect(page.locator('#p-failures')).toHaveClass(/on/, { timeout: 100 });
  await page.click('nav [data-tab="runs"]');
  await expect(page.locator('#p-runs')).toHaveClass(/on/, { timeout: 100 });
  const slowest = rowsOf(fx('ActionsSlowestRuns', { repo: REPO, since: SINCE, limit: 15 }));
  const failed = rowsOf(fx('ActionsFailedRuns', { repo: REPO, since: SINCE, limit: 50 }));
  await expect(page.locator('#p-runs tr.pick')).toHaveCount(slowest.length + failed.length);
  expect(errors).toEqual([]);
});
