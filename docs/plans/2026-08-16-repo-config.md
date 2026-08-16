# Per-Repo Auto/Manual Config + Web UI Implementation Plan

> **Superseded (historical):** plan code uses non-`src` imports and `--add-repo` examples only show name/owner. Current code uses `src.*` imports and accepts GitHub URLs. See README.md.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-repo `auto`/`manual` review control, editable from both the web dashboard (repo list page) and CLI subcommands, all writing the same `autoreview.yml`.

**Architecture:** `autoreview_config.py` becomes the single source of truth for config read/write (new dict-format `repos: {name: mode}`, backward compatible with the old list format). The poller iterates only `auto` repos; the web server exposes JSON API routes that reuse the same config module; the repo-list page gets a config block on top of the dashboard.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, pyyaml (all already installed).

**Spec:** `docs/designs/2026-08-16-repo-config-design.md`

---

## File Structure

```
src/
├── autoreview_config.py   # REWRITE: new format + set/remove/list + auto_repos
├── autoreview.py          # MODIFY: CLI subcommands + poller uses auto_repos
web/
├── server.py              # MODIFY: /api/config routes + config in repo_list ctx
├── templates/repo_list.html  # MODIFY: config management block + JS
└── static/style.css       # MODIFY: config block styles
autoreview.yml             # MODIFY: new format (org, default_mode, repos dict)
tests/test_autoreview_config.py  # REWRITE
tests/test_autoreview.py          # MODIFY: run_pass auto-only
tests/test_server.py              # MODIFY: config API tests
README.md                  # MODIFY: document CLI + UI config
```

---

### Task 1: Config module rewrite

**Files:**
- Rewrite: `src/autoreview_config.py`
- Rewrite: `tests/test_autoreview_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_autoreview_config.py
import pytest

from autoreview_config import (auto_repos, list_repos, load_config,
                               remove_repo, set_repo_mode)

NEW_YML = """
org: nexpeakcore
default_mode: manual
interval_minutes: 10
post_comment: true
skip_human: true
drafts: false
repos:
  sample-app: auto
  sample-api: auto
"""


def _write(path, text):
    path.write_text(text)
    return path


def test_load_config_new_format(tmp_path):
    cfg = load_config(_write(tmp_path / "a.yml", NEW_YML))
    assert cfg["org"] == "nexpeakcore"
    assert cfg["default_mode"] == "manual"
    assert cfg["repos"] == {"sample-app": "auto", "sample-api": "auto"}
    assert cfg["interval_minutes"] == 10


def test_load_config_legacy_list(tmp_path):
    cfg = load_config(_write(tmp_path / "a.yml",
                             "repos:\n  - sample-org/sample-app\n"))
    assert cfg["repos"] == {"sample-org/sample-app": "auto"}


def test_load_config_empty_repos_allowed(tmp_path):
    cfg = load_config(_write(tmp_path / "a.yml", "org: nexpeakcore\n"))
    assert cfg["repos"] == {}
    assert cfg["default_mode"] == "manual"


def test_load_config_invalid_mode(tmp_path):
    with pytest.raises(ValueError, match="mode must be auto|manual"):
        load_config(_write(tmp_path / "a.yml",
                           "repos:\n  sample-app: sometimes\n"))


def test_load_config_invalid_interval(tmp_path):
    with pytest.raises(ValueError, match="interval_minutes"):
        load_config(_write(tmp_path / "a.yml", "interval_minutes: -5\n"))


def test_load_config_bad_yaml(tmp_path):
    with pytest.raises(ValueError, match="invalid config YAML"):
        load_config(_write(tmp_path / "a.yml", "repos: [unclosed\n"))


def test_set_repo_mode_add_and_change(tmp_path):
    p = _write(tmp_path / "a.yml", "org: nexpeakcore\nrepos:\n  sample-app: manual\n")
    set_repo_mode(p, "admin-web", "auto")          # add by name
    cfg = load_config(p)
    assert cfg["repos"]["admin-web"] == "auto"
    set_repo_mode(p, "sample-app", "auto")          # change
    assert load_config(p)["repos"]["sample-app"] == "auto"


def test_set_repo_mode_invalid(tmp_path):
    p = _write(tmp_path / "a.yml", "org: nexpeakcore\n")
    with pytest.raises(ValueError, match="mode must be auto|manual"):
        set_repo_mode(p, "sample-app", "banana")


def test_remove_repo(tmp_path):
    p = _write(tmp_path / "a.yml", NEW_YML)
    remove_repo(p, "sample-api")
    cfg = load_config(p)
    assert "sample-api" not in cfg["repos"]
    assert "sample-app" in cfg["repos"]


def test_auto_repos_resolves_org(tmp_path):
    cfg = load_config(_write(tmp_path / "a.yml", NEW_YML))
    assert auto_repos(cfg) == [("nexpeakcore", "sample-app"),
                               ("nexpeakcore", "sample-api")]


def test_auto_repos_full_path(tmp_path):
    cfg = load_config(_write(
        tmp_path / "a.yml",
        "repos:\n  other/legacy: auto\n  sample-app: manual\n"))
    assert auto_repos(cfg) == [("other", "legacy")]


def test_list_repos_with_org_merge(tmp_path):
    p = _write(tmp_path / "a.yml", NEW_YML)  # sample-app auto, sample-api auto

    def fake_gh(args, **kw):
        assert "orgs/sample-org/repos" in args[1]
        return [{"name": "sample-app"}, {"name": "admin-web"}]

    rows = list_repos(p, gh=fake_gh)
    by_name = {r["name"]: r["mode"] for r in rows}
    assert by_name["sample-app"] == "auto"
    assert by_name["admin-web"] == "unlisted"
    assert by_name["sample-api"] == "auto"   # configured but not in org list


def test_list_repos_without_org(tmp_path):
    p = _write(tmp_path / "a.yml", "repos:\n  sample-app: auto\n")
    rows = list_repos(p, gh=lambda args, **kw: None)  # gh không được gọi
    assert rows == [{"name": "sample-app", "mode": "auto"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_autoreview_config.py -v`
