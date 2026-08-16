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
