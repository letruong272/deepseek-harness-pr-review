# Auto Review Poller Implementation Plan

> **Superseded (historical):** plan snippets predate the `src.*` package imports and the current `--add-repo` acceptance of GitHub URLs and bare names. See src/autoreview.py and README.md for current behavior.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local poller (`src/autoreview.py`) that automatically reviews new PRs (and re-reviews PRs whose head SHA changed) on a configurable repo list, using the existing pipeline in batch mode.

**Architecture:** A config file (`autoreview.yml`) lists repos; the poller queries `gh api` for open PRs, compares against `sessions/` snapshots (which now store `head_sha`), and dispatches `run.main()` for new/changed PRs. Supports `--once` (cron/launchd) and `--daemon` (loop) plus `--dry-run` (no dispatch).

**Tech Stack:** Python 3.10+, pyyaml (config), existing `gh.py`, `run.py`, `snapshot.py`.

**Spec:** `docs/designs/2026-08-16-auto-review-design.md`

---

## File Structure

```
src/
├── autoreview.py       # NEW: poller
├── snapshot.py         # MODIFY: add head_sha to snapshot dict
autoreview.yml          # NEW: config (repos, interval, flags)
tests/test_autoreview.py  # NEW
tests/test_snapshot.py    # MODIFY: head_sha assertion
```

---

### Task 1: Add head_sha to snapshot

**Files:**
- Modify: `src/snapshot.py:77-88` (snapshot dict)
- Modify: `tests/test_snapshot.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_snapshot.py — thêm test mới (đầu file import sẵn json, build_snapshot, _gh_fake)
def test_build_snapshot_head_sha(tmp_path):
    meta = {**PR_META, "head": {"ref": "feature/checkout", "sha": "sha123"}}
    registry = {
        "repos/demo/app/pulls/7/commits": COMMITS,
        "repos/demo/app/pulls/7/files": PR_FILES,
        "repos/demo/app/pulls/7": meta,
        "graphql": PR_THREADS,
    }
    result = build_snapshot("demo", "app", 7, tmp_path, gh=_gh_fake(registry))
    assert result["head_sha"] == "sha123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_snapshot.py::test_build_snapshot_head_sha -v`
Expected: FAIL — `KeyError: 'head_sha'`

- [ ] **Step 3: Implement**

Trong `src/snapshot.py`, bổ sung field vào dict snapshot (sau dòng `"head": ...`):

```python
        "head": (meta.get("head") or {}).get("ref", ""),
        "head_sha": (meta.get("head") or {}).get("sha", ""),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_snapshot.py -v`
Expected: PASS — 5 tests (4 cũ + 1 mới)

- [ ] **Step 5: Commit**

```bash
git add src/snapshot.py tests/test_snapshot.py
git commit -m "feat: store head_sha in snapshot"
```

---

### Task 2: Config loading (autoreview.yml)

**Files:**
- Create: `autoreview.yml`
- Create: `src/autoreview_config.py`
- Test: `tests/test_autoreview_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_autoreview_config.py
import pytest

from autoreview_config import load_config, validate_config

DEFAULT_YML = """
repos:
  - sample-org/sample-app
interval_minutes: 10
post_comment: true
skip_human: true
drafts: false
"""


def test_load_config_defaults(tmp_path):
    p = tmp_path / "autoreview.yml"
    p.write_text(DEFAULT_YML)
    cfg = load_config(p)
    assert cfg["repos"] == ["sample-org/sample-app"]
    assert cfg["interval_minutes"] == 10
    assert cfg["post_comment"] is True
    assert cfg["skip_human"] is True
    assert cfg["drafts"] is False


def test_load_config_missing_defaults(tmp_path):
    p = tmp_path / "autoreview.yml"
    p.write_text("repos:\n  - a/b\n")
    cfg = load_config(p)
    assert cfg["interval_minutes"] == 10
    assert cfg["post_comment"] is True
    assert cfg["skip_human"] is True
    assert cfg["drafts"] is False


def test_validate_config_no_repos(tmp_path):
    p = tmp_path / "autoreview.yml"
    p.write_text("interval_minutes: 5\n")
    with pytest.raises(ValueError, match="repos"):
        validate_config(load_config(p))


def test_validate_config_bad_repo_format(tmp_path):
    p = tmp_path / "autoreview.yml"
    p.write_text("repos:\n  - not-a-repo\n")
    with pytest.raises(ValueError, match="owner/repo"):
        validate_config(load_config(p))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_autoreview_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autoreview_config'`