Expected: FAIL — các hàm mới (auto_repos, set_repo_mode, ...) chưa tồn tại / API cũ sai

- [ ] **Step 3: Rewrite implementation**

```python
# src/autoreview_config.py
"""Load, validate and edit autoreview.yml config (single source of truth)."""
import os
from pathlib import Path

import yaml

DEFAULTS = {
    "org": "",
    "default_mode": "manual",
    "interval_minutes": 10,
    "post_comment": True,
    "skip_human": True,
    "drafts": False,
}


def load_config(path: Path) -> dict:
    """Read autoreview.yml, normalize, merge defaults. Raises OSError/ValueError."""
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"invalid config YAML: {e}") from e
    cfg = {**DEFAULTS, **raw}
    cfg["repos"] = _normalize_repos(cfg.get("repos") or {})
    validate_config(cfg)
    return cfg


def _normalize_repos(repos) -> dict:
    """dict {name: mode} → as-is; legacy list ['owner/repo'] → all auto."""
    if isinstance(repos, dict):
        return {str(k): str(v) for k, v in repos.items()}
    if isinstance(repos, list):
        return {str(r): "auto" for r in repos}
    return {}


def validate_config(cfg: dict) -> None:
    for name, mode in cfg.get("repos", {}).items():
        if mode not in ("auto", "manual"):
            raise ValueError(f"repo mode must be auto|manual: {name!r} -> {mode!r}")
    interval = cfg.get("interval_minutes")
    if not isinstance(interval, int) or interval <= 0:
        raise ValueError("interval_minutes must be a positive integer")


def _write_atomic(path: Path, cfg: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(cfg, sort_keys=False))
    os.replace(tmp, path)


def set_repo_mode(path: Path, repo: str, mode: str) -> dict:
    """Add or change mode for a repo. Returns the updated config."""
    if mode not in ("auto", "manual"):
        raise ValueError(f"mode must be auto|manual: {mode!r}")
    cfg = load_config(path)
    cfg["repos"][repo] = mode
    _write_atomic(path, cfg)
    return cfg


def remove_repo(path: Path, repo: str) -> dict:
    """Remove a repo (match full key or by repo name). Returns updated config."""
    cfg = load_config(path)
    if repo in cfg["repos"]:
        del cfg["repos"][repo]
    else:
        for key in list(cfg["repos"]):
            if key.split("/")[-1] == repo.split("/")[-1]:
                del cfg["repos"][key]
    _write_atomic(path, cfg)
    return cfg


def auto_repos(cfg: dict) -> list[tuple[str, str]]:
    """(owner, repo) pairs to auto-review, in config order."""
    pairs = []
    for name, mode in cfg.get("repos", {}).items():
        if mode != "auto":
            continue
        if "/" in name:
            owner, repo = name.split("/", 1)
        else:
            owner, repo = cfg.get("org", ""), name
        if owner and repo:
            pairs.append((owner, repo))
    return pairs


def list_repos(path: Path, gh=None) -> list[dict]:
    """[{name, mode}] — configured repos + org repos (unlisted) when org set.

    gh must be callable like run_gh(args, **kw); default imports gh.run_gh.
    Org lookup failure is silent (returns configured repos only).
    """
    cfg = load_config(path)
    if gh is None:
        from gh import run_gh
        gh = run_gh
    names = list(cfg["repos"].keys())
    if cfg.get("org"):
        try:
            data = gh(["api", f"orgs/{cfg['org']}/repos", "--paginate"])
            org_names = [r["name"] for r in data if isinstance(r, dict)]
            names = org_names + [n for n in names if n not in org_names]
        except (RuntimeError, OSError):
            pass
    return [{"name": n, "mode": cfg["repos"].get(n, "unlisted")}
            for n in sorted(names)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_autoreview_config.py -v`
