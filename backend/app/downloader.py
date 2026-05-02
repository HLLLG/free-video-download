import asyncio
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import yt_dlp

from . import douyin as douyin_extractor
from .config import (
    DEFAULT_FORMAT,
    MAX_DURATION_SECONDS,
    MAX_URL_LENGTH,
    MERGE_OUTPUT_FORMAT,
    TEMP_ROOT,
)
from .tasks import DOWNLOAD_SEMAPHORE, DownloadTask, register_task, remove_task


PLATFORM_LABELS = {
    "youtube": "YouTube",
    "youtube:tab": "YouTube",
    "bilibili": "Bilibili",
    "bilibilibangumi": "Bilibili 番剧",
    "bilibilisearch": "Bilibili",
    "douyin": "抖音",
    "tiktok": "TikTok",
    "twitter": "X / Twitter",
    "x": "X / Twitter",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "weibo": "微博",
    "xiaohongshu": "小红书",
    "kuaishou": "快手",
    "vimeo": "Vimeo",
    "twitch": "Twitch",
}

PLATFORM_REFERERS = {
    "bilibili": "https://www.bilibili.com",
    "bilibilibangumi": "https://www.bilibili.com",
    "douyin": "https://www.douyin.com",
    "xiaohongshu": "https://www.xiaohongshu.com",
    "weibo": "https://weibo.com",
}


QUALITY_SELECTORS = {
    "best": {
        "label": "最佳画质",
        "description": "自动选择当前链接可用的最佳画质",
        "selector": "bv*+ba/b",
        "pro": False,
    },
    "1080p": {
        "label": "1080p 高清",
        "description": "适合大多数高清视频下载",
        "selector": "bv*[height<=1080]+ba/b[height<=1080]",
        "pro": False,
    },
    "720p": {
        "label": "720p 标清",
        "description": "体积更小，手机保存更快",
        "selector": "bv*[height<=720]+ba/b[height<=720]",
        "pro": False,
    },
    "480p": {
        "label": "480p 流畅",
        "description": "网络较慢时推荐",
        "selector": "bv*[height<=480]+ba/b[height<=480]",
        "pro": False,
    },
    "audio": {
        "label": "仅音频",
        "description": "提取音频文件",
        "selector": "bestaudio/best",
        "pro": False,
    },
    "4k": {
        "label": "4K 超清",
        "description": "Pro 专享：适合高画质收藏",
        "selector": "bv*[height<=2160]+ba/b[height<=2160]",
        "pro": True,
    },
}


class DownloadError(Exception):
    pass


class DownloadCancelled(Exception):
    """用户在下载过程中主动取消时抛出，用来中止 yt-dlp。"""


def _normalize_bilibili_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host != "bilibili.com":
        return url

    return urlunparse(parsed._replace(netloc=f"www.{parsed.netloc}"))


def validate_url(url: str) -> str:
    clean = url.strip()
    if not clean:
        raise DownloadError("请先粘贴视频链接")
    if len(clean) > MAX_URL_LENGTH:
        raise DownloadError("链接过长，请检查后重试")
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DownloadError("请输入有效的视频链接")
    return _normalize_bilibili_url(clean)


def _safe_error(error: Exception) -> str:
    message = str(error).strip()
    message = re.sub(r"\s+", " ", message)
    return message[:500] or "处理失败，请稍后重试"


def _base_ydl_opts() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": False,
    }


def _format_duration(seconds: int | float | None) -> str | None:
    if not seconds:
        return None
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _available_heights(formats: list[dict]) -> set[int]:
    heights = set()
    for item in formats:
        height = item.get("height")
        if isinstance(height, int):
            heights.add(height)
    return heights


_QUALITY_HEIGHT_CAP = {
    "best": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "4k": 2160,
}


def _format_filesize(num_bytes: float | int | None) -> str | None:
    """把字节数格式化成易读字符串，例如 124.5 MB / 1.2 GB。"""
    if not num_bytes or num_bytes <= 0:
        return None
    try:
        size = float(num_bytes)
    except (TypeError, ValueError):
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def _estimate_format_size(fmt: dict, duration: int | float | None) -> float | None:
    """从 yt-dlp 单个 format 中获取或估算文件大小（字节）。"""
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if size:
        try:
            return float(size)
        except (TypeError, ValueError):
            pass
    tbr = fmt.get("tbr")  # kbps
    if tbr and duration:
        try:
            return float(tbr) * 1000 / 8 * float(duration)
        except (TypeError, ValueError):
            return None
    return None


