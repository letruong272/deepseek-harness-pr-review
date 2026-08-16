import os

import pytest

from config import load_config


def test_load_config_defaults(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DSH_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    cfg = load_config()
    assert cfg.api_key == ""
    assert cfg.model == "deepseek-v4-flash"
    assert cfg.base_url == "https://api.deepseek.com/v1"
    assert cfg.session_root.name == "sessions"


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DSH_MODEL", "deepseek-r1")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("DSH_SESSION_ROOT", "/tmp/my-sessions")
    cfg = load_config()
    assert cfg.api_key == "sk-test"
    assert cfg.model == "deepseek-r1"
    assert cfg.base_url == "http://localhost:8000/v1"
    assert str(cfg.session_root) == "/tmp/my-sessions"
