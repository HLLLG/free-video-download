import asyncio
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request as URLRequest, urlopen

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .downloader import (
    DownloadError,
    create_download_task,
    get_platform_referer,
    parse_video_info,
    run_download_task,
)
from .membership.api import router as membership_router
from .membership.dependencies import get_active_membership_from_request
from .tasks import cancel_task, get_task
from .summary.api import router as summary_router


router = APIRouter()
router.include_router(membership_router)
router.include_router(summary_router)


class InfoRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)


class DownloadRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    quality: str = Field(default="1080p", max_length=32)


def _http_error(exc: Exception) -> HTTPException:
    status = 400 if isinstance(exc, DownloadError) else 500
    return HTTPException(status_code=status, detail=str(exc))


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.post("/info")
async def info(payload: InfoRequest) -> dict:
    try:
        return await asyncio.to_thread(parse_video_info, payload.url)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/download")
async def download(payload: DownloadRequest, request: Request) -> dict:
    try:
        active_membership = await get_active_membership_from_request(request)
        task = create_download_task(
            payload.url,
            payload.quality,
            allow_pro=bool(active_membership),
        )
        asyncio.create_task(run_download_task(task, payload.url, payload.quality))
        return {"task_id": task.task_id, "status": task.status}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/progress/{task_id}")
async def progress(task_id: str) -> dict:
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return task.to_dict()


@router.post("/cancel/{task_id}")
async def cancel(task_id: str) -> dict:
    task = cancel_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return task.to_dict()


_THUMBNAIL_HOST_ALLOW = (
    "ytimg.com",
    "ggpht.com",
    "googleusercontent.com",
    "hdslb.com",
    "bilivideo.com",
    "biliimg.com",
    "douyinpic.com",
    "douyincdn.com",
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "ibyteimg.com",
    "twimg.com",
    "cdninstagram.com",
    "fbcdn.net",
    "xhscdn.com",
    "sinaimg.cn",
    "vimeocdn.com",
    "jtvnw.net",
)


def _is_allowed_thumbnail(host: str) -> bool:
    host = host.lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in _THUMBNAIL_HOST_ALLOW)


@router.get("/thumbnail")
async def thumbnail(
    url: str = Query(..., min_length=1, max_length=2048),
    platform: str | None = Query(default=None, max_length=64),
) -> Response:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="封面链接无效")
    if not _is_allowed_thumbnail(parsed.netloc):
        raise HTTPException(status_code=400, detail="封面来源不在白名单内")

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FreeVideoDownload/1.0)",
        "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5",
    }
    referer = get_platform_referer(platform)
    if referer:
        headers["Referer"] = referer

    upstream_request = URLRequest(url, headers=headers)

    def _fetch() -> tuple[bytes, str]:
        with urlopen(upstream_request, timeout=10) as response:
            return response.read(), response.headers.get("Content-Type", "image/jpeg")

    try:
        content, content_type = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"封面拉取失败：{exc}") from exc

    return Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=600"})


@router.get("/file/{task_id}")
async def file(task_id: str) -> FileResponse:
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if task.status != "done" or not task.file_path:
        raise HTTPException(status_code=409, detail="文件尚未下载完成")

    path = Path(task.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件已被清理，请重新下载")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
