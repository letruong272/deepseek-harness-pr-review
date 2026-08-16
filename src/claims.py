"""Phase 2: split the PR description into verifiable claims (LLM)."""
import json
import re
from pathlib import Path

from src.llm import chat as _default_chat

SCHEMA_HINT = """
Split the PR description below into verifiable claims (each claim must be
verifiable by reading the code). Return a JSON array matching this schema:
[{"id": "C1", "text": "<brief>", "category": "feature|bugfix|refactor|perf|ux|docs",
  "files": ["<related files, empty if unknown>"], "docs": ["<docs this claim mentions>"]}]
Do not add any text outside the JSON. If there are no claims, return [].
"""


def _parse_claims(raw: str) -> list[dict]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("claims response must be a list")
    for c in data:
        if not isinstance(c, dict) or "id" not in c:
            raise ValueError(f"claim has invalid schema (missing id): {c}")
        if "text" not in c or "category" not in c:
            raise ValueError(f"claim has invalid schema (missing text/category): {c}")
        if c["category"] not in ("feature", "bugfix", "refactor", "perf", "ux", "docs"):
            raise ValueError(f"invalid category: {c.get('category')}")
    return data


def extract_claims(snapshot: dict, cfg: dict, session_dir: Path,
                   chat=_default_chat) -> list[dict]:
    """Extract claims from the snapshot body. Save claims.json, return the claims list."""
    description = f"# Title: {snapshot['title']}\n\n{snapshot['body']}"
    file_names = [f["filename"] for f in snapshot.get("files", [])]
    messages = [
        {"role": "system", "content": SCHEMA_HINT},
        {"role": "user", "content": f"Description:\n{description}\n\nFiles changed:\n{file_names}"},
    ]
    try:
        raw = chat(messages, model=cfg["model"], api_key=cfg["api_key"],
                   base_url=cfg["base_url"])
        claims = _parse_claims(raw)
    except (json.JSONDecodeError, ValueError, RuntimeError) as e:
        raise RuntimeError(f"invalid claims response: {e}") from e

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "claims.json").write_text(json.dumps(claims, indent=2))
    return claims
