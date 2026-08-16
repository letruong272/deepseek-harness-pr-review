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
    assert metrics.list_repos(tmp_path) == [("nexpeakcore", "sample-api"),
                                            ("nexpeakcore", "sample-app")]


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
    assert rec["verdict_count"] == {"ACCURATE": 0, "PARTIAL": 0,
                                    "MISLEADING": 1, "NO_CLAIMS": 1}
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
