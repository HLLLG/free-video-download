import os
from pathlib import Path

from ..config import TEMP_ROOT


def _load_backend_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
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


_load_backend_env()


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

SUMMARY_DAILY_LIMIT_PER_IP = int(os.getenv("SUMMARY_DAILY_LIMIT_PER_IP", "5"))
SUMMARY_MAX_DURATION_SECONDS = int(os.getenv("SUMMARY_MAX_DURATION_SECONDS", str(40 * 60)))
SUMMARY_TASK_TTL_SECONDS = int(os.getenv("SUMMARY_TASK_TTL_SECONDS", str(30 * 60)))
SUMMARY_LLM_TIMEOUT_SECONDS = int(os.getenv("SUMMARY_LLM_TIMEOUT_SECONDS", "120"))
SUMMARY_CHAT_TIMEOUT_SECONDS = int(os.getenv("SUMMARY_CHAT_TIMEOUT_SECONDS", "60"))

SUMMARY_ROOT: Path = TEMP_ROOT / "summaries"
SUMMARY_ROOT.mkdir(parents=True, exist_ok=True)