def _pick_video_size(
    formats: list[dict], max_height: int | None, duration: int | float | None
) -> float | None:
    """挑选最贴近目标清晰度的视频流，返回估算的视频字节数。"""
    candidates = []
    for fmt in formats:
        vcodec = fmt.get("vcodec")
        if vcodec in (None, "none"):
            continue
        height = fmt.get("height")
        if not isinstance(height, int):
            continue
        if max_height is not None and height > max_height:
            continue
        size = _estimate_format_size(fmt, duration)
        if size is None:
            continue
        candidates.append((height, size))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[-1][1]


def _pick_audio_size(formats: list[dict], duration: int | float | None) -> float | None:
    """挑选体积最大的纯音频流（通常对应最佳音质），返回估算字节数。"""
    best = None
    for fmt in formats:
        acodec = fmt.get("acodec")
        vcodec = fmt.get("vcodec")
        if acodec in (None, "none"):
            continue
        if vcodec not in (None, "none"):
            continue
        size = _estimate_format_size(fmt, duration)
        if size is None:
            continue
        if best is None or size > best:
            best = size
    return best


def _estimate_combined_size(
    formats: list[dict], max_height: int | None, duration: int | float | None
) -> float | None:
    """估算视频+音频合并后的体积；若没有可用纯视频流，则退化为带音轨的整流体积。"""
    video_size = _pick_video_size(formats, max_height, duration)
    audio_size = _pick_audio_size(formats, duration)

    if video_size is not None and audio_size is not None:
        return video_size + audio_size
    if video_size is not None:
        return video_size

    fallback = None
    for fmt in formats:
        vcodec = fmt.get("vcodec")
        if vcodec in (None, "none"):
            continue
        height = fmt.get("height")
        if max_height is not None and isinstance(height, int) and height > max_height:
            continue
        size = _estimate_format_size(fmt, duration)
        if size is None:
            continue
        if fallback is None or size > fallback:
            fallback = size
    return fallback


def _estimate_quality_size(
    key: str, formats: list[dict], duration: int | float | None
) -> float | None:
    if key == "audio":
        return _pick_audio_size(formats, duration)
    cap = _QUALITY_HEIGHT_CAP.get(key)
    return _estimate_combined_size(formats, cap, duration)


def build_quality_options(
    formats: list[dict], duration: int | float | None = None
) -> list[dict]:
    heights = _available_heights(formats)
    options = []
    for key in ["best", "1080p", "720p", "480p", "audio", "4k"]:
        item = QUALITY_SELECTORS[key]
        if key == "1080p" and not any(height >= 720 for height in heights):
            continue
        if key == "720p" and not any(height >= 480 for height in heights):
            continue
        if key == "480p" and not heights:
            continue
        size_bytes = _estimate_quality_size(key, formats, duration)
        options.append(
            {
                "key": key,
                "label": item["label"],
                "description": item["description"],
                "pro": item["pro"],
                "size_bytes": int(size_bytes) if size_bytes else None,
                "size_text": _format_filesize(size_bytes),
            }
        )
    return options


def _build_douyin_qualities(info: douyin_extractor.DouyinVideoInfo) -> list[dict]:
    """抖音返回的画质档位本身就够用，把它们映射到我们对外提供的 quality key 上。

    规则：
      - height >= 1080 → 1080p
      - 720 <= height < 1080 → 720p
      - 480 <= height < 720 → 480p
      - 其他归到 best（始终保留作为兜底）
      - audio 总是提供（用 ffmpeg 从 mp4 提取）
    """
    by_key: dict[str, dict] = {}
    duration = info.duration_seconds

    def estimate_size(stream: douyin_extractor.DouyinStream) -> int | None:
        if stream.size_bytes:
            return stream.size_bytes
        if stream.bitrate and duration:
            return int(stream.bitrate / 8 * duration)
        return None

    streams_by_height = sorted(info.streams, key=lambda s: s.height or 0, reverse=True)
    for stream in streams_by_height:
        height = stream.height or 0
        if height >= 1080:
            target = "1080p"
        elif height >= 720:
            target = "720p"
        elif height >= 480:
            target = "480p"
        else:
            target = None

        if target and target not in by_key:
            preset = QUALITY_SELECTORS[target]
            size = estimate_size(stream)
            by_key[target] = {
                "key": target,
                "label": preset["label"],
                "description": preset["description"],
                "pro": preset["pro"],
                "size_bytes": size,
                "size_text": _format_filesize(size),
            }

    best_stream = streams_by_height[0] if streams_by_height else None
    best_size = estimate_size(best_stream) if best_stream else None
    by_key.setdefault(
        "best",
        {
            "key": "best",
            "label": QUALITY_SELECTORS["best"]["label"],
            "description": QUALITY_SELECTORS["best"]["description"],
            "pro": False,
            "size_bytes": best_size,
            "size_text": _format_filesize(best_size),
        },
    )

    audio_size = None
    if best_stream and best_stream.bitrate and duration:
        # 抖音不分离纯音频流，这里粗略给个 128kbps 估算
        audio_size = int(128_000 / 8 * duration)
    by_key["audio"] = {
        "key": "audio",
        "label": QUALITY_SELECTORS["audio"]["label"],
        "description": QUALITY_SELECTORS["audio"]["description"],
        "pro": False,
        "size_bytes": audio_size,
        "size_text": _format_filesize(audio_size),
    }

    order = ["best", "1080p", "720p", "480p", "audio", "4k"]
    return [by_key[k] for k in order if k in by_key]


