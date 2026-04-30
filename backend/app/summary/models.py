import time
from dataclasses import asdict, dataclass, field
from typing import Literal


SummaryStatus = Literal["queued", "extracting_subtitles", "summarizing", "done", "error"]
ChatRole = Literal["user", "assistant"]


@dataclass
class SubtitleSegment:
    index: int
    start: float
    end: float
    start_text: str
    end_text: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChatMessage:
    role: ChatRole
    content: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SummaryTask:
    summary_id: str
    url: str
    client_ip: str
    title: str | None = None
    platform: str | None = None
    status: SummaryStatus = "queued"
    pct: float = 0
    stage_text: str = "等待生成 AI 总结"
    duration: int | None = None
    language: str | None = None
    segments: list[SubtitleSegment] = field(default_factory=list)
    summary_text: str | None = None
    outline_markdown: str | None = None
    mindmap_markdown: str | None = None
    chat_messages: list[ChatMessage] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def fail(self, message: str) -> None:
        self.status = "error"
        self.error = message
        self.pct = 100
        self.stage_text = "AI 总结失败"
        self.touch()

    def to_dict(self, include_result: bool = True) -> dict:
        data = asdict(self)
        data["segments"] = [segment.to_dict() for segment in self.segments] if include_result else []
        data["chat_messages"] = [message.to_dict() for message in self.chat_messages]
        if not include_result:
            data["summary_text"] = None
            data["outline_markdown"] = None
            data["mindmap_markdown"] = None
        return data


class SummaryError(Exception):
    """Raised when an AI summary task cannot be completed safely."""

