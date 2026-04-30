from __future__ import annotations

import asyncio
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import SummaryError
from .settings import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    SUMMARY_CHAT_TIMEOUT_SECONDS,
    SUMMARY_LLM_TIMEOUT_SECONDS,
)


def _api_url() -> str:
    return DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"


def _extract_json_object(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if not match:
            raise SummaryError("AI 总结结果格式异常，请重试。") from None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise SummaryError("AI 总结结果格式异常，请重试。") from exc


def _request_chat(messages: list[dict], timeout: int, max_tokens: int) -> str:
    if not DEEPSEEK_API_KEY:
        raise SummaryError("AI 总结服务暂未配置，请联系管理员。")

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
    }
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        _api_url(),
        data=body,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
        if exc.code == 401:
            raise SummaryError("AI 总结服务鉴权失败，请检查 DeepSeek API Key。") from exc
        if exc.code == 429:
            raise SummaryError("AI 总结服务请求过于频繁，请稍后重试。") from exc
        raise SummaryError(f"AI 总结服务请求失败：HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise SummaryError(f"AI 总结服务连接失败：{exc.reason}") from exc
    except TimeoutError as exc:
        raise SummaryError("AI 总结生成超时，请稍后重试。") from exc

    try:
        data = json.loads(raw)
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise SummaryError("AI 总结服务返回格式异常，请稍后重试。") from exc


async def create_summary(system_prompt: str, user_prompt: str) -> dict:
    content = await asyncio.to_thread(
        _request_chat,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        SUMMARY_LLM_TIMEOUT_SECONDS,
        5000,
    )
    data = _extract_json_object(content)
    required = ("summary_text", "outline_markdown", "mindmap_markdown")
    if any(not isinstance(data.get(key), str) or not data[key].strip() for key in required):
        raise SummaryError("AI 总结结果缺少必要字段，请重试。")
    return data


async def answer_question(system_prompt: str, user_prompt: str) -> str:
    content = await asyncio.to_thread(
        _request_chat,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        SUMMARY_CHAT_TIMEOUT_SECONDS,
        2000,
    )
    answer = content.strip()
    if not answer:
        raise SummaryError("AI 对话返回为空，请重试。")
    return answer

