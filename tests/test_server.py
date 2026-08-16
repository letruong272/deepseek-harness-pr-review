# tests/test_server.py
import json

import pytest
from fastapi.testclient import TestClient

from autoreview_config import load_config
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


def test_repo_page(client, monkeypatch):
    monkeypatch.setattr("gh.run_gh",
                        lambda args, **kw: [{"number": 77, "title": "Google sign-in",
                                             "draft": False}])
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


def test_api_config_and_toggle(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text(
        "org: nexpeakcore\nrepos:\n  sample-app: auto\n")
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))

    def fake_gh(args, **kw):
        return [{"name": "sample-app"}, {"name": "admin-web"}]

    monkeypatch.setattr("gh.run_gh", fake_gh)

    client = TestClient(app)

    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["org"] == "nexpeakcore"
    by_name = {x["name"]: x["mode"] for x in data["repos"]}
    assert by_name["sample-app"] == "auto"
    assert by_name["admin-web"] == "unlisted"

    r = client.post("/api/config/repos/sample-app/mode",
                    json={"mode": "manual"})
    assert r.status_code == 200
    assert load_config(cfg_path)["repos"]["sample-app"] == "manual"

    r = client.post("/api/config/repos", json={"repo": "payments"})
    assert r.status_code == 200
    assert load_config(cfg_path)["repos"]["payments"] == "auto"

    r = client.delete("/api/config/repos/payments")
    assert r.status_code == 200
    assert "payments" not in load_config(cfg_path)["repos"]


def test_api_add_repo_without_org_rejects_name(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("repos:\n  sample-app: auto\n")  # no org
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    client = TestClient(app)
    r = client.post("/api/config/repos", json={"repo": "payments"})
    assert r.status_code == 400
    assert "org" in r.json()["detail"]


def test_api_toggle_bad_mode_400(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: auto\n")
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    client = TestClient(app)
    r = client.post("/api/config/repos/sample-app/mode", json={"mode": "x"})
    assert r.status_code == 400


def test_api_config_missing_file_404(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(tmp_path / "none.yml"))
    client = TestClient(app)
    assert client.get("/api/config").status_code == 404


def test_config_page_has_config_block(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: auto\n")
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setattr("gh.run_gh", lambda args, **kw: [{"name": "sample-app"}])
    client = TestClient(app)
    r = client.get("/config")
    assert r.status_code == 200
    assert "Repo configuration" in r.text
    assert "sample-app" in r.text


def test_repo_list_page_has_no_config_block(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: auto\n")
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setattr("gh.run_gh", lambda args, **kw: [{"name": "sample-app"}])
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Repo configuration" not in r.text
    assert "Config" in r.text  # navbar link


def test_repo_page_shows_open_prs(client, tmp_path, monkeypatch):
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
