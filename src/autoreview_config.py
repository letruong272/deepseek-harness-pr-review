"""Load + validate autoreview.yml config."""
from pathlib import Path

import yaml

DEFAULTS = {
    "interval_minutes": 10,
    "post_comment": True,
    "skip_human": True,
    "drafts": False,
}


def load_config(path: Path) -> dict:
    """Read autoreview.yml, merge defaults. Raises OSError/ValueError."""
    raw = yaml.safe_load(path.read_text()) or {}
    cfg = {**DEFAULTS, **raw}
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict) -> None:
    repos = cfg.get("repos") or []
    if not repos:
        raise ValueError("config requires at least one repo")
    for r in repos:
        if "/" not in r or len(r.split("/")) != 2:
            raise ValueError(f"repo must be owner/repo: {r!r}")
