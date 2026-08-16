# Harness PR Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Headless tool chạy local, dùng DeepSeek Harness SDK để deep-dive review PR trên GitHub: verify PR description thành từng claim, xác minh docs trong repo có đúng với code không, phân tích tác động tới requirement, hỏi human khi không chắc (≤20 chữ), xuất report tiếng Việt + post 1 comment tiếng Anh lên PR.

**Architecture:** Pipeline 5 phase, mỗi phase là 1 module riêng (snapshot → claims → verify → human_gate → synthesize), orchestrated bởi `run.py`. Mỗi phase lưu kết quả dạng JSON vào `sessions/<owner>/<repo>/pr-<n>/`, cho phép re-run từng phần. Deep-dive chạy bằng `DeepSeekHarness` SDK với worktree disposable, agent tự đọc code và ghi `findings.json` theo schema cố định.

**Tech Stack:** Python 3.10+, `deepseek-harness-sdk` (bundled runtime), `gh` CLI, `pytest`. Không dependency nặng khác.

**Spec:** `docs/superpowers/specs/2026-08-16-harness-pr-review-design.md`

---

## File Structure

```
harness/
├── pyproject.toml              # package metadata + pytest config
├── .env.example                # template: DEEPSEEK_API_KEY, DSH_MODEL
├── .gitignore                  # .venv, __pycache__, sessions/, .env
├── cordis/
│   └── minimal.cordis.yml      # composition file cho DeepSeekHarness (copy từ deepseek-harness repo)
├── src/
│   ├── __init__.py             # version
│   ├── config.py               # Config dataclass, load_config() từ env
│   ├── gh.py                   # run_gh() wrapper + gh_available()
│   ├── snapshot.py             # Phase 1: build_snapshot()
│   ├── llm.py                  # chat() — OpenAI-compatible POST + retry
│   ├── claims.py               # Phase 2: extract_claims()
│   ├── verify.py               # Phase 3: setup_workspace(), run_verify()
│   ├── human_gate.py           # Phase 4: run_gate(), trim_question()
│   ├── synthesize.py           # Phase 5: build_report(), build_comment(), post_comment()
│   └── run.py                  # CLI orchestration
└── tests/
    ├── test_config.py
    ├── test_gh.py
    ├── test_snapshot.py
    ├── test_llm.py
    ├── test_claims.py
    ├── test_verify.py
    ├── test_human_gate.py
    ├── test_synthesize.py
    └── test_run.py
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
def test_package_imports():
    import src  # noqa: F401

    assert src.__version__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src'` (hoặc `src.__version__` chưa tồn tại)

- [ ] **Step 3: Write minimal implementation**

