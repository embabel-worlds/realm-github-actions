# realm-github-actions

**Why was the build slow, and what keeps failing?** GitHub Actions keeps every run, job and
step, and its own tab shows them one at a time. This realm reads them as a graph off the
repositories you follow — runs with their queue and run time, the jobs under the slowest and
the failed ones, the step that broke, the annotations GitHub attached — and, beside the exact
figures, composes what the Actions tab cannot: the recurring causes, the jobs that pass on
retry, which mains are red across every repository you follow, and the paragraph for standup.

```
(ActionsWatch {full_name, branch})      the watchlist — the one stored type; the app's picker and the fleet views read it
   -[:HAS_WORKFLOW_RUN]-> (WorkflowRun) the live door, off every followed repository at once

(GitHubRepository {full_name})          pinned by 'owner/repo'; the same label realm-github anchors issues on
   -[:HAS_WORKFLOW]->     (Workflow)
   -[:HAS_WORKFLOW_RUN]-> (WorkflowRun) LIVE — newest first, a literal `since` pushed to GitHub's created filter
   -[:HAS_RUN_HISTORY]->  (WorkflowRun) HISTORY — 31 calendar days, one call per day, closed days cached
         -[:HAS_JOB]->            (WorkflowJob)        one call per run, all attempts
               -[:HAS_ANNOTATION]->  (CheckAnnotation)  one call per job
```

Nothing is mirrored. A view pins a repository, the engine fetches from GitHub for that query,
materialises transient nodes, runs the Cypher and rolls them back. One source, the GitHub REST
API, read-only: nothing here can re-run, cancel or dispatch anything.

> "Which mains are broken?" — one query over every repository you follow, the latest completed
> run of every workflow on its watched branch, from GitHub, right now.

## What's inside

- `apis/` — five GitHub operations, vendored and trimmed from the official OpenAPI document
  (`scripts/trim-openapi.py`), bearer-authenticated from `GH_TOKEN`.
- `types/` — the graph above, every hop a declared virtual join. `ActionsWatch` is the only
  stored type. Ids arrive from GitHub as strings; the types say so.
- `producers/` — four remote producers. `runsByRepo` is the live door with pushdown on
  `created_at`, `head_branch`, `event`, `actor` and `conclusion`; `runHistoryByRepo` is the
  same endpoint read as calendar periods (see *Caching*).
- `views/` — the answer surface, one per question: `actions.yml` (counts, summary, slowest,
  failed, trend, retries, workflows), `jobs.yml` (a run's jobs, slowest jobs, failing steps,
  flaky jobs), `intelligence.yml` (failure themes with `themes()`, the standup briefing with
  `synthesize()`, both in-query), `fleet.yml` (the watchlist, broken mains, broken PRs).
- `wasm/handlers.ts` — `ciWatch`, a weekday-morning schedule over the watchlist: what is red
  now, what failed in the last day, the longest run. Installed makes it available; an operator
  adopts it before it fires.
- `apps/ci-health.html` — **CI Health**: a picker over the repositories you follow (filter,
  swap, follow and unfollow), an ask bar in words, a Fleet tab of broken mains and broken PRs,
  the per-repository dashboard, every view runnable from a generated form with the Cypher that
  ran, and a *How it works* page that reads each view back from the server.
- `skills/github-actions/SKILL.md` — question → view, for an assistant.
- `hints/tips.yml` — the console's tips, each a question the battery proves.
- `tests/` and `scripts/` — the harness (below).

## Setup

1. A GitHub token that can read Actions on the repositories you will follow: a fine-grained
   PAT with **Actions: read** and **Checks: read** (Metadata: read comes with it), or a classic
   token with `repo`. Public repositories read with any token.
2. Put it in the appliance's environment as `GH_TOKEN` — the name `gh auth` itself exports,
   and the one realm-npm reads. On the Docker appliance the compose file forwards `GH_TOKEN`
   from the shell that ran `docker compose up`, or takes it from `secrets.env` beside the
   compose file. The realm never carries it.
3. Clone this repository into the appliance's realms mount and install it by reference:
   `install_realm_from_path` with `realm-github-actions`, then `realm_refresh` after any edit.
