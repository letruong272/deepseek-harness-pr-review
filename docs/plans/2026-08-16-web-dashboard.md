# Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read-only local web dashboard (FastAPI + Jinja2 + Chart.js) showing per-repo and per-PR review metrics from the `sessions/` directory: PRs reviewed, bugs, doc errors, verdicts, open questions.

**Architecture:** A `web/` package with a pure metrics layer (`metrics.py` — reads sessions JSON into PR/repo records, no HTTP) and a thin FastAPI server (`server.py`) rendering 3 Jinja2 pages. No DB — every request reads `sessions/` fresh. Reuses `config.py` for `DSH_SESSION_ROOT`.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, Jinja2, httpx (TestClient), Chart.js via CDN. Installed as `pip install -e '.[web]'`.

**Spec:** `docs/designs/2026-08-16-web-dashboard-design.md`

---

## File Structure

```
web/
├── __init__.py          # empty
├── metrics.py           # session data → PR/repo records (pure logic)
├── server.py            # FastAPI app + 3 routes
├── templates/
│   ├── base.html        # shared layout: title + back link
│   ├── repo_list.html   # page 1: repo cards
│   ├── repo.html        # page 2: KPI cards + donut + PR table
│   └── pr.html          # page 3: tabs (Claims/Docs/Impact/Threads/Confirm)
└── static/
    └── style.css        # minimal styling
tests/
├── test_metrics.py
└── test_server.py
```

---

### Task 1: Metrics layer

