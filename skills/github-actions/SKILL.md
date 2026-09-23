---
name: github-actions
description: Answer questions about a repository's GitHub Actions CI — how the builds are doing, what failed, why a run was slow, what keeps failing, which jobs are flaky — using realm-github-actions' saved views rather than hand-written Cypher.
---

# GitHub Actions: question → view

Every answer this realm gives starts at a repository pinned by name. Ask which repository
if it is not obvious; never guess an owner/repo. Then call the view that claims the
question — each carries the exact figure and a link per row, so cite the numbers.

| The person asks | Call | Notes |
|---|---|---|
| how many builds ran / failed, success rate | `ActionsRunCount` | one row |
| how are the builds doing, which workflow fails most, average build time | `ActionsWorkflowSummary` | per workflow, worst first |
| slowest builds, what took longest | `ActionsSlowestRuns` | then `ActionsRunJobs` on a runId |
| what failed this week, failed builds on main | `ActionsFailedRuns` | `branch` narrows |
| why was run X slow, which job/step failed in run X | `ActionsRunJobs` | needs `runId`; pass `since` = the run's createdAt if you have it |
| where does the build time go, slowest jobs | `ActionsSlowestJobs` | opens the jobs of the N slowest runs |
| what keeps failing, most common failure, which step breaks | `ActionsFailingSteps` | deterministic counts |
| why do builds fail, common causes, summarise failures | `ActionsFailureThemes` | costs a model call |
| flaky builds, what passed on retry | `ActionsPassedOnRetry` | run level |
| flaky jobs, which job do we keep re-running | `ActionsFlakyJobs` | job level, via re-run attempts |
| builds per day, is CI getting slower | `ActionsDailyRuns` | trend |
| brief me on CI, standup summary | `ActionsBriefing` | costs a model call; figures from the views above |
| what workflows are there | `ActionsWorkflows` | |

## Windows

`days` is a relative window applied in the graph. `since`/`until` are ISO-8601 bounds; a
`since` LITERAL is pushed down to GitHub and fetches one page instead of the last 1,000
runs. When you know the dates, pass `since`. When writing Cypher yourself, filter
`run.created_at >= '2026-09-16T00:00:00Z'` with a literal for the same reason.

## What is not here

No logs (the failing step name and GitHub's failure annotations are the nearest thing),
no billing or minutes, no test-case granularity, no runner inventory. Say so rather than
composing an answer from the wrong rows.