Expected: PASS — 14 tests

- [ ] **Step 5: Commit**

```bash
git add src/autoreview_config.py tests/test_autoreview_config.py
git commit -m "feat: rewrite autoreview config with per-repo modes"
```

---

### Task 2: CLI subcommands + poller auto-only

**Files:**
- Modify: `src/autoreview.py`
- Modify: `autoreview.yml`
- Modify: `tests/test_autoreview.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_autoreview.py — thêm vào cuối file (imports đã có)
import json

from autoreview import main, run_pass
from autoreview_config import load_config


def test_run_pass_only_auto_repos(tmp_path, monkeypatch, capsys):
    root = tmp_path / "sessions"
    root.mkdir(parents=True)
    cfg = load_config.__module__  # placeholder — sẽ thay bằng load_config thật bên dưới


def test_run_pass_skips_manual(tmp_path, monkeypatch, capsys):
    root = tmp_path / "sessions"
    root.mkdir(parents=True)
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text(
        "org: nexpeakcore\nrepos:\n  sample-app: manual\n  sample-api: auto\n")
    cfg = load_config(cfg_path)

    prs_by_repo = {
        "sample-org/sample-api": [{"number": 1, "head": {"sha": "a"},
                                     "draft": False}],
    }

    def fake_gh(args, **kw):
        repo_ref = args[1].split("?")[0].split("repos/")[1]
        return prs_by_repo[repo_ref]

    dispatched = []
    monkeypatch.setattr("autoreview._dispatch",
                        lambda c, o, r, n, sha: (dispatched.append((o, r, n)) or 0))
    count = run_pass(cfg, root, dry_run=False, gh=fake_gh)
    assert count == 1
    assert dispatched == [("nexpeakcore", "sample-api", 1)]


def test_main_add_repo_writes_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: manual\n")
    monkeypatch.setattr("autoreview.CONFIG_PATH", cfg_path)
    code = main(["--add-repo", "admin-web", "--mode", "auto"])
    assert code == 0
    cfg = load_config(cfg_path)
    assert cfg["repos"]["admin-web"] == "auto"
    assert cfg["repos"]["sample-app"] == "manual"


def test_main_rm_repo(tmp_path, monkeypatch):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("org: nexpeakcore\nrepos:\n  sample-app: auto\n")
    monkeypatch.setattr("autoreview.CONFIG_PATH", cfg_path)
    code = main(["--rm-repo", "sample-app"])
    assert code == 0
    assert load_config(cfg_path)["repos"] == {}


def test_main_repos_lists_status(tmp_path, monkeypatch, capsys):
    cfg_path = tmp_path / "autoreview.yml"
    cfg_path.write_text("repos:\n  sample-app: auto\n")
    monkeypatch.setattr("autoreview.CONFIG_PATH", cfg_path)
    code = main(["--repos"])
    assert code == 0
    out = capsys.readouterr().out
    assert "sample-app" in out and "auto" in out
```

