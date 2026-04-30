SUMMARY_SYSTEM_PROMPT = """你是专业的视频学习助理。你只根据用户提供的带时间戳字幕进行总结，不编造字幕中不存在的信息。
输出必须是严格 JSON，不要使用 Markdown 代码块包裹。所有正文使用简体中文。"""


def build_summary_prompt(title: str | None, transcript: str) -> str:
    video_title = title or "未命名视频"
    return f"""请根据以下视频字幕生成学习型总结。

视频标题：{video_title}

要求：
1. summary_text：用 200-400 字概括视频整体内容。
2. outline_markdown：输出 Markdown，大纲分层清晰，重要要点尽量附时间戳。
3. key_points：提取 5-10 个核心知识点，每个知识点包含 title、timestamp、description。
4. mindmap_markdown：输出适合 Markmap 渲染的 Markdown，从 # 视频主题 开始，最多 3 层。
5. 不要虚构字幕之外的信息。

JSON 格式：
{{
  "summary_text": "视频总览",
  "outline_markdown": "## 视频大纲\\n...",
  "key_points": [
    {{"title": "核心知识点", "timestamp": "00:00", "description": "说明"}}
  ],
  "mindmap_markdown": "# 视频主题\\n## 第一部分\\n- 要点"
}}

字幕：
{transcript}
"""


CHAT_SYSTEM_PROMPT = """你是视频内容问答助手。你只能基于提供的字幕回答问题。
如果字幕中没有足够信息，请明确说明。回答应简洁、准确，并尽量引用相关时间戳。"""


def build_chat_prompt(title: str | None, transcript: str, question: str) -> str:
    video_title = title or "未命名视频"
    return f"""视频标题：{video_title}

字幕：
{transcript}

用户问题：
{question}

请用简体中文回答，并尽量用项目符号列出关键依据。"""

