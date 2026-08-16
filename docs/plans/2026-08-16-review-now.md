# Review Now Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Review now" / "Re-review" button per open PR on the repo page that triggers a synchronous review via the existing pipeline, using the repo's auto-review config.

**Architecture:** A new `POST /api/repos/{owner}/{repo}/pr/{n}/review` route in `web/server.py` builds run.py args from `autoreview.yml` (skip_human/post_comment), guards concurrency with a lock file, and calls `run.main(args)`. `repo.html` renders the button per PR row; JS disables it while running and reloads on completion.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2 (all installed).

**Spec:** `docs/designs/2026-08-16-review-now-design.md`

---

## File Structure

```
web/server.py              # MODIFY: /api/.../review route + lock helpers
web/templates/repo.html    # MODIFY: Review now / Re-review button + JS
web/static/style.css       # MODIFY: .btn-review style
tests/test_server.py       # MODIFY: review API tests
README.md                  # MODIFY: mention trigger button
```

---

### Task 1: Review trigger API

**Files:**
- Modify: `web/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server.py — thêm vào cuối file
def test_trigger_review_ok(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: auto\n")
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    calls = []

    def fake_main(argv):
        calls.append(argv)
        return 0

    monkeypatch.setattr("server.run_main", fake_main)
    client = TestClient(app)
    r = client.post("/api/repos/sample-org/sample-app/pr/78/review")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    args = calls[0]
    assert "sample-org/sample-app" in args and "78" in args
    assert "--force" in args
    assert "--skip-human" in args       # config mặc định skip_human: true
    assert "--no-post" not in args      # config mặc định post_comment: true


def test_trigger_review_no_post_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: auto\n"
                        "post_comment: false\nskip_human: false\n")
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    calls = []

    def fake_main(argv):
        calls.append(argv)
        return 0

    monkeypatch.setattr("server.run_main", fake_main)
    client = TestClient(app)
    r = client.post("/api/repos/sample-org/sample-app/pr/78/review")
    assert r.status_code == 200
    assert "--no-post" in calls[0]
    assert "--skip-human" not in calls[0]


def test_trigger_review_missing_key(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: auto\n")
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    monkeypatch.setattr("server.run_main", lambda argv: 3)  # thiếu API key
    client = TestClient(app)
    r = client.post("/api/repos/sample-org/sample-app/pr/78/review")
    assert r.status_code == 400
    assert "DEEPSEEK_API_KEY" in r.json()["detail"]


def test_trigger_review_error_500(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: auto\n")
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    monkeypatch.setattr("server.run_main", lambda argv: 2)  # gh lỗi
    client = TestClient(app)
    r = client.post("/api/repos/sample-org/sample-app/pr/78/review")
    assert r.status_code == 500
    assert "review failed" in r.json()["detail"]


def test_trigger_review_concurrent_409(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: auto\n")
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setattr("server.run_main", lambda argv: 0)
    lock = tmp_path / "sessions" / "nexpeakcore" / "sample-app" / "pr-78" \
        / "review.lock"
    lock.parent.mkdir(parents=True)
    lock.touch()
    client = TestClient(app)
    r = client.post("/api/repos/sample-org/sample-app/pr/78/review")
    assert r.status_code == 409
    assert "already running" in r.json()["detail"]
```

Lưu ý: test mock `server.run_main` — server phải import `main as run_main` từ run module (module-level hoặc trong hàm). Plan chọn import trong hàm (`from run import main as run_main`) để không kéo nặng — khi đó patch phải là `run.run_main`? Không — import trong hàm resolve `run.run_main` tại call time. Nếu test patch `server.run_main` thì cần server.py có attribute. Để đơn giản: **import module-level** trong server.py: `from run import main as run_main` — khi đó patch `server.run_main` hoạt động. `run.py` import SDK trễ (trong run_verify) nên module-level import run an toàn.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py::test_trigger_review_ok -v`
Expected: FAIL — 404 (route chưa có)

- [ ] **Step 3: Implement**

`web/server.py`:

1. Thêm import (đầu file, sau `from web import metrics`):

```python
from run import main as run_main
```

2. Thêm helper lock + route (trước `if __name__ == "__main__":`):

```python
def _review_lock_path(session_root: Path, owner: str, repo: str, n: int) -> Path:
    return session_root / owner / repo / f"pr-{n}" / "review.lock"