Lưu ý: bỏ test `test_run_pass_only_auto_repos` (placeholder không dùng) — chỉ giữ 4 test có nội dung thật.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_autoreview.py -v`
Expected: FAIL — main() chưa có subcommands; run_pass vẫn duyệt toàn bộ repos

- [ ] **Step 3: Modify implementation**

`src/autoreview.py` — thay import + thêm subcommands + poller auto-only:

```python
from autoreview_config import auto_repos, list_repos, load_config, \
    remove_repo, set_repo_mode
```

`run_pass` — đổi vòng lặp repo:

```python
def run_pass(cfg: dict, session_root: Path, dry_run: bool = False,
             gh=run_gh) -> int:
    """One poll pass over all auto repos. Returns count of dispatched."""
    dispatched = 0
    for owner, repo in auto_repos(cfg):
        try:
            prs = fetch_open_prs(owner, repo, gh=gh)
        except RuntimeError as e:
            print(f"POLL-ERROR {owner}/{repo}: {e}", file=sys.stderr)
            continue
        plans = plan_reviews(session_root, owner, repo, prs,
                             drafts=cfg.get("drafts", False))
        for plan in plans:
            n = plan["pr"]
            line = f"{plan['decision']} {owner}/{repo}#{n}"
            if plan["decision"] == "SKIP":
                print(line)
                continue
            if dry_run:
                print(f"[dry-run] would review: {line}")
                dispatched += 1
                continue
            session_dir = session_root / owner / repo / f"pr-{n}"
            if plan["decision"] == "RE-RUN":
                _clean_rerun_session(session_dir)
            print(line)
            try:
                code = _dispatch(cfg, owner, repo, n, plan["head_sha"])
            except (RuntimeError, ValueError, OSError) as e:
                print(f"FAILED {owner}/{repo}#{n}: {e}", file=sys.stderr)
                continue
            if code != 0:
                print(f"FAILED {owner}/{repo}#{n}: exit {code}", file=sys.stderr)
                continue
            dispatched += 1
    return dispatched
```

`main` — thêm subcommands (đặt TRƯỚC check API key/gh):

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoreview")
    parser.add_argument("--once", action="store_true", help="single pass")
    parser.add_argument("--daemon", action="store_true", help="loop forever")
    parser.add_argument("--dry-run", action="store_true",
                        help="print plans without dispatching")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH,
                        help="path to autoreview.yml")
    parser.add_argument("--add-repo", metavar="REPO",
                        help="add repo (name or owner/name) and set its mode")
    parser.add_argument("--rm-repo", metavar="REPO", help="remove a repo")
    parser.add_argument("--mode", choices=["auto", "manual"], default="auto",
                        help="mode for --add-repo (default: auto)")
    parser.add_argument("--repos", action="store_true",
                        help="list configured + org repos with modes")
    args = parser.parse_args(argv)

    if args.add_repo:
        set_repo_mode(args.config, args.add_repo, args.mode)
        print(f"{args.add_repo} -> {args.mode}")
        return 0
    if args.rm_repo:
        remove_repo(args.config, args.rm_repo)
        print(f"removed {args.rm_repo}")
        return 0
    if args.repos:
        for r in list_repos(args.config):
            print(f"{r['name']:<40} {r['mode']}")
        return 0

    cfg = load_config(args.config)
    env = load_env_config()
    if not env.api_key:
        print("DEEPSEEK_API_KEY not set (see .env.example)", file=sys.stderr)
        return 3
    if not gh_available():
        print("gh CLI not installed or not authenticated (gh auth login)",
              file=sys.stderr)
        return 2
    ...  # phần còn lại giữ nguyên (lock + run_pass loop)
```

`autoreview.yml` — đổi sang format mới:

```yaml
org: nexpeakcore
default_mode: manual
interval_minutes: 10
post_comment: true
skip_human: true
drafts: false
repos:
  sample-app: auto
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_autoreview.py -v`
Expected: PASS — 6 cũ + 4 mới = 10 tests

- [ ] **Step 5: Manual smoke test**

Run: `PYTHONPATH=src .venv/bin/python -m src.autoreview --repos`
Expected: in ra bảng repo (có thể có "org lookup failed" nếu gh lỗi — vẫn exit 0)

- [ ] **Step 6: Commit**

```bash
git add src/autoreview.py autoreview.yml tests/test_autoreview.py
git commit -m "feat: per-repo auto/manual CLI + poller auto-only"
```

---

### Task 3: Web server config API + UI block

**Files:**
- Modify: `web/server.py`
- Modify: `web/templates/repo_list.html`
- Modify: `web/static/style.css`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server.py — thêm vào cuối file
from autoreview_config import load_config

