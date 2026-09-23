// The TypeScript this realm runs, on the appliance's wasm host. One file, by contract.
//
// Handler shape: export function name(args, ctx) — args FIRST; the surface is ctx.gateway.
// There is no global `gateway`. Graph reads go through ctx.gateway.cypher.query, which takes
// no bound params, so values are interpolated as escaped Cypher string literals here — they
// come from this realm's own ActionsWatch nodes, never from a caller.
//
// A literal head_branch and a literal created_at lower bound are both pushed down to GitHub
// by the runsByRepo producer, so each watched repository costs one or two API calls.

type Row = Record<string, any>

async function read(ctx: any, cypher: string): Promise<Row[]> {
  const res = await ctx.gateway.cypher.query({ cypher })
  if (!res) return []
  if (Array.isArray(res)) return res
  if (Array.isArray(res.rows)) return res.rows
  if (res.data && Array.isArray(res.data.rows)) return res.data.rows
  return []
}

const lit = (s: any): string => "'" + String(s ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'") + "'"
const num = (v: any): number => { const n = Number(v); return Number.isFinite(n) ? n : NaN }
/** Same labelling rule as the views: GitHub's dynamic workflows (Dependabot, Copilot, dependency
 *  submission) name each run with per-run prose, so label those by the dynamic path segment. */
const label = (x: Row): string =>
  String(x.path ?? '').startsWith('dynamic/') ? 'dynamic: ' + String(x.path).split('/')[1] : String(x.workflow ?? '')

/** The daily CI watch: for every ActionsWatch, the watched branch's runs since a cut-off,
 *  what failed, what is red right now, and the longest run. */
export async function ciWatch(args: { hours?: number }, ctx: any) {
  const hours = args && typeof args.hours === 'number' && args.hours > 0 ? args.hours : 24
  const since = new Date(Date.now() - hours * 3600 * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z')
  const watches = await read(ctx, `MATCH (w:ActionsWatch) RETURN w.full_name AS repo, w.branch AS branch, w.note AS note LIMIT 50`)
  const repositories: Row[] = []
  for (const w of watches) {
    const branch = w.branch && String(w.branch).trim() !== '' ? String(w.branch) : 'main'
    const runs = await read(ctx, `
      MATCH (r:GitHubRepository {full_name: ${lit(w.repo)}})-[:HAS_WORKFLOW_RUN]->(run:WorkflowRun)
      WHERE run.head_branch = ${lit(branch)} AND run.created_at >= ${lit(since)}
      RETURN run.id AS id, run.name AS workflow, run.path AS path, run.status AS status,
             run.conclusion AS conclusion, run.created_at AS createdAt, run.html_url AS url,
             CASE WHEN run.status = 'completed'
                  THEN duration.inSeconds(datetime(run.run_started_at), datetime(run.updated_at)).seconds
                  ELSE null END AS runSeconds
      ORDER BY run.created_at DESC
      LIMIT 500`)
    const failed = runs.filter(x => x.conclusion === 'failure')
    // Latest completed run per workflow: is that workflow red on this branch right now?
    const latest: Record<string, Row> = {}
    for (const x of runs) { const k = label(x); if (x.status === 'completed' && !latest[k]) latest[k] = x }
    const redNow = Object.values(latest).filter(x => x.conclusion === 'failure')
    const completed = runs.filter(x => Number.isFinite(num(x.runSeconds)))
    const longest = completed.length ? completed.reduce((a, b) => (num(b.runSeconds) > num(a.runSeconds) ? b : a)) : null
    repositories.push({
      repo: w.repo, branch, note: w.note ?? null,
      runs: runs.length, failed: failed.length,
      redNow: redNow.map(x => ({ workflow: label(x), url: x.url, at: x.createdAt })),
      failedRuns: failed.slice(0, 10).map(x => ({ workflow: label(x), url: x.url, at: x.createdAt })),
      longestRun: longest ? { workflow: label(longest), minutes: Math.round(num(longest.runSeconds) / 6) / 10, url: longest.url } : null,
    })
  }
  const red = repositories.filter(r => r.redNow.length > 0)
  const headline = watches.length === 0
    ? 'No ActionsWatch is seeded, so there is nothing to watch.'
    : red.length === 0
      ? `All ${repositories.length} watched branch(es) are green on their latest runs; ${repositories.reduce((n, r) => n + r.failed, 0)} run(s) failed in the last ${hours} h.`
      : `${red.length} watched branch(es) are RED right now: ` + red.map(r => `${r.repo}@${r.branch} (${r.redNow.map(x => x.workflow).join(', ')})`).join('; ')
  return { checkedAt: new Date().toISOString(), since, hours, headline, repositories }
}

/* Weekday mornings. A red main at 08:00 is the thing to know before standup. Installation
   makes the schedule available; an operator adopts it before it fires. */
defineSchedule('ciWatch', '0 0 8 * * MON-FRI')
