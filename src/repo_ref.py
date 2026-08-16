"""Parse GitHub URLs/refs into (owner, repo[, pr]). Lazy-friendly input."""
import re

_REPO_URL = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)(?:/pull/(?P<pr>\d+))?(?:/.*)?")
_REPO_REF = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)$")


def parse_repo(value: str) -> tuple[str, str]:
    """Extract (owner, repo) from a URL (https://github.com/o/r[/...]) or o/r."""
    value = value.strip()
    m = _REPO_URL.match(value)
    if m:
        return m.group("owner"), m.group("repo")
    m = _REPO_REF.match(value)
    if m:
        return m.group("owner"), m.group("repo")
    raise ValueError(f"cannot parse repo from: {value!r}")


def parse_pr(value: str) -> tuple[str, str, int]:
    """Extract (owner, repo, pr) from URL, o/r#n or o/r + n."""
    value = value.strip()
    m = _REPO_URL.match(value)
    if m and m.group("pr"):
        return m.group("owner"), m.group("repo"), int(m.group("pr"))
    if "#" in value:
        ref, _, pr = value.partition("#")
        owner, repo = parse_repo(ref)
        if not pr.isdigit():
            raise ValueError(f"invalid PR number: {pr!r}")
        return owner, repo, int(pr)
    raise ValueError(f"cannot parse PR from: {value!r} (use URL or owner/repo#n)")