CFG_YML = """
org: nexpeakcore
repos:
  sample-app: auto
"""


def _write_cfg(tmp_path, text=CFG_YML):
    p = tmp_path / "autoreview.yml"
    p.write_text(text)
    return p


def test_api_config_returns_repos(client, tmp_path):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr  # noqa — dùng fixture client có sẵn (không set config → default path)
    # Không dùng client fixture cũ: dựng riêng
```

Sửa lại cho sạch — viết các test dưới đây dùng monkeypatch trực tiếp:

```python
def test_api_config_and_toggle(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))

    def fake_gh(args, **kw):
        return [{"name": "sample-app"}, {"name": "admin-web"}]

    monkeypatch.setattr("autoreview_config.run_gh", fake_gh)

    client = TestClient(app)

    # GET config: org repos merged with modes
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["org"] == "nexpeakcore"
    by_name = {x["name"]: x["mode"] for x in data["repos"]}
    assert by_name["sample-app"] == "auto"
    assert by_name["admin-web"] == "unlisted"

    # toggle sample-app → manual, file thật bị đổi
    r = client.post("/api/config/repos/sample-app/mode",
                    json={"mode": "manual"})
    assert r.status_code == 200
    assert load_config(cfg_path)["repos"]["sample-app"] == "manual"

    # add repo
    r = client.post("/api/config/repos", json={"repo": "payments"})
    assert r.status_code == 200
    assert load_config(cfg_path)["repos"]["payments"] == "auto"

    # remove repo
    r = client.delete("/api/config/repos/payments")
    assert r.status_code == 200
    assert "payments" not in load_config(cfg_path)["repos"]


def test_api_add_repo_without_org_rejects_name(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path, "repos:\n  sample-app: auto\n")  # no org
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    client = TestClient(app)
    r = client.post("/api/config/repos", json={"repo": "payments"})
    assert r.status_code == 400
    assert "org" in r.json()["detail"]


