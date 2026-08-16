import json

import pytest

from synthesize import build_comment, build_report, post_comment

SNAPSHOT = {
    "owner": "demo", "repo": "app", "pr": 7,
    "title": "Add checkout flow", "author": "dev1", "base": "main", "head": "x",
    "labels": ["feature"], "body": "Adds checkout.",
    "files": [{"filename": "src/checkout.py", "status": "added",
               "additions": 50, "deletions": 0, "patch": ""}],
    "commits": [{"sha": "a", "message": "feat"}],
    "threads": [{"path": "src/checkout.py", "line": 3, "author": "r1",
                 "body": "Missing validation", "resolved": False, "outdated": False}],
}

CLAIMS = [
    {"id": "C1", "text": "Adds checkout", "category": "feature",
     "files": ["src/checkout.py"], "docs": []},
]

FINDINGS = {
    "claims": [{"id": "C1", "status": "PASS", "evidence": ["src/checkout.py:1"], "note": ""}],
    "docs": [{"path": "docs/payment.md", "status": "WRONG", "what": "doc nói retry 3, code retry 5"}],
    "impact": [{"requirement": "REQ-1 checkout", "impact": "CHANGED", "detail": "luồng mới"}],
    "threads": [{"text": "Missing validation", "status": "STILL_VALID", "note": "chưa fix"}],
    "unresolved_questions": [],
}

ANSWERS = [{"question": "Doc payment sai?", "kind": "doc", "answer": "y"}]


def test_build_report_vn(tmp_path):
    report = build_report(SNAPSHOT, CLAIMS, FINDINGS, ANSWERS, tmp_path)
    assert "## Verdict" in report
    assert "ĐÚNG" in report
    assert "WRONG" in report
    assert "REQ-1" in report
    assert "chưa fix" in report
    assert (tmp_path / "report.md").exists()


def test_build_comment_en_has_marker_and_verdict():
    comment = build_comment(SNAPSHOT, CLAIMS, FINDINGS, ANSWERS)
    assert "<!-- harness-pr-review -->" in comment
    assert "PASS" in comment
    assert "docs/payment.md" in comment
    assert "STILL_VALID" in comment


def test_post_comment_skips_if_marker_exists(monkeypatch):
    existing = [{"body": "<!-- harness-pr-review --> old"}]
    calls = []
    monkeypatch.setattr("synthesize.run_gh",
                        lambda args, **kw: (existing if "GET" in args else None))
    posted = post_comment("demo", "app", 7, "new", gh=lambda args, **kw: None,
                          list_comments=lambda: existing)
    assert posted is False


def test_post_comment_posts_when_no_marker(monkeypatch):
    posted = post_comment("demo", "app", 7, "new",
                          gh=lambda args, **kw: {"id": 1},
                          list_comments=lambda: [{"body": "other"}])
    assert posted is True