4. Follow a repository — from the app's picker, or:
   `gateway.repository.createEntry({ type: 'ActionsWatch', data: { full_name: 'owner/repo', branch: 'main' } })`.
5. Open **CI Health** from the console's Apps tab, or ask: *how are the builds doing in
   owner/repo*, *which mains are broken*, *why was run 123 slow*.

## Caching — because completed runs never change

Two doors to the same runs. Windowed analytics (count, summary, trend, slowest, failures,
flakiness, themes, briefing) read `HAS_RUN_HISTORY`: the last 31 days as calendar periods, one
small GitHub call per day per repository, and a **closed day is cached for the life of the
process**. Every history view keeps its predicates behind a `WITH`, so all of them share one
cached fetch per repository: the first read of a repository costs about 31 calls in parallel
(ten to twenty seconds), and every later read of any window costs at most one call, for
today's slice after five minutes. Measured on this appliance: a 30-day count in 0.14 s with no
GitHub call.

"Right now" views — the newest runs, a run's jobs, the fleet's broken mains and broken PRs —
read `HAS_WORKFLOW_RUN` live with a literal `since` pushed to GitHub's `created` filter, one
or two calls per repository, cached five minutes.

The honest edge of the history door: a run still in progress when its day closed, or re-run
days later, keeps in history the state it had when that day was last read, until the
appliance restarts. The live door does not have this edge.

## Verify before anyone asks it anything

```
GH_TOKEN=... EMBABEL_AUTH=user:pass APPLIANCE=http://127.0.0.1:11043 sh tests/verify.sh owner/repo
```

The ladder in `tests/verify.py`, on a window fixed before anything is read and ending two hours
ago so an in-flight run cannot move a figure:

- **L0** reads GitHub's API directly and computes the reference figures.
- **L1** counts the traversal through the engine; exact equality.
- **L2** runs every view with the same window and reconciles to the row: run count, every run
  once by id, the slowest run's seconds and id, per-workflow runs and failures, per-day counts,
  failed and passed-on-retry counts, the slowest run's job ids and failed steps against
  GitHub's step conclusions, the workflow count, and the fleet — the latest conclusion per
  followed repository and workflow, and the red PR branches — against GitHub. The two
  model-backed views must compose and name only workflows that exist.
- **L3** runs `tests/questions.yml` through the ask surface: count and superlative questions
  assert `matchesView` twice each (generation is stochastic); the adversarial half is asked
  three times and must return no rows or only declared properties.
- **L5** checks the app is served.

`scripts/test-views.py` is the smoke half: every view, real parameters, rows required.
`npm install && npm run test:app` drives the served app in headless Chrome against a stubbed
runtime fed by `tests/capture-fixtures.py` (captured envelopes, never hand-written): render
counts, the picker and fleet, every tab, the jobs drawer, the views explorer, the ask bar,
forced failures, the empty watchlist, the badge in the viewport, zero console errors, and
controls responding while a call is in flight.

Green means: every figure on every surface equals what GitHub says for the same window.

## Honest ledger

- Verified live against `embabel/embabel-agent` and `embabel/embabel-agent-examples`, public
  repositories, with a classic token.
- Failure text is the failed step's name plus GitHub's check-run annotations (often just
  "Process completed with exit code 1"); the realm does not read logs. That is the next
  producer worth adding.
- The natural-language path selects a view when one claims the question; otherwise it composes
  its own Cypher over the same rows, and a phrasing like "this week" may mean since Monday. The
  ladder's last run on 23 September 2026: L0–L2 exact on every figure, 36 checks green, and
  six red — all in three battery phrasings the generator still composes with a different
  measure than the view ("CI success rate" over all runs rather than completed ones, "took the
  longest" in minutes over a day-aligned window, "fails most often" as a count over 31 days).
  The figures those answers carry are real; they are not the view's. The stable fix is view
  selection, and the descriptions now claim those phrasings; until it holds, the app and the
  hints route those questions to the views.
- Looking a run up by id without its date walks the last 1,000 runs and once returned nothing
  on this appliance; every surface here passes the run's `created_at` as `since`.
- `pr_numbers` is usually empty: GitHub links pull requests to a run only in some cases.
  Broken PRs are identified by branch and title.

## Licence

Apache 2.0.