```python
# pyproject.toml
[project]
name = "harness-pr-review"
version = "0.1.0"
description = "Headless PR review automation on top of DeepSeek Harness"
requires-python = ">=3.10"
dependencies = [
    "deepseek-harness-sdk",
]

[project.optional-dependencies]
dev = ["pytest"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```python
# src/__init__.py
__version__ = "0.1.0"
```

```bash
# .gitignore
.venv/
__pycache__/
*.pyc
.env
sessions/
.pytest_cache/
dist/
```

```bash
# .env.example
DEEPSEEK_API_KEY=sk-your-key-here
DSH_MODEL=deepseek-v4-flash
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: PASS — `1 passed`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore .env.example src/__init__.py tests/test_smoke.py
git commit -m "chore: scaffold project"
```

---

### Task 2: Config module

**Files:**
- Create: `src/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/config.py
"""Cấu hình từ environment. Tất cả env đều optional."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    api_key: str
    model: str
    base_url: str
    session_root: Path


def load_config() -> Config:
    return Config(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        model=os.environ.get("DSH_MODEL", "deepseek-v4-flash"),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        session_root=Path(os.environ.get("DSH_SESSION_ROOT", "sessions")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS — `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add config module"
```

---

### Task 3: gh CLI wrapper

**Files:**
- Create: `src/gh.py`
- Test: `tests/test_gh.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gh.py
import json

import pytest

from gh import gh_available, run_gh


def test_run_gh_json(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        assert text is True
        return type("R", (), {"returncode": 0, "stdout": json.dumps({"ok": 1}), "stderr": ""})()

    monkeypatch.setattr("gh.subprocess.run", fake_run)
    out = run_gh(["api", "repos/x/y/pulls/1"])
    assert out == {"ok": 1}
    assert "gh" in captured["cmd"][0]


def test_run_gh_error(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "not found"})()

    monkeypatch.setattr("gh.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="gh api failed: not found"):
        run_gh(["api", "repos/x/y/pulls/1"])


def test_gh_available(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return type("R", (), {"returncode": 0, "stdout": "1\n", "stderr": ""})()

    monkeypatch.setattr("gh.subprocess.run", fake_run)
    assert gh_available() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gh.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gh'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/gh.py
"""Wrapper mỏng quanh gh CLI. Gh phải được auth sẵn (gh auth login)."""
import subprocess
import sys


def _run_gh_impl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
    )


def run_gh(args: list[str], *, json: bool = True) -> dict | list:
    """Chạy `gh <args>`; nếu json=True thì parse stdout. Raise RuntimeError khi fail."""
    proc = _run_gh_impl(args + (["--jq", "."] if json else []))
    if proc.returncode != 0:
        raise RuntimeError(f"gh api failed: {proc.stderr.strip()}")
    if not json:
        return proc.stdout
    import json as _json

    return _json.loads(proc.stdout)


def gh_available() -> bool:
    try:
        proc = _run_gh_impl(["--version"])
        return proc.returncode == 0
    except FileNotFoundError:
        return False
```

Lưu ý: `run_gh` được gọi qua `gh.run_gh(...)` trong test (import `from gh import ...` nhưng monkeypatch `gh.subprocess.run`). Đảm bảo module này `import subprocess` ở module level, và `sys` không dùng thì bỏ — chỉ giữ `import subprocess`.

```python
# src/gh.py (bản cuối, sạch)
"""Wrapper mỏng quanh gh CLI. Gh phải được auth sẵn (gh auth login)."""
import json
import subprocess


def _run_gh_impl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def run_gh(args: list[str], *, json: bool = True) -> dict | list:
    proc = _run_gh_impl(args + (["--jq", "."] if json else []))
    if proc.returncode != 0:
        raise RuntimeError(f"gh api failed: {proc.stderr.strip()}")
    if not json:
        return proc.stdout
    return json.loads(proc.stdout)


def gh_available() -> bool:
    try:
        proc = _run_gh_impl(["--version"])
        return proc.returncode == 0
    except FileNotFoundError:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_gh.py -v`
Expected: PASS — `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/gh.py tests/test_gh.py
git commit -m "feat: add gh cli wrapper"
```

---

### Task 4: Phase 1 — Snapshot (fetch PR data)

**Files:**
- Create: `src/snapshot.py`
- Test: `tests/test_snapshot.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_snapshot.py
import json

import pytest

from snapshot import build_snapshot


def _gh_fake(registry):
    """Trả về run_gh thay thế dựa theo tiền tố của args."""
    def fake(args, *, json=True):
        key = next(k for k in registry if args[1].startswith(k))
        val = registry[key]
        if isinstance(val, Exception):
            raise val
        return val

    return fake


PR_META = {
    "number": 7,
    "title": "Add checkout flow",
    "body": "Adds checkout. Fixes payment retry. Docs: docs/payment.md",
    "user": {"login": "dev1"},
    "base": {"ref": "main"},
    "head": {"ref": "feature/checkout"},
    "labels": [{"name": "feature"}],
}

PR_FILES = [
    {"filename": "src/checkout.py", "status": "added", "additions": 50, "deletions": 0,
     "patch": "@@ -0,0 +1 @@\n+def checkout():"},
]

PR_THREADS = {
    "data": {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "nodes": [
                        {"isResolved": False, "isOutdated": False,
                         "comments": {"nodes": [
                             {"path": "src/checkout.py", "line": 3,
                              "author": {"login": "reviewer1"}, "body": "Missing validation"}]}},
                    ]
                }
            }
        }
    }
}

COMMITS = [{"sha": "abc123", "commit": {"message": "feat: checkout"}}]


def test_build_snapshot(tmp_path):
    registry = {
        "repos/demo/app/pulls/7/commits": COMMITS,
        "repos/demo/app/pulls/7/files": PR_FILES,
        "repos/demo/app/pulls/7": PR_META,
        "graphql": PR_THREADS,
    }
    session_dir = tmp_path / "sessions"
    result = build_snapshot("demo", "app", 7, session_dir, gh=_gh_fake(registry))

    assert result["title"] == "Add checkout flow"
    assert result["body"].startswith("Adds checkout")
    assert result["files"][0]["filename"] == "src/checkout.py"
    assert result["threads"][0]["resolved"] is False
    assert result["commits"][0]["sha"] == "abc123"
    assert (session_dir / "snapshot.json").exists()
    saved = json.loads((session_dir / "snapshot.json").read_text())
    assert saved["pr"] == 7


def test_build_snapshot_no_patch_field(tmp_path):
    files = [{"filename": "src/a.py", "status": "modified", "additions": 1, "deletions": 1}]
    registry = {
        "repos/demo/app/pulls/7/commits": COMMITS,
        "repos/demo/app/pulls/7/files": files,
        "repos/demo/app/pulls/7": PR_META,
        "graphql": PR_THREADS,
    }
    result = build_snapshot("demo", "app", 7, tmp_path, gh=_gh_fake(registry))
    assert result["files"][0]["patch"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snapshot'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/snapshot.py
"""Phase 1: fetch PR metadata, files, commits, review threads từ GitHub."""
import json
from pathlib import Path

from gh import run_gh as _default_gh


def _get_threads(owner: str, repo: str, n: int, gh) -> list[dict]:
    query = """
    query($owner:String!,$repo:String!,$pr:Int!){
      repository(owner:$owner,name:$repo){
        pullRequest(number:$pr){
          reviewThreads(first:100){
            nodes{
              isResolved
              isOutdated
              comments(first:100){
                nodes{
                  path
                  line
                  author{login}
                  body
                }
              }
            }
          }
        }
      }
    }
    """
    payload = gh(["api", "graphql", "-f", f"query={query}",
                  "-F", f"owner={owner}", "-F", f"repo={repo}", "-F", f"pr={n}"])
    nodes = payload["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    threads = []
    for node in nodes:
        for c in node["comments"]["nodes"]:
            threads.append({
                "path": c.get("path"),
                "line": c.get("line"),
                "author": (c.get("author") or {}).get("login"),
                "body": c.get("body"),
                "resolved": node["isResolved"],
                "outdated": node["isOutdated"],
            })
    return threads


def build_snapshot(owner: str, repo: str, n: int, session_dir: Path,
                   gh=_default_gh) -> dict:
    """Fetch PR data và lưu snapshot.json vào session_dir. Trả về dict snapshot."""
    meta = gh([f"api", f"repos/{owner}/{repo}/pulls/{n}"])
    files = gh([f"api", f"repos/{owner}/{repo}/pulls/{n}/files", "--paginate"])
    commits = gh([f"api", f"repos/{owner}/{repo}/pulls/{n}/commits", "--paginate"])
    threads = _get_threads(owner, repo, n, gh)

    snapshot = {
        "owner": owner,
        "repo": repo,
        "pr": n,
        "title": meta.get("title", ""),
        "body": meta.get("body") or "",
        "author": (meta.get("user") or {}).get("login", ""),
        "base": (meta.get("base") or {}).get("ref", ""),
        "head": (meta.get("head") or {}).get("ref", ""),
        "labels": [l.get("name") for l in meta.get("labels", [])],
        "files": [
            {
                "filename": f.get("filename", ""),
                "status": f.get("status", ""),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch": f.get("patch", ""),
            }
            for f in files
        ],
        "commits": [
            {"sha": c.get("sha", ""), "message": c.get("commit", {}).get("message", "")}
            for c in commits
        ],
        "threads": threads,
    }

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
    return snapshot
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_snapshot.py -v`
Expected: PASS — `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/snapshot.py tests/test_snapshot.py
git commit -m "feat: add PR snapshot phase"
```

---

### Task 5: LLM chat helper (cho claim extraction)

**Files:**
- Create: `src/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm.py
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from llm import chat


class _Handler(BaseHTTPRequestHandler):
    captured = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        _Handler.captured["body"] = body
        response = {"choices": [{"message": {"content": "hello"}}]}
        data = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


def test_chat_ok(server):
    port = server.server_address[1]
    out = chat([{"role": "user", "content": "hi"}], model="m",
               api_key="k", base_url=f"http://127.0.0.1:{port}/v1")
    assert out == "hello"
    assert _Handler.captured["body"]["model"] == "m"
    assert _Handler.captured["body"]["messages"][0]["content"] == "hi"


class _FlakyHandler(BaseHTTPRequestHandler):
    count = 0

    def do_POST(self):
        _FlakyHandler.count += 1
        if _FlakyHandler.count < 3:
            self.send_response(500)
            self.end_headers()
            return
        data = json.dumps({"choices": [{"message": {"content": "retried"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_chat_retries(monkeypatch):
    _FlakyHandler.count = 0
    srv = HTTPServer(("127.0.0.1", 0), _FlakyHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        out = chat([{"role": "user", "content": "hi"}], model="m", api_key="k",
                   base_url=f"http://127.0.0.1:{port}/v1", retries=3)
        assert out == "retried"
        assert _FlakyHandler.count == 3
    finally:
        srv.shutdown()


def test_chat_gives_up(monkeypatch):
    class _AlwaysFail(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), _AlwaysFail)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        with pytest.raises(RuntimeError, match="chat failed after 3 retries"):
            chat([{"role": "user", "content": "hi"}], model="m", api_key="k",
                 base_url=f"http://127.0.0.1:{port}/v1", retries=3)
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/llm.py
"""OpenAI-compatible chat completion qua stdlib (không cần thêm dependency)."""
import json
import time
import urllib.error
import urllib.request


def chat(messages: list[dict], *, model: str, api_key: str, base_url: str,
         max_tokens: int = 4096, retries: int = 3) -> str:
    """POST {base_url}/chat/completions. Retry tối đa `retries` lần (timeout/429/5xx)."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode()

    last_err = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(2 * attempt)
    raise RuntimeError(f"chat failed after {retries} retries: {last_err}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm.py -v`
Expected: PASS — `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/llm.py tests/test_llm.py
git commit -m "feat: add llm chat helper with retry"
```

---

### Task 6: Phase 2 — Claim extraction

**Files:**
- Create: `src/claims.py`
- Test: `tests/test_claims.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_claims.py
import json

import pytest

from claims import extract_claims


FIXTURE_RESPONSE = """```json
[
  {"id": "C1", "text": "Adds checkout", "category": "feature",
   "files": ["src/checkout.py"], "docs": []},
  {"id": "C2", "text": "Fixes payment retry", "category": "bugfix",
   "files": ["src/payment.py"], "docs": ["docs/payment.md"]}
]
```"""


def test_extract_claims(tmp_path):
    snapshot = {
        "title": "Add checkout flow",
        "body": "Adds checkout. Fixes payment retry.",
        "files": [{"filename": "src/checkout.py"}, {"filename": "src/payment.py"}],
    }
    session_dir = tmp_path / "s"
    claims = extract_claims(
        snapshot,
        {"model": "m", "api_key": "k", "base_url": "http://x/v1"},
        session_dir,
        chat=lambda messages, **kw: FIXTURE_RESPONSE,
    )
    assert claims[0]["id"] == "C1"
    assert claims[1]["category"] == "bugfix"
    assert claims[1]["docs"] == ["docs/payment.md"]
    saved = json.loads((session_dir / "claims.json").read_text())
    assert len(saved) == 2


def test_extract_claims_invalid_response(tmp_path):
    session_dir = tmp_path / "s"
    with pytest.raises(RuntimeError, match="invalid claims response"):
        extract_claims(
            {"title": "t", "body": "b", "files": []},
            {"model": "m", "api_key": "k", "base_url": "http://x/v1"},
            session_dir,
            chat=lambda messages, **kw: "not json at all",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_claims.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claims'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/claims.py
"""Phase 2: tách PR description thành các claim kiểm chứng được (LLM)."""
import json
import re
from pathlib import Path

from llm import chat as _default_chat

SCHEMA_HINT = """
Tách mô tả PR dưới đây thành các claim kiểm chứng được (mỗi claim phải có thể
xác minh bằng cách đọc code). Trả về JSON array đúng schema:
[{"id": "C1", "text": "<ngắn gọn>", "category": "feature|bugfix|refactor|perf|ux|docs",
  "files": ["<file liên quan, rỗng nếu không rõ>"], "docs": ["<docs bị claim này nhắc tới>"]}]
Không thêm text ngoài JSON. Nếu không có claim nào, trả về [].
"""


def _parse_claims(raw: str) -> list[dict]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("claims response must be a list")
    return data


def extract_claims(snapshot: dict, cfg: dict, session_dir: Path,
                   chat=_default_chat) -> list[dict]:
    """Tách claim từ snapshot body. Lưu claims.json, trả về list claims."""
    description = f"# Title: {snapshot['title']}\n\n{snapshot['body']}"
    file_names = [f["filename"] for f in snapshot.get("files", [])]
    messages = [
        {"role": "system", "content": SCHEMA_HINT},
        {"role": "user", "content": f"Description:\n{description}\n\nFiles changed:\n{file_names}"},
    ]
    try:
        raw = chat(messages, model=cfg["model"], api_key=cfg["api_key"],
                   base_url=cfg["base_url"])
        claims = _parse_claims(raw)
    except (json.JSONDecodeError, ValueError, RuntimeError) as e:
        raise RuntimeError(f"invalid claims response: {e}") from e

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "claims.json").write_text(json.dumps(claims, indent=2))
    return claims
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_claims.py -v`
Expected: PASS — `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/claims.py tests/test_claims.py
git commit -m "feat: add claim extraction phase"
```

---

### Task 7: Phase 3 — Workspace setup + verify agent

**Files:**
- Create: `cordis/minimal.cordis.yml`
- Create: `src/verify.py`
- Test: `tests/test_verify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_verify.py
import json
import subprocess

import pytest

from verify import build_verify_prompt, parse_findings, setup_workspace


def test_setup_workspace_clones_and_checks_out(tmp_path):
    # Tạo "remote" repo local với nhánh pull/7/head
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=origin, check=True)
    (origin / "app.py").write_text("print('base')\n")
    subprocess.run(["git", "add", "."], cwd=origin, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "base"], cwd=origin, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "pull/7/head"], cwd=origin, check=True)
    (origin / "app.py").write_text("print('feature')\n")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qam", "feat"], cwd=origin, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=origin, check=True)

    ws = tmp_path / "ws"
    setup_workspace("demo", "app", 7, ws, remote_url=str(origin))

    assert (ws / "app.py").read_text() == "print('feature')\n"


def test_parse_findings_ok(tmp_path):
    f = tmp_path / "findings.json"
    f.write_text(json.dumps({"claims": [{"id": "C1", "status": "PASS",
                                          "evidence": ["a.py:1"], "note": ""}],
                             "docs": [], "impact": [], "threads": [],
                             "unresolved_questions": []}))
    parsed = parse_findings(f)
    assert parsed["claims"][0]["status"] == "PASS"


def test_parse_findings_invalid(tmp_path):
    f = tmp_path / "findings.json"
    f.write_text("garbage")
    with pytest.raises(RuntimeError, match="invalid findings"):
        parse_findings(f)


def test_build_verify_prompt_contains_parts():
    snapshot = {"title": "T", "body": "B", "files": [{"filename": "a.py"}],
                "threads": [{"body": "c1", "resolved": False}], "commits": []}
    claims = [{"id": "C1", "text": "x", "category": "feature", "files": [], "docs": []}]
    prompt = build_verify_prompt(snapshot, claims)
    assert "findings.json" in prompt
    assert "C1" in prompt
    assert "FABRICATED" in prompt
    assert "UNVERIFIED" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'verify'`

- [ ] **Step 3: Copy cordis composition file**

Tải file composition gốc từ deepseek-harness repo (đã lấy trong lúc research — nội dung đầy đủ bên dưới):

```yaml
# cordis/minimal.cordis.yml
# Complete unattended minimal-agent composition for the Python SDK. The model
# sees one deployment-selected system prompt and only the owner-scoped
# persistent Bash and string-replace editor tools.
- id: sdk-jsonrpc-server
  name: '@deepseek-ai/dsh-sdk-jsonrpc-server'
  config:
    maxTokensAsSuccess: false

- id: llm-deepseek
  name: '@deepseek-ai/dsh-llm-deepseek'
  config:
    apiKeyEnv: DEEPSEEK_API_KEY
    streamIdleTimeoutMs: 172800000
    models:
      - id: !!js process.env.DSH_MODEL ?? 'deepseek-v4-flash'
        contextWindow: !!js Number(process.env.DSH_CONTEXT_WINDOW ?? 1000000)

- id: sandbox
  name: '@deepseek-ai/dsh-sandbox-local'

- id: sandbox-policy
  name: '@deepseek-ai/dsh-sandbox-policy'
  config:
    mode: danger-full-access
    workspaceRoot: !!js process.env.DSH_CWD ?? process.cwd()

- id: subprocess
  name: '@deepseek-ai/dsh-subprocess-local'

- id: pty
  name: '@deepseek-ai/dsh-terminal'

- id: terminal-bash
  name: '@deepseek-ai/dsh-terminal-bash'
  config:
    timeoutMs: 300000

- id: fs-local
  name: '@deepseek-ai/dsh-fs-local'
  config:
    cwd: !!js process.env.DSH_CWD ?? process.cwd()

- id: agent-spine
  name: '@deepseek-ai/dsh-agent-spine-demo'
  config:
    includeHarnessIdentity: false
    includeRuntimeContext: false
    persona: !!js process.env.DSH_SYSTEM_PROMPT ?? 'You are a helpful software engineer assistant.'
    workspaceContext: false
    skills:
      enabled: false
    toolBash: false
    toolJobs: false

- id: persistent-bash
  name: '@deepseek-ai/dsh-tool-bash-persistent'
  config:
    timeoutMs: 300000
    description: |-
      Run commands in a bash shell
      * When invoking this tool, the contents of the "command" parameter does NOT need to be XML-escaped.
      * You don't have access to the internet via this tool.
      * You do have access to a mirror of common linux and python packages via apt and pip.
      * State is persistent across command calls and discussions with the user.
      * To inspect a particular line range of a file, e.g. lines 10-25, try 'sed -n 10,25p /path/to/the/file'.
      * Please avoid commands that may produce a very large amount of output.
      * Please run long lived commands in the background, e.g. 'sleep 10 &' or start a server in the background.

- id: str-replace-editor
  name: '@deepseek-ai/dsh-tool-str-replace-editor'
  config:
    maxOutputChars: 16000

- id: sessions
  name: '@deepseek-ai/dsh-session-persistence-jsonl'
  config:
    root: !!js process.env.DSH_SESSION_ROOT ?? './.sessions'
    compression: none
```

Kiểm tra file hợp lệ: `python -c "import yaml, pathlib; print(yaml.safe_load(pathlib.Path('cordis/minimal.cordis.yml').read_text()))"` — nếu thiếu pyyaml thì `pip install pyyaml` (dev-only) rồi chạy lại. Expected: in ra list chứa các id.

- [ ] **Step 4: Write minimal implementation**

```python
# src/verify.py
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
    subprocess.run(["git", "fetch", "origin", f"pull/{n}/head:pr-{n}"],
                   cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-f", "pr-{n}"], cwd=workspace,
                   check=True, capture_output=True)


def build_verify_prompt(snapshot: dict, claims: list[dict]) -> str:
    """Prompt hướng dẫn agent verify trong workspace và ghi findings.json."""
    files_summary = [
        f"- {f['filename']} (+{f['additions']}/-{f['deletions']})" for f in snapshot["files"]
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

Cuối cùng: GHI file findings.json vào thư mục workspace ({Path('.').resolve()})
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
    try:
        data = json.loads(path.read_text())
        assert isinstance(data, dict)
        for key in ("claims", "docs", "impact", "threads", "unresolved_questions"):
            assert isinstance(data.get(key), list)
        for c in data["claims"]:
            assert c.get("id") and c.get("status") in (
                "PASS", "FAIL", "PARTIAL", "UNVERIFIED")
        for d in data["docs"]:
            assert d.get("status") in ("MATCH", "STALE", "WRONG", "FABRICATED")
    except (json.JSONDecodeError, AssertionError, KeyError) as e:
        raise RuntimeError(f"invalid findings: {e}") from e
    return data
```

Lưu ý: trong `setup_workspace`, thay `pr-{n}` bằng f-string khi thực thi (bản code trên đang có lỗi string — bước 5 dưới đây sửa cho đúng).

- [ ] **Step 5: Sửa lỗi f-string trong setup_workspace**

```python
def setup_workspace(owner: str, repo: str, n: int, workspace: Path,
                    remote_url: str | None = None) -> None:
    if not workspace.exists():
        url = remote_url or f"https://github.com/{owner}/{repo}.git"
        subprocess.run(["git", "clone", "--no-checkout", url, str(workspace)],
                       check=True, capture_output=True)
    branch = f"pr-{n}"
    subprocess.run(["git", "fetch", "origin", f"pull/{n}/head:{branch}"],
                   cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-f", branch], cwd=workspace,
                   check=True, capture_output=True)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_verify.py -v`
Expected: PASS — `4 passed`

- [ ] **Step 7: Commit**

```bash
git add cordis/minimal.cordis.yml src/verify.py tests/test_verify.py
git commit -m "feat: add workspace setup and verify agent"
```

---

### Task 8: Phase 4 — Human gate

**Files:**
- Create: `src/human_gate.py`
- Test: `tests/test_human_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_human_gate.py
import json

import pytest

from human_gate import run_gate, trim_question


def test_trim_question_limits_words():
    q = "This is a very long question " * 10
    assert len(trim_question(q, max_words=20).split()) == 20


def test_trim_question_keeps_short():
    q = "Doc sai, phải không?"
    assert trim_question(q) == q


def test_run_gate_writes_answers(tmp_path, monkeypatch):
    findings = {
        "claims": [{"id": "C1", "status": "UNVERIFIED", "evidence": [], "note": ""}],
        "docs": [{"path": "docs/a.md", "status": "WRONG",
                  "what": "doc nói X, code làm Y"}],
        "impact": [], "threads": [],
        "unresolved_questions": ["Doc A đúng không?"],
    }
    monkeypatch.setattr("builtins.input",
                        lambda prompt: "y" if "sai doc" in prompt or "Doc A" in prompt else "n")
    session_dir = tmp_path / "s"
    answers = run_gate(findings, session_dir)
    assert len(answers) == 3
    assert all(a["answer"] for a in answers)
    saved = json.loads((session_dir / "answers.json").read_text())
    assert len(saved) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_human_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'human_gate'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/human_gate.py
"""Phase 4: human-in-the-loop — hỏi xác nhận khi docs sai hoặc claim chưa chắc."""
import json
from pathlib import Path


def trim_question(q: str, max_words: int = 20) -> str:
    words = q.split()
    if len(words) <= max_words:
        return q
    return " ".join(words[:max_words])


def _collect_questions(findings: dict) -> list[tuple[str, str]]:
    """Trả về [(question, kind)] — kind dùng để quyết định cách hỏi."""
    questions: list[tuple[str, str]] = []
    for d in findings.get("docs", []):
        if d["status"] in ("WRONG", "FABRICATED"):
            q = trim_question(f"Doc {d['path']}: {d['what']}. Doc sai, phải không?")
            questions.append((q, "doc"))
    for c in findings.get("claims", []):
        if c["status"] == "UNVERIFIED":
            q = trim_question(f"Claim {c['id']} không xác minh được. Giữ UNVERIFIED?")
            questions.append((q, "claim"))
    for q in findings.get("unresolved_questions", []):
        questions.append((trim_question(q), "free"))
    return questions


def run_gate(findings: dict, session_dir: Path, interactive: bool = True) -> list[dict]:
    """Hỏi từng câu (≤20 chữ). Lưu answers.json. Trả về list câu trả lời."""
    answers: list[dict] = []
    for question, kind in _collect_questions(findings):
        if interactive:
            answer = input(f"[harness] {question} (y/n hoặc trả lời tự do): ").strip()
        else:
            answer = "SKIPPED"
        answers.append({"question": question, "kind": kind, "answer": answer})

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "answers.json").write_text(json.dumps(answers, indent=2))
    return answers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_human_gate.py -v`
Expected: PASS — `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/human_gate.py tests/test_human_gate.py
git commit -m "feat: add interactive human gate"
```

---

### Task 9: Phase 5 — Synthesize report + post comment

**Files:**
- Create: `src/synthesize.py`
- Test: `tests/test_synthesize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synthesize.py
import json

import pytest

from synthesize import build_comment, build_report, post_comment

SNAPSHOT = {
    "owner": "demo", "repo": "app", "pr": 7,
    "title": "Add checkout flow", "author": "dev1", "base": "main", "head": "x",
    "labels": ["feature"], "body": "Adds checkout.",
    "files": [{"filename": "src/checkout.py", "status": "added",
               "additions": 50, "deletions": 0, "patch": ""}],
    "commits": [{"sha": "a", "message": "feat"}],
    "threads": [{"path": "src/checkout.py", "line": 3, "author": "r1",
                 "body": "Missing validation", "resolved": False, "outdated": False}],
}

CLAIMS = [
    {"id": "C1", "text": "Adds checkout", "category": "feature",
     "files": ["src/checkout.py"], "docs": []},
]

FINDINGS = {
    "claims": [{"id": "C1", "status": "PASS", "evidence": ["src/checkout.py:1"], "note": ""}],
    "docs": [{"path": "docs/payment.md", "status": "WRONG", "what": "doc nói retry 3, code retry 5"}],
    "impact": [{"requirement": "REQ-1 checkout", "impact": "CHANGED", "detail": "luồng mới"}],
    "threads": [{"text": "Missing validation", "status": "STILL_VALID", "note": "chưa fix"}],
    "unresolved_questions": [],
}

ANSWERS = [{"question": "Doc payment sai?", "kind": "doc", "answer": "y"}]


def test_build_report_vn(tmp_path):
    report = build_report(SNAPSHOT, CLAIMS, FINDINGS, ANSWERS, tmp_path)
    assert "## Verdict" in report
    assert "ĐÚNG" in report
    assert "WRONG" in report
    assert "REQ-1" in report
    assert "chưa fix" in report
    assert (tmp_path / "report.md").exists()


def test_build_comment_en_has_marker_and_verdict():
    comment = build_comment(SNAPSHOT, CLAIMS, FINDINGS, ANSWERS)
    assert "<!-- harness-pr-review -->" in comment
    assert "PASS" in comment
    assert "docs/payment.md" in comment
    assert "STILL_VALID" in comment


def test_post_comment_skips_if_marker_exists(monkeypatch):
    existing = [{"body": "<!-- harness-pr-review --> old"}]
    calls = []
    monkeypatch.setattr("synthesize.run_gh",
                        lambda args, **kw: (existing if "GET" in args else None))
    posted = post_comment("demo", "app", 7, "new", gh=lambda args, **kw: None,
                          list_comments=lambda: existing)
    assert posted is False


def test_post_comment_posts_when_no_marker(monkeypatch):
    posted = post_comment("demo", "app", 7, "new",
                          gh=lambda args, **kw: {"id": 1},
                          list_comments=lambda: [{"body": "other"}])
    assert posted is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthesize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'synthesize'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/synthesize.py
"""Phase 5: tổng hợp report tiếng Việt + post comment tiếng Anh lên PR."""
import json
from pathlib import Path

from gh import run_gh as _default_gh

MARKER = "<!-- harness-pr-review -->"
STATUS_VN = {"PASS": "ĐÚNG", "FAIL": "SAI", "PARTIAL": "ĐÚNG MỘT PHẦN",
             "UNVERIFIED": "CHƯA XÁC MINH"}


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
    """Viết report.md tiếng Việt. Trả về nội dung report."""
    verdict = _overall_verdict(findings)
    lines = [
        f"# Review PR #{snapshot['pr']} — {snapshot['title']}",
        "",
        f"- Tác giả: {snapshot['author']} | Base: {snapshot['base']} → Head: {snapshot['head']}",
        f"- Files thay đổi: {len(snapshot['files'])} | Commits: {len(snapshot['commits'])}",
        f"- **Verdict description: {verdict}**",
        "",
        "## Claims",
        "",
        "| Claim | Trạng thái | Bằng chứng | Ghi chú |",
        "|---|---|---|---|",
    ]
    for c in findings.get("claims", []):
        lines.append(
            f"| {c['id']} | {STATUS_VN.get(c['status'], c['status'])} | "
            f"{', '.join(c.get('evidence', [])) or '-'} | {c.get('note', '')} |")
    lines += [
        "", "## Docs (so với thực tế)", "",
        "| Doc | Trạng thái | Khác biệt |", "|---|---|---|",
    ]
    for d in findings.get("docs", []):
        lines.append(f"| {d['path']} | {d['status']} | {d.get('what', '')} |")
    lines += [
        "", "## Tác động tới requirement", "",
        "| Requirement | Impact | Chi tiết |", "|---|---|---|",
    ]
    for i in findings.get("impact", []):
        lines.append(f"| {i['requirement']} | {i['impact']} | {i.get('detail', '')} |")
    lines += [
        "", "## Review threads", "",
        "| Comment | Trạng thái | Ghi chú |", "|---|---|---|",
    ]
    for t in findings.get("threads", []):
        lines.append(f"| {t['text'][:120]} | {t['status']} | {t.get('note', '')} |")
    lines += ["", "## Confirm log", ""]
    for a in answers:
        lines.append(f"- **{a['question']}** → {a['answer']}")
    if not answers:
        lines.append("- (không có)")
    report = "\n".join(lines) + "\n"

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "report.md").write_text(report)
    return report


def build_comment(snapshot: dict, claims: list[dict], findings: dict,
                  answers: list[dict]) -> str:
    """Xây comment tiếng Anh (1 lần duy nhất, có marker)."""
    verdict = _overall_verdict(findings)
    claim_lines = "\n".join(
        f"- {c['id']}: {c['status']}" for c in findings.get("claims", []))
    doc_lines = "\n".join(
        f"- {d['path']}: {d['status']}" for d in findings.get("docs", []))
    thread_lines = "\n".join(
        f"- {t['text'][:100]} → {t['status']}" for t in findings.get("threads", []))
    return (
        f"## Harness PR Review\n\n"
        f"**Verdict: description is {verdict}**\n\n"
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
                 gh=_default_gh, list_comments=None) -> bool:
    """Post comment nếu chưa có marker. Trả về True nếu đã post."""
    if list_comments is None:
        list_comments = lambda: gh([f"api", f"repos/{owner}/{repo}/issues/{n}/comments"])
    for c in list_comments():
        if MARKER in c.get("body", ""):
            return False
    gh([f"api", f"repos/{owner}/{repo}/issues/{n}/comments",
        "-f", f"body={body}"])
    return True
```

Lưu ý: các test dùng `monkeypatch.setattr("synthesize.run_gh", ...)` — vì `synthesize.py` import `run_gh` ở module level, đảm bảo dòng import là `from gh import run_gh as _default_gh` (không `import gh`), để monkeypatch `synthesize.run_gh` không vô hiệu. Nếu test `test_post_comment_skips_if_marker_exists` thấy `calls` không dùng thì bỏ biến đó đi.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synthesize.py -v`
Expected: PASS — `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthesize.py tests/test_synthesize.py
git commit -m "feat: add report synthesis and PR comment"
```

---

### Task 10: CLI orchestration (run.py)

**Files:**
- Create: `src/run.py`
- Test: `tests/test_run.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run.py
import json
from pathlib import Path

from run import main

FIXTURES = {
    "snapshot.json": {
        "owner": "demo", "repo": "app", "pr": 7, "title": "T",
        "body": "B", "author": "a", "base": "main", "head": "x",
        "labels": [], "files": [], "commits": [], "threads": [],
    },
    "claims.json": [],
    "findings.json": {
        "claims": [], "docs": [], "impact": [], "threads": [],
        "unresolved_questions": [],
    },
}


def test_main_fixtures_mode(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for name, data in FIXTURES.items():
        (fixtures / name).write_text(json.dumps(data))
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    code = main(["demo/app", "7", "--fixtures", str(fixtures), "--no-post"])
    assert code == 0
    report = tmp_path / "sessions" / "demo" / "app" / "pr-7" / "report.md"
    assert report.exists()


def test_main_requires_gh(tmp_path, monkeypatch):
    monkeypatch.setattr("run.gh_available", lambda: False)
    code = main(["demo/app", "7", "--fixtures", str(tmp_path / "nonexistent"),
                 "--no-post"])
    assert code == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'run'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/run.py
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

    if "#" in args.pr and args.number is None:
        owner, repo, num = args.pr.replace("/", " ").split("#")
        owner, repo = args.pr.split("/")[:2]
        num = args.pr.split("#")[1]
    else:
        parts = args.pr.split("/")
        if len(parts) != 2 or args.number is None:
            print("usage: python -m src.run <owner>/<repo> <pr-number>",
                  file=sys.stderr)
            return 2
        owner, repo = parts
        num = str(args.number)

    cfg = load_config()
    if not cfg.api_key and args.fixtures is None:
        print("DEEPSEEK_API_KEY chưa set (xem .env.example)", file=sys.stderr)
        return 3
    if not gh_available() and args.fixtures is None:
        print("gh CLI chưa có hoặc chưa auth (gh auth login)", file=sys.stderr)
        return 2

    session_dir = cfg.session_root / owner / repo / f"pr-{num}"
    session_dir.mkdir(parents=True, exist_ok=True)

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
        workspace = session_dir / "workspace"
        setup_workspace(owner, repo, int(num), workspace)
        findings = _load_or_skip("findings.json", session_dir, args.force)
        if findings is None:
            findings = run_verify(
                {"model": cfg.model}, workspace, session_dir, snapshot, claims)

    answers = _load_or_skip("answers.json", session_dir, args.force)
    if answers is None:
        answers = run_gate(findings, session_dir, interactive=not args.skip_human)

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


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_run.py -v`
Expected: PASS — `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/run.py tests/test_run.py
git commit -m "feat: add CLI orchestration"
```

---

### Task 11: E2E + README + full suite

**Files:**
- Create: `tests/test_e2e.py`
- Create: `README.md`

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_e2e.py
"""E2E chạy pipeline đầy đủ qua --fixtures (không gọi gh/model)."""
import json
import subprocess
import sys
from pathlib import Path

FIXTURES = {
    "snapshot.json": {
        "owner": "demo", "repo": "app", "pr": 7, "title": "Add checkout",
        "body": "Adds checkout. Fixes retry.", "author": "dev1",
        "base": "main", "head": "feature/x", "labels": ["feature"],
        "files": [{"filename": "src/checkout.py", "status": "added",
                   "additions": 10, "deletions": 0, "patch": ""}],
        "commits": [{"sha": "a", "message": "feat"}],
        "threads": [{"path": "src/checkout.py", "line": 1, "author": "r",
                     "body": "check validation", "resolved": False,
                     "outdated": False}],
    },
    "claims.json": [
        {"id": "C1", "text": "Adds checkout", "category": "feature",
         "files": ["src/checkout.py"], "docs": []},
    ],
    "findings.json": {
        "claims": [{"id": "C1", "status": "PASS",
                    "evidence": ["src/checkout.py:1"], "note": ""}],
        "docs": [{"path": "docs/checkout.md", "status": "WRONG",
                  "what": "doc nói X, code làm Y"}],
        "impact": [{"requirement": "REQ-1", "impact": "CHANGED", "detail": "d"}],
        "threads": [{"text": "check validation", "status": "STILL_VALID",
                     "note": "chưa fix"}],
        "unresolved_questions": ["Docs checkout sai?"],
    },
}


def test_e2e_fixtures(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for name, data in FIXTURES.items():
        (fixtures / name).write_text(json.dumps(data))

    env = {"PYTHONPATH": "src", "DSH_SESSION_ROOT": str(tmp_path / "sessions")}
    proc = subprocess.run(
        [sys.executable, "-m", "src.run", "demo/app", "7",
         "--fixtures", str(fixtures), "--no-post", "--skip-human"],
        capture_output=True, text=True, env=env,
        cwd=Path(__file__).resolve().parents[1])
    assert proc.returncode == 0, proc.stderr

    report = Path(env["DSH_SESSION_ROOT"]) / "demo" / "app" / "pr-7" / "report.md"
    text = report.read_text()
    assert "## Verdict" in text
    assert "docs/checkout.md" in text
    assert "REQ-1" in text
    assert "SKIPPED" in text
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m pytest tests/test_e2e.py -v`
Expected: PASS — `1 passed`

- [ ] **Step 3: Write README**

```markdown
# Harness PR Review

Headless PR review chạy local dựa trên DeepSeek Harness SDK: deep-dive code,
xác minh PR description theo từng claim, kiểm tra docs trong repo có đúng với
thực tế không, phân tích tác động tới requirement, human-in-the-loop khi không
chắc (≤20 chữ/câu). Output: report tiếng Việt local + 1 comment tiếng Anh lên PR.

## Cài đặt

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .[dev]
gh auth login          # bắt buộc
export DEEPSEEK_API_KEY=sk-...   # xem .env.example
```

## Dùng

```bash
python -m src.run owner/repo 123              # interactive
python -m src.run owner/repo 123 --skip-human # batch, không hỏi
python -m src.run owner/repo 123 --no-post    # không post comment
```

Kết quả tại `sessions/<owner>/<repo>/pr-<n>/report.md`.

## Chạy test

```bash
python -m pytest -v
```
```

- [ ] **Step 4: Run full suite**

Run: `python -m pytest -v`
Expected: PASS — tất cả test (smoke 1 + config 2 + gh 3 + snapshot 2 + llm 3 + claims 2 + verify 4 + human_gate 3 + synthesize 4 + run 2 + e2e 1 = 27 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e.py README.md
git commit -m "docs: add README and e2e test"
```

---

## Self-Review Checklist

- **Spec coverage:** snapshot (T1-T4), claims (T5-T6), verify + docs reality-check + impact + threads (T7), human gate ≤20 chữ (T8), report VN + comment EN + 1 comment idempotent (T9), orchestration + skip-human + force + fixtures e2e (T10-T11), error handling gh/model/retry (T3, T5, T10), testing per phase (T1-T11). ✅
- **Placeholders:** không có TBD/TODO; mọi step đều có code hoặc lệnh cụ thể. ✅
- **Type consistency:** `run_gh(args, *, json=True)` (T3) dùng nhất quán ở T4, T9; `build_snapshot(owner, repo, n, session_dir, gh=...)` (T4) khớp call trong T10; `extract_claims(snapshot, cfg, session_dir, chat=...)` (T6) khớp T10; `run_verify(cfg, workspace, session_dir, snapshot, claims)` (T7) khớp T10; `run_gate(findings, session_dir, interactive=...)` (T8) khớp T10; `build_report/build_comment/post_comment` (T9) khớp T10. Schema JSON (claims/findings/answers) giữ nguyên giữa các task. ✅
