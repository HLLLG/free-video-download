import os
from pathlib import Path


APP_NAME = "Free Video Download"
API_PREFIX = "/api"

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
BACKEND_DIR = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path(os.environ.get("FVD_TEMP_DIR") or BACKEND_DIR / "var" / "downloads")
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

TASK_TTL_SECONDS = 30 * 60
MAX_CONCURRENT_DOWNLOADS = 3
MAX_URL_LENGTH = 2048
MAX_DURATION_SECONDS = 4 * 60 * 60

DEFAULT_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]"
MERGE_OUTPUT_FORMAT = "mp4"