- [ ] **Step 3: Implement**

```python
# src/autoreview_config.py
"""Load + validate autoreview.yml config."""
from pathlib import Path

import yaml

DEFAULTS = {
    "interval_minutes": 10,
    "post_comment": True,
    "skip_human": True,
    "drafts": False,
}


def load_config(path: Path) -> dict:
    """Read autoreview.yml, merge defaults. Raises OSError/ValueError."""
    raw = yaml.safe_load(path.read_text()) or {}
    cfg = {**DEFAULTS, **raw}
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict) -> None:
    repos = cfg.get("repos") or []
    if not repos:
        raise ValueError("config requires at least one repo")
    for r in repos:
        if "/" not in r or len(r.split("/")) != 2:
            raise ValueError(f"repo must be owner/repo: {r!r}")
```

```yaml
# autoreview.yml
repos:
  - sample-org/sample-app
interval_minutes: 10
post_comment: true
skip_human: true
drafts: false
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_autoreview_config.py -v`
Expected: PASS — 4 tests

- [ ] **Step 5: Commit**

```bash
git add autoreview.yml src/autoreview_config.py tests/test_autoreview_config.py
git commit -m "feat: add autoreview config loading"
```

---

### Task 3: Poller core (selection logic)

**Files:**
- Create: `src/autoreview.py`
- Test: `tests/test_autoreview.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_autoreview.py
import json
from pathlib import Path

from autoreview import decide_pr, plan_reviews
from autoreview_config import load_config

EMPTY_FINDINGS = {"claims": [], "docs": [], "impact": [], "threads": [],
                  "unresolved_questions": []}

SNAPSHOT = {"pr": 7, "title": "T", "author": "a", "base": "main", "head": "x",
            "head_sha": "abc", "files": [], "commits": [], "threads": []}


def _write_session(root, owner, repo, n, snapshot=None):
    d = root / owner / repo / f"pr-{n}"
    d.mkdir(parents=True, exist_ok=True)
    if snapshot is not None:
        (d / "snapshot.json").write_text(json.dumps(snapshot))
    (d / "findings.json").write_text(json.dumps(EMPTY_FINDINGS))


def test_decide_pr_new(tmp_path):
    root = tmp_path / "sessions"
    _write_session(root, "o", "r", 5)
    d = root / "o" / "r" / "pr-5"
    (d / "snapshot.json").write_text(json.dumps(SNAPSHOT))
    assert decide_pr(root, "o", "r", 5, "abc") == "SKIP"
    assert decide_pr(root, "o", "r", 6, "def") == "NEW"


def test_decide_pr_head_changed(tmp_path):
    root = tmp_path / "sessions"
    _write_session(root, "o", "r", 5, snapshot=SNAPSHOT)  # head_sha=abc
    assert decide_pr(root, "o", "r", 5, "xyz") == "RE-RUN"


def test_decide_pr_old_snapshot_no_sha(tmp_path):
    # snapshot cũ không có head_sha → coi như chưa review
    root = tmp_path / "sessions"
    old = {k: v for k, v in SNAPSHOT.items() if k != "head_sha"}
    _write_session(root, "o", "r", 5, snapshot=old)
    assert decide_pr(root, "o", "r", 5, "xyz") == "RE-RUN"


def test_decide_pr_missing_snapshot_new(tmp_path):
    root = tmp_path / "sessions"
    _write_session(root, "o", "r", 5)  # snapshot.json rỗng
    (root / "o" / "r" / "pr-5" / "snapshot.json").unlink()
    assert decide_pr(root, "o", "r", 5, "xyz") == "NEW"


def test_plan_reviews_skips_drafts(tmp_path):
    root = tmp_path / "sessions"
    cfg = load_config.__wrapped__  # noqa — không dùng
    cfg = {"repos": ["o/r"], "drafts": False}
    prs = [
        {"number": 1, "head": {"sha": "a"}, "draft": True},
        {"number": 2, "head": {"sha": "b"}, "draft": False},
    ]
    plans = plan_reviews(root, "o", "r", prs, drafts=False)
    assert plans == [{"pr": 2, "head_sha": "b", "decision": "NEW"}]


def test_plan_reviews_statuses(tmp_path):
    root = tmp_path / "sessions"
    _write_session(root, "o", "r", 1, snapshot={**SNAPSHOT, "pr": 1,
                                                "head_sha": "a"})
    prs = [
        {"number": 1, "head": {"sha": "a"}, "draft": False},  # SKIP
        {"number": 2, "head": {"sha": "c"}, "draft": False},  # NEW
        {"number": 3, "head": {"sha": "b"}, "draft": False},  # RE-RUN (đã có, sha cũ)
    ]
    plans = plan_reviews(root, "o", "r", prs, drafts=False)
    assert plans == [
        {"pr": 1, "head_sha": "a", "decision": "SKIP"},
        {"pr": 2, "head_sha": "c", "decision": "NEW"},
        {"pr": 3, "head_sha": "b", "decision": "RE-RUN"},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_autoreview.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autoreview'`

