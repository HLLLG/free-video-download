import os
from pathlib import Path


def load_backend_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


load_backend_env()


APP_NAME = "Free Video Download"
API_PREFIX = "/api"

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
BACKEND_DIR = Path(__file__).resolve().parents[1]
VAR_ROOT = Path(os.environ.get("FVD_VAR_DIR") or BACKEND_DIR / "var")
VAR_ROOT.mkdir(parents=True, exist_ok=True)

TEMP_ROOT = Path(os.environ.get("FVD_TEMP_DIR") or VAR_ROOT / "downloads")
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = Path(os.environ.get("FVD_DATABASE_PATH") or VAR_ROOT / "app.db")
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

TASK_TTL_SECONDS = 30 * 60
MAX_CONCURRENT_DOWNLOADS = 3
MAX_URL_LENGTH = 2048
MAX_DURATION_SECONDS = 4 * 60 * 60

DEFAULT_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]"
MERGE_OUTPUT_FORMAT = "mp4"