**Files:**
- Create: `web/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics.py
import json
import os

from web import metrics

EMPTY_FINDINGS = {"claims": [], "docs": [], "impact": [], "threads": [],
                  "unresolved_questions": []}

SNAPSHOT = {"pr": 7, "title": "Add checkout", "author": "dev1",
            "base": "main", "head": "x", "files": [], "commits": [], "threads": []}


def _write_session(root, owner, repo, pr, snapshot=None, findings=None,
                   answers=None, report=None):
    d = root / owner / repo / f"pr-{pr}"
    d.mkdir(parents=True, exist_ok=True)
    if snapshot is not None:
        (d / "snapshot.json").write_text(json.dumps(snapshot))
    if findings is not None:
        (d / "findings.json").write_text(json.dumps(findings))
    if answers is not None:
        (d / "answers.json").write_text(json.dumps(answers))
    if report is not None:
        (d / "report.md").write_text(report)


def test_list_repos_empty(tmp_path):
    assert metrics.list_repos(tmp_path) == []


def test_list_repos_finds_pairs(tmp_path):
    _write_session(tmp_path, "nexpeakcore", "sample-app", 7,
                   snapshot=SNAPSHOT, findings=EMPTY_FINDINGS)
    _write_session(tmp_path, "nexpeakcore", "sample-api", 3,
                   snapshot=SNAPSHOT, findings=EMPTY_FINDINGS)
    assert metrics.list_repos(tmp_path) == [("nexpeakcore", "sample-app"),
                                            ("nexpeakcore", "sample-api")]


def test_pr_record_counts(tmp_path):
    findings = {
        "claims": [{"id": "C1", "status": "FAIL", "evidence": [], "note": ""},
                   {"id": "C2", "status": "PASS", "evidence": [], "note": ""}],
        "docs": [{"path": "a.md", "status": "WRONG", "what": ""},
                 {"path": "b.md", "status": "FABRICATED", "what": ""},
                 {"path": "c.md", "status": "MATCH", "what": ""}],
        "impact": [{"requirement": "R1", "impact": "BROKEN", "detail": ""}],
        "threads": [],
        "unresolved_questions": [],
    }
    _write_session(tmp_path, "o", "r", 7, snapshot=SNAPSHOT,
                   findings=findings,
                   answers=[{"question": "q1", "kind": "doc", "answer": "SKIPPED"},
                            {"question": "q2", "kind": "claim", "answer": "y"}])
    rec = metrics.pr_record(tmp_path, "o", "r", 7)
    assert rec["verdict"] == "MISLEADING"
    assert rec["bugs"] == 2            # 1 FAIL claim + 1 BROKEN impact
    assert rec["doc_errors"] == 2      # WRONG + FABRICATED
    assert rec["open_questions"] == 1  # only SKIPPED counted
    assert rec["claims_total"] == 2
    assert rec["failed"] is False


def test_pr_record_failed_phase(tmp_path):
    _write_session(tmp_path, "o", "r", 7, snapshot=SNAPSHOT,
                   findings=EMPTY_FINDINGS,
                   report="# Review FAILED\n\n- Lỗi: boom\n")
    rec = metrics.pr_record(tmp_path, "o", "r", 7)
    assert rec["failed"] is True


def test_pr_record_missing_files_returns_none(tmp_path):
    _write_session(tmp_path, "o", "r", 7, snapshot=SNAPSHOT)  # no findings
    assert metrics.pr_record(tmp_path, "o", "r", 7) is None


def test_pr_record_corrupt_json_skipped(tmp_path):
    d = tmp_path / "o" / "r" / "pr-7"
    d.mkdir(parents=True)
    (d / "snapshot.json").write_text("garbage")
    (d / "findings.json").write_text("garbage")
    assert metrics.pr_record(tmp_path, "o", "r", 7) is None


def test_repo_record_aggregates(tmp_path):
    findings = {
        "claims": [{"id": "C1", "status": "FAIL", "evidence": [], "note": ""}],
        "docs": [], "impact": [], "threads": [], "unresolved_questions": [],
    }
    _write_session(tmp_path, "o", "r", 7, snapshot=SNAPSHOT, findings=EMPTY_FINDINGS)
    _write_session(tmp_path, "o", "r", 8, snapshot=SNAPSHOT, findings=findings)
    rec = metrics.repo_record(tmp_path, "o", "r")
    assert rec["prs_total"] == 2
    assert rec["bugs_total"] == 1
    assert rec["doc_errors_total"] == 0
    assert rec["verdict_count"] == {"ACCURATE": 1, "PARTIAL": 0,
                                    "MISLEADING": 1, "NO_CLAIMS": 0}
    assert len(rec["prs"]) == 2


def test_repo_record_missing_returns_none(tmp_path):
    assert metrics.repo_record(tmp_path, "o", "nope") is None


def test_pr_detail_merges_claims(tmp_path):
    claims = [{"id": "C1", "text": "Adds checkout", "category": "feature",
               "files": [], "docs": []}]
    findings = {
        "claims": [{"id": "C1", "status": "PASS", "evidence": ["a.py:1"],
                    "note": ""}],
        "docs": [], "impact": [], "threads": [], "unresolved_questions": [],
    }
    _write_session(tmp_path, "o", "r", 7, snapshot=SNAPSHOT, findings=findings)
    (tmp_path / "o" / "r" / "pr-7" / "claims.json").write_text(
        json.dumps(claims))
    detail = metrics.pr_detail(tmp_path, "o", "r", 7)
    assert detail["claims"][0]["text"] == "Adds checkout"
    assert detail["claims"][0]["status"] == "PASS"
    assert detail["claims"][0]["category"] == "feature"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web'`

- [ ] **Step 3: Write minimal implementation**

```python
# web/__init__.py
"""Web dashboard package."""
```

