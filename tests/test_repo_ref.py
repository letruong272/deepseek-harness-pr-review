# tests/test_repo_ref.py
import pytest

from repo_ref import parse_pr, parse_repo


def test_parse_repo_url_full():
    assert parse_repo("https://github.com/nexpeakcore/erp/pull/935") == \
        ("nexpeakcore", "erp")
    assert parse_repo("https://github.com/nexpeakcore/erp") == \
        ("nexpeakcore", "erp")


def test_parse_repo_no_scheme():
    assert parse_repo("github.com/nexpeakcore/erp") == ("nexpeakcore", "erp")
    assert parse_repo("nexpeakcore/erp") == ("nexpeakcore", "erp")


def test_parse_repo_invalid():
    with pytest.raises(ValueError, match="cannot parse repo"):
        parse_repo("not-a-repo")


def test_parse_pr_url():
    assert parse_pr("https://github.com/nexpeakcore/erp/pull/935") == \
        ("nexpeakcore", "erp", 935)


def test_parse_pr_shorthand():
    assert parse_pr("nexpeakcore/erp#935") == ("nexpeakcore", "erp", 935)


def test_parse_pr_invalid_number():
    with pytest.raises(ValueError, match="invalid PR number"):
        parse_pr("nexpeakcore/erp#abc")
