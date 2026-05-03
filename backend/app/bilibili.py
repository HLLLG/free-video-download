from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

import requests


_BILIBILI_HOST_SUFFIXES = (
    "bilibili.com",
    "b23.tv",
)

_BILIBILI_REFERER = "https://www.bilibili.com"
_BILIBILI_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"(?:^|[^0-9])av([0-9]{1,20})(?:[^0-9]|$)", re.IGNORECASE)
_INVALID_FILENAME_RE = re.compile(r"[\\/:*?\"<>|\r\n\t]+")

_SESSION_LOCK = threading.Lock()
_SESSION: requests.Session | None = None
_SESSION_AT = 0.0
_SESSION_TTL_SECONDS = 5 * 60


class BilibiliError(Exception):
    pass


@dataclass
class BilibiliTrack:
    track_id: int | None
    width: int | None
    height: int | None
    bandwidth: int | None
    size_bytes: int | None
    url_list: list[str]


@dataclass
class BilibiliVideoInfo:
    aid: int
    cid: int
    bvid: str | None
    title: str
    uploader: str | None
    duration_seconds: float | None
    cover_url: str | None
    webpage_url: str
    view_count: int | None
    like_count: int | None
    video_tracks: list[BilibiliTrack]
    audio_tracks: list[BilibiliTrack]
    progressive_tracks: list[BilibiliTrack]


@dataclass
class BilibiliSelection:
    video: BilibiliTrack | None = None
    audio: BilibiliTrack | None = None
    progressive: BilibiliTrack | None = None


def _safe_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.hostname and parsed.hostname.lower() == "bilibili.com":
        return parsed._replace(netloc="www.bilibili.com").geturl()
    return value


def _cookie_header() -> str:
    parts: list[str] = []
    sessdata = os.getenv("BILIBILI_SESSDATA", "").strip()
    bili_jct = os.getenv("BILIBILI_BILI_JCT", "").strip()
    buvid3 = os.getenv("BILIBILI_BUVID3", "").strip()
    if sessdata:
        parts.append(f"SESSDATA={sessdata}")
    if bili_jct:
        parts.append(f"bili_jct={bili_jct}")
    if buvid3:
        parts.append(f"buvid3={buvid3}")
    return "; ".join(parts)


def _base_headers() -> dict[str, str]:
    headers = {
        "User-Agent": _BILIBILI_USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Referer": _BILIBILI_REFERER,
        "Origin": _BILIBILI_REFERER,
    }
    cookie = _cookie_header()
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _get_session() -> requests.Session:
    global _SESSION, _SESSION_AT
    with _SESSION_LOCK:
        now = time.time()
        if _SESSION and now - _SESSION_AT < _SESSION_TTL_SECONDS:
            return _SESSION
        session = requests.Session()
        session.headers.update(_base_headers())
        _SESSION = session
        _SESSION_AT = now
        return session


def is_bilibili_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in _BILIBILI_HOST_SUFFIXES)


def _extract_bvid(url: str) -> str | None:
    match = _BV_RE.search(url)
    return match.group(1) if match else None


def _extract_aid(url: str) -> int | None:
    match = _AV_RE.search(url)
    if not match:
        return None
    return _safe_int(match.group(1))


def _resolve_short_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host != "b23.tv":
        return url
    session = _get_session()
    try:
        response = session.get(url, timeout=12, allow_redirects=True)
        response.raise_for_status()
        return response.url or url
    except requests.RequestException:
        return url


