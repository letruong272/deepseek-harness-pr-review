"""Phase 3: setup worktree + chạy agent deep-dive (DeepSeekHarness SDK)."""
import json
import subprocess
from pathlib import Path

VERIFY_SCHEMA = """{
  "claims": [{"id": "C1", "status": "PASS|FAIL|PARTIAL|UNVERIFIED",
              "evidence": ["file:line"], "note": "ngắn gọn"}],
  "docs": [{"path": "docs/x.md", "status": "MATCH|STALE|WRONG|FABRICATED",
            "what": "khác biệt ngắn gọn"}],
  "impact": [{"requirement": "tên requirement", "impact": "CHANGED|BROKEN|UNAFFECTED|RISK",
              "detail": "ngắn gọn"}],
  "threads": [{"text": "nội dung comment", "status": "RESOLVED|STILL_VALID|FIXED|OUTDATED",
               "note": "ngắn gọn"}],
  "unresolved_questions": ["câu hỏi ≤20 chữ cho human"]
}"""


def setup_workspace(owner: str, repo: str, n: int, workspace: Path,
                    remote_url: str | None = None) -> None:
    """Clone repo (lần đầu) + checkout nhánh PR head vào workspace (disposable)."""
    if not workspace.exists():
        url = remote_url or f"https://github.com/{owner}/{repo}.git"
        subprocess.run(["git", "clone", "--no-checkout", url, str(workspace)],
                       check=True, capture_output=True)
    branch = f"pr-{n}"
    subprocess.run(["git", "fetch", "origin", f"pull/{n}/head:{branch}"],
                   cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-f", branch], cwd=workspace,
                   check=True, capture_output=True)


def build_verify_prompt(snapshot: dict, claims: list[dict]) -> str:
    """Prompt hướng dẫn agent verify trong workspace và ghi findings.json."""
    files_summary = [
        f"- {f['filename']} (+{f.get('additions', 0)}/-{f.get('deletions', 0)})"
        for f in snapshot["files"]
    ]
    threads_summary = [
        f"- (resolved={t['resolved']}) {t.get('author')}: {t.get('body', '')[:200]}"
        for t in snapshot.get("threads", [])
    ]
    return f"""
Bạn đang trong workspace chứa code của PR. Nhiệm vụ: deep-dive verify.

PR title: {snapshot['title']}
PR body: {snapshot['body']}
Files changed:
{chr(10).join(files_summary) if files_summary else '- (none)'}
Review threads:
{chr(10).join(threads_summary) if threads_summary else '- (none)'}

Claims cần verify (đọc code thực tế, đừng tin description):
{json.dumps(claims, indent=2)}

Yêu cầu:
1. Với từng claim: PASS (code làm đúng như mô tả) / FAIL (mô tả sai) /
   PARTIAL (đúng một phần) / UNVERIFIED (không thể xác minh). Kèm evidence file:line.
2. Docs reality-check: với mọi docs trong repo liên quan tới code thay đổi,
   đọc docs và đối chiếu code thực tế. Status: MATCH / STALE / WRONG / FABRICATED
   (FABRICATED = docs mô tả tính năng không tồn tại trong code).
3. Impact: thay đổi này tác động requirement/business logic nào?
   CHANGED / BROKEN / UNAFFECTED / RISK, kèm detail ngắn.
4. Threads: comment chưa resolved còn đúng với code hiện tại không?
5. Không đoán. Mọi thứ không xác minh được → UNVERIFIED và thêm vào
   unresolved_questions (mỗi câu ≤20 chữ, tiếng Việt).

Cuối cùng: GHI file findings.json vào thư mục workspace hiện tại (nơi bạn đang làm việc)
đúng schema (không có markdown fence, JSON thuần):
{VERIFY_SCHEMA}
"""


def run_verify(cfg: dict, workspace: Path, session_dir: Path, snapshot: dict,
               claims: list[dict]) -> dict:
    """Chạy agent DeepSeekHarness, đọc findings.json agent ghi, validate & trả về."""
    from deepseek_harness import DeepSeekHarness  # import trễ (SDK nặng)

    session_dir.mkdir(parents=True, exist_ok=True)
    session_root = str(session_dir)
    prompt = build_verify_prompt(snapshot, claims)

    with DeepSeekHarness(
        provider="deepseek-official",
        model=cfg["model"],
        max_tokens=49_152,
        cwd=str(workspace),
        session_root=session_root,
        cordis=str(Path("cordis/minimal.cordis.yml").resolve()),
    ) as harness:
        result = harness.run(prompt, session_id="verify")

    (session_dir / "agent-log.txt").write_text(result.final_response)
    return parse_findings(workspace / "findings.json")


def parse_findings(path: Path) -> dict:
    """Đọc + validate findings.json. Raise RuntimeError nếu sai schema."""
    if not path.exists():
        raise RuntimeError(f"invalid findings: {path} không tồn tại (agent không ghi findings.json)")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid findings: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError("invalid findings: phải là JSON object")
    for key in ("claims", "docs", "impact", "threads", "unresolved_questions"):
        if not isinstance(data.get(key), list):
            raise RuntimeError(f"invalid findings: thiếu key {key} (phải là list)")
    for c in data["claims"]:
        if not c.get("id") or c.get("status") not in ("PASS", "FAIL", "PARTIAL", "UNVERIFIED"):
            raise RuntimeError(f"invalid findings: claim sai schema: {c}")
    for d in data["docs"]:
        if d.get("status") not in ("MATCH", "STALE", "WRONG", "FABRICATED"):
            raise RuntimeError(f"invalid findings: doc sai schema: {d}")
    return data