@app.post("/api/repos/{owner}/{repo}/pr/{pr}/review")
def trigger_review(owner: str, repo: str, pr: int):
    """Run a review synchronously using the repo's autoreview config."""
    cfg_path = _config_path()
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="autoreview.yml not found")
    try:
        cfg = load_autoreview_config(cfg_path)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"invalid config: {e}")

    env = load_config()
    if not env.api_key:
        raise HTTPException(status_code=400,
                            detail="DEEPSEEK_API_KEY not set (see .env.example)")

    lock = _review_lock_path(_session_root(), owner, repo, pr)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock.touch(exist_ok=False)
    except FileExistsError:
        raise HTTPException(status_code=409,
                            detail=f"review already running for #{pr}")
    try:
        args = [f"{owner}/{repo}", str(pr), "--force"]
        if cfg.get("skip_human", True):
            args.append("--skip-human")
        if not cfg.get("post_comment", True):
            args.append("--no-post")
        exit_code = run_main(args)
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass

    if exit_code != 0:
        raise HTTPException(
            status_code=500,
            detail=f"review failed (exit {exit_code}): "
                   f"check server log / sessions/{owner}/{repo}/pr-{pr}/report.md")
    return {"ok": True, "exit": exit_code,
            "report": f"sessions/{owner}/{repo}/pr-{pr}/report.md"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS — 14 cũ + 5 mới = 19 tests

- [ ] **Step 5: Commit**

```bash
git add web/server.py tests/test_server.py
git commit -m "feat: add synchronous review trigger API"
```

---

### Task 2: Button + JS + README

**Files:**
- Modify: `web/templates/repo.html`
- Modify: `web/static/style.css`
- Modify: `README.md`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py — thêm vào cuối
def test_repo_page_has_review_buttons(client, monkeypatch):
    monkeypatch.setattr("gh.run_gh",
                        lambda args, **kw: [
                            {"number": 78, "title": "chore: update deps",
                             "draft": False}])
    resp = client.get("/repos/sample-org/sample-app")
    assert resp.status_code == 200
    assert "Review now" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py::test_repo_page_has_review_buttons -v`
Expected: FAIL — "Review now" chưa có trong HTML

- [ ] **Step 3: Implement**

`web/templates/repo.html` — thêm cột Actions + button trong vòng lặp PR rows (sau cột Doc errors):

```html
      {% if p.status == 'reviewed' %}
        <td>{{ p.bugs }}</td><td>{{ p.doc_errors }}</td>
      {% else %}
        <td class="muted">—</td><td class="muted">—</td>
      {% endif %}
      <td>
        <button class="tab-btn review-btn" data-pr="{{ p.pr }}"
                onclick="triggerReview({{ p.pr }}, this)">
          {% if p.status == 'reviewed' %}Re-review{% else %}Review now{% endif %}
        </button>
      </td>
    </tr>
  {% endfor %}
```

Cập nhật thead:

```html
  <thead><tr><th>#</th><th>Title</th><th>Draft</th><th>Review status</th>
    <th>Bugs</th><th>Doc errors</th><th>Actions</th></tr></thead>
```

Thêm JS cuối template (sau `{% endblock %}` block content — bên trong block):

```html
<script>
async function triggerReview(pr, btn) {
  if (btn.disabled) return;
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "Running…";
  try {
    const r = await fetch(`/api/repos/{{ repo.owner }}/{{ repo.repo }}/pr/${pr}/review`,
                          {method: "POST"});
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      alert(data.detail || "review failed");
      btn.textContent = original;
      btn.disabled = false;
      return;
    }
    location.reload();
  } catch (e) {
    alert("network error: " + e);
    btn.textContent = original;
    btn.disabled = false;
  }
}
</script>
```

`web/static/style.css`:

```css
.review-btn { border: 1px solid var(--accent, #4dabf7); color: #1a73e8;
              background: #fff; }
.review-btn:disabled { opacity: .5; cursor: wait; }
```

`README.md` — trong Web dashboard section, thêm dòng:

```markdown
Each open PR row has a **Review now** / **Re-review** button that runs the
review synchronously using the repo's auto-review config (skip-human +
post-comment flags from `autoreview.yml`).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS — 19 cũ + 1 mới = 20 tests

- [ ] **Step 5: Manual smoke test**

Restart server (port 6789), mở `/repos/sample-org/sample-app`:
- #78 → button "Review now"; #77 closed nên không có
- Bấm "Review now" trên #78 → button "Running…" → đợi agent xong (2-5 phút)
  → trang reload → "Reviewed · 1 round" + rounds.txt tạo; nếu post_comment
  true → comment update trên PR #78

- [ ] **Step 6: Full suite + commit + push**

```bash
.venv/bin/python -m pytest -q
git add web/ README.md tests/test_server.py
git commit -m "feat: add review trigger button to repo page"
git push origin main
```

---

## Self-Review Checklist

- **Spec coverage:** POST route synchronous (T1), args from autoreview.yml
  skip_human→--skip-human, post_comment false→--no-post (T1), always --force
  (T1), return ok/exit/report (T1), 400 missing key + gh (T1 exit 3/2 → 400/500),
  500 with stderr note (T1), 409 lock review.lock (T1), buttons per status
  Review now/Re-review + disabled running (T2), JS fetch + reload (T2), README
  (T2). ✅
- **Placeholders:** no TBD/TODO; complete code per step. ✅
- **Type consistency:** route path `/api/repos/{owner}/{repo}/pr/{pr}/review`
  matches JS fetch template; `run_main(argv) -> int` from run.main; lock path
  `session_root/owner/repo/pr-{n}/review.lock` consistent between helper and
  tests; button data-pr + onclick triggerReview(pr, this). ✅