```python
# web/metrics.py
"""Read sessions/ data into PR and repo metric records. Pure logic, no HTTP."""
import json
import sys
from datetime import datetime
from pathlib import Path

from synthesize import _overall_verdict

VERDICTS = ("ACCURATE", "PARTIAL", "MISLEADING", "NO_CLAIMS")
REQUIRED_FILES = ("snapshot.json", "findings.json")


def _warn(msg: str) -> None:
    print(f"[metrics] {msg}", file=sys.stderr)


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        _warn(f"skipping corrupt file: {path}")
        return None


def _session_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        d for d in root.glob("*/*/pr-*")
        if d.is_dir() and all((d / f).exists() for f in REQUIRED_FILES))


def _session_updated(session_dir: Path) -> str:
    try:
        return datetime.fromtimestamp(session_dir.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M")
    except OSError:
        return ""


def list_repos(session_root: Path) -> list[tuple[str, str]]:
    """Return sorted [(owner, repo)] pairs with review data."""
    pairs = sorted({(d.parent.parent.name, d.parent.name)
                    for d in _session_dirs(session_root)})
    return pairs


def pr_record(session_root: Path, owner: str, repo: str, n: int) -> dict | None:
    """Build one PR metric record. None if missing/corrupt data."""
    session_dir = session_root / owner / repo / f"pr-{n}"
    if not session_dir.is_dir():
        return None
    snapshot = _read_json(session_dir / "snapshot.json")
    findings = _read_json(session_dir / "findings.json")
    if snapshot is None or findings is None:
        return None

    answers = _read_json(session_dir / "answers.json") or []
    answers = answers if isinstance(answers, list) else []

    report = session_dir / "report.md"
    failed = report.exists() and report.read_text(
        errors="replace").startswith("# Review FAILED")

    claims = findings.get("claims", [])
    docs = findings.get("docs", [])
    impact = findings.get("impact", [])

    return {
        "pr": n,
        "title": snapshot.get("title", ""),
        "author": snapshot.get("author", ""),
        "base": snapshot.get("base", ""),
        "head": snapshot.get("head", ""),
        "verdict": _overall_verdict(findings),
        "claims_total": len(claims),
        "bugs": sum(1 for c in claims if c.get("status") == "FAIL")
                + sum(1 for i in impact if i.get("impact") == "BROKEN"),
        "doc_errors": sum(1 for d in docs
                          if d.get("status") in ("WRONG", "FABRICATED")),
        "open_questions": sum(1 for a in answers
                              if a.get("answer") in ("SKIPPED", "")),
        "updated_at": _session_updated(session_dir),
        "failed": failed,
    }


def repo_record(session_root: Path, owner: str, repo: str) -> dict | None:
    """Build one repo aggregate record. None if repo has no review data."""
    dirs = [d for d in _session_dirs(session_root)
            if d.parent.parent.name == owner and d.parent.name == repo]
    if not dirs:
        return None
    prs = []
    for d in dirs:
        n = int(d.name.split("-")[1])
        rec = pr_record(session_root, owner, repo, n)
        if rec is not None:
            prs.append(rec)
    prs.sort(key=lambda r: (r["failed"], -r["updated_at"]))
    verdict_count = {v: 0 for v in VERDICTS}
    for r in prs:
        if not r["failed"]:
            verdict_count[r["verdict"]] += 1
    return {
        "owner": owner,
        "repo": repo,
        "prs_total": len(prs),
        "bugs_total": sum(r["bugs"] for r in prs),
        "doc_errors_total": sum(r["doc_errors"] for r in prs),
        "verdict_count": verdict_count,
        "prs": prs,
    }


def pr_detail(session_root: Path, owner: str, repo: str, n: int) -> dict | None:
    """Full data for the PR detail page (claims merged with claim text)."""
    rec = pr_record(session_root, owner, repo, n)
    if rec is None:
        return None
    session_dir = session_root / owner / repo / f"pr-{n}"
    snapshot = _read_json(session_dir / "snapshot.json")
    findings = _read_json(session_dir / "findings.json")
    claims_json = _read_json(session_dir / "claims.json") or []
    claims_json = claims_json if isinstance(claims_json, list) else []
    by_id = {c.get("id"): c for c in claims_json if isinstance(c, dict)}

    claims = []
    for fc in findings.get("claims", []):
        base = by_id.get(fc.get("id"), {})
        claims.append({
            "id": fc.get("id", ""),
            "text": base.get("text", ""),
            "category": base.get("category", ""),
            "status": fc.get("status", ""),
            "evidence": fc.get("evidence", []),
            "note": fc.get("note", ""),
        })

    answers = _read_json(session_dir / "answers.json") or []
    answers = answers if isinstance(answers, list) else []

    return {
        "pr": rec,
        "title": snapshot.get("title", ""),
        "body": snapshot.get("body", ""),
        "claims": claims,
        "docs": findings.get("docs", []),
        "impact": findings.get("impact", []),
        "threads": findings.get("threads", []),
        "answers": answers,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: PASS — 9 tests

- [ ] **Step 5: Commit**

```bash
git add web/__init__.py web/metrics.py tests/test_metrics.py
git commit -m "feat: add metrics layer for web dashboard"
```

---

### Task 2: Web extras in pyproject

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject**

```toml
[project.optional-dependencies]
dev = ["pytest"]
web = ["fastapi", "uvicorn", "jinja2", "httpx"]
```

- [ ] **Step 2: Install**

Run: `.venv/bin/pip install -e '.[web]'`
Expected: fastapi, uvicorn, jinja2, httpx installed successfully

- [ ] **Step 3: Verify import**

Run: `.venv/bin/python -c "import fastapi, uvicorn, jinja2, httpx; print('web deps OK')"`
Expected: `web deps OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add web extras to pyproject"
```

---

### Task 3: FastAPI server + templates

**Files:**
- Create: `web/server.py`
- Create: `web/templates/base.html`
- Create: `web/templates/repo_list.html`
- Create: `web/templates/repo.html`
- Create: `web/templates/pr.html`
- Create: `web/static/style.css`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
import json

import pytest
from fastapi.testclient import TestClient

from web.server import app

EMPTY_FINDINGS = {"claims": [], "docs": [], "impact": [], "threads": [],
                  "unresolved_questions": []}

SNAPSHOT = {"pr": 7, "title": "Add checkout", "author": "dev1",
            "base": "main", "head": "x", "files": [], "commits": [], "threads": []}


def _write_session(root, owner, repo, pr, snapshot=None, findings=None,
                   answers=None, report=None):
    d = root / owner / repo / f"pr-{pr}"
    d.mkdir(parents=True, exist_ok=True)
    if snapshot is not None:
        (d / "snapshot.json").write_text(json.dumps(snapshot))
    if findings is not None:
        (d / "findings.json").write_text(json.dumps(findings))
    if answers is not None:
        (d / "answers.json").write_text(json.dumps(answers or []))
    if report is not None:
        (d / "report.md").write_text(report)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path))
    _write_session(tmp_path, "nexpeakcore", "sample-app", 77,
                   snapshot={**SNAPSHOT, "pr": 77, "title": "Google sign-in"},
                   findings={
                       "claims": [{"id": "C1", "status": "PASS",
                                   "evidence": ["a.dart:1"], "note": ""}],
                       "docs": [{"path": "docs/PLAN.md", "status": "WRONG",
                                 "what": "doc sai"}],
                       "impact": [{"requirement": "Auth", "impact": "CHANGED",
                                   "detail": "d"}],
                       "threads": [{"text": "check validation",
                                    "status": "STILL_VALID", "note": ""}],
                       "unresolved_questions": ["Doc PLAN wrong?"],
                   },
                   answers=[{"question": "Doc PLAN wrong?", "kind": "doc",
                             "answer": "SKIPPED"}])
    return TestClient(app)


def test_repo_list_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "sample-app" in resp.text


def test_repo_list_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path))
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    assert "No reviews yet" in resp.text


def test_repo_page(client):
    resp = client.get("/repos/sample-org/sample-app")
    assert resp.status_code == 200
    assert "Google sign-in" in resp.text
    assert "PRs REVIEWED" in resp.text


def test_pr_page_tabs(client):
    resp = client.get("/repos/sample-org/sample-app/pr/77")
    assert resp.status_code == 200
    assert "Claims" in resp.text
    assert "Docs" in resp.text
    assert "STILL_VALID" in resp.text
    assert "SKIPPED" in resp.text


def test_unknown_repo_404(client):
    assert client.get("/repos/sample-org/nope").status_code == 404


def test_unknown_pr_404(client):
    assert client.get("/repos/sample-org/sample-app/pr/999").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web.server'`

