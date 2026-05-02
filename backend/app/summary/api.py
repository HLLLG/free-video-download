import asyncio
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..config import MAX_URL_LENGTH
from ..downloader import DownloadError, validate_url
from .bilibili_auth import check_cookie_login
from .export import SUPPORTED_FORMATS, media_type_for, render_subtitle, safe_filename
from .models import SummaryError
from .pipeline import chat_with_summary, run_summary_task
from .rate_limit import assert_daily_limit, get_summary_access_context, increment_usage
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
    access = await get_summary_access_context(request)
    try:
        assert_daily_limit(access)
        try:
            validate_url(payload.url)
        except DownloadError as exc:
            raise SummaryError(str(exc)) from exc
        if payload.duration and payload.duration > access.max_duration_seconds:
            limit_minutes = access.max_duration_seconds // 60
            if access.is_pro:
                raise SummaryError(f"当前 Pro 版仅支持总结 {limit_minutes} 分钟以内的视频。")
            raise SummaryError(
                f"当前免费版仅支持总结 {limit_minutes} 分钟以内的视频，请升级 Pro 后再试。"
            )
        task = create_summary_task(
            payload.url,
            access.client_ip,
            payload.title,
            max_duration_seconds=access.max_duration_seconds,
        )
        increment_usage(access)
        asyncio.create_task(run_summary_task(task))
        return {"summary_id": task.summary_id, "status": task.status}
    except SummaryError as exc:
        raise _summary_http_error(exc) from exc


@router.get("/bilibili/cookie-status")
async def bilibili_cookie_status() -> dict:
    """运营方自检：当前 .env 配置的 BILIBILI_SESSDATA 在 B 站是否仍被识别为登录态。

    返回脱敏后的登录信息（uname / mid），不暴露 Cookie 原文。
    用法： curl http://127.0.0.1:8001/api/summary/bilibili/cookie-status
    """
    status = check_cookie_login()
    if not status.has_cookie:
        return {
            "has_cookie": False,
            "is_login": False,
            "hint": "未在 backend/.env 配置 BILIBILI_SESSDATA。如需总结 B 站视频请添加该配置。",
        }
    if status.is_login:
        return {
            "has_cookie": True,
            "is_login": True,
            "uname": status.uname,
            "mid": status.mid,
            "hint": f"Cookie 当前有效，登录身份：{status.uname or '未知'}（mid={status.mid}）。",
        }
    return {
        "has_cookie": True,
        "is_login": False,
        "code": status.code,
        "message": status.message,
        "hint": (
            "Cookie 已被 B 站拒绝（可能被风控吊销或填写错误）。"
            "请重新登录小号，复制最新 SESSDATA 到 backend/.env 后重启服务。"
        ),
    }


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

