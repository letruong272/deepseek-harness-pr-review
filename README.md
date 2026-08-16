# Harness PR Review

Headless PR review running locally on the DeepSeek Harness SDK: deep-dive code,
verify the PR description claim by claim, check whether docs in the repo match
reality, analyze requirement impact, and use human-in-the-loop when uncertain
(≤20 words/question). Output: local English report + one English comment on the PR.

## Install

Requirements: Python 3.10+ (recommended 3.11), `gh` CLI already authenticated.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'   # zsh needs quotes; SDK comes from PyPI (deepseek-harness-sdk)
gh auth login          # required
export DEEPSEEK_API_KEY=sk-...   # see .env.example
```

## Usage

Run from this repo's directory (PYTHONPATH=src needed if not installed with -e):

```bash
PYTHONPATH=src python -m src.run owner/repo 123              # interactive
PYTHONPATH=src python -m src.run owner/repo 123 --skip-human # batch, no questions
PYTHONPATH=src python -m src.run owner/repo 123 --no-post    # don't post a comment
PYTHONPATH=src python -m src.run owner/repo#123              # shorthand syntax
```

Results land in `sessions/<owner>/<repo>/pr-<n>/report.md` (change the directory with `DSH_SESSION_ROOT`).

## Pipeline

1. **Snapshot** — fetch PR metadata, diff files, commits, review threads (GitHub REST + GraphQL)
2. **Claims** — LLM splits the description into verifiable claims
3. **Verify** — DeepSeek Harness agent deep-dives in a disposable worktree:
   verifies each claim, docs reality-check (MATCH/STALE/WRONG/FABRICATED),
   requirement impact, review thread status
4. **Human gate** — asks for confirmation (≤20 words/question) when docs are wrong or claims are uncertain
5. **Synthesize** — English report.md + one English comment on the PR (idempotent)

## Running tests

```bash
python -m pytest -v
```

## Web dashboard

Read-only dashboard for review metrics (PRs reviewed, bugs, doc errors, verdicts
per repo). Reads `sessions/` directly — no database.

```bash
pip install -e '.[web]'
DSH_SESSION_ROOT=sessions python -m web.server
# open http://127.0.0.1:8000
```

Pages: repo list → repo detail (KPIs + verdict donut + PR table) → PR detail
(tabs: Claims / Docs / Impact / Threads / Confirm).

## Configuration

| Env | Default | Meaning |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | DeepSeek API key |
| `DSH_MODEL` | `deepseek-v4-flash` | Model used for the agent + claim extraction |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible endpoint |
| `DSH_SESSION_ROOT` | `sessions` | Directory storing per-phase results |
