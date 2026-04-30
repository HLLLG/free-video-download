from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from urllib.request import Request, urlopen

import yt_dlp

from ..downloader import DownloadError, validate_url
from .models import SubtitleSegment, SummaryError
from .settings import SUMMARY_MAX_DURATION_SECONDS


LANGUAGE_PRIORITY = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "en")
FORMAT_PRIORITY = ("json3", "json", "vtt", "srt")
USER_AGENT = "Mozilla/5.0 (compatible; FreeVideoDownload/1.0)"


@dataclass
class SubtitleTrack:
    language: str
    url: str
    ext: str
    source: str


@dataclass
class SubtitleExtraction:
    title: str | None
    platform: str | None
    duration: int | None
    language: str
    segments: list[SubtitleSegment]


def _format_timestamp(seconds: float | int | None) -> str:
    if seconds is None:
        seconds = 0
    total = max(0, int(float(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\\.*?\}", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_lang(value: str) -> str:
    return value.lower().replace("_", "-")


def _track_sort_key(track: dict) -> tuple[int, str]:
    ext = (track.get("ext") or "").lower()
    try:
        rank = FORMAT_PRIORITY.index(ext)
    except ValueError:
        rank = len(FORMAT_PRIORITY)
    return rank, ext


def _pick_track_from_bucket(bucket: dict, source: str) -> SubtitleTrack | None:
    if not bucket:
        return None

    available = {str(language): tracks for language, tracks in bucket.items() if tracks}
    if not available:
        return None

    ordered_languages: list[str] = []
    normalized = {_normalize_lang(language): language for language in available}
    for preferred in LANGUAGE_PRIORITY:
        preferred_norm = _normalize_lang(preferred)
        if preferred_norm in normalized:
            ordered_languages.append(normalized[preferred_norm])
            continue
        prefix_match = next(
            (language for norm, language in normalized.items() if norm.startswith(preferred_norm + "-")),
            None,
        )
        if prefix_match:
            ordered_languages.append(prefix_match)
    ordered_languages.extend(language for language in available if language not in ordered_languages)

    for language in ordered_languages:
        tracks = sorted(available[language], key=_track_sort_key)
        for track in tracks:
            url = track.get("url")
            ext = (track.get("ext") or "").lower()
            if url and ext:
                return SubtitleTrack(language=language, url=url, ext=ext, source=source)
    return None


def _select_subtitle_track(info: dict) -> SubtitleTrack | None:
    return _pick_track_from_bucket(info.get("subtitles") or {}, "subtitles") or _pick_track_from_bucket(
        info.get("automatic_captions") or {},
        "automatic_captions",
    )


def _download_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_timecode(value: str) -> float:
    clean = value.strip().replace(",", ".")
    parts = clean.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
    except ValueError:
        return 0
    return 0


def _parse_vtt_or_srt(content: str) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").replace("\r", "\n"))
    timing = re.compile(
        r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[\.,]\d{1,3})\s*-->\s*"
        r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[\.,]\d{1,3})"
    )
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or lines[0].upper().startswith("WEBVTT"):
            continue
        timing_index = next((idx for idx, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        match = timing.search(lines[timing_index])
        if not match:
            continue
        text = _clean_text(" ".join(lines[timing_index + 1 :]))
        if text:
            cues.append((_parse_timecode(match.group("start")), _parse_timecode(match.group("end")), text))
    return cues


def _parse_json3(content: str) -> list[tuple[float, float, str]]:
    data = json.loads(content)
    cues: list[tuple[float, float, str]] = []
    for event in data.get("events") or []:
        start_ms = event.get("tStartMs")
        if start_ms is None:
            continue
        duration_ms = event.get("dDurationMs") or 0
        text = _clean_text("".join((seg.get("utf8") or "") for seg in event.get("segs") or []))
        if text:
            start = float(start_ms) / 1000
            end = start + float(duration_ms) / 1000
            cues.append((start, end, text))
    return cues


def _parse_bilibili_json(content: str) -> list[tuple[float, float, str]]:
    data = json.loads(content)
    body = data.get("body") if isinstance(data, dict) else None
    if not isinstance(body, list):
        return []
    cues: list[tuple[float, float, str]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        text = _clean_text(str(item.get("content") or ""))
        if not text:
            continue
        start = float(item.get("from") or 0)
        end = float(item.get("to") or start)
        cues.append((start, end, text))
    return cues


def _parse_subtitle_content(content: str, ext: str) -> list[tuple[float, float, str]]:
    normalized_ext = ext.lower()
    if normalized_ext == "json3":
        return _parse_json3(content)
    if normalized_ext == "json":
        cues = _parse_bilibili_json(content)
        return cues or _parse_json3(content)
    if normalized_ext in {"vtt", "srt"}:
        return _parse_vtt_or_srt(content)
    return _parse_vtt_or_srt(content)


def _dedupe_cues(cues: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    deduped: list[tuple[float, float, str]] = []
    previous_text = ""
    for start, end, text in sorted(cues, key=lambda item: item[0]):
        clean = _clean_text(text)
        if not clean or clean == previous_text:
            continue
        previous_text = clean
        deduped.append((start, max(end, start), clean))
    return deduped


def _aggregate_cues(cues: list[tuple[float, float, str]]) -> list[SubtitleSegment]:
    segments: list[SubtitleSegment] = []
    current_text: list[str] = []
    current_start: float | None = None
    current_end: float | None = None

    def flush() -> None:
        nonlocal current_start, current_end, current_text
        text = _clean_text(" ".join(current_text))
        if current_start is not None and current_end is not None and text:
            segments.append(
                SubtitleSegment(
                    index=len(segments) + 1,
                    start=current_start,
                    end=current_end,
                    start_text=_format_timestamp(current_start),
                    end_text=_format_timestamp(current_end),
                    text=text,
                )
            )
        current_start = None
        current_end = None
        current_text = []

    for start, end, text in _dedupe_cues(cues):
        if current_start is None:
            current_start = start
        current_end = end
        current_text.append(text)
        text_len = len("".join(current_text))
        span = current_end - current_start
        if text_len >= 400 or span >= 45:
            flush()
    flush()
    return segments


def _extract_info(url: str) -> dict:
    with yt_dlp.YoutubeDL(
        {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "ignoreerrors": False,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "json3/vtt/srt/best",
        }
    ) as ydl:
        return ydl.sanitize_info(ydl.extract_info(url, download=False))


def extract_subtitles(url: str) -> SubtitleExtraction:
    try:
        clean_url = validate_url(url)
    except DownloadError as exc:
        raise SummaryError(str(exc)) from exc

    try:
        info = _extract_info(clean_url)
    except Exception as exc:
        raise SummaryError(f"字幕信息解析失败：{str(exc)[:300]}") from exc

    duration = info.get("duration")
    try:
        duration_seconds = int(duration) if duration else None
    except (TypeError, ValueError):
        duration_seconds = None
    if duration_seconds and duration_seconds > SUMMARY_MAX_DURATION_SECONDS:
        raise SummaryError("当前免费版仅支持总结 40 分钟以内的视频。")

    track = _select_subtitle_track(info)
    if not track:
        raise SummaryError("当前视频没有可用字幕，AI 总结暂不支持。后续版本会加入语音转写能力。")

    try:
        content = _download_text(track.url)
        cues = _parse_subtitle_content(content, track.ext)
    except Exception as exc:
        raise SummaryError(f"字幕下载或解析失败：{str(exc)[:300]}") from exc

    segments = _aggregate_cues(cues)
    if not segments:
        raise SummaryError("字幕内容为空，AI 总结暂不支持。")

    extractor = (info.get("extractor_key") or info.get("extractor") or "").strip()
    return SubtitleExtraction(
        title=info.get("title"),
        platform=extractor or None,
        duration=duration_seconds,
        language=track.language,
        segments=segments,
    )


def segments_to_transcript(segments: list[SubtitleSegment]) -> str:
    return "\n".join(f"[{segment.start_text}-{segment.end_text}] {segment.text}" for segment in segments)