def _parse_douyin(url: str) -> dict:
    try:
        info = douyin_extractor.fetch_video_info(url)
    except Exception as exc:
        raise DownloadError(f"解析失败：{_safe_error(exc)}") from exc

    duration = int(info.duration_seconds) if info.duration_seconds else None
    if duration and duration > MAX_DURATION_SECONDS:
        raise DownloadError("视频时长超过 MVP 限制，请换一个较短的视频链接")

    qualities = _build_douyin_qualities(info)

    return {
        "title": info.title or "未命名视频",
        "uploader": info.uploader,
        "duration": duration,
        "duration_text": _format_duration(duration),
        "thumbnail": info.cover_url,
        "platform": PLATFORM_LABELS["douyin"],
        "platform_key": "douyin",
        "webpage_url": info.webpage_url,
        "view_count": None,
        "like_count": None,
        "qualities": qualities,
    }


def parse_video_info(url: str) -> dict:
    url = validate_url(url)
    if douyin_extractor.is_douyin_url(url):
        return _parse_douyin(url)
    try:
        with yt_dlp.YoutubeDL({**_base_ydl_opts(), "skip_download": True}) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
    except Exception as exc:
        raise DownloadError(f"解析失败：{_safe_error(exc)}") from exc

    raw_duration = info.get("duration")
    try:
        duration = int(raw_duration) if raw_duration else None
    except (TypeError, ValueError):
        duration = None
    if duration and duration > MAX_DURATION_SECONDS:
        raise DownloadError("视频时长超过 MVP 限制，请换一个较短的视频链接")

    formats = info.get("formats") or []
    qualities = build_quality_options(formats, duration)
    if not qualities:
        qualities = build_quality_options([], duration)

    extractor = (info.get("extractor_key") or info.get("extractor") or "").lower()
    platform_label = PLATFORM_LABELS.get(extractor) or info.get("extractor_key") or info.get("extractor") or "Video"

    def _to_int(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "title": info.get("title") or "未命名视频",
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": duration,
        "duration_text": _format_duration(duration),
        "thumbnail": info.get("thumbnail"),
        "platform": platform_label,
        "platform_key": extractor,
        "webpage_url": info.get("webpage_url") or url,
        "view_count": _to_int(info.get("view_count")),
        "like_count": _to_int(info.get("like_count")),
        "qualities": qualities,
    }


def get_platform_referer(platform_key: str | None) -> str | None:
    if not platform_key:
        return None
    return PLATFORM_REFERERS.get(platform_key.lower())


def create_download_task(url: str, quality: str, *, allow_pro: bool = False) -> DownloadTask:
    url = validate_url(url)
    if quality not in QUALITY_SELECTORS:
        quality = "1080p"
    if QUALITY_SELECTORS[quality]["pro"] and not allow_pro:
        raise DownloadError("该清晰度为 Pro 专享，请先开通会员。")

    task_id = uuid.uuid4().hex
    workdir = TEMP_ROOT / task_id
    workdir.mkdir(parents=True, exist_ok=True)
    task = register_task(task_id, workdir)
    task.title = "等待下载"
    task.touch()
    return task


