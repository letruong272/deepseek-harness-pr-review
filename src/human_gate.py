"""Phase 4: human-in-the-loop — hỏi xác nhận khi docs sai hoặc claim chưa chắc."""
import json
from pathlib import Path


def trim_question(q: str, max_words: int = 20) -> str:
    words = q.split()
    if len(words) <= max_words:
        return q
    return " ".join(words[:max_words])


def _collect_questions(findings: dict) -> list[tuple[str, str]]:
    """Trả về [(question, kind)] — kind dùng để quyết định cách hỏi."""
    questions: list[tuple[str, str]] = []
    for d in findings.get("docs", []):
        if d["status"] in ("WRONG", "FABRICATED"):
            q = trim_question(f"Doc {d['path']}: {d['what']}. Doc sai, phải không?")
            questions.append((q, "doc"))
    for c in findings.get("claims", []):
        if c["status"] == "UNVERIFIED":
            q = trim_question(f"Claim {c['id']} không xác minh được. Giữ UNVERIFIED?")
            questions.append((q, "claim"))
    for q in findings.get("unresolved_questions", []):
        questions.append((trim_question(q), "free"))
    return questions


def run_gate(findings: dict, session_dir: Path, interactive: bool = True) -> list[dict]:
    """Hỏi từng câu (≤20 chữ). Lưu answers.json. Trả về list câu trả lời."""
    answers: list[dict] = []
    for question, kind in _collect_questions(findings):
        if interactive:
            answer = input(f"[harness] {question} (y/n hoặc trả lời tự do): ").strip()
        else:
            answer = "SKIPPED"
        answers.append({"question": question, "kind": kind, "answer": answer})

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "answers.json").write_text(json.dumps(answers, indent=2))
    return answers