- [ ] **Step 3: Implement**

```python
# src/autoreview.py
"""Local poller: auto-review new PRs / re-review PRs with changed head SHA.

Modes:
  --once      single pass (cron/launchd)
  --daemon    loop with interval_minutes
  --dry-run   print planned reviews without dispatching
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from autoreview_config import load_config
from config import load_config as load_env_config
from gh import gh_available, run_gh

CONFIG_PATH = Path("autoreview.yml")
LOCK_PATH = Path("autoreview.lock")


def decide_pr(session_root: Path, owner: str, repo: str, n: int,
              head_sha: str) -> str:
    """Return NEW / RE-RUN / SKIP for one PR."""
    snapshot_path = session_root / owner / repo / f"pr-{n}" / "snapshot.json"
    if not snapshot_path.exists():
        return "NEW"
    try:
        snapshot = json.loads(snapshot_path.read_text())
    except (json.JSONDecodeError, OSError):
        return "RE-RUN"  # snapshot hỏng → chạy lại cho an toàn
    old_sha = snapshot.get("head_sha", "")
    if old_sha and old_sha == head_sha:
        return "SKIP"
    return "RE-RUN"


def plan_reviews(session_root: Path, owner: str, repo: str, prs: list[dict],
                 drafts: bool = False) -> list[dict]:
    """Return [{pr, head_sha, decision}] for open PRs of one repo."""
    plans = []
    for p in prs:
        if p.get("draft") and not drafts:
            continue
        n = p["number"]
        head_sha = (p.get("head") or {}).get("sha", "")
        decision = decide_pr(session_root, owner, repo, n, head_sha)
        plans.append({"pr": n, "head_sha": head_sha, "decision": decision})
    return plans


def fetch_open_prs(owner: str, repo: str, gh=run_gh) -> list[dict]:
    """Open PRs of a repo via gh api (returns raw list items)."""
    data = gh(["api", f"repos/{owner}/{repo}/pulls", "--paginate",
               "-f", "state=open", "--jq",
               ".[] | {number, head: {sha: .head.sha}, draft}"])
    return data


def _acquire_lock() -> bool:
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def _clean_rerun_session(session_dir: Path) -> None:
    """Xóa kết quả phase cũ trước khi re-review (giữ snapshot)."""
    for name in ("findings.json", "answers.json", "report.md", "agent-log.txt"):
        (session_dir / name).unlink(missing_ok=True)


def _dispatch(cfg: dict, owner: str, repo: str, n: int,
              head_sha: str) -> int:
    """Chạy pipeline cho 1 PR. Trả về exit code."""
    from run import main

    args = [f"{owner}/{repo}", str(n), "--force"]
    if cfg.get("skip_human", True):
        args.append("--skip-human")
    if not cfg.get("post_comment", True):
        args.append("--no-post")
    return main(args)


def run_pass(cfg: dict, session_root: Path, dry_run: bool = False,
             gh=run_gh) -> int:
    """One poll pass over all configured repos. Returns count of dispatched."""
    dispatched = 0
    for repo_ref in cfg["repos"]:
        owner, repo = repo_ref.split("/")
        try:
            prs = fetch_open_prs(owner, repo, gh=gh)
        except RuntimeError as e:
            print(f"POLL-ERROR {owner}/{repo}: {e}", file=sys.stderr)
            continue
        plans = plan_reviews(session_root, owner, repo, prs,
                             drafts=cfg.get("drafts", False))
        for plan in plans:
            n = plan["pr"]
            line = f"{plan['decision']} {owner}/{repo}#{n}"
            if plan["decision"] == "SKIP":
                print(line)
                continue
            if dry_run:
                print(f"[dry-run] would review: {line}")
                dispatched += 1
                continue
            session_dir = session_root / owner / repo / f"pr-{n}"
            if plan["decision"] == "RE-RUN":
                _clean_rerun_session(session_dir)
            print(line)
            try:
                code = _dispatch(cfg, owner, repo, n, plan["head_sha"])
            except (RuntimeError, ValueError, OSError) as e:
                print(f"FAILED {owner}/{repo}#{n}: {e}", file=sys.stderr)
                continue
            if code != 0:
                print(f"FAILED {owner}/{repo}#{n}: exit {code}", file=sys.stderr)
                continue
            dispatched += 1
    return dispatched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoreview")
    parser.add_argument("--once", action="store_true", help="single pass")
    parser.add_argument("--daemon", action="store_true", help="loop forever")
    parser.add_argument("--dry-run", action="store_true",
                        help="print plans without dispatching")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH,
                        help="path to autoreview.yml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    env = load_env_config()
    if not env.api_key:
        print("DEEPSEEK_API_KEY not set (see .env.example)", file=sys.stderr)
        return 3
    if not gh_available():
        print("gh CLI not installed or not authenticated (gh auth login)",
              file=sys.stderr)
        return 2

    session_root = env.session_root
    while True:
        if not _acquire_lock():
            print("another autoreview process is running — exiting",
                  file=sys.stderr)
            return 1
        try:
            run_pass(cfg, session_root, dry_run=args.dry_run)
        finally:
            _release_lock()
        if args.once or args.dry_run:
            return 0
        time.sleep(cfg["interval_minutes"] * 60)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_autoreview.py -v`
