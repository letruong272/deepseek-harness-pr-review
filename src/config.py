"""Configuration from the environment. All env vars are optional.

A `.env` file next to the working directory is loaded first (simple KEY=VALUE
parser — no dotenv dependency); real environment variables win over it.
"""
import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    path = Path(".env")
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


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
