import asyncio
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from .config import MAX_CONCURRENT_DOWNLOADS, TASK_TTL_SECONDS


TaskStatus = Literal["queued", "running", "done", "error", "cancelled"]


@dataclass
class DownloadTask:
    task_id: str
    status: TaskStatus = "queued"
    pct: float | None = 0
    speed: float | None = None
    eta: float | None = None
    title: str | None = None
    file_path: str | None = None
    error: str | None = None
    stage: str = "queued"
    stage_text: str | None = None
    cancelled: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    workdir: str | None = None

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("workdir", None)
        return data


def cancel_task(task_id: str) -> DownloadTask | None:
    """标记任务为已取消，并清理临时目录。yt-dlp 进度 hook 会检测此标志并中止。"""
    task = TASKS.get(task_id)
    if not task:
        return None
    if task.status in ("done", "error", "cancelled"):
        return task
    task.cancelled = True
    task.status = "cancelled"
    task.stage = "cancelled"
    task.stage_text = "已取消"
    task.speed = None
    task.eta = None
    task.touch()
    return task


def remove_task(task_id: str) -> None:
    """清理任务的临时目录并从内存中删除任务记录。"""
    task = TASKS.pop(task_id, None)
    if task and task.workdir:
        shutil.rmtree(task.workdir, ignore_errors=True)


TASKS: dict[str, DownloadTask] = {}
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


def register_task(task_id: str, workdir: Path) -> DownloadTask:
    task = DownloadTask(task_id=task_id, workdir=str(workdir))
    TASKS[task_id] = task
    return task


def get_task(task_id: str) -> DownloadTask | None:
    return TASKS.get(task_id)


async def cleanup_expired_tasks() -> None:
    while True:
        now = time.time()
        for task_id, task in list(TASKS.items()):
            if now - task.created_at > TASK_TTL_SECONDS:
                if task.workdir:
                    shutil.rmtree(task.workdir, ignore_errors=True)
                TASKS.pop(task_id, None)
        await asyncio.sleep(60)
