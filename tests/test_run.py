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
