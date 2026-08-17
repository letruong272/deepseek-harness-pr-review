# tests/test_repo_ref.py
import pytest

from src.repo_ref import parse_pr, parse_repo


def test_parse_repo_url_full():
    assert parse_repo("https://github.com/sample-org/sample-repo/pull/935") == \
        ("sample-org", "sample-repo")
    assert parse_repo("https://github.com/sample-org/sample-repo") == \
        ("sample-org", "sample-repo")


def test_parse_repo_no_scheme():
    assert parse_repo("github.com/sample-org/sample-repo") == ("sample-org", "sample-repo")
    assert parse_repo("sample-org/sample-repo") == ("sample-org", "sample-repo")


def test_parse_repo_invalid():
    with pytest.raises(ValueError, match="cannot parse repo"):
        parse_repo("not-a-repo")


def test_parse_pr_url():
    assert parse_pr("https://github.com/sample-org/sample-repo/pull/935") == \
        ("sample-org", "sample-repo", 935)


def test_parse_pr_shorthand():
    assert parse_pr("sample-org/sample-repo#935") == ("sample-org", "sample-repo", 935)


def test_parse_pr_invalid_number():
    with pytest.raises(ValueError, match="invalid PR number"):
        parse_pr("sample-org/sample-repo#abc")
