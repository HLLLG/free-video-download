import asyncio
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..config import MAX_URL_LENGTH
from ..downloader import DownloadError, validate_url
from .export import SUPPORTED_FORMATS, media_type_for, render_subtitle, safe_filename
from .models import SummaryError
from .pipeline import chat_with_summary, run_summary_task
from .rate_limit import assert_daily_limit, get_client_ip, increment_usage
from .settings import SUMMARY_MAX_DURATION_SECONDS
from .tasks import create_summary_task, get_summary_task, remove_summary_task


router = APIRouter(prefix="/summary", tags=["summary"])


class SummaryRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=MAX_URL_LENGTH)
    title: str | None = Field(default=None, max_length=300)
    duration: int | None = Field(default=None, ge=0)


class SummaryChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)


def _summary_http_error(exc: SummaryError) -> HTTPException:
    message = str(exc)
    if "每天最多" in message or "请求过于频繁" in message:
        return HTTPException(status_code=429, detail=message)
    if "不存在" in message or "过期" in message:
        return HTTPException(status_code=404, detail=message)
    if "尚未完成" in message:
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=400, detail=message)


@router.post("")
async def create_summary(payload: SummaryRequest, request: Request) -> dict:
    client_ip = get_client_ip(request)
    try:
        assert_daily_limit(client_ip)
        try:
            validate_url(payload.url)
        except DownloadError as exc:
            raise SummaryError(str(exc)) from exc
        if payload.duration and payload.duration > SUMMARY_MAX_DURATION_SECONDS:
            raise SummaryError("当前免费版仅支持总结 40 分钟以内的视频。")
        task = create_summary_task(payload.url, client_ip, payload.title)
        increment_usage(client_ip)
        asyncio.create_task(run_summary_task(task))
        return {"summary_id": task.summary_id, "status": task.status}
    except SummaryError as exc:
        raise _summary_http_error(exc) from exc


@router.get("/{summary_id}")
async def get_summary(summary_id: str) -> dict:
    task = get_summary_task(summary_id)
    if not task:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    return task.to_dict(include_result=task.status == "done")


@router.post("/{summary_id}/chat")
async def chat(summary_id: str, payload: SummaryChatRequest) -> dict:
    task = get_summary_task(summary_id)
    if not task:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    try:
        answer = await chat_with_summary(task, payload.message)
        return {
            "answer": answer,
            "messages": [message.to_dict() for message in task.chat_messages],
        }
    except SummaryError as exc:
        raise _summary_http_error(exc) from exc


@router.get("/{summary_id}/subtitle")
async def download_subtitle(summary_id: str, format: str = "srt") -> Response:
    fmt = (format or "srt").lower()
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"暂不支持的字幕格式：{format}，可选 srt / vtt / txt",
        )
    task = get_summary_task(summary_id)
    if not task:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    if not task.segments:
        raise HTTPException(status_code=409, detail="字幕尚未抽取完成，请稍后再试")

    body = render_subtitle(task.segments, fmt)
    filename = safe_filename(task.title, fmt)
    # RFC 5987 风格的 filename* 兼容中文标题，老浏览器读 ASCII 兜底名
    fallback_name = f"subtitle.{fmt}"
    disposition = (
        f'attachment; filename="{fallback_name}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=body.encode("utf-8"),
        media_type=media_type_for(fmt),
        headers={"Content-Disposition": disposition},
    )


@router.delete("/{summary_id}")
async def delete_summary(summary_id: str) -> dict:
    task = remove_summary_task(summary_id)
    if not task:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    return {"ok": True}