- [ ] **Step 3: Write minimal implementation**

```python
# web/server.py
"""FastAPI app: read-only PR review dashboard over sessions/."""
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from config import load_config
from web import metrics

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="PR Review Dashboard")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _session_root() -> Path:
    return load_config().session_root


@app.get("/", response_class=HTMLResponse)
def repo_list(request: Request):
    root = _session_root()
    repos = []
    for owner, repo in metrics.list_repos(root):
        rec = metrics.repo_record(root, owner, repo)
        if rec is not None:
            repos.append(rec)
    repos.sort(key=lambda r: r["prs_total"], reverse=True)
    return templates.TemplateResponse(
        request, "repo_list.html", {"repos": repos})


@app.get("/repos/{owner}/{repo}", response_class=HTMLResponse)
def repo_page(request: Request, owner: str, repo: str):
    rec = metrics.repo_record(_session_root(), owner, repo)
    if rec is None:
        raise HTTPException(status_code=404, detail="Repo not found in sessions")
    verdict_json = json.dumps(rec["verdict_count"])
    return templates.TemplateResponse(
        request, "repo.html",
        {"repo": rec, "verdict_json": verdict_json})


@app.get("/repos/{owner}/{repo}/pr/{pr}", response_class=HTMLResponse)
def pr_page(request: Request, owner: str, repo: str, pr: int):
    detail = metrics.pr_detail(_session_root(), owner, repo, pr)
    if detail is None:
        raise HTTPException(status_code=404, detail="PR not found in sessions")
    return templates.TemplateResponse(request, "pr.html", {"detail": detail})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
```

