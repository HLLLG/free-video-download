# Free Video Download

一个基于 Python + FastAPI + yt-dlp 的万能视频下载站 MVP。用户可以粘贴公开视频链接，解析视频信息，选择清晰度，查看异步下载进度，并在完成后保存到本地；也可以对带字幕的视频生成 AI 摘要、时间戳字幕、思维导图并继续追问。

## 功能

- 单链接视频解析。
- 标题、封面、作者、时长、平台展示。
- 1080p / 720p / 480p / 仅音频等清晰度选择。
- 异步下载任务和进度轮询。
- 下载完成后返回文件。
- 临时文件自动清理。
- AI 视频总结：基于平台原生字幕生成视频总览、结构化要点和思维导图。
- 带时间戳字幕展示和基于字幕内容的 AI 追问。
- 免费限额：AI 总结次数由环境变量 `SUMMARY_DAILY_LIMIT_PER_IP` 控制（默认 `0` 表示不限制，便于测试；生产可设为正整数）；单视频最长 40 分钟。
- 营销型首页、Pro 付费能力预留、移动端适配。

## 本地开发

### 后端

需要 Python 3.10+ 和 ffmpeg。

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

健康检查（端口需与上面一致，且与 `frontend/vite.config.js` 中 `/api` 代理目标一致）：

```bash
curl http://127.0.0.1:8001/api/health
```

AI 视频总结需要配置 DeepSeek API Key：

```bash
set DEEPSEEK_API_KEY=sk-...
```

也可以在 `backend/.env` 写入：

```bash
DEEPSEEK_API_KEY=sk-...
```

默认使用 `deepseek-v4-flash`，通过 OpenAI Chat Completions 兼容接口调用 DeepSeek。MVP 仅使用平台原生字幕，无字幕视频会提示暂不支持。

#### B 站字幕（AI 生成 / AI 翻译 / 部分 UP 上传）

B 站把字幕分为「UP 上传」「AI 自动生成」「AI 翻译」三类，绝大多数情况下需要登录态才能读取（接口会返回 `need_login_subtitle: true`）。如果运营方希望支持 B 站 AI 总结，可在 `backend/.env` 中配置共享小号的 SESSDATA：

```bash
BILIBILI_SESSDATA=你的SESSDATA
# 可选：写入这两个能进一步降低风控概率
BILIBILI_BILI_JCT=你的bili_jct
BILIBILI_BUVID3=你的buvid3
```

注意事项：

- SESSDATA 一般 1-3 个月失效，需要运营方手动更新；
- 后端只把 Cookie 用于 B 站 / hdslb.com 域，绝不会带给第三方平台；
- 不配置 Cookie 时，B 站需登录字幕的视频会返回明确提示「站点未配置 B 站登录态 Cookie」，不影响 YouTube 等其他平台。

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。

## 生产构建

```bash
cd frontend
npm install
npm run build
```

前端构建产物会输出到 `frontend/dist`，后端启动时会自动挂载静态页面。修改 `frontend/src` 后请重新执行 `npm run build`，否则仅跑后端时浏览器仍可能加载旧的打包文件。

## 文档

- [需求分析](docs/requirements-analysis.md)
- [方案设计](docs/technical-design.md)
- [AI 视频总结方案](docs/ai-summary-design.md)
- [项目总结](docs/project-summary.md)

## 注意事项

- `yt-dlp` 支持平台很多，但部分平台或高画质资源可能需要 cookies、登录态或会员权限。
- MVP 暂不支持用户上传 cookies。
- 大文件会消耗磁盘空间，生产环境请配置独立临时目录、并发限制和更严格的清理策略。
- 生产环境建议定期升级 `yt-dlp`。
- AI 总结会将视频字幕发送给 DeepSeek 生成结果，请仅处理你有权查看和分析的内容。

## 免责声明

本项目只是 `yt-dlp` 的可视化封装。所有视频内容版权归原作者和平台所有，请仅下载你有权获取和保存的内容。本站不绕过 DRM，不鼓励违反平台条款或版权规则的使用方式，也不长期缓存用户视频。