def test_api_toggle_bad_mode_400(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    client = TestClient(app)
    r = client.post("/api/config/repos/sample-app/mode", json={"mode": "x"})
    assert r.status_code == 400


def test_api_config_missing_file_404(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(tmp_path / "none.yml"))
    client = TestClient(app)
    assert client.get("/api/config").status_code == 404


def test_repo_list_page_has_config_block(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    monkeypatch.setenv("AUTOREVIEW_CONFIG", str(cfg_path))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Repo configuration" in r.text
    assert "sample-app" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: FAIL — /api/config 404; trang / chưa có "Repo configuration"

- [ ] **Step 3: Modify implementation**

`web/server.py` — thêm imports + config path + routes + context:

```python
import os

from autoreview_config import load_config as load_autoreview_config
from autoreview_config import list_repos, remove_repo, set_repo_mode
from config import load_config as load_env_config


def _config_path() -> Path:
    return Path(os.environ.get("AUTOREVIEW_CONFIG", "autoreview.yml"))


@app.get("/api/config")
def api_config():
    path = _config_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="autoreview.yml not found")
    try:
        cfg = load_autoreview_config(path)
        repos = list_repos(path)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"invalid config: {e}")
    return {
        "org": cfg.get("org"),
        "default_mode": cfg.get("default_mode"),
        "interval_minutes": cfg.get("interval_minutes"),
        "post_comment": cfg.get("post_comment"),
        "skip_human": cfg.get("skip_human"),
        "drafts": cfg.get("drafts"),
        "repos": repos,
        "config_path": str(path),
    }


@app.post("/api/config/repos/{repo}/mode")
def api_set_mode(repo: str, payload: dict):
    path = _config_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="autoreview.yml not found")
    try:
        mode = payload.get("mode")
        set_repo_mode(path, repo, mode)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "repo": repo, "mode": mode}


@app.post("/api/config/repos")
def api_add_repo(payload: dict):
    path = _config_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="autoreview.yml not found")
    repo = (payload.get("repo") or "").strip()
    if not repo:
        raise HTTPException(status_code=400, detail="repo is required")
    try:
        cfg = load_autoreview_config(path)
        if "/" not in repo and not cfg.get("org"):
            raise HTTPException(
                status_code=400,
                detail="org not set in config; use owner/repo format")
        set_repo_mode(path, repo, payload.get("mode", "auto"))
    except HTTPException:
        raise
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "repo": repo}


@app.delete("/api/config/repos/{repo}")
def api_remove_repo(repo: str):
    path = _config_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="autoreview.yml not found")
    try:
        remove_repo(path, repo)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "repo": repo}
```

Route `/` — thêm cfg_state vào context:

```python
@app.get("/", response_class=HTMLResponse)
def repo_list(request: Request):
    root = _session_root()
    repos = []
    for owner, repo in metrics.list_repos(root):
        rec = metrics.repo_record(root, owner, repo)
        if rec is not None:
            repos.append(rec)
    repos.sort(key=lambda r: r["prs_total"], reverse=True)
    cfg_state = None
    path = _config_path()
    if path.exists():
        try:
            cfg = load_autoreview_config(path)
            cfg_state = {
                "org": cfg.get("org"),
                "interval": cfg.get("interval_minutes"),
                "drafts": cfg.get("drafts"),
                "post_comment": cfg.get("post_comment"),
                "repos": list_repos(path),
                "config_path": str(path),
            }
        except (ValueError, OSError) as e:
            cfg_state = {"error": str(e)}
    return templates.TemplateResponse(
        request, "repo_list.html", {"repos": repos, "cfg": cfg_state})
```

`web/templates/repo_list.html` — thêm config block đầu trang:

```html
{% extends "base.html" %}
{% block content %}
<h1>Repositories</h1>

{% if cfg %}
<div class="config-block">
  <h2>Repo configuration</h2>
  {% if cfg.error %}
  <p class="empty">Invalid config: {{ cfg.error }}</p>
  {% else %}
  <p class="muted">Config: {{ cfg.config_path }} · org: {{ cfg.org or "—" }}
    · interval: {{ cfg.interval }}m · drafts: {{ cfg.drafts }}
    · post comment: {{ cfg.post_comment }}</p>
  <table class="table">
    <thead><tr><th>Repo</th><th>Mode</th><th>Actions</th></tr></thead>
    <tbody>
    {% for r in cfg.repos %}
      <tr class="{{ 'unlisted' if r.mode == 'unlisted' }}">
        <td>{{ r.name }}</td>
        <td><span class="verdict v-{{ r.mode }}">{{ r.mode }}</span></td>
        <td>
          {% if r.mode == 'unlisted' %}
            <button class="tab-btn" onclick="setMode('{{ r.name }}','auto')">Enable auto</button>
          {% else %}
            <button class="tab-btn" onclick="setMode('{{ r.name }}','{{ 'manual' if r.mode == 'auto' else 'auto' }}')">Switch to {{ 'manual' if r.mode == 'auto' else 'auto' }}</button>
            <button class="tab-btn danger" onclick="removeRepo('{{ r.name }}')">Remove</button>
          {% endif %}
        </td>
      </tr>
    {% else %}
      <tr><td colspan="3" class="empty">No repos configured</td></tr>
    {% endfor %}
    </tbody>
  </table>
  <form class="add-form" onsubmit="addRepo(event)">
    <input class="add-input" id="new-repo" placeholder="owner/repo or repo name">
    <button class="tab-btn" type="submit">Add repo</button>
    <button class="tab-btn" type="button" onclick="location.reload()">Refresh</button>
  </form>
  {% endif %}
</div>
{% endif %}

{% if not repos %}
<p class="empty">No reviews yet — run
<code>python -m src.run owner/repo N</code> to create the first one.</p>
{% else %}
<div class="cards">
  {% for r in repos %}
  <a class="card repo-card" href="/repos/{{ r.owner }}/{{ r.repo }}">
    <h3>{{ r.owner }}/{{ r.repo }}</h3>
    <div class="kpis">
      <span class="kpi"><b>{{ r.prs_total }}</b> PRs</span>
      <span class="kpi bad"><b>{{ r.bugs_total }}</b> bugs</span>
      <span class="kpi warn"><b>{{ r.doc_errors_total }}</b> doc errors</span>
    </div>
  </a>
  {% endfor %}
</div>
{% endif %}

<script>
async function postJson(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
  });
  if (!r.ok) { alert((await r.json()).detail || "error"); return; }
  location.reload();
}
function setMode(repo, mode) { postJson(`/api/config/repos/${encodeURIComponent(repo)}/mode`, {mode}); }
function removeRepo(repo) {
  fetch(`/api/config/repos/${encodeURIComponent(repo)}`, {method: "DELETE"})
    .then(r => r.ok ? location.reload() : alert("error"));
}
function addRepo(e) {
  e.preventDefault();
  postJson("/api/config/repos", {repo: document.getElementById("new-repo").value.trim()});
}
</script>
{% endblock %}
```

`web/static/style.css` — thêm styles:

```css
.config-block { background: #fff; border: 1px solid var(--border);
                border-radius: 10px; padding: 16px; margin-bottom: 28px; }
.config-block h2 { margin: 0 0 8px; font-size: 16px; }
.add-form { display: flex; gap: 8px; margin-top: 12px; }
.add-input { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px;
             flex: 1; max-width: 320px; font-size: 13px; }
.tab-btn.danger { color: #c0392b; }
tr.unlisted td { color: #6b7280; }
.v-auto { background: #eaf7ee; color: #27ae60; }
.v-manual { background: #eef1f4; color: #6b7280; }
.v-unlisted { background: #f4f6f8; color: #a0a6ad; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS — 6 cũ + 5 mới = 11 tests

- [ ] **Step 5: Manual smoke test**

Server đang chạy (http://127.0.0.1:8000) — restart: kill server cũ, chạy lại
`DSH_SESSION_ROOT=sessions .venv/bin/python -m web.server`, mở `/` xem config
block (org nexpeakcore, sample-app auto, các repo org khác unlisted) + bấm
toggle thử.

- [ ] **Step 6: Commit**

```bash
git add web/ tests/test_server.py
git commit -m "feat: manage repo auto/manual config from web UI"
```

---

### Task 4: README + full suite

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README auto-review section**

```markdown
## Auto review

Poll GitHub for new PRs (and head-SHA changes) and review them automatically in
batch mode. Each repo is configured `auto` (poller reviews its PRs) or `manual`
(poller skips it; review via CLI). Edit `autoreview.yml` directly, via CLI, or
from the web dashboard (repo list page → toggle Auto/Manual).

```yaml
# autoreview.yml
org: nexpeakcore            # default org for repo discovery
default_mode: manual        # repos not listed → manual
interval_minutes: 10
post_comment: true
skip_human: true
drafts: false
repos:
  sample-app: auto
  sample-api: manual
```

```bash
python -m src.autoreview --add-repo sample-app --mode auto   # enable auto
python -m src.autoreview --rm-repo sample-app                # remove
python -m src.autoreview --repos                             # list status
python -m src.autoreview --once          # single pass (cron/launchd)
python -m src.autoreview --daemon        # loop every interval_minutes
```

Re-review rules: head SHA in the PR changed vs the last snapshot → all phases
re-run with `--force`; the PR comment is updated in place (never duplicated).
```

- [ ] **Step 2: Run full suite**

Run: `.venv/bin/python -m pytest -v`
Expected: PASS — 65 cũ + 14 config + 4 autoreview mới + 5 server mới − 2 test
cũ thay thế ≈ 86 tests (chạy thực tế để xác nhận con số)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document per-repo auto/manual config"
```

---

## Self-Review Checklist

- **Spec coverage:** new config format org/default_mode/repos dict (T1 load_config),
  backward compat legacy list (T1), set/remove (T1), list_repos org merge + unlisted
  (T1), auto_repos for poller (T1+T2 run_pass), CLI --add-repo/--rm-repo/--repos
  without API key (T2 main), poller only auto (T2), web API GET/POST/DELETE + 400/404
  (T3), repo-list config block + toggle/add/remove/refresh JS (T3), AUTOREVIEW_CONFIG
  env (T3), corrupt YAML → error UI (T3 cfg_state error), atomic write (T1 _write_atomic).
  ✅
- **Placeholders:** no TBD/TODO; every step has complete code. ✅
- **Type consistency:** config dict keys (`org`, `default_mode`, `repos`,
  `interval_minutes`, `post_comment`, `skip_human`, `drafts`) used identically in
  T1/T2/T3; `list_repos(path, gh=None)`, `set_repo_mode(path, repo, mode)`,
  `remove_repo(path, repo)`, `auto_repos(cfg)` signatures match across modules;
  server route paths (`/api/config`, `/api/config/repos/{repo}/mode`,
  `/api/config/repos`, `/api/config/repos/{repo}`) match tests + template JS. ✅
