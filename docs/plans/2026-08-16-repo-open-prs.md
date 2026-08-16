# Repo Page — Open PRs + Review Status + Rounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repo page lists ALL open PRs (from GitHub) with per-PR review status (Not reviewed / Reviewing / Reviewed N rounds), plus broader Bugs/Doc errors metrics that match the PR detail page.

**Architecture:** `run.py` increments `rounds.txt` in the session dir whenever verify actually runs; `web/metrics.py` reads rounds, widens the bug/doc-error definitions (PARTIAL/RISK/STALE now count), and gains `open_prs()` which merges GitHub open PRs (via gh) with session state; `server.repo_page` + `repo.html` render the new table.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, existing `gh.py`/`autoreview.fetch_open_prs`.

**Spec:** `docs/designs/2026-08-16-repo-open-prs-design.md`

---

## File Structure

```
src/run.py               # MODIFY: bump rounds.txt when verify runs
web/metrics.py           # MODIFY: rounds, wider metrics, open_prs()
web/server.py            # MODIFY: repo_page passes open_prs + rounds
web/templates/repo.html  # MODIFY: new table columns
tests/test_run.py        # MODIFY: rounds tests
tests/test_metrics.py    # MODIFY: rounds + wider metrics + open_prs tests
tests/test_server.py     # MODIFY: repo page open PRs tests
```

---

### Task 1: Round tracking in run.py

**Files:**
- Modify: `src/run.py`
- Modify: `tests/test_run.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_run.py — thêm vào cuối file
def test_verify_run_bumps_rounds(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setattr("run.gh_available", lambda: True)

    fake_snapshot = {"owner": "demo", "repo": "app", "pr": 7, "title": "T",
                     "body": "B", "author": "a", "base": "main", "head": "x",
                     "labels": [], "files": [], "commits": [], "threads": []}
    fake_findings = {"claims": [], "docs": [], "impact": [], "threads": [],
                     "unresolved_questions": []}

    def fake_build_snapshot(owner, repo, n, session_dir, gh=None):
        return fake_snapshot

    def fake_extract_claims(snapshot, cfg, session_dir, chat=None):
        return []

    def fake_setup_workspace(owner, repo, n, workspace, remote_url=None):
        pass

    def fake_run_verify(cfg, workspace, session_dir, snapshot, claims):
        return fake_findings

    monkeypatch.setattr("snapshot.build_snapshot", fake_build_snapshot)
    monkeypatch.setattr("claims.extract_claims", fake_extract_claims)
    monkeypatch.setattr("verify.setup_workspace", fake_setup_workspace)
    monkeypatch.setattr("run.run_verify", fake_run_verify)

    assert main(["demo/app", "7", "--no-post"]) == 0
    rounds_file = tmp_path / "sessions" / "demo" / "app" / "pr-7" / "rounds.txt"
    assert rounds_file.read_text().strip() == "1"

    assert main(["demo/app", "7", "--no-post"]) == 0  # cached run, no bump
    assert rounds_file.read_text().strip() == "1"

    assert main(["demo/app", "7", "--no-post", "--force"]) == 0  # force → bump
    assert rounds_file.read_text().strip() == "2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_run.py::test_verify_run_bumps_rounds -v`
Expected: FAIL — `FileNotFoundError: rounds.txt` không tồn tại

- [ ] **Step 3: Implement**

Thêm helper vào `src/run.py` (sau `_load_or_skip`):

```python
def _bump_rounds(session_dir: Path) -> None:
    """Increment the review-round counter for a session (after a verify pass)."""
    path = session_dir / "rounds.txt"
    try:
        current = int(path.read_text().strip() or "0")
    except (OSError, ValueError):
        current = 0
    path.write_text(str(current + 1))
```

Trong `main()`, tại nhánh `if findings is None:` sau khi ghi findings.json:

```python
            findings = _load_or_skip("findings.json", session_dir, args.force)
            if findings is None:
                workspace = session_dir / "workspace"
                setup_workspace(owner, repo, int(num), workspace)
                findings = run_verify(
                    {"model": cfg.model}, workspace, session_dir, snapshot, claims)
                (session_dir / "findings.json").write_text(
                    json.dumps(findings, indent=2))
                _bump_rounds(session_dir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_run.py -v`
Expected: PASS — 3 cũ + 1 mới = 4 tests

- [ ] **Step 5: Commit**

```bash
git add src/run.py tests/test_run.py
git commit -m "feat: track review rounds in session"
```

---

### Task 2: Wider metrics + rounds in metrics.py

**Files:**
- Modify: `web/metrics.py`
- Modify: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_metrics.py — thêm vào cuối file
def test_pr_record_wider_metrics(tmp_path):
    findings = {
        "claims": [{"id": "C1", "status": "FAIL", "evidence": [], "note": ""},
                   {"id": "C2", "status": "PARTIAL", "evidence": [], "note": ""},
                   {"id": "C3", "status": "PASS", "evidence": [], "note": ""}],
        "docs": [{"path": "a.md", "status": "WRONG", "what": ""},
                 {"path": "b.md", "status": "STALE", "what": ""},
                 {"path": "c.md", "status": "FABRICATED", "what": ""},
                 {"path": "d.md", "status": "MATCH", "what": ""}],
        "impact": [{"requirement": "R1", "impact": "BROKEN", "detail": ""},
                   {"requirement": "R2", "impact": "RISK", "detail": ""},
                   {"requirement": "R3", "impact": "CHANGED", "detail": ""}],
        "threads": [],
        "unresolved_questions": [],
    }
    _write_session(tmp_path, "o", "r", 7, snapshot=SNAPSHOT, findings=findings)
    rec = metrics.pr_record(tmp_path, "o", "r", 7)
    assert rec["bugs"] == 4          # FAIL + PARTIAL + BROKEN + RISK
    assert rec["doc_errors"] == 3    # WRONG + FABRICATED + STALE


def test_pr_record_rounds(tmp_path):
    _write_session(tmp_path, "o", "r", 7, snapshot=SNAPSHOT,
                   findings=EMPTY_FINDINGS)
    (tmp_path / "o" / "r" / "pr-7" / "rounds.txt").write_text("3")
    rec = metrics.pr_record(tmp_path, "o", "r", 7)
    assert rec["rounds"] == 3


def test_pr_record_rounds_fallback(tmp_path):
    # không có rounds.txt → 1
    _write_session(tmp_path, "o", "r", 7, snapshot=SNAPSHOT,
                   findings=EMPTY_FINDINGS)
    assert metrics.pr_record(tmp_path, "o", "r", 7)["rounds"] == 1


def test_pr_record_rounds_garbage(tmp_path):
    _write_session(tmp_path, "o", "r", 7, snapshot=SNAPSHOT,
                   findings=EMPTY_FINDINGS)
    (tmp_path / "o" / "r" / "pr-7" / "rounds.txt").write_text("abc")
    assert metrics.pr_record(tmp_path, "o", "r", 7)["rounds"] == 1


def test_open_prs_merge(tmp_path):
    root = tmp_path / "sessions"
    _write_session(root, "o", "r", 7, snapshot=SNAPSHOT,
                   findings=EMPTY_FINDINGS)
    (root / "o" / "r" / "pr-7" / "rounds.txt").write_text("2")
    # pr-8: session dir có snapshot nhưng chưa có findings → Reviewing…
    d8 = root / "o" / "r" / "pr-8"
    d8.mkdir(parents=True)
    (d8 / "snapshot.json").write_text(json.dumps(SNAPSHOT))

    open_prs = [
        {"number": 7, "title": "T7", "draft": False},
        {"number": 8, "title": "T8", "draft": True},
        {"number": 9, "title": "T9", "draft": False},
    ]

    def fake_gh(args, **kw):
        assert "pulls" in args[1]
        return open_prs

    rows = metrics.open_prs(root, "o", "r", gh=fake_gh)
    by_num = {r["pr"]: r for r in rows}
    assert by_num[7]["status"] == "reviewed"
    assert by_num[7]["rounds"] == 2
    assert by_num[7]["draft"] is False
    assert by_num[8]["status"] == "reviewing"
    assert by_num[9]["status"] == "not_reviewed"
    # sort theo number desc
    assert [r["pr"] for r in rows] == [9, 8, 7]


