# Design: Review Now Button (Trigger Review from Repo Page)

> **Superseded (historical):** proposed lock file `review-{n}.lock`. Current code uses `session_dir/review.lock` with JSON metadata (pid + started_at). See review-status-log design for the current spec.

- Date: 2026-08-16
- Status: Approved (3 sections reviewed)

## Goal

Add a "Review now" / "Re-review" button on the repo page for each open PR so a
review can be triggered from the web UI, using the repo's current auto-review
config.

## API

`POST /api/repos/{owner}/{repo}/pr/{n}/review` — synchronous review:

1. Read `autoreview.yml` (same `_config_path()` as the config page) → build args:
   - `--force` (always full re-run when triggered manually)
   - `--skip-human` if `skip_human: true`
   - `--no-post` if `post_comment: false`
2. Call `run.main(args)` inside the request
3. Return `{ok: true, exit: 0, report: "<session_dir>/report.md"}` or
   `{detail}` HTTP 500 with exit code / stderr tail

No server-side hard timeout (agent can take 2-5 min); browser fetch waits;
progress printed to server stdout.

## UI (repo.html, Review status column)

- `Not reviewed` → button **Review now**
- `Reviewing…` → disabled button **Reviewing…**
- `Reviewed · N rounds` → button **Re-review**
- JS: click → button disabled + "Running…", POST, on completion reload page
  (fresh status/rounds)

## Edge cases

- API key missing → HTTP 400 "DEEPSEEK_API_KEY not set"
- gh not authenticated → HTTP 400 clear message
- Review error (model/agent) → HTTP 500 `{detail: "review failed (exit N):
  <stderr tail>"}`, button re-enabled
- Concurrent triggers → HTTP 409 "review already running" (lock file
  `review-{n}.lock` in session dir, try-acquire)
- PR not open anymore → still allowed (review current head, intended)

## Testing

- `test_server.py`: POST review with mocked `run.main` (exit 0) → 200; exit 3
  (missing key) → 400; exception → 500; existing lock → 409; button markup
  present in repo page
- Manual E2E: click Review now for PR #78 on local server → wait 2-5 min →
  page reload shows "Reviewed · 1 round" + PR comment (if post_comment true)
