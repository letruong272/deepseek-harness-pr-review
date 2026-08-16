# Design: Web Dashboard for PR Review Metrics

> **Superseded (historical):** describes the original read-only dashboard on port 8000. Current web dashboard runs on port 6789 and adds repo config management, review triggers, review status/log and open-PR tables. See README.md for current behavior.

- Date: 2026-08-16
- Status: Approved (3 sections reviewed)

## Goal

A read-only local web dashboard for the deepseek-harness-pr-review tool. It reads the
`sessions/` data produced by the headless pipeline and shows per-repo and per-PR
metrics: number of reviewed PRs, bugs found, doc errors, verdicts, and open
human-gate questions. No DB, no auth, no review triggering — it only displays data.

## Pages & Layout (user-approved mockups)

1. **`/` — Repo list**: one card per repo found under `sessions/`, showing
   PRs reviewed / bugs / doc errors. Clicking a card goes to the repo page.
2. **`/repos/{owner}/{repo}` — Repo detail** (mockup C, repo-focused): 4 KPI cards
   (PRs REVIEWED, BUGS, DOC ERRORS, OPEN Qs) + verdict distribution donut
   (Chart.js) + table of the repo's PRs: `#`, title, verdict (color-coded
   ACCURATE/PARTIAL/MISLEADING), bugs, doc errors. Clicking a row goes to PR detail.
3. **`/repos/{owner}/{repo}/pr/{n}` — PR detail** (mockup B, tabs): tabbed view:
   - **Claims**: table (id, text, category, status, evidence file:line, note)
   - **Docs**: table (path, status, difference)
   - **Impact**: table (requirement, impact, detail)
   - **Threads**: table (text, status, note)
   - **Confirm**: answers log (question → answer)

## Data Flow

No database. Each request reads directly from
`sessions/<owner>/<repo>/pr-<n>/{snapshot,findings,answers}.json` via a metrics
layer. `SESSION_ROOT` env (reuses `config.py`, default `sessions/`).

## Metrics Definitions

**PR record** (from findings.json + snapshot.json):
- `verdict` = same logic as `synthesize._overall_verdict`
  (ACCURATE / PARTIAL / MISLEADING / NO_CLAIMS)
- `bugs` = count of claims `FAIL` + impact `BROKEN`
- `doc_errors` = count of docs `WRONG` + `FABRICATED`
- `open_questions` = answers with answer `SKIPPED` or empty
- `failed` = true if `report.md` starts with `# Review FAILED` (phase error) —
  displayed with red highlight, excluded from verdict counts

**Repo record**: `{owner, repo, prs_total, bugs_total, doc_errors_total,
verdict_count: {ACCURATE: n, PARTIAL: n, MISLEADING: n, NO_CLAIMS: n},
prs: [PR record...]}`

**Rules:**
- Only PRs with both `snapshot.json` and `findings.json` are listed
- Sort: repos by `prs_total` desc; PRs by `updated_at` desc
- Every JSON read is try/except — one corrupt file skips that PR, never crashes the page

## Architecture

```
web/
├── server.py           # FastAPI app: routes, reads sessions/ via metrics
├── metrics.py          # session data → PR/repo records (pure logic, testable)
├── templates/
│   ├── base.html       # shared layout: navbar + repo name
│   ├── repo_list.html  # page 1
│   ├── repo.html       # page 2
│   └── pr.html         # page 3
├── static/style.css    # minimal styling
└── tests/test_metrics.py, tests/test_server.py
```

Run: `python -m web.server` → http://127.0.0.1:8000

## Error Handling

- `sessions/` missing or empty → empty state message on repo list:
  "No reviews yet — run `python -m src.run owner/repo N`"
- Corrupt JSON → skip that PR, warn to stderr
- Unknown repo/PR → 404 with clear message
- All data from JSON, no markdown parsing

## Testing

- `test_metrics.py`: fixture sessions dir (1 repo, 2 PRs: one complete, one with
  FAIL claim + BROKEN impact + WRONG doc) → assert bug/doc/verdict counts;
  corrupt JSON skipped
- `test_server.py` (FastAPI TestClient): fixture sessions dir → GET `/` 200 +
  repo name; GET `/repos/sample-org/sample-app` 200 + PR #77; GET PR detail 200
  + tabs; unknown → 404; empty sessions → empty state
- Optional E2E: run server with real `SESSION_ROOT`

## Stack

- FastAPI + uvicorn + Jinja2 + Chart.js (CDN)
- Added as optional extras: `pip install -e '.[web]'` (fastapi, uvicorn, jinja2)
- Reuses existing `config.py` (DSH_SESSION_ROOT)
