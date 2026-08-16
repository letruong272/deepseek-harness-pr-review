"""Phase 5: synthesize the report + post an English comment on the PR."""
from pathlib import Path

from src.gh import run_gh

MARKER = "<!-- harness-pr-review -->"
STATUS_LABELS = {"PASS": "Matches", "FAIL": "Mismatch", "PARTIAL": "Partial",
                 "UNVERIFIED": "Unverified"}


def _cell(text, max_len=200):
    text = str(text or "")
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text.replace("|", "\\|").replace("\n", "<br>")


def _bullet(text, max_len=100):
    text = str(text or "")
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text.replace("\n", " ")


def _overall_verdict(findings: dict) -> str:
    statuses = [c["status"] for c in findings.get("claims", [])]
    if not statuses:
        return "NO CLAIMS"
    if any(s == "FAIL" for s in statuses):
        return "MISLEADING"
    if any(s in ("PARTIAL", "UNVERIFIED") for s in statuses):
        return "PARTIAL"
    return "ACCURATE"


def build_report(snapshot: dict, claims: list[dict], findings: dict,
                 answers: list[dict], session_dir: Path) -> str:
    """Write report.md. Returns the report content."""
    verdict = _overall_verdict(findings)
    text_by_id = {cl["id"]: cl.get("text", "") for cl in claims}
    lines = [
        f"# Review PR #{snapshot['pr']} — {snapshot['title']}",
        "",
        f"- Author: {snapshot['author']} | Base: {snapshot['base']} → Head: {snapshot['head']}",
        f"- Files changed: {len(snapshot['files'])} | Commits: {len(snapshot['commits'])}",
        f"## Verdict: {verdict}",
        "",
        "## Claims",
        "",
        "| Claim | Content | Status | Evidence | Notes |",
        "|---|---|---|---|---|",
    ]
    for c in findings.get("claims", []):
        text = text_by_id.get(c["id"], c.get("text", ""))
        lines.append(
            f"| {c['id']} | {_cell(text)} | {STATUS_LABELS.get(c['status'], c['status'])} | "
            f"{_cell(', '.join(c.get('evidence', [])) or '-')} | {_cell(c.get('note', ''))} |")
    lines += [
        "", "## Docs vs reality", "",
        "| Doc | Status | Difference |", "|---|---|---|",
    ]
    for d in findings.get("docs", []):
        lines.append(f"| {_cell(d['path'])} | {d['status']} | {_cell(d.get('what', ''))} |")
    lines += [
        "", "## Requirement impact", "",
        "| Requirement | Impact | Detail |", "|---|---|---|",
    ]
    for i in findings.get("impact", []):
        lines.append(f"| {_cell(i['requirement'])} | {i['impact']} | {_cell(i.get('detail', ''))} |")
    lines += [
        "", "## Review threads", "",
        "| Comment | Status | Notes |", "|---|---|---|",
    ]
    for t in findings.get("threads", []):
        lines.append(f"| {_cell(t['text'], max_len=120)} | {t['status']} | {_cell(t.get('note', ''))} |")
    lines += ["", "## Confirmation log", ""]
    for a in answers:
        lines.append(f"- **{a['question']}** → {a['answer']}")
    if not answers:
        lines.append("- (none)")
    report = "\n".join(lines) + "\n"

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "report.md").write_text(report)
    return report


def build_comment(snapshot: dict, claims: list[dict], findings: dict,
                  answers: list[dict], report_content: str | None = None) -> str:
    """Build the English comment (single one, with marker).

    If report_content is passed, the comment embeds the whole report (enough
    information to read directly on the PR); otherwise it is only a summary.
    """
    verdict = _overall_verdict(findings)
    if report_content:
        return (
            f"## Harness PR Review — Verdict: {verdict}\n\n"
            f"<details open>\n\n<summary>Full report</summary>\n\n"
            f"{report_content}\n\n</details>\n\n{MARKER}"
        )
    claim_lines = "\n".join(
        f"- {c['id']}: {c['status']}" for c in findings.get("claims", []))
    doc_lines = "\n".join(
        f"- {d['path']}: {d['status']}" for d in findings.get("docs", []))
    thread_lines = "\n".join(
        f"- {_bullet(t['text'])} → {t['status']}" for t in findings.get("threads", []))
    return (
        f"## Harness PR Review\n\n"
        f"**Verdict: {verdict}**\n\n"
        f"### Claims\n{claim_lines or '- none'}\n\n"
        f"### Docs vs reality\n{doc_lines or '- none'}\n\n"
        f"### Unresolved threads\n{thread_lines or '- none'}\n\n"
        f"### Action needed\n"
        f"- Fix description if marked MISLEADING\n"
        f"- Confirm docs marked WRONG/FABRICATED (see local report)\n\n"
        f"Full report: local `sessions/{snapshot['owner']}/{snapshot['repo']}/"
        f"pr-{snapshot['pr']}/report.md`\n\n{MARKER}"
    )


def post_comment(owner: str, repo: str, n: int, body: str, *,
                 gh=run_gh, list_comments=None) -> bool:
    """Post a comment if there is no marker; otherwise UPDATE the existing comment (keep a single comment).

    Returns True if a new one was created, False if an existing comment was updated.
    """
    if list_comments is None:
        list_comments = lambda: gh(["api", f"repos/{owner}/{repo}/issues/{n}/comments", "--paginate"])
    for c in list_comments():
        if MARKER in c.get("body", ""):
            gh(["api", f"repos/{owner}/{repo}/issues/comments/{c['id']}",
                "-X", "PATCH", "-f", f"body={body}"])
            return False
    gh(["api", f"repos/{owner}/{repo}/issues/{n}/comments",
        "-f", f"body={body}"])
    return True
