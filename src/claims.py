"""Phase 2: tách PR description thành các claim kiểm chứng được (LLM)."""
import json
import re
from pathlib import Path

from llm import chat as _default_chat

SCHEMA_HINT = """
Tách mô tả PR dưới đây thành các claim kiểm chứng được (mỗi claim phải có thể
xác minh bằng cách đọc code). Trả về JSON array đúng schema:
[{"id": "C1", "text": "<ngắn gọn>", "category": "feature|bugfix|refactor|perf|ux|docs",
  "files": ["<file liên quan, rỗng nếu không rõ>"], "docs": ["<docs bị claim này nhắc tới>"]}]
Không thêm text ngoài JSON. Nếu không có claim nào, trả về [].
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
            raise ValueError(f"claim sai schema (thiếu id): {c}")
        if "text" not in c or "category" not in c:
            raise ValueError(f"claim sai schema (thiếu text/category): {c}")
        if c["category"] not in ("feature", "bugfix", "refactor", "perf", "ux", "docs"):
            raise ValueError(f"category không hợp lệ: {c.get('category')}")
    return data


def extract_claims(snapshot: dict, cfg: dict, session_dir: Path,
                   chat=_default_chat) -> list[dict]:
    """Tách claim từ snapshot body. Lưu claims.json, trả về list claims."""
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