def _resolve_final_file(workdir: Path) -> Path | None:
    candidates = [path for path in workdir.iterdir() if path.is_file() and not path.name.endswith(".part")]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _make_progress_hook(task: DownloadTask):
    """
    yt-dlp 在视频+音频分流下载时会对每个流分别回调 hook，
    这里把多个流的字节数累加，给前端展示的是整体进度，
    避免下载完视频后进度从 ~50% 突然回到 0% 再涨。
    """
    streams: dict[str, dict[str, float]] = {}

    def _stream_key(data: dict) -> str:
        info = data.get("info_dict") or {}
        return (
            data.get("filename")
            or info.get("format_id")
            or info.get("_filename")
            or "default"
        )

    def hook(data: dict) -> None:
        if task.cancelled:
            raise DownloadCancelled()
        status = data.get("status")
        info = data.get("info_dict") or {}
        if status == "downloading":
            key = _stream_key(data)
            total = (
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
                or info.get("filesize")
                or info.get("filesize_approx")
                or 0
            )
            downloaded = data.get("downloaded_bytes", 0) or 0
            streams[key] = {"total": float(total or 0), "downloaded": float(downloaded)}

            total_sum = sum(item["total"] for item in streams.values())
            done_sum = sum(item["downloaded"] for item in streams.values())
            if total_sum > 0:
                pct = round(done_sum / total_sum * 100, 1)
                task.pct = min(pct, 99)
            else:
                task.pct = None

            task.speed = data.get("speed")
            task.eta = data.get("eta")
            task.title = info.get("title") or task.title
            task.stage = "downloading"
            task.stage_text = "正在下载"
            task.touch()
        elif status == "finished":
            key = _stream_key(data)
            if key in streams and streams[key]["total"]:
                streams[key]["downloaded"] = streams[key]["total"]
            task.file_path = data.get("filename")
            task.pct = 99
            task.speed = None
            task.eta = None
            task.touch()

    return hook


def _make_postprocessor_hook(task: DownloadTask):
    """ffmpeg 合并 / 转码 / 提取音频等后处理阶段的状态提示。"""

    POSTPROCESSOR_TEXT = {
        "Merger": "正在合并音视频",
        "FFmpegMerger": "正在合并音视频",
        "FFmpegVideoRemuxer": "正在重新封装视频",
        "FFmpegVideoConvertor": "正在转码视频",
        "FFmpegExtractAudio": "正在提取音频",
        "FFmpegMetadata": "正在写入元数据",
    }

    def hook(data: dict) -> None:
        if task.cancelled:
            raise DownloadCancelled()
        status = data.get("status")
        pp = data.get("postprocessor") or ""
        text = POSTPROCESSOR_TEXT.get(pp) or "正在处理文件"
        if status == "started":
            task.stage = "postprocessing"
            task.stage_text = text
            task.pct = 99
            task.speed = None
            task.eta = None
            task.touch()
        elif status == "finished":
            task.stage = "postprocessing"
            task.stage_text = f"{text} 完成"
            task.touch()

    return hook


_DOUYIN_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _douyin_safe_filename(title: str, ext: str) -> str:
    """抖音的标题里经常带 emoji、换行、井号话题，做一下清洗以适配 Windows 文件系统。"""
    cleaned = _DOUYIN_INVALID_FS_CHARS.sub(" ", title or "douyin")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if not cleaned:
        cleaned = "douyin"
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip()
    return f"{cleaned}.{ext}"


def _run_ffmpeg_extract_audio(src: Path, dst: Path) -> None:
    """用 ffmpeg 把抖音 mp4 里的音轨抽出来转成 mp3（仅在用户选择仅音频时调用）。"""
    import subprocess

    creationflags = 0
    try:
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    except AttributeError:
        pass
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-vn", "-acodec", "libmp3lame", "-q:a", "2",
        str(dst),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        raise DownloadError(f"音频提取失败：{result.stderr.strip()[:200] or '未知错误'}")


