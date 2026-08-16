import json
import subprocess

import pytest

from verify import build_verify_prompt, parse_findings, setup_workspace


def test_setup_workspace_clones_and_checks_out(tmp_path):
    # Create a local "remote" repo with a pull/7/head branch
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=origin, check=True)
    (origin / "app.py").write_text("print('base')\n")
    subprocess.run(["git", "add", "."], cwd=origin, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "base"], cwd=origin, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "pull/7/head"], cwd=origin, check=True)
    (origin / "app.py").write_text("print('feature')\n")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qam", "feat"], cwd=origin, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=origin, check=True)

    ws = tmp_path / "ws"
    setup_workspace("demo", "app", 7, ws, remote_url=str(origin))

    assert (ws / "app.py").read_text() == "print('feature')\n"


def test_setup_workspace_rerun_existing_checkout(tmp_path):
    # Workspace đã tồn tại + branch pr-7 đang checkout → re-review phải thành công
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=origin, check=True)
    (origin / "app.py").write_text("print('base')\n")
    subprocess.run(["git", "add", "."], cwd=origin, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "base"], cwd=origin, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "pull/7/head"], cwd=origin, check=True)
    (origin / "app.py").write_text("print('feature')\n")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qam", "feat"], cwd=origin, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=origin, check=True)

    ws = tmp_path / "ws"
    setup_workspace("demo", "app", 7, ws, remote_url=str(origin))  # lần 1
    assert (ws / "app.py").read_text() == "print('feature')\n"

    # push thêm commit mới lên nhánh PR rồi re-run
    subprocess.run(["git", "checkout", "-q", "pull/7/head"], cwd=origin, check=True)
    (origin / "app.py").write_text("print('feature v2')\n")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qam", "feat2"], cwd=origin, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=origin, check=True)

    setup_workspace("demo", "app", 7, ws, remote_url=str(origin))  # re-review
    assert (ws / "app.py").read_text() == "print('feature v2')\n"


def test_parse_findings_ok(tmp_path):
    f = tmp_path / "findings.json"
    f.write_text(json.dumps({"claims": [{"id": "C1", "status": "PASS",
                                          "evidence": ["a.py:1"], "note": ""}],
                             "docs": [], "impact": [], "threads": [],
                             "unresolved_questions": []}))
    parsed = parse_findings(f)
    assert parsed["claims"][0]["status"] == "PASS"


def test_parse_findings_invalid(tmp_path):
    f = tmp_path / "findings.json"
    f.write_text("garbage")
    with pytest.raises(RuntimeError, match="invalid findings"):
        parse_findings(f)


def test_parse_findings_missing(tmp_path):
    f = tmp_path / "findings.json"
    with pytest.raises(RuntimeError, match="does not exist"):
        parse_findings(f)


def test_build_verify_prompt_contains_parts():
    snapshot = {"title": "T", "body": "B", "files": [{"filename": "a.py"}],
                "threads": [{"body": "c1", "resolved": False}], "commits": []}
    claims = [{"id": "C1", "text": "x", "category": "feature", "files": [], "docs": []}]
    prompt = build_verify_prompt(snapshot, claims)
    assert "findings.json" in prompt
    assert "C1" in prompt
    assert "FABRICATED" in prompt
    assert "UNVERIFIED" in prompt
