# Design: Repo Page — Open PRs, Review Status, Rounds, Metric Fix

- Date: 2026-08-16
- Status: Approved (3 sections reviewed)

## Goal

Fix `/repos/{owner}/{repo}` so it lists ALL open PRs (not just reviewed ones),
shows each PR's review status (not reviewed / reviewing / reviewed N rounds),
and corrects the Bugs / Doc errors numbers so they match what the PR detail page
shows.

## Part 1 — Repo page table (all open PRs)

Table columns: `# | Title | Draft | Review status | Bugs | Doc errors`

- Source of open PRs: `gh api repos/{o}/{r}/pulls?state=open`
  (reuse `autoreview.fetch_open_prs`)
- Review status per PR (from sessions/):
  - `Not reviewed` — no session dir
  - `Reviewing…` — session dir exists but findings.json missing (in progress)
  - `Reviewed · N rounds` — findings.json exists, N from rounds.txt (fallback 1)
- Merged/closed PRs with sessions are NOT shown in the table but still counted in KPIs
- KPI cards stay, label clarified: "Bugs (based on N reviewed PRs)"
- Draft badge shown; gh failure → table shows reviewed PRs only + "open PRs unavailable" badge
- Sort: open PRs by number desc (newest first)

## Part 2 — Round tracking + broader metrics

**Round tracking (pipeline):**
- `run.py`: when `run_verify` actually runs (findings regenerated) → increment
  `session_dir/rounds.txt` (+1)
- Auto re-review (`--force` via autoreview) goes through run.py → counted automatically
- PR with findings but no rounds.txt (legacy data) → display 1
- Manual run without `--force` (cache hit) → no increment

**Broader metrics (`web/metrics.py`):**
- `bugs` = claims `FAIL` + `PARTIAL` + impact `BROKEN` + `RISK`
- `doc_errors` = docs `WRONG` + `FABRICATED` + `STALE`
- Real pr-77 fixture: 10 claims (1 PARTIAL), 4 docs (2 STALE), 5 impact (2 RISK)
  → bugs = 3, doc_errors = 2

**Data flow:**
- `metrics.pr_record` adds `rounds` (from rounds.txt, fallback 1)
- `metrics.open_prs(session_root, owner, repo, gh)` → merge open PRs (gh) +
  session state → list of rows
- `server.repo_page` calls `open_prs` + renders new table
- `repo.html` adds Draft + Review status columns

## Part 3 — Error handling & edge cases

- gh failure fetching open PRs → show reviewed PRs from sessions + badge
- Draft PRs shown with badge
- Corrupt rounds.txt (not a number) → treated as 1
- Session dir without findings (in-progress) → "Reviewing…", no crash
- KPI verdict donut counts only reviewed PRs (unchanged) + "based on N reviewed" label

## Testing

- `test_metrics.py`: rounds from file / fallback 1; new metric definitions
  (PARTIAL/RISK/STALE counted); open_prs merge with fake gh
- `test_run.py`: verify run → rounds.txt incremented; cached run → no increment
- `test_server.py`: repo page shows un-reviewed open PR + "Not reviewed" + rounds
  (fake gh); gh failure badge
- Smoke: `/repos/sample-org/sample-app` shows #77 Reviewed 1 round + #78/#1
  Not reviewed