def _call_api(path: str, params: dict) -> dict:
    session = _get_session()
    url = f"https://api.bilibili.com{path}"
    try:
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise BilibiliError(f"B 站接口请求失败：{exc}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise BilibiliError("B 站接口返回非 JSON 数据") from exc
    code = _safe_int(payload.get("code"))
    if code not in (0, None):
        message = str(payload.get("message") or "未知错误")
        raise BilibiliError(f"B 站接口返回异常：code={code}, message={message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise BilibiliError("B 站接口返回缺少 data 字段")
    return data


def _collect_urls(item: dict) -> list[str]:
    values: list[str] = []
    base = item.get("baseUrl") or item.get("base_url")
    if isinstance(base, str) and base:
        values.append(base)
    backups = item.get("backupUrl") or item.get("backup_url") or []
    if isinstance(backups, list):
        values.extend(str(entry) for entry in backups if entry)
    if "url" in item and isinstance(item["url"], str):
        values.append(item["url"])
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _build_track(item: dict, duration: float | None) -> BilibiliTrack | None:
    urls = _collect_urls(item)
    if not urls:
        return None
    bandwidth = _safe_int(item.get("bandwidth"))
    size_bytes = _safe_int(item.get("size"))
    if size_bytes is None and bandwidth and duration:
        size_bytes = int(max(0, bandwidth * duration / 8))
    return BilibiliTrack(
        track_id=_safe_int(item.get("id")),
        width=_safe_int(item.get("width")),
        height=_safe_int(item.get("height")),
        bandwidth=bandwidth,
        size_bytes=size_bytes,
        url_list=urls,
    )


def _pick_page_cid(view_data: dict, source_url: str) -> int:
    pages = view_data.get("pages") or []
    if not isinstance(pages, list) or not pages:
        cid = _safe_int(view_data.get("cid"))
        if cid:
            return cid
        raise BilibiliError("视频缺少分 P 信息，无法确定 cid")
    parsed = urlparse(source_url)
    query = parse_qs(parsed.query)
    requested_page = _safe_int((query.get("p") or [None])[0]) or 1
    index = max(0, min(len(pages) - 1, requested_page - 1))
    page = pages[index] if isinstance(pages[index], dict) else {}
    cid = _safe_int(page.get("cid"))
    if not cid:
        raise BilibiliError("视频分 P 缺少 cid，暂不支持")
    return cid


def fetch_video_info(url: str) -> BilibiliVideoInfo:
    if not is_bilibili_url(url):
        raise BilibiliError("非 B 站链接")

    normalized = _normalize_url(_resolve_short_url(url))
    bvid = _extract_bvid(normalized)
    aid = _extract_aid(normalized)
    if not bvid and not aid:
        raise BilibiliError("未识别到 BV/av 视频 ID，可能不是标准视频页链接")

    view_params: dict[str, str | int] = {"bvid": bvid} if bvid else {"aid": aid}
    view_data = _call_api("/x/web-interface/view", view_params)

    aid_value = _safe_int(view_data.get("aid"))
    if not aid_value:
        raise BilibiliError("视频信息缺少 aid")
    cid_value = _pick_page_cid(view_data, normalized)
    duration = _safe_float(view_data.get("duration"))

    play_data = _call_api(
        "/x/player/playurl",
        {
            "avid": aid_value,
            "cid": cid_value,
            "qn": 127,
            "fnval": 4048,
            "fnver": 0,
            "fourk": 1,
        },
    )

    dash = play_data.get("dash") if isinstance(play_data.get("dash"), dict) else {}
    dash_video_items = dash.get("video") if isinstance(dash.get("video"), list) else []
    dash_audio_items = dash.get("audio") if isinstance(dash.get("audio"), list) else []
    durl_items = play_data.get("durl") if isinstance(play_data.get("durl"), list) else []

    video_tracks = [track for track in (_build_track(item, duration) for item in dash_video_items) if track]
    audio_tracks = [track for track in (_build_track(item, duration) for item in dash_audio_items) if track]
    progressive_tracks = [track for track in (_build_track(item, duration) for item in durl_items) if track]

    if not video_tracks and not progressive_tracks:
        raise BilibiliError("未解析到可用的视频流")

    owner = view_data.get("owner") if isinstance(view_data.get("owner"), dict) else {}
    stat = view_data.get("stat") if isinstance(view_data.get("stat"), dict) else {}

    return BilibiliVideoInfo(
        aid=aid_value,
        cid=cid_value,
        bvid=str(view_data.get("bvid") or bvid) if (view_data.get("bvid") or bvid) else None,
        title=str(view_data.get("title") or "Bilibili 视频"),
        uploader=str(owner.get("name")) if owner.get("name") else None,
        duration_seconds=duration,
        cover_url=str(view_data.get("pic")) if view_data.get("pic") else None,
        webpage_url=str(view_data.get("short_link") or normalized),
        view_count=_safe_int(stat.get("view")),
        like_count=_safe_int(stat.get("like")),
        video_tracks=video_tracks,
        audio_tracks=audio_tracks,
        progressive_tracks=progressive_tracks,
    )


_QUALITY_CAPS = {
    "best": None,
    "4k": 2160,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}


def _pick_video_track(video_tracks: list[BilibiliTrack], cap_height: int | None) -> BilibiliTrack | None:
    if not video_tracks:
        return None
    if cap_height is None:
        return max(video_tracks, key=lambda item: ((item.height or 0), (item.bandwidth or 0)))
    under_cap = [item for item in video_tracks if (item.height or 0) <= cap_height]
    if under_cap:
        return max(under_cap, key=lambda item: ((item.height or 0), (item.bandwidth or 0)))
    return min(video_tracks, key=lambda item: (item.height or 10_000, -(item.bandwidth or 0)))


def _pick_audio_track(audio_tracks: list[BilibiliTrack]) -> BilibiliTrack | None:
    if not audio_tracks:
        return None
    return max(audio_tracks, key=lambda item: (item.bandwidth or 0, item.size_bytes or 0))


def estimate_quality_size(info: BilibiliVideoInfo, quality_key: str) -> int | None:
    if quality_key == "audio":
        audio = _pick_audio_track(info.audio_tracks)
        if audio and audio.size_bytes:
            return audio.size_bytes
        progressive = _pick_video_track(info.progressive_tracks, _QUALITY_CAPS["480p"])
        return progressive.size_bytes if progressive else None
    cap = _QUALITY_CAPS.get(quality_key)
    if cap is None and quality_key not in {"best", "4k"}:
        return None
    video = _pick_video_track(info.video_tracks, cap)
    if video:
        audio = _pick_audio_track(info.audio_tracks)
        total = (video.size_bytes or 0) + (audio.size_bytes or 0 if audio else 0)
        return total or None
    progressive = _pick_video_track(info.progressive_tracks, cap)
    return progressive.size_bytes if progressive else None


def select_stream(info: BilibiliVideoInfo, quality: str) -> BilibiliSelection:
    if quality == "audio":
        audio = _pick_audio_track(info.audio_tracks)
        if audio:
            return BilibiliSelection(audio=audio)
        progressive = _pick_video_track(info.progressive_tracks, _QUALITY_CAPS["480p"])
        if progressive:
            return BilibiliSelection(progressive=progressive)
        raise BilibiliError("未找到可用音频流")

    cap = _QUALITY_CAPS.get(quality)
    if cap is None and quality not in {"best", "4k"}:
        cap = _QUALITY_CAPS["best"]

    video = _pick_video_track(info.video_tracks, cap)
    if video:
        return BilibiliSelection(video=video, audio=_pick_audio_track(info.audio_tracks))

    progressive = _pick_video_track(info.progressive_tracks, cap)
    if progressive:
        return BilibiliSelection(progressive=progressive)
    raise BilibiliError("未找到可用视频流")


def _download_with_urls(
    urls: list[str],
    dest_path,
    *,
    on_progress=None,
    is_cancelled=None,
    chunk_size: int = 256 * 1024,
) -> None:
    if not urls:
        raise BilibiliError("下载链接为空")
    session = _get_session()
    last_error: Exception | None = None
    for url in urls:
        try:
            with session.get(url, stream=True, timeout=30) as response:
                if response.status_code in (403, 404, 412):
                    last_error = RuntimeError(f"流地址返回 HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                total = _safe_int(response.headers.get("Content-Length")) or 0
                downloaded = 0
                start_at = time.time()
                last_emit = 0.0
                with open(dest_path, "wb") as fp:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if is_cancelled and is_cancelled():
                            raise BilibiliError("download cancelled")
                        if not chunk:
                            continue
                        fp.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if on_progress and (now - last_emit) >= 0.25:
                            elapsed = max(now - start_at, 0.001)
                            on_progress(downloaded, total or None, downloaded / elapsed)
                            last_emit = now
                if on_progress:
                    elapsed = max(time.time() - start_at, 0.001)
                    on_progress(downloaded, total or downloaded, downloaded / elapsed)
                return
        except BilibiliError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            continue
    raise BilibiliError(f"B 站资源下载失败：{last_error}")


def download_track(
    track: BilibiliTrack,
    dest_path,
    *,
    on_progress=None,
    is_cancelled=None,
) -> None:
    _download_with_urls(
        track.url_list,
        dest_path,
        on_progress=on_progress,
        is_cancelled=is_cancelled,
    )


def safe_filename(title: str, ext: str) -> str:
    cleaned = _INVALID_FILENAME_RE.sub(" ", title or "bilibili")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if not cleaned:
        cleaned = "bilibili"
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip()
    return f"{cleaned}.{ext}"

