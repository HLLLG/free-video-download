"""
抖音专用解析与下载实现。

背景：yt-dlp 内置的 douyin 提取器需要 "fresh cookies"，否则会报
"Fresh cookies (not necessarily logged in) are needed"。我们要求用户
零配置即可使用，所以这里走另一条路：
  1) 用 PC 端浏览器先 GET 一下 douyin.com 主页，让服务端下发 __ac_nonce 之类
     的匿名 cookie；
  2) 再请求 iesdouyin.com/share/video/{aweme_id} 的分享页（移动端 UA），
     抖音会把视频信息以 SSR 的 `window._ROUTER_DATA` 形式直接渲染到 HTML，
     无需登录、无需 ttwid、msToken、a_bogus 等签名参数；
  3) 取出其中的 play_addr / bit_rate，把链接里的 playwm 替换成 play 拿到
     无水印 mp4 直链，然后用 requests 流式下载。
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

import requests


DOUYIN_HOST_KEYWORDS = (
    "douyin.com",
    "iesdouyin.com",
    "snssdk.com",
)


_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 "
    "Mobile/15E148 Safari/604.1"
)


def _base_headers() -> dict[str, str]:
    return {
        "User-Agent": _MOBILE_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.douyin.com/",
    }


def is_douyin_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(host == kw or host.endswith("." + kw) or host.endswith(kw) for kw in DOUYIN_HOST_KEYWORDS)


_AWEME_ID_PATTERNS = [
    re.compile(r"/video/(\d+)"),
    re.compile(r"/share/video/(\d+)"),
    re.compile(r"/note/(\d+)"),
    re.compile(r"/share/note/(\d+)"),
    re.compile(r"modal_id=(\d+)"),
    re.compile(r"item_ids?=(\d+)"),
    re.compile(r"aweme_id=(\d+)"),
]


def _extract_id_from_text(text: str) -> str | None:
    for pat in _AWEME_ID_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def _resolve_short_link(url: str, session: requests.Session) -> str:
    """v.douyin.com 短链需要先跟随重定向才能拿到真实的 aweme_id。"""
    try:
        resp = session.get(
            url,
            headers=_base_headers(),
            timeout=15,
            allow_redirects=True,
        )
        return resp.url or url
    except requests.RequestException:
        return url


def extract_aweme_id(url: str, session: requests.Session | None = None) -> str:
    """从各种形式的抖音链接中提取视频 ID。"""
    direct = _extract_id_from_text(url)
    if direct:
        return direct

    sess = session or requests.Session()
    final = _resolve_short_link(url, sess)
    direct = _extract_id_from_text(final)
    if direct:
        return direct
    raise ValueError("无法从链接中识别抖音视频 ID，请确认链接是否完整")


@dataclass
class _CachedSession:
    session: requests.Session
    fetched_at: float


_SESSION_LOCK = threading.Lock()
_CACHED_SESSION: _CachedSession | None = None
_SESSION_TTL = 5 * 60  # 5 分钟内复用同一个 cookie，避免每次请求都去 warmup


def _get_warm_session() -> requests.Session:
    """获取一个已经访问过 douyin.com 主页、带匿名 cookie 的 Session。

    线程安全；缓存复用，过期后自动重建。
    """
    global _CACHED_SESSION
    with _SESSION_LOCK:
        now = time.time()
        if _CACHED_SESSION and now - _CACHED_SESSION.fetched_at < _SESSION_TTL:
            return _CACHED_SESSION.session

        sess = requests.Session()
        try:
            sess.get(
                "https://www.douyin.com/",
                headers=_base_headers(),
                timeout=15,
                allow_redirects=True,
            )
        except requests.RequestException:
            pass
        _CACHED_SESSION = _CachedSession(session=sess, fetched_at=now)
        return sess


_ROUTER_DATA_RE = re.compile(
    r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", re.DOTALL
)


def _fetch_share_page(aweme_id: str, session: requests.Session) -> dict:
    url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
    resp = session.get(url, headers=_base_headers(), timeout=15, allow_redirects=True)
    if resp.status_code != 200:
        raise RuntimeError(f"抖音分享页响应异常 (HTTP {resp.status_code})")
    match = _ROUTER_DATA_RE.search(resp.text)
    if not match:
        # 极少数情况下抖音会返回风控页，重新 warmup 一次再试
        raise RuntimeError("未能在分享页找到视频数据，可能链接已失效或触发了风控")
    raw = match.group(1).strip()
    raw = raw.rstrip(";")
    return json.loads(raw)


def _safe_pick(d: dict | None, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _replace_playwm(url: str) -> str:
    """把抖音返回的带水印链接 playwm 替换成 play，得到无水印版本。"""
    if not url:
        return url
    return url.replace("/playwm/", "/play/").replace("playwm?", "play?")


def _normalize_url(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    return url


def _collect_play_urls(addr: dict | None) -> list[str]:
    urls = _safe_pick(addr, "url_list", default=[]) or []
    cleaned: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if not u:
            continue
        u = _normalize_url(u)
        u = _replace_playwm(u)
        if u in seen:
            continue
        seen.add(u)
        cleaned.append(u)
    return cleaned


@dataclass
class DouyinStream:
    quality_label: str  # 例如 "1080p"、"720p"、"标清"
    height: int | None
    width: int | None
    bitrate: int | None  # bps
    size_bytes: int | None
    url_list: list[str]


@dataclass
class DouyinVideoInfo:
    aweme_id: str
    title: str
    description: str
    uploader: str | None
    duration_seconds: float | None
    cover_url: str | None
    webpage_url: str
    streams: list[DouyinStream]


def _gear_to_label(gear_name: str | None, height: int | None) -> str:
    name = (gear_name or "").lower()
    if "1080" in name or (height and height >= 1080):
        return "1080p"
    if "720" in name or (height and height >= 720):
        return "720p"
    if "540" in name or (height and height >= 480):
        return "540p"
    if "360" in name or (height and height >= 320):
        return "360p"
    if "lower" in name or (height and height < 320):
        return "流畅"
    return "标清"


def _build_streams(video: dict) -> list[DouyinStream]:
    streams: list[DouyinStream] = []

    bit_rates = video.get("bit_rate") or []
    for item in bit_rates:
        addr = item.get("play_addr") or {}
        urls = _collect_play_urls(addr)
        if not urls:
            continue
        height = item.get("height") or video.get("height")
        width = item.get("width") or video.get("width")
        streams.append(
            DouyinStream(
                quality_label=_gear_to_label(item.get("gear_name"), height),
                height=height if isinstance(height, int) else None,
                width=width if isinstance(width, int) else None,
                bitrate=item.get("bit_rate") if isinstance(item.get("bit_rate"), int) else None,
                size_bytes=addr.get("data_size") if isinstance(addr.get("data_size"), int) else None,
                url_list=urls,
            )
        )

    if not streams:
        addr = video.get("play_addr") or {}
        urls = _collect_play_urls(addr)
        if urls:
            height = video.get("height") if isinstance(video.get("height"), int) else None
            width = video.get("width") if isinstance(video.get("width"), int) else None
            streams.append(
                DouyinStream(
                    quality_label=_gear_to_label(None, height),
                    height=height,
                    width=width,
                    bitrate=None,
                    size_bytes=addr.get("data_size") if isinstance(addr.get("data_size"), int) else None,
                    url_list=urls,
                )
            )

    streams.sort(key=lambda s: ((s.height or 0), (s.bitrate or 0)), reverse=True)
    return streams


def fetch_video_info(url: str) -> DouyinVideoInfo:
    session = _get_warm_session()
    aweme_id = extract_aweme_id(url, session)
    try:
        data = _fetch_share_page(aweme_id, session)
    except Exception:
        # cookie 可能过期，重置后再试一次
        with _SESSION_LOCK:
            globals()["_CACHED_SESSION"] = None
        session = _get_warm_session()
        data = _fetch_share_page(aweme_id, session)

    page = _safe_pick(data, "loaderData", "video_(id)/page", default={}) or {}
    video_info_res = page.get("videoInfoRes") or {}
    items = video_info_res.get("item_list") or []
    if not items:
        filter_list = video_info_res.get("filter_list") or []
        if filter_list:
            notice = filter_list[0].get("notice") or "视频不可用或已被删除"
            raise RuntimeError(f"抖音返回：{notice}")
        raise RuntimeError("未获取到视频信息，可能链接已失效或视频被屏蔽")

    item = items[0]
    aweme_type = item.get("aweme_type")
    if item.get("images"):
        # 图集类型暂不支持下载（没有视频流）
        raise RuntimeError("该链接是抖音图文内容，暂不支持视频下载")

    video = item.get("video") or {}
    streams = _build_streams(video)
    if not streams:
        raise RuntimeError("未解析到可下载的视频流")

    raw_duration = video.get("duration")
    duration_seconds: float | None = None
    if isinstance(raw_duration, (int, float)) and raw_duration > 0:
        # 抖音的 duration 单位是毫秒
        duration_seconds = raw_duration / 1000.0

    cover = (
        _safe_pick(video, "origin_cover", "url_list", default=None)
        or _safe_pick(video, "cover", "url_list", default=None)
        or _safe_pick(video, "dynamic_cover", "url_list", default=None)
        or []
    )
    cover_url = _normalize_url(cover[0]) if cover else None

    title = (item.get("desc") or "").strip().split("\n", 1)[0][:120] or "抖音视频"
    description = item.get("desc") or ""
    uploader = _safe_pick(item, "author", "nickname")

    webpage_url = f"https://www.douyin.com/video/{aweme_id}"

    return DouyinVideoInfo(
        aweme_id=aweme_id,
        title=title,
        description=description,
        uploader=uploader,
        duration_seconds=duration_seconds,
        cover_url=cover_url,
        webpage_url=webpage_url,
        streams=streams,
    )


# ---------------------------------------------------------------------------
# 下载部分
# ---------------------------------------------------------------------------

QUALITY_HEIGHT_CAP: dict[str, int | None] = {
    "best": None,
    "4k": 2160,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "audio": None,  # 抖音返回的就是 mp4，单独提取音频走 ffmpeg
}


def select_stream(streams: list[DouyinStream], quality: str) -> DouyinStream:
    """根据请求的画质 key 在已解析到的 stream 列表里挑一个最合适的。

    抖音不像 B 站 / YouTube 那样总会提供多档；如果用户想要的高度找不到，
    就退回给最接近的可用档位（不报错）。
    """
    if not streams:
        raise RuntimeError("没有可用的视频流")
    cap = QUALITY_HEIGHT_CAP.get(quality)
    if cap is None:
        return streams[0]
    candidates = [s for s in streams if (s.height or 0) <= cap]
    if candidates:
        return max(candidates, key=lambda s: (s.height or 0, s.bitrate or 0))
    return min(streams, key=lambda s: (s.height or 9999))


def stream_download(
    stream: DouyinStream,
    dest_path,
    *,
    on_progress=None,
    is_cancelled=None,
    chunk_size: int = 256 * 1024,
) -> None:
    """把抖音视频流下载到本地文件，支持进度回调与取消。

    on_progress(downloaded_bytes, total_bytes_or_none, speed_bytes_per_sec)
    is_cancelled() -> bool，下载循环里会周期性检查
    """
    session = _get_warm_session()
    headers = {
        "User-Agent": _MOBILE_UA,
        "Referer": "https://www.douyin.com/",
        "Accept": "*/*",
    }

    last_error: Exception | None = None
    for url in stream.url_list:
        try:
            with session.get(url, headers=headers, stream=True, timeout=30) as resp:
                if resp.status_code in (403, 404):
                    last_error = RuntimeError(f"视频源返回 {resp.status_code}")
                    continue
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length") or 0) or stream.size_bytes
                downloaded = 0
                started = time.time()
                last_emit = 0.0
                with open(dest_path, "wb") as fp:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if is_cancelled and is_cancelled():
                            raise _DouyinCancelled()
                        if not chunk:
                            continue
                        fp.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if on_progress and (now - last_emit) >= 0.25:
                            elapsed = max(now - started, 0.001)
                            on_progress(downloaded, total or None, downloaded / elapsed)
                            last_emit = now
                if on_progress:
                    elapsed = max(time.time() - started, 0.001)
                    on_progress(downloaded, total or downloaded, downloaded / elapsed)
                return
        except _DouyinCancelled:
            raise
        except requests.RequestException as exc:
            last_error = exc
            continue
    raise RuntimeError(f"抖音视频下载失败：{last_error}")


class _DouyinCancelled(Exception):
    pass
