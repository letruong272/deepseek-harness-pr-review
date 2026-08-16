"""CLI entry: orchestrates 5 phase. Usage:
harness-pr-review <owner>/<repo> <pr> [--skip-human] [--force] [--no-post]
                  [--fixtures DIR] [--dry-run]
harness-pr-review doctor
"""
import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

from config import load_config
from gh import gh_available, run_gh
from human_gate import run_gate
from synthesize import build_comment, build_report, post_comment
from verify import run_verify, setup_workspace


def _doctor() -> int:
    """Check readiness: Python, gh, API key, SDK, config. Exit 0 if ready."""
    import platform

    ok = True
    py = platform.python_version_tuple()
    if (int(py[0]), int(py[1])) >= (3, 10):
        print(f"✓ Python 3.10+ ({platform.python_version()})")
    else:
        print(f"✗ Python 3.10+ required, found {platform.python_version()}")
        ok = False

    if gh_available():
        try:
            user = run_gh(["api", "user"])
            print(f"✓ gh CLI installed + authenticated ({user.get('login', '?')})")
        except RuntimeError:
            print("✗ gh CLI installed but not authenticated — run `gh auth login`")
            ok = False
    else:
        print("✗ gh CLI not installed — install GitHub CLI and run `gh auth login`")
        ok = False

    cfg = load_config()
    if cfg.api_key:
        print("✓ DEEPSEEK_API_KEY set")
    else:
        print("✗ DEEPSEEK_API_KEY not set — see .env.example")
        ok = False

    try:
        importlib.metadata.version("deepseek-harness-sdk")
        print(f"✓ deepseek-harness-sdk installed "
              f"({importlib.metadata.version('deepseek-harness-sdk')})")
    except importlib.metadata.PackageNotFoundError:
        print("✗ deepseek-harness-sdk not installed — run `pip install -e '.[dev]'`")
        ok = False

    from autoreview_config import load_config as load_autoreview_config

    config_path = Path("autoreview.yml")
    if config_path.exists():
        try:
            acfg = load_autoreview_config(config_path)
            print(f"✓ autoreview.yml valid ({len(acfg['repos'])} repos)")
        except (ValueError, OSError) as e:
            print(f"✗ autoreview.yml invalid: {e}")
            ok = False
    else:
        print("· autoreview.yml not found (optional — only needed for auto review)")

    if ok:
        print("\nReady. Run: harness-pr-review owner/repo 123")
    return 0 if ok else 1


def _load_or_skip(name: str, session_dir: Path, force: bool) -> dict | list | None:
    path = session_dir / name
    if path.exists() and not force:
        return json.loads(path.read_text())
    return None


def _write_failed_report(session_dir: Path, error: Exception) -> None:
    lines = [
        "# Review FAILED",
        "",
        f"- Error: {error}",
        f"- Failed phase: see stderr",
        f"- Existing artifacts: {[p.name for p in sorted(session_dir.iterdir()) if p.is_file()]}",
        "",
    ]
    (session_dir / "report.md").write_text("\n".join(lines))


def _bump_rounds(session_dir: Path) -> None:
    """Increment the review-round counter for a session (after a verify pass)."""
    path = session_dir / "rounds.txt"
    try:
        current = int(path.read_text().strip() or "0")
    except (OSError, ValueError):
        current = 0
    path.write_text(str(current + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-pr-review")
    parser.add_argument("pr", nargs="?", help="<owner>/<repo> <pr-number> or owner/repo#n")
    parser.add_argument("number", nargs="?", type=int,
                        help="PR number (omit if pr = owner/repo#n)")
    parser.add_argument("--skip-human", action="store_true",
                        help="don't ask, mark as SKIPPED")
    parser.add_argument("--force", action="store_true",
                        help="re-run phases that already have results")
    parser.add_argument("--no-post", action="store_true",
                        help="don't post a comment on the PR")
    parser.add_argument("--dry-run", action="store_true",
                        help="only build the report, don't post")
    parser.add_argument("--fixtures", type=Path, default=None,
                        help="directory containing snapshot.json/claims.json/findings.json "
                             "(for e2e, skips gh & model)")
    parser.add_argument("doctor", nargs="?", help="check readiness (Python, gh, API key, SDK)")
    args = parser.parse_args(argv)

    if args.doctor == "doctor" or args.pr == "doctor":
        return _doctor()
    if args.pr is None:
        parser.print_help()
        return 2

    base = args.pr.split("#")[0]
    parts = base.split("/")
    if len(parts) != 2 or (args.number is None and "#" not in args.pr):
        print("usage: python -m src.run <owner>/<repo> <pr-number>",
              file=sys.stderr)
        return 2
    owner, repo = parts
    num = str(args.number if args.number is not None else args.pr.split("#")[1])
    if not num.isdigit():
        print(f"invalid PR number: {num}", file=sys.stderr)
        return 2

    cfg = load_config()
    if not cfg.api_key and args.fixtures is None:
        print("DEEPSEEK_API_KEY not set (see .env.example)", file=sys.stderr)
        return 3
    if not gh_available() and args.fixtures is None:
        print("gh CLI not installed or not authenticated (gh auth login)", file=sys.stderr)
        return 2

    session_dir = cfg.session_root / owner / repo / f"pr-{num}"
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.fixtures is not None:
            for name in ("snapshot.json", "claims.json", "findings.json"):
                src = args.fixtures / name
                if not src.exists():
                    print(f"missing fixture: {src}", file=sys.stderr)
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
                _bump_rounds(session_dir)

        answers = _load_or_skip("answers.json", session_dir, args.force)
        if answers is None:
            answers = run_gate(findings, session_dir,
                               interactive=not args.skip_human)

        snapshot = json.loads((session_dir / "snapshot.json").read_text())
        claims = json.loads((session_dir / "claims.json").read_text())
        report = build_report(snapshot, claims, findings, answers, session_dir)
        print(f"Report: {session_dir / 'report.md'}")

        if args.dry_run or args.fixtures is not None or args.no_post:
            return 0
        body = build_comment(snapshot, claims, findings, answers,
                             report_content=report)
        if post_comment(owner, repo, int(num), body):
            print("Posted comment to PR.")
        else:
            print("Comment exists — updated with full report.")
        return 0
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        _write_failed_report(session_dir, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