```html
<!-- web/templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}PR Review Dashboard{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
  {% block head %}{% endblock %}
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/">PR Review Dashboard</a>
    {% block nav %}{% endblock %}
  </header>
  <main class="container">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

```html
<!-- web/templates/repo_list.html -->
{% extends "base.html" %}
{% block content %}
<h1>Repositories</h1>
{% if not repos %}
<p class="empty">No reviews yet — run
<code>python -m src.run owner/repo N</code> to create the first one.</p>
{% else %}
<div class="cards">
  {% for r in repos %}
  <a class="card repo-card" href="/repos/{{ r.owner }}/{{ r.repo }}">
    <h3>{{ r.owner }}/{{ r.repo }}</h3>
    <div class="kpis">
      <span class="kpi"><b>{{ r.prs_total }}</b> PRs</span>
      <span class="kpi bad"><b>{{ r.bugs_total }}</b> bugs</span>
      <span class="kpi warn"><b>{{ r.doc_errors_total }}</b> doc errors</span>
    </div>
  </a>
  {% endfor %}
</div>
{% endif %}
{% endblock %}
```

```html
<!-- web/templates/repo.html -->
{% extends "base.html" %}
{% block nav %}<a class="crumb" href="/">← Repos</a>{% endblock %}
{% block head %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
{% endblock %}
{% block content %}
<h1>{{ repo.owner }}/{{ repo.repo }}</h1>

<div class="kpi-row">
  <div class="kpi-card"><div class="kpi-label">PRs REVIEWED</div>
    <div class="kpi-value">{{ repo.prs_total }}</div></div>
  <div class="kpi-card bad"><div class="kpi-label">BUGS</div>
    <div class="kpi-value">{{ repo.bugs_total }}</div></div>
  <div class="kpi-card warn"><div class="kpi-label">DOC ERRORS</div>
    <div class="kpi-value">{{ repo.doc_errors_total }}</div></div>
  <div class="kpi-card"><div class="kpi-label">OPEN Qs</div>
    <div class="kpi-value">{{ open_qs }}</div></div>
  <div class="kpi-card chart-card"><div class="kpi-label">VERDICTS</div>
    <canvas id="verdictChart" width="90" height="90"></canvas></div>
</div>

<h2>Pull requests</h2>
<table class="table">
  <thead><tr><th>#</th><th>Title</th><th>Verdict</th><th>Bugs</th>
    <th>Doc errors</th><th>Updated</th></tr></thead>
  <tbody>
  {% for p in repo.prs %}
    <tr class="{{ 'failed' if p.failed else '' }}">
      <td><a href="/repos/{{ repo.owner }}/{{ repo.repo }}/pr/{{ p.pr }}">#{{ p.pr }}</a></td>
      <td>{{ p.title }} {% if p.failed %}<span class="tag fail">FAILED</span>{% endif %}</td>
      <td><span class="verdict v-{{ p.verdict|lower }}">{{ p.verdict }}</span></td>
      <td>{{ p.bugs }}</td><td>{{ p.doc_errors }}</td>
      <td class="muted">{{ p.updated_at }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<script>
const verdictData = {{ verdict_json | safe }};
new Chart(document.getElementById("verdictChart"), {
  type: "doughnut",
  data: {
    labels: Object.keys(verdictData),
    datasets: [{
      data: Object.values(verdictData),
      backgroundColor: ["#27ae60", "#f39c12", "#e74c3c", "#95a5a6"]
    }]
  },
  options: { plugins: { legend: { display: false } } }
});
</script>
{% endblock %}
```

Lưu ý: `open_qs` chưa có — thêm vào template context. Cách tính: tổng `open_questions` của các PR trong repo. Sửa route:

```python
@app.get("/repos/{owner}/{repo}", response_class=HTMLResponse)
def repo_page(request: Request, owner: str, repo: str):
    rec = metrics.repo_record(_session_root(), owner, repo)
    if rec is None:
        raise HTTPException(status_code=404, detail="Repo not found in sessions")
    verdict_json = json.dumps(rec["verdict_count"])
    open_qs = sum(p["open_questions"] for p in rec["prs"])
    return templates.TemplateResponse(
        request, "repo.html",
        {"repo": rec, "verdict_json": verdict_json, "open_qs": open_qs})
```

```html
<!-- web/templates/pr.html -->
{% extends "base.html" %}
{% block nav %}
<a class="crumb" href="/repos/{{ detail.pr.author and detail.pr.author or '' }}"></a>
<a class="crumb" href="/repos/{{ repo_owner }}/{{ repo_name }}">← {{ repo_owner }}/{{ repo_name }}</a>
{% endblock %}
{% block content %}
<h1>PR #{{ detail.pr.pr }} — {{ detail.title }}</h1>
<p class="muted">{{ detail.pr.author }} · {{ detail.pr.base }} → {{ detail.pr.head }}</p>
<span class="verdict v-{{ detail.pr.verdict|lower }}">{{ detail.pr.verdict }}</span>

<div class="tabs">
  <button class="tab-btn active" onclick="showTab('tab-claims', this)">Claims ({{ detail.claims|length }})</button>
  <button class="tab-btn" onclick="showTab('tab-docs', this)">Docs ({{ detail.docs|length }})</button>
  <button class="tab-btn" onclick="showTab('tab-impact', this)">Impact ({{ detail.impact|length }})</button>
  <button class="tab-btn" onclick="showTab('tab-threads', this)">Threads ({{ detail.threads|length }})</button>
  <button class="tab-btn" onclick="showTab('tab-confirm', this)">Confirm ({{ detail.answers|length }})</button>
</div>

<div id="tab-claims" class="tab-panel">
  <table class="table">
    <thead><tr><th>Claim</th><th>Category</th><th>Status</th><th>Evidence</th><th>Note</th></tr></thead>
    <tbody>
    {% for c in detail.claims %}
      <tr>
        <td><b>{{ c.id }}</b> {{ c.text }}</td>
        <td>{{ c.category }}</td>
        <td><span class="verdict v-{{ c.status|lower }}">{{ c.status }}</span></td>
        <td class="muted">{{ c.evidence|join(", ") }}</td>
        <td class="muted">{{ c.note }}</td>
      </tr>
    {% else %}
      <tr><td colspan="5" class="empty">No claims</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<div id="tab-docs" class="tab-panel" style="display:none">
  <table class="table">
    <thead><tr><th>Doc</th><th>Status</th><th>Difference</th></tr></thead>
    <tbody>
    {% for d in detail.docs %}
      <tr><td>{{ d.path }}</td>
          <td><span class="verdict v-{{ d.status|lower }}">{{ d.status }}</span></td>
          <td class="muted">{{ d.what }}</td></tr>
    {% else %}
      <tr><td colspan="3" class="empty">No docs checked</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<div id="tab-impact" class="tab-panel" style="display:none">
  <table class="table">
    <thead><tr><th>Requirement</th><th>Impact</th><th>Detail</th></tr></thead>
    <tbody>
    {% for i in detail.impact %}
      <tr><td>{{ i.requirement }}</td>
          <td><span class="verdict v-{{ i.impact|lower }}">{{ i.impact }}</span></td>
          <td class="muted">{{ i.detail }}</td></tr>
    {% else %}
      <tr><td colspan="3" class="empty">No impact analysis</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<div id="tab-threads" class="tab-panel" style="display:none">
  <table class="table">
    <thead><tr><th>Comment</th><th>Status</th><th>Note</th></tr></thead>
    <tbody>
    {% for t in detail.threads %}
      <tr><td>{{ t.text }}</td>
          <td><span class="verdict v-{{ t.status|lower }}">{{ t.status }}</span></td>
          <td class="muted">{{ t.note }}</td></tr>
    {% else %}
      <tr><td colspan="3" class="empty">No review threads</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<div id="tab-confirm" class="tab-panel" style="display:none">
  <table class="table">
    <thead><tr><th>Question</th><th>Answer</th></tr></thead>
    <tbody>
    {% for a in detail.answers %}
      <tr><td>{{ a.question }}</td>
          <td>{{ a.answer }}</td></tr>
    {% else %}
      <tr><td colspan="2" class="empty">No confirmations recorded</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<script>
function showTab(id, btn) {
  document.querySelectorAll(".tab-panel").forEach(p => p.style.display = "none");
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById(id).style.display = "block";
  btn.classList.add("active");
}
</script>
{% endblock %}
```

Lưu ý: pr.html dùng `repo_owner`/`repo_name` chưa có — route phải truyền:

```python
@app.get("/repos/{owner}/{repo}/pr/{pr}", response_class=HTMLResponse)
def pr_page(request: Request, owner: str, repo: str, pr: int):
    detail = metrics.pr_detail(_session_root(), owner, repo, pr)
    if detail is None:
        raise HTTPException(status_code=404, detail="PR not found in sessions")
    return templates.TemplateResponse(
        request, "pr.html",
        {"detail": detail, "repo_owner": owner, "repo_name": repo})
```

```css
/* web/static/style.css */
:root { --border: #e3e8ee; --muted: #6b7280; }
body { margin: 0; font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
       background: #f6f8fa; color: #1f2937; }
.topbar { background: #2c3e50; color: #fff; padding: 10px 20px;
          display: flex; align-items: center; gap: 16px; }
.brand { color: #fff; font-weight: 700; text-decoration: none; }
.crumb { color: #bdc3c7; text-decoration: none; font-size: 13px; }
.container { max-width: 1000px; margin: 20px auto; padding: 0 16px; }
h1 { font-size: 22px; }
h2 { font-size: 16px; margin-top: 28px; }
.muted { color: var(--muted); }
.empty { color: var(--muted); padding: 12px 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.card { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
a.card { text-decoration: none; color: inherit; display: block; }
a.card:hover { border-color: #2c3e50; }
.kpis { display: flex; gap: 16px; margin-top: 8px; }
.kpi.bad b { color: #c0392b; }
.kpi.warn b { color: #b9770e; }
.kpi-row { display: flex; gap: 12px; flex-wrap: wrap; }
.kpi-card { background: #fff; border: 1px solid var(--border); border-radius: 8px;
            padding: 12px 18px; text-align: center; min-width: 110px; }
.kpi-card.bad .kpi-value { color: #c0392b; }
.kpi-card.warn .kpi-value { color: #b9770e; }
.kpi-label { font-size: 11px; color: var(--muted); }
.kpi-value { font-size: 24px; font-weight: 700; }
.chart-card canvas { margin: 0 auto; }
.table { width: 100%; border-collapse: collapse; background: #fff;
         border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
         font-size: 13px; }
.table th { text-align: left; background: #f4f6f8; padding: 8px 10px; }
.table td { padding: 8px 10px; border-top: 1px solid var(--border); vertical-align: top; }
tr.failed td { background: #fdecea; }
.tag.fail { background: #e74c3c; color: #fff; font-size: 10px; padding: 1px 6px;
            border-radius: 8px; margin-left: 6px; }
.verdict { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
.v-accurate, .v-pass, .v-match, .v-resolved, .v-fixed { background: #eaf7ee; color: #27ae60; }
.v-partial, .v-wrong, .v-stale, .v-still_valid, .v-risk, .v-changed { background: #fdf6e3; color: #b9770e; }
.v-misleading, .v-fail, .v-fabricated, .v-broken { background: #fdecea; color: #c0392b; }
.v-no_claims, .v-unverified, .v-outdated, .v-unaffected { background: #eef1f4; color: #6b7280; }
.tabs { display: flex; gap: 4px; margin: 16px 0; flex-wrap: wrap; }
.tab-btn { background: #f4f6f8; border: 1px solid var(--border); padding: 6px 14px;
           border-radius: 6px 6px 0 0; cursor: pointer; font-size: 13px; }
.tab-btn.active { background: #2c3e50; color: #fff; border-color: #2c3e50; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS — 6 tests

- [ ] **Step 5: Manual smoke test**

Run: `DSH_SESSION_ROOT=sessions .venv/bin/python -m web.server &` rồi mở
`http://127.0.0.1:8000` — thấy repo list có `sample-org/sample-app`, click
vào repo → PR #77 → tabs hiển thị dữ liệu. Sau đó kill server.

- [ ] **Step 6: Commit**

```bash
git add web/ tests/test_server.py
git commit -m "feat: add web dashboard server and templates"
```

---

### Task 4: README + full suite

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add web section to README**

```markdown
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
```

- [ ] **Step 2: Run full suite**

Run: `.venv/bin/python -m pytest -v`
Expected: PASS — 39 existing + 9 metrics + 6 server = 54 tests

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document web dashboard usage"
```

---

## Self-Review Checklist

- **Spec coverage:** repo list page (T3 route `/`), repo detail with 4 KPI cards +
  donut (T3 repo.html + T1 repo_record verdict_count), PR detail tabs
  Claims/Docs/Impact/Threads/Confirm (T1 pr_detail + T3 pr.html), metrics
  definitions bugs=FAIL+BROKEN / doc_errors=WRONG+FABRICATED / open_questions=SKIPPED
  (T1 pr_record), failed detection via `# Review FAILED` (T1), corrupt JSON skip
  (T1 `_read_json`), empty state (T3 repo_list.html), 404s (T3), SESSION_ROOT env
  reuse (T3 `_session_root`), Chart.js CDN donut (T3), `[web]` extras (T2). ✅
- **Placeholders:** no TBD/TODO; all steps have complete code. ✅
- **Type consistency:** `pr_record(session_root, owner, repo, n)`,
  `repo_record(session_root, owner, repo)`, `list_repos(session_root)`,
  `pr_detail(session_root, owner, repo, n)` — used identically in T1 tests and T3
  server. Record keys (`pr`, `title`, `verdict`, `bugs`, `doc_errors`,
  `open_questions`, `failed`, `updated_at`, `prs_total`, `bugs_total`,
  `doc_errors_total`, `verdict_count`, `prs`) match across T1/T3 templates. ✅
