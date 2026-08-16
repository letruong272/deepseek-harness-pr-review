"""Wrapper mỏng quanh gh CLI. Gh phải được auth sẵn (gh auth login)."""
import json as _json
import subprocess


def _run_gh_impl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def run_gh(args: list[str], *, json: bool = True) -> dict | list:
    proc = _run_gh_impl(args + (["--jq", "."] if json else []))
    if proc.returncode != 0:
        raise RuntimeError(f"gh api failed: {proc.stderr.strip()}")
    if not json:
        return proc.stdout
    return _json.loads(proc.stdout)


def gh_available() -> bool:
    try:
        proc = _run_gh_impl(["--version"])
        return proc.returncode == 0
    except FileNotFoundError:
        return False
