import json

import pytest

from human_gate import run_gate, trim_question


def test_trim_question_limits_words():
    q = "This is a very long question " * 10
    assert len(trim_question(q, max_words=20).split()) == 20


def test_trim_question_keeps_short():
    q = "Doc sai, phải không?"
    assert trim_question(q) == q


def test_run_gate_writes_answers(tmp_path, monkeypatch):
    findings = {
        "claims": [{"id": "C1", "status": "UNVERIFIED", "evidence": [], "note": ""}],
        "docs": [{"path": "docs/a.md", "status": "WRONG",
                  "what": "doc nói X, code làm Y"}],
        "impact": [], "threads": [],
        "unresolved_questions": ["Doc A đúng không?"],
    }
    monkeypatch.setattr("builtins.input",
                        lambda prompt: "y" if "sai doc" in prompt or "Doc A" in prompt else "n")
    session_dir = tmp_path / "s"
    answers = run_gate(findings, session_dir)
    assert len(answers) == 3
    assert all(a["answer"] for a in answers)
    saved = json.loads((session_dir / "answers.json").read_text())
    assert len(saved) == 3
