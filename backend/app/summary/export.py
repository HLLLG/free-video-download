"""把内存中的 SubtitleSegment 列表导出成 SRT / VTT / TXT 文本。"""

from __future__ import annotations

import re

from .models import SubtitleSegment


SUPPORTED_FORMATS = ("srt", "vtt", "txt")


def _format_timestamp(seconds: float, separator: str) -> str:
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    millis = int(round((total - int(total)) * 1000))
    if millis == 1000:
        millis = 0
        secs += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _to_srt(segments: list[SubtitleSegment]) -> str:
    lines: list[str] = []
    for idx, segment in enumerate(segments, start=1):
        start = _format_timestamp(segment.start, ",")
        end = _format_timestamp(max(segment.end, segment.start), ",")
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(segment.text.strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _to_vtt(segments: list[SubtitleSegment]) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for segment in segments:
        start = _format_timestamp(segment.start, ".")
        end = _format_timestamp(max(segment.end, segment.start), ".")
        lines.append(f"{start} --> {end}")
        lines.append(segment.text.strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _to_txt(segments: list[SubtitleSegment]) -> str:
    lines = [segment.text.strip() for segment in segments if segment.text.strip()]
    return "\n".join(lines) + "\n"


_FORMATTERS = {
    "srt": _to_srt,
    "vtt": _to_vtt,
    "txt": _to_txt,
}


_MEDIA_TYPES = {
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}


_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def render_subtitle(segments: list[SubtitleSegment], fmt: str) -> str:
    formatter = _FORMATTERS.get(fmt.lower())
    if not formatter:
        raise ValueError(f"unsupported subtitle format: {fmt}")
    return formatter(segments)


def media_type_for(fmt: str) -> str:
    return _MEDIA_TYPES.get(fmt.lower(), "text/plain; charset=utf-8")


def safe_filename(title: str | None, fmt: str) -> str:
    base = (title or "subtitle").strip()
    base = _INVALID_FILENAME_CHARS.sub(" ", base)
    base = re.sub(r"\s+", " ", base).strip().strip(".")
    if not base:
        base = "subtitle"
    if len(base) > 80:
        base = base[:80].rstrip()
    return f"{base}.{fmt.lower()}"
