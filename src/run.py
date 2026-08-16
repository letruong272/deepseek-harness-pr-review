"""CLI entry: orchestrates 5 phase. Usage:
python -m src.run <owner>/<repo> <pr> [--skip-human] [--force] [--no-post]
                    [--fixtures DIR] [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

from config import load_config
from gh import gh_available
from human_gate import run_gate
from synthesize import build_comment, build_report, post_comment
from verify import run_verify, setup_workspace


def _load_or_skip(name: str, session_dir: Path, force: bool) -> dict | list | None:
    path = session_dir / name
    if path.exists() and not force:
        return json.loads(path.read_text())
    return None


def _write_failed_report(session_dir: Path, error: Exception) -> None:
    lines = [
        "# Review FAILED",
        "",
        f"- Lỗi: {error}",
        f"- Phase lỗi: xem stderr",
        f"- Đã có: {[p.name for p in sorted(session_dir.iterdir()) if p.is_file()]}",
        "",
    ]
    (session_dir / "report.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-pr-review")
    parser.add_argument("pr", help="<owner>/<repo> <pr-number> hoặc owner/repo#n")
    parser.add_argument("number", nargs="?", type=int,
                        help="PR number (nếu pr = owner/repo#n thì bỏ qua)")
    parser.add_argument("--skip-human", action="store_true",
                        help="không hỏi, đánh dấu SKIPPED")
    parser.add_argument("--force", action="store_true",
                        help="chạy lại các phase đã có kết quả")
    parser.add_argument("--no-post", action="store_true",
                        help="không post comment lên PR")
    parser.add_argument("--dry-run", action="store_true",
                        help="chỉ build report, không post")
    parser.add_argument("--fixtures", type=Path, default=None,
                        help="thư mục chứa snapshot.json/claims.json/findings.json "
                             "(dùng cho e2e, bỏ qua gh & model)")
    args = parser.parse_args(argv)

    base = args.pr.split("#")[0]
    parts = base.split("/")
    if len(parts) != 2 or (args.number is None and "#" not in args.pr):
        print("usage: python -m src.run <owner>/<repo> <pr-number>",
              file=sys.stderr)
        return 2
    owner, repo = parts
    num = str(args.number if args.number is not None else args.pr.split("#")[1])
    if not num.isdigit():
        print(f"PR number không hợp lệ: {num}", file=sys.stderr)
        return 2

    cfg = load_config()
    if not cfg.api_key and args.fixtures is None:
        print("DEEPSEEK_API_KEY chưa set (xem .env.example)", file=sys.stderr)
        return 3
    if not gh_available() and args.fixtures is None:
        print("gh CLI chưa có hoặc chưa auth (gh auth login)", file=sys.stderr)
        return 2

    session_dir = cfg.session_root / owner / repo / f"pr-{num}"
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.fixtures is not None:
            for name in ("snapshot.json", "claims.json", "findings.json"):
                src = args.fixtures / name
                if not src.exists():
                    print(f"fixture thiếu: {src}", file=sys.stderr)
                    return 2
                (session_dir / name).write_text(src.read_text())
            findings = json.loads((session_dir / "findings.json").read_text())
        else:
            from snapshot import build_snapshot
            from claims import extract_claims

            snapshot = _load_or_skip("snapshot.json", session_dir, args.force)
            if snapshot is None:
                snapshot = build_snapshot(owner, repo, int(num), session_dir)
            claims = _load_or_skip("claims.json", session_dir, args.force)
            if claims is None:
                claims = extract_claims(
                    snapshot, {"model": cfg.model, "api_key": cfg.api_key,
                               "base_url": cfg.base_url}, session_dir)
            findings = _load_or_skip("findings.json", session_dir, args.force)
            if findings is None:
                workspace = session_dir / "workspace"
                setup_workspace(owner, repo, int(num), workspace)
                findings = run_verify(
                    {"model": cfg.model}, workspace, session_dir, snapshot, claims)
                (session_dir / "findings.json").write_text(
                    json.dumps(findings, indent=2))

        answers = _load_or_skip("answers.json", session_dir, args.force)
        if answers is None:
            answers = run_gate(findings, session_dir,
                               interactive=not args.skip_human)

        snapshot = json.loads((session_dir / "snapshot.json").read_text())
        claims = json.loads((session_dir / "claims.json").read_text())
        build_report(snapshot, claims, findings, answers, session_dir)
        print(f"Report: {session_dir / 'report.md'}")

        if args.dry_run or args.fixtures is not None or args.no_post:
            return 0
        body = build_comment(snapshot, claims, findings, answers)
        if post_comment(owner, repo, int(num), body):
            print("Đã post comment lên PR.")
        else:
            print("Comment đã tồn tại (có marker) — bỏ qua.")
        return 0
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        _write_failed_report(session_dir, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