def test_open_prs_gh_failure(tmp_path):
    root = tmp_path / "sessions"
    _write_session(root, "o", "r", 7, snapshot=SNAPSHOT,
                   findings=EMPTY_FINDINGS)

    def fake_gh(args, **kw):
        raise RuntimeError("rate limited")

    rows = metrics.open_prs(root, "o", "r", gh=fake_gh)
    # gh lỗi → trả PR đã review từ sessions, đánh dấu unavailable
    assert rows[0]["pr"] == 7
    assert rows[0]["unavailable"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: FAIL — `open_prs` chưa tồn tại; bugs/doc_errors đếm sai cho trường hợp mới

Lưu ý: test cũ `test_pr_record_counts` (FAIL claim + BROKEN impact + WRONG/FABRICATED docs) vẫn phải pass — bugs giờ = 1 FAIL + 0 PARTIAL + 1 BROKEN + 0 RISK = 2 (không đổi); doc_errors = 2 (WRONG + FABRICATED, không có STALE) — không đổi. ✅

- [ ] **Step 3: Implement**

`web/metrics.py`:

```python
def _read_rounds(session_dir: Path) -> int:
    """Rounds from rounds.txt; fallback 1 for legacy sessions; garbage → 1."""
    path = session_dir / "rounds.txt"
    if not path.exists():
        return 1
    try:
        return max(1, int(path.read_text().strip()))
    except (OSError, ValueError):
        return 1
```

Sửa `pr_record` — bugs/doc_errors rộng hơn + rounds:

```python
        "bugs": sum(1 for c in claims
                    if c.get("status") in ("FAIL", "PARTIAL"))
                + sum(1 for i in impact
                      if i.get("impact") in ("BROKEN", "RISK")),
        "doc_errors": sum(1 for d in docs
                          if d.get("status") in ("WRONG", "FABRICATED", "STALE")),
```

thêm vào dict trả về:

```python
        "rounds": _read_rounds(session_dir),
```

Thêm hàm `open_prs` (đặt sau `repo_record`):

```python
def open_prs(session_root: Path, owner: str, repo: str, gh=None) -> list[dict]:
    """Merge GitHub open PRs with session state.

    Returns rows: {pr, title, draft, status, rounds, unavailable} sorted by pr desc.
    status: reviewed | reviewing | not_reviewed
    gh failure → rows for reviewed sessions only, unavailable=True.
    """
    if gh is None:
        from gh import run_gh
        gh = run_gh
    rows = []
    unavailable = False
    try:
        prs = gh(["api", f"repos/{owner}/{repo}/pulls?state=open", "--paginate"])
    except (RuntimeError, OSError):
        prs = []
        unavailable = True

    session_dir = session_root / owner / repo
    seen = set()
    for p in prs:
        n = int(p["number"])
        seen.add(n)
        d = session_dir / f"pr-{n}"
        if (d / "findings.json").exists():
            rows.append({"pr": n, "title": p.get("title", ""),
                         "draft": bool(p.get("draft")),
                         "status": "reviewed",
                         "rounds": _read_rounds(d), "unavailable": unavailable})
        elif d.exists():
            rows.append({"pr": n, "title": p.get("title", ""),
                         "draft": bool(p.get("draft")),
                         "status": "reviewing", "rounds": None,
                         "unavailable": unavailable})
        else:
            rows.append({"pr": n, "title": p.get("title", ""),
                         "draft": bool(p.get("draft")),
                         "status": "not_reviewed", "rounds": None,
                         "unavailable": unavailable})

    if unavailable:
        # gh lỗi → fallback: PR đã review từ sessions
        for d in sorted((session_root / owner / repo).glob("pr-*")):
            n = int(d.name.split("-")[1])
            if n in seen:
                continue
            if (d / "findings.json").exists():
                rows.append({"pr": n, "title": "", "draft": False,
                             "status": "reviewed",
                             "rounds": _read_rounds(d), "unavailable": True})

    rows.sort(key=lambda r: r["pr"], reverse=True)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: PASS — 9 cũ + 6 mới = 15 tests

- [ ] **Step 5: Commit**

```bash
git add web/metrics.py tests/test_metrics.py
git commit -m "feat: wider metrics, rounds, open PRs merge in metrics"
```

---

### Task 3: Repo page renders open PRs

**Files:**
- Modify: `web/server.py`
- Modify: `web/templates/repo.html`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server.py — thêm vào cuối file
def test_repo_page_shows_open_prs(client, tmp_path, monkeypatch):
    # client fixture có sẵn: session sample-org/sample-app pr-77 (reviewed, rounds fallback 1)
    def fake_gh(args, **kw):
        return [
            {"number": 78, "title": "chore: update deps", "draft": False},
            {"number": 77, "title": "Google sign-in", "draft": False},
        ]

    monkeypatch.setattr("gh.run_gh", fake_gh)
    resp = client.get("/repos/sample-org/sample-app")
    assert resp.status_code == 200
    assert "chore: update deps" in resp.text
    assert "Not reviewed" in resp.text
    assert "Reviewed" in resp.text


def test_repo_page_gh_failure_badge(client, tmp_path, monkeypatch):
    def fake_gh(args, **kw):
        raise RuntimeError("rate limited")

    monkeypatch.setattr("gh.run_gh", fake_gh)
    resp = client.get("/repos/sample-org/sample-app")
    assert resp.status_code == 200
    assert "open PRs unavailable" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: FAIL — trang repo chưa hiện "Not reviewed"/"chore: update deps"

- [ ] **Step 3: Implement**

`web/server.py` — `repo_page` dùng open_prs + gh:

```python
@app.get("/repos/{owner}/{repo}", response_class=HTMLResponse)
def repo_page(request: Request, owner: str, repo: str):
    rec = metrics.repo_record(_session_root(), owner, repo)
    if rec is None:
        raise HTTPException(status_code=404, detail="Repo not found in sessions")
    verdict_json = json.dumps(rec["verdict_count"])
    open_qs = sum(p["open_questions"] for p in rec["prs"])
    from gh import run_gh

    pr_rows = metrics.open_prs(_session_root(), owner, repo, gh=run_gh)
    return templates.TemplateResponse(
        request, "repo.html",
        {"repo": rec, "verdict_json": verdict_json, "open_qs": open_qs,
         "pr_rows": pr_rows})
```

`web/templates/repo.html` — thay bảng Pull requests:

```html
<h2>Pull requests</h2>
<table class="table">
  <thead><tr><th>#</th><th>Title</th><th>Draft</th><th>Review status</th>
    <th>Bugs</th><th>Doc errors</th></tr></thead>
  <tbody>
  {% for p in pr_rows %}
    <tr>
      <td><a href="/repos/{{ repo.owner }}/{{ repo.repo }}/pr/{{ p.pr }}">#{{ p.pr }}</a></td>
      <td>{{ p.title }}</td>
      <td>{% if p.draft %}<span class="tag draft">DRAFT</span>{% endif %}</td>
      <td>
        {% if p.status == 'reviewed' %}
          <span class="verdict v-pass">Reviewed · {{ p.rounds }} round{{ 's' if p.rounds != 1 }}</span>
        {% elif p.status == 'reviewing' %}
          <span class="verdict v-partial">Reviewing…</span>
        {% else %}
          <span class="verdict v-unlisted">Not reviewed</span>
        {% endif %}
        {% if p.unavailable %}<span class="tag fail">open PRs unavailable</span>{% endif %}
      </td>
      {% if p.status == 'reviewed' %}
        <td>{{ p.bugs }}</td><td>{{ p.doc_errors }}</td>
      {% else %}
        <td class="muted">—</td><td class="muted">—</td>
      {% endif %}
    </tr>
  {% endfor %}
  </tbody>
</table>
```

Lưu ý: `p.bugs`/`p.doc_errors` — rows từ `open_prs` chưa có bugs/doc_errors. Sửa `open_prs` trong Task 2: thêm bugs/doc_errors cho status reviewed bằng cách gọi `pr_record`:

Trong vòng lặp gh PRs, nhánh reviewed:

```python
            rec = pr_record(session_root, owner, repo, n)
            rows.append({"pr": n, "title": p.get("title", ""),
                         "draft": bool(p.get("draft")),
                         "status": "reviewed",
                         "rounds": _read_rounds(d),
                         "bugs": rec["bugs"] if rec else 0,
                         "doc_errors": rec["doc_errors"] if rec else 0,
                         "unavailable": unavailable})
```

(và fallback branch tương tự với rec). `test_metrics.py` test `open_prs` không assert bugs nên không vỡ.

CSS — thêm tag draft:

```css
.tag.draft { background: #6b7280; color: #fff; font-size: 10px; padding: 1px 6px;
             border-radius: 8px; margin-left: 6px; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS — 12 cũ + 2 mới = 14 tests

- [ ] **Step 5: Manual smoke test**

Restart server (port 6789), mở `/repos/sample-org/sample-app`:
- #78 chore: update deps → Not reviewed
- #1 Configure Renovate → Not reviewed
- #77 Google sign-in → Reviewed · 1 round (rounds.txt mới tạo cho session cũ? — session pr-77 chưa có rounds.txt → fallback 1)
- KPI: bugs = 3, doc errors = 2 (metric mới)

- [ ] **Step 6: Commit**

```bash
git add web/ tests/test_server.py
git commit -m "feat: show open PRs with review status on repo page"
```

---

### Task 4: README + full suite

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README dashboard section**

```markdown
Pages: repo list → repo detail (KPIs + verdict donut + PR table) → PR detail
(tabs: Claims / Docs / Impact / Threads / Confirm). The PR table lists ALL open
PRs from GitHub with review status (Not reviewed / Reviewing / Reviewed N
rounds); Bugs counts FAIL + PARTIAL claims and BROKEN + RISK impacts; Doc
errors counts WRONG + FABRICATED + STALE docs.
```

- [ ] **Step 2: Run full suite**

Run: `.venv/bin/python -m pytest -v`
Expected: PASS — 84 cũ + 1 run + 6 metrics + 2 server = 93 tests (chạy thực tế xác nhận)

- [ ] **Step 3: Commit + push**

```bash
git add README.md
git commit -m "docs: document open PR table and wider metrics"
git push origin main
```

---

## Self-Review Checklist

- **Spec coverage:** rounds.txt bump on verify (T1 run.py), cached run no bump
  (T1), force bump (T1), rounds read + fallback 1 + garbage → 1 (T2), wider bugs
  (FAIL+PARTIAL, BROKEN+RISK) and doc_errors (WRONG+FABRICATED+STALE) (T2), open_prs
  merge + statuses reviewed/reviewing/not_reviewed (T2), gh failure → unavailable
  + fallback sessions (T2), sort by pr desc (T2), repo page table with Draft/
  Review status/Bugs/Doc errors (T3), KPI donut unchanged (T3), README (T4). ✅
- **Placeholders:** no TBD/TODO; complete code per step. ✅
- **Type consistency:** `open_prs(session_root, owner, repo, gh=None) -> list[dict]`
  rows `{pr, title, draft, status, rounds, bugs, doc_errors, unavailable}` —
  Task 2 produces, Task 3 template consumes (p.pr/p.title/p.draft/p.status/
  p.rounds/p.bugs/p.doc_errors/p.unavailable); `_read_rounds(session_dir) -> int`
  used in both pr_record and open_prs; `_bump_rounds(session_dir)` in run.py T1. ✅
