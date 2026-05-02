from __future__ import annotations

from .llm_client import answer_question, create_summary
from .models import ChatMessage, SummaryError, SummaryTask
from .prompts import CHAT_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT, build_chat_prompt, build_summary_prompt
from .subtitles import extract_subtitles, segments_to_transcript
from .tasks import SUMMARY_SEMAPHORE


async def run_summary_task(task: SummaryTask) -> None:
    async with SUMMARY_SEMAPHORE:
        try:
            task.status = "extracting_subtitles"
            task.pct = 15
            task.stage_text = "正在读取视频字幕..."
            task.touch()

            extraction = extract_subtitles(
                task.url,
                max_duration_seconds=task.max_duration_seconds,
            )
            task.title = task.title or extraction.title
            task.platform = extraction.platform
            task.duration = extraction.duration
            task.language = extraction.language
            task.segments = extraction.segments
            task.pct = 45
            task.stage_text = "字幕读取完成，正在生成 AI 总结..."
            task.touch()

            transcript = segments_to_transcript(task.segments)
            task.status = "summarizing"
            task.pct = 60
            task.stage_text = "正在生成视频要点和思维导图..."
            task.touch()

            summary = await create_summary(
                SUMMARY_SYSTEM_PROMPT,
                build_summary_prompt(task.title, transcript),
            )
            task.summary_text = summary["summary_text"].strip()
            task.outline_markdown = summary["outline_markdown"].strip()
            task.mindmap_markdown = summary["mindmap_markdown"].strip()
            task.status = "done"
            task.pct = 100
            task.stage_text = "AI 总结已完成"
            task.touch()
        except SummaryError as exc:
            task.fail(str(exc))
        except Exception as exc:
            task.fail(f"AI 总结失败：{str(exc)[:300]}")


async def chat_with_summary(task: SummaryTask, message: str) -> str:
    if task.status != "done":
        raise SummaryError("AI 总结尚未完成，暂时无法追问。")
    question = message.strip()
    if not question:
        raise SummaryError("请输入要追问的问题。")
    if len(question) > 1000:
        raise SummaryError("问题过长，请缩短后重试。")

    transcript = segments_to_transcript(task.segments)
    task.chat_messages.append(ChatMessage(role="user", content=question))
    task.touch()

    answer = await answer_question(
        CHAT_SYSTEM_PROMPT,
        build_chat_prompt(task.title, transcript, question),
    )
    task.chat_messages.append(ChatMessage(role="assistant", content=answer))
    task.touch()
    return answer

