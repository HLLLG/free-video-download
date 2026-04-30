import asyncio
import shutil
import time
import uuid
from pathlib import Path

from .models import SummaryTask
from .settings import SUMMARY_ROOT, SUMMARY_TASK_TTL_SECONDS


SUMMARY_TASKS: dict[str, SummaryTask] = {}
SUMMARY_SEMAPHORE = asyncio.Semaphore(2)


def create_summary_task(url: str, client_ip: str, title: str | None = None) -> SummaryTask:
    summary_id = uuid.uuid4().hex[:16]
    task = SummaryTask(summary_id=summary_id, url=url, client_ip=client_ip, title=title)
    SUMMARY_TASKS[summary_id] = task
    (SUMMARY_ROOT / summary_id).mkdir(parents=True, exist_ok=True)
    return task


def get_summary_task(summary_id: str) -> SummaryTask | None:
    return SUMMARY_TASKS.get(summary_id)


def remove_summary_task(summary_id: str) -> SummaryTask | None:
    task = SUMMARY_TASKS.pop(summary_id, None)
    shutil.rmtree(SUMMARY_ROOT / summary_id, ignore_errors=True)
    return task


def summary_workdir(summary_id: str) -> Path:
    path = SUMMARY_ROOT / summary_id
    path.mkdir(parents=True, exist_ok=True)
    return path


async def cleanup_expired_summary_tasks() -> None:
    while True:
        now = time.time()
        for summary_id, task in list(SUMMARY_TASKS.items()):
            if now - task.created_at > SUMMARY_TASK_TTL_SECONDS:
                remove_summary_task(summary_id)
        await asyncio.sleep(60)

