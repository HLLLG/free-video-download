import os
from pathlib import Path

from ..config import TEMP_ROOT, load_backend_env


load_backend_env()


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

# Free 用户默认每天 3 次；可通过环境变量覆盖，<=0 表示关闭限额。
SUMMARY_DAILY_LIMIT_PER_IP = int(os.getenv("SUMMARY_DAILY_LIMIT_PER_IP", "3"))
SUMMARY_MAX_DURATION_SECONDS = int(os.getenv("SUMMARY_MAX_DURATION_SECONDS", str(40 * 60)))
PRO_SUMMARY_MAX_DURATION_SECONDS = int(
    os.getenv("PRO_SUMMARY_MAX_DURATION_SECONDS", str(120 * 60))
)
SUMMARY_TASK_TTL_SECONDS = int(os.getenv("SUMMARY_TASK_TTL_SECONDS", str(30 * 60)))
SUMMARY_LLM_TIMEOUT_SECONDS = int(os.getenv("SUMMARY_LLM_TIMEOUT_SECONDS", "120"))
SUMMARY_CHAT_TIMEOUT_SECONDS = int(os.getenv("SUMMARY_CHAT_TIMEOUT_SECONDS", "60"))

# Bilibili 登录态 Cookie：B 站 AI 生成字幕、AI 翻译字幕、部分 UP 上传字幕
# 必须带 SESSDATA 才能在 /x/player/v2 拿到 subtitles 列表。
# 这里的 Cookie 由站长（运营方）在 .env 提供，所有用户共用，不暴露给前端。
# 一旦 Cookie 失效（B 站约 1-3 个月强制刷新），需要站长手动更新。
BILIBILI_SESSDATA = os.getenv("BILIBILI_SESSDATA", "").strip()
BILIBILI_BILI_JCT = os.getenv("BILIBILI_BILI_JCT", "").strip()
BILIBILI_BUVID3 = os.getenv("BILIBILI_BUVID3", "").strip()


SUMMARY_ROOT: Path = TEMP_ROOT / "summaries"
SUMMARY_ROOT.mkdir(parents=True, exist_ok=True)

