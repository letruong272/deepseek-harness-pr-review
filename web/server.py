"""FastAPI app: PR review dashboard + repo auto/manual config management."""
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from autoreview_config import load_config as load_autoreview_config
from autoreview_config import list_repos, remove_repo, set_repo_mode
from config import load_config
from web import metrics

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="PR Review Dashboard")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _session_root() -> Path:
    return load_config().session_root


def _config_path() -> Path:
    return Path(os.environ.get("AUTOREVIEW_CONFIG", "autoreview.yml"))


@app.get("/", response_class=HTMLResponse)
def repo_list(request: Request):
    root = _session_root()
    repos = []
    for owner, repo in metrics.list_repos(root):
        rec = metrics.repo_record(root, owner, repo)
        if rec is not None:
            repos.append(rec)
    repos.sort(key=lambda r: r["prs_total"], reverse=True)
    return templates.TemplateResponse(
        request, "repo_list.html", {"repos": repos})


@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request):
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
        request, "config.html", {"cfg": cfg_state})


@app.get("/repos/{owner}/{repo}", response_class=HTMLResponse)
def repo_page(request: Request, owner: str, repo: str):
    rec = metrics.repo_record(_session_root(), owner, repo)
    if rec is None:
        raise HTTPException(status_code=404, detail="Repo not found in sessions")
    verdict_json = json.dumps(rec["verdict_count"])
    open_qs = sum(p["open_questions"] for p in rec["prs"])
    from gh import run_gh

    pr_rows = metrics.open_prs(_session_root(), owner, repo, gh=run_gh)
    return templates.TemplateResponse(
        request, "repo.html",
        {"repo": rec, "verdict_json": verdict_json, "open_qs": open_qs,
         "pr_rows": pr_rows})


@app.get("/repos/{owner}/{repo}/pr/{pr}", response_class=HTMLResponse)
def pr_page(request: Request, owner: str, repo: str, pr: int):
    detail = metrics.pr_detail(_session_root(), owner, repo, pr)
    if detail is None:
        raise HTTPException(status_code=404, detail="PR not found in sessions")
    return templates.TemplateResponse(
        request, "pr.html",
        {"detail": detail, "repo_owner": owner, "repo_name": repo})


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=6789)
