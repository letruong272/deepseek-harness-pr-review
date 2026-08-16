# tests/test_autoreview_config.py
import pytest

from autoreview_config import load_config, validate_config

DEFAULT_YML = """
repos:
  - sample-org/sample-app
interval_minutes: 10
post_comment: true
skip_human: true
drafts: false
"""


def test_load_config_defaults(tmp_path):
    p = tmp_path / "autoreview.yml"
    p.write_text(DEFAULT_YML)
    cfg = load_config(p)
    assert cfg["repos"] == ["sample-org/sample-app"]
    assert cfg["interval_minutes"] == 10
    assert cfg["post_comment"] is True
    assert cfg["skip_human"] is True
    assert cfg["drafts"] is False


def test_load_config_missing_defaults(tmp_path):
    p = tmp_path / "autoreview.yml"
    p.write_text("repos:\n  - a/b\n")
    cfg = load_config(p)
    assert cfg["interval_minutes"] == 10
    assert cfg["post_comment"] is True
    assert cfg["skip_human"] is True
    assert cfg["drafts"] is False


def test_validate_config_no_repos(tmp_path):
    p = tmp_path / "autoreview.yml"
    p.write_text("interval_minutes: 5\n")
    with pytest.raises(ValueError, match="at least one repo"):
        validate_config(load_config(p))


def test_validate_config_bad_repo_format(tmp_path):
    p = tmp_path / "autoreview.yml"
    p.write_text("repos:\n  - not-a-repo\n")
    with pytest.raises(ValueError, match="owner/repo"):
        validate_config(load_config(p))
