# tests/test_autoreview.py
import json

from autoreview import decide_pr, plan_reviews

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
    _write_session(root, "o", "r", 5)  # findings.json rỗng, snapshot.json không tồn tại
    assert decide_pr(root, "o", "r", 5, "xyz") == "NEW"


def test_plan_reviews_skips_drafts(tmp_path):
    root = tmp_path / "sessions"
    prs = [
        {"number": 1, "head": {"sha": "a"}, "draft": True},
        {"number": 2, "head": {"sha": "b"}, "draft": False},
    ]
    plans = plan_reviews(root, "o", "r", prs, drafts=False)
    assert plans == [{"pr": 2, "head_sha": "b", "decision": "NEW"}]


def test_plan_reviews_statuses(tmp_path):
    root = tmp_path / "sessions"
    # pr-1 đã review với head_sha=a; pr-3 đã review với head_sha=old
    _write_session(root, "o", "r", 1, snapshot={**SNAPSHOT, "pr": 1,
                                                "head_sha": "a"})
    _write_session(root, "o", "r", 3, snapshot={**SNAPSHOT, "pr": 3,
                                                "head_sha": "old"})
    prs = [
        {"number": 1, "head": {"sha": "a"}, "draft": False},   # SKIP
        {"number": 2, "head": {"sha": "c"}, "draft": False},   # NEW
        {"number": 3, "head": {"sha": "b"}, "draft": False},   # RE-RUN
    ]
    plans = plan_reviews(root, "o", "r", prs, drafts=False)
    assert plans == [
        {"pr": 1, "head_sha": "a", "decision": "SKIP"},
        {"pr": 2, "head_sha": "c", "decision": "NEW"},
        {"pr": 3, "head_sha": "b", "decision": "RE-RUN"},
    ]