def _download_douyin_sync(task: DownloadTask, url: str, quality: str) -> None:
    """抖音专用下载路径，绕开 yt-dlp 的 cookie 校验。"""
    workdir = Path(task.workdir or TEMP_ROOT / task.task_id)
    workdir.mkdir(parents=True, exist_ok=True)

    task.status = "running"
    task.stage = "preparing"
    task.stage_text = "正在解析视频"
    task.touch()

    try:
        info = douyin_extractor.fetch_video_info(url)
    except Exception as exc:
        raise DownloadError(f"解析失败：{_safe_error(exc)}") from exc

    duration = int(info.duration_seconds) if info.duration_seconds else None
    if duration and duration > MAX_DURATION_SECONDS:
        raise DownloadError("视频时长超过 MVP 限制，请换一个较短的视频链接")

    stream = douyin_extractor.select_stream(info.streams, quality)
    is_audio = quality == "audio"

    task.title = info.title
    task.stage = "downloading"
    task.stage_text = "正在下载"
    task.pct = 0
    task.touch()

    video_filename = _douyin_safe_filename(info.title, "mp4")
    video_path = workdir / video_filename

    def on_progress(downloaded: int, total: int | None, speed: float) -> None:
        if task.cancelled:
            return
        if total and total > 0:
            pct = round(downloaded / total * 100, 1)
            task.pct = min(pct, 99)
        else:
            task.pct = None
        task.speed = speed if speed > 0 else None
        if total and speed > 0:
            remaining = max(total - downloaded, 0)
            task.eta = remaining / speed if speed else None
        else:
            task.eta = None
        task.touch()

    def is_cancelled() -> bool:
        return task.cancelled

    try:
        douyin_extractor.stream_download(
            stream,
            video_path,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
    except douyin_extractor._DouyinCancelled as exc:  # noqa: SLF001
        raise DownloadCancelled() from exc

    if task.cancelled:
        raise DownloadCancelled()

    final_file = video_path
    if is_audio:
        task.stage = "postprocessing"
        task.stage_text = "正在提取音频"
        task.pct = 99
        task.speed = None
        task.eta = None
        task.touch()
        audio_filename = _douyin_safe_filename(info.title, "mp3")
        audio_path = workdir / audio_filename
        _run_ffmpeg_extract_audio(video_path, audio_path)
        try:
            video_path.unlink(missing_ok=True)
        except OSError:
            pass
        final_file = audio_path

    if not final_file.exists():
        raise DownloadError("下载完成但未找到输出文件")

    task.file_path = str(final_file)
    task.pct = 100
    task.status = "done"
    task.stage = "done"
    task.stage_text = "下载完成"
    task.speed = None
    task.eta = None
    task.touch()


def _download_sync(task: DownloadTask, url: str, quality: str) -> None:
    url = validate_url(url)
    if douyin_extractor.is_douyin_url(url):
        _download_douyin_sync(task, url, quality)
        return

    workdir = Path(task.workdir or TEMP_ROOT / task.task_id)
    selector = QUALITY_SELECTORS.get(quality, {}).get("selector", DEFAULT_FORMAT)
    is_audio = quality == "audio"
    opts = {
        **_base_ydl_opts(),
        "format": selector,
        "outtmpl": str(workdir / "%(title).80s.%(ext)s"),
        "progress_hooks": [_make_progress_hook(task)],
        "postprocessor_hooks": [_make_postprocessor_hook(task)],
        "concurrent_fragment_downloads": 4,
        "windowsfilenames": True,
        "trim_file_name": 80,
    }
    if is_audio:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    else:
        opts["merge_output_format"] = MERGE_OUTPUT_FORMAT

    task.status = "running"
    task.stage = "downloading"
    task.stage_text = "正在下载"
    task.touch()
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    if task.cancelled:
        raise DownloadCancelled()

    final_file = _resolve_final_file(workdir)
    if not final_file:
        raise DownloadError("下载完成但未找到输出文件")
    task.file_path = str(final_file)
    task.pct = 100
    task.status = "done"
    task.stage = "done"
    task.stage_text = "下载完成"
    task.speed = None
    task.eta = None
    task.touch()


def _cleanup_workdir(task: DownloadTask) -> None:
    """删除任务工作目录里所有部分下载/合并产物。"""
    if not task.workdir:
        return
    try:
        from shutil import rmtree

        rmtree(task.workdir, ignore_errors=True)
    except Exception:
        pass


def _is_cancelled_exception(exc: BaseException) -> bool:
    """yt-dlp 会把 hook 抛出的异常包成 DownloadError，这里递归检查根因。"""
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, DownloadCancelled):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


async def run_download_task(task: DownloadTask, url: str, quality: str) -> None:
    async with DOWNLOAD_SEMAPHORE:
        try:
            await asyncio.to_thread(_download_sync, task, url, quality)
        except Exception as exc:
            if task.cancelled or _is_cancelled_exception(exc):
                task.status = "cancelled"
                task.stage = "cancelled"
                task.stage_text = "已取消"
                task.speed = None
                task.eta = None
                task.error = None
                task.file_path = None
                task.touch()
                _cleanup_workdir(task)
                remove_task(task.task_id)
                return
            task.status = "error"
            task.error = _safe_error(exc)
            task.touch()