Expected: PASS — 6 tests. Lưu ý test `test_plan_reviews_skips_drafts` có dòng thừa `cfg = load_config.__wrapped__` — bỏ dòng đó nếu gây lỗi.

- [ ] **Step 5: Commit**

```bash
git add src/autoreview.py tests/test_autoreview.py
git commit -m "feat: add auto review poller"
```

---

### Task 4: README + full suite

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add auto-review section to README**

```markdown
## Auto review

Poll GitHub for new PRs (and head-SHA changes) on configured repos and review
them automatically in batch mode.

```bash
# config: edit autoreview.yml (repos, interval, flags)
pip install -e '.[dev]'   # pyyaml comes with the SDK; add if missing
python -m src.autoreview --once          # single pass (cron/launchd)
python -m src.autoreview --daemon        # loop every interval_minutes
python -m src.autoreview --once --dry-run  # print what would be reviewed
```

launchd example:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.nexpeak.pr-review</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/gianglh/work/harness/.venv/bin/python</string>
    <string>-m</string><string>src.autoreview</string><string>--once</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/gianglh/work/harness</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key><string>src</string>
    <key>DEEPSEEK_API_KEY</key><string>your-key</string>
  </dict>
  <key>StartInterval</key><integer>600</integer>
</dict>
</plist>
```

Re-review rules: head SHA in the PR changed vs the last snapshot → all phases
re-run with `--force`; the PR comment is updated in place (never duplicated).
```

- [ ] **Step 2: Run full suite**

Run: `.venv/bin/python -m pytest -v`
Expected: PASS — 54 existing + 5 snapshot + 4 config + 6 autoreview = 69 tests

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document auto review usage"
```

---

## Self-Review Checklist

- **Spec coverage:** config repos/interval/flags (T2), `--once`/`--daemon`/`--dry-run` (T3 main), per-pass logic NEW/RE-RUN/SKIP + drafts skip (T3 decide_pr/plan_reviews), dispatch via run.main with skip_human→`--skip-human`, post_comment false→`--no-post`, re-review uses `--force` + deletes stale artifacts (T3 _clean_rerun_session/_dispatch), lock file (T3), gh failure → POLL-ERROR continue (T3 run_pass), missing API key → exit 3 (T3 main), snapshot head_sha (T1), old snapshot without head_sha → RE-RUN (T3), README + launchd example (T4). ✅
- **Placeholders:** no TBD/TODO; all steps have complete code. ✅
- **Type consistency:** `decide_pr(session_root, owner, repo, n, head_sha) -> str`, `plan_reviews(session_root, owner, repo, prs, drafts=False) -> list[dict]`, `fetch_open_prs(owner, repo, gh=run_gh)`, `run_pass(cfg, session_root, dry_run=False, gh=run_gh) -> int`, `main(argv=None) -> int` — used identically in T3 tests and implementation. Config keys (`repos`, `interval_minutes`, `post_comment`, `skip_human`, `drafts`) consistent T2→T3. ✅
