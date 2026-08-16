import json

from run import main

FIXTURES = {
    "snapshot.json": {
        "owner": "demo", "repo": "app", "pr": 7, "title": "T",
        "body": "B", "author": "a", "base": "main", "head": "x",
        "labels": [], "files": [], "commits": [], "threads": [],
    },
    "claims.json": [],
    "findings.json": {
        "claims": [], "docs": [], "impact": [], "threads": [],
        "unresolved_questions": [],
    },
}


def test_main_fixtures_mode(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for name, data in FIXTURES.items():
        (fixtures / name).write_text(json.dumps(data))
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))

    code = main(["demo/app", "7", "--fixtures", str(fixtures), "--no-post"])
    assert code == 0
    report = tmp_path / "sessions" / "demo" / "app" / "pr-7" / "report.md"
    assert report.exists()


def test_main_requires_gh(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("run.gh_available", lambda: False)
    code = main(["demo/app", "7", "--no-post"])
    assert code == 2


def test_main_owner_repo_hash_parsing(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for name, data in FIXTURES.items():
        (fixtures / name).write_text(json.dumps(data))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    code = main(["demo/app#7", "--fixtures", str(fixtures), "--no-post"])
    assert code == 0
    assert (tmp_path / "sessions" / "demo" / "app" / "pr-7" / "report.md").exists()


def test_rerun_skips_verify(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setattr("run.gh_available", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    calls = {"verify": 0}
    fake_snapshot = {"owner": "demo", "repo": "app", "pr": 7, "title": "T",
                     "body": "B", "author": "a", "base": "main", "head": "x",
                     "labels": [], "files": [], "commits": [], "threads": []}
    fake_claims = []
    fake_findings = {"claims": [], "docs": [], "impact": [], "threads": [],
                     "unresolved_questions": []}
    fake_setup_calls = []

    def fake_build_snapshot(owner, repo, n, session_dir, gh=None):
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "snapshot.json").write_text(json.dumps(fake_snapshot))
        return fake_snapshot

    def fake_extract_claims(snapshot, cfg, session_dir, chat=None):
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "claims.json").write_text(json.dumps(fake_claims))
        return fake_claims

    def fake_setup_workspace(owner, repo, n, workspace, remote_url=None):
        fake_setup_calls.append(1)

    def fake_run_verify(cfg, workspace, session_dir, snapshot, claims):
        calls["verify"] += 1
        return fake_findings

    monkeypatch.setattr("snapshot.build_snapshot", fake_build_snapshot)
    monkeypatch.setattr("claims.extract_claims", fake_extract_claims)
    monkeypatch.setattr("run.setup_workspace", fake_setup_workspace)
    monkeypatch.setattr("run.run_verify", fake_run_verify)

    code1 = main(["demo/app", "7", "--no-post"])
    assert code1 == 0
    assert calls["verify"] == 1
    assert len(fake_setup_calls) == 1
    assert (tmp_path / "sessions" / "demo" / "app" / "pr-7" / "findings.json").exists()

    code2 = main(["demo/app", "7", "--no-post"])
    assert code2 == 0
    assert calls["verify"] == 1
    assert len(fake_setup_calls) == 1
