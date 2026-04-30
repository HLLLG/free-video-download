# 项目总结：Free Video Download

> 沉淀版本：MVP 视频下载 + AI 视频总结功能完成
> 最近更新：2026-05-01

## 1. 项目定位

Free Video Download 是一个基于 `yt-dlp` 的万能视频下载站 MVP。用户在浏览器中粘贴公开视频链接，即可解析视频信息、选择清晰度、查看异步下载进度，并在完成后下载到本地。当前版本已经新增 AI 视频总结能力：对带字幕的视频生成视频总览、结构化要点、时间戳字幕、思维导图，并支持基于字幕内容继续追问。项目目标是把命令行工具 `yt-dlp` 与 AI 学习助手能力包装成对普通用户友好的 Web 产品，并预留 Pro 付费、移动端等增长空间。

## 2. 已完成的能力

### 2.1 解析与下载

- 单链接视频解析：返回标题、封面、作者、时长、平台标签等结构化信息。
- 清晰度选择：内置 `best / 1080p / 720p / 480p / 仅音频` 等格式，并预留 `4K` 等 Pro 档位字段。
- 异步下载任务：每次下载创建独立任务 ID，前端通过轮询 `/api/progress/{task_id}` 获取进度、速度、ETA 与阶段文案。
- 任务取消：支持显式取消，进度 hook 检测取消标志后中止 `yt-dlp`。
- 文件下发：下载完成后通过 `/api/file/{task_id}` 以 `application/octet-stream` 返回，浏览器直接保存。
- 临时文件治理：每个任务一个独立工作目录，任务完成、取消或超出 TTL 后由后台协程统一清理。

### 2.2 平台与兼容性

- 通用平台：YouTube、Bilibili、TikTok、X / Twitter、Instagram、Facebook、Vimeo、Twitch、微博、快手、小红书等。
- 抖音定制：内置 `douyin` 提取器分支，处理抖音常见的反爬与封面 Referer 问题。
- 封面代理：`/api/thumbnail` 仅放行白名单 CDN，并按平台注入 Referer，解决跨域与防盗链导致的封面加载失败。
- 合并输出：默认通过 `ffmpeg` 合并音视频为 `mp4`。

### 2.3 前端体验

- Vite + 原生 HTML/CSS/JS 单页：无重型框架依赖，构建产物可直接由后端托管。
- 营销型首页：突出 "粘贴 → 解析 → 下载" 三步流，并铺设 Pro 付费能力的占位区。
- 移动端适配：响应式布局，适配主流手机尺寸。
- 进度可视化：实时显示百分比、速度、ETA、阶段文案，并支持中途取消。

### 2.4 AI 视频总结

- 总结入口：视频解析成功后，在下载按钮旁展示 "AI 总结" 入口。
- 字幕来源：通过 `yt-dlp` 读取平台原生字幕，优先中文，其次英文；无字幕视频暂不支持。
- 总结产物：生成视频总览、结构化 Markdown 要点、带时间戳字幕和 Markmap 思维导图。
- AI 追问：基于已抽取字幕调用 DeepSeek 回答问题，并尽量引用时间戳依据。
- 模型接入：使用 DeepSeek V4-Flash（`deepseek-v4-flash`），通过 OpenAI Chat Completions 兼容协议调用，显式关闭 thinking mode。
- 限流策略：MVP 阶段按 IP 进行内存限流，每 IP 每天 5 次，单视频最长 40 分钟。
- 任务治理：总结任务与结果保存在内存中，默认 30 分钟 TTL，由独立清理协程回收。

## 3. 系统架构

```text
浏览器
  │  POST /api/info      解析视频信息
  │  POST /api/download  创建下载任务
  │  GET  /api/progress  轮询进度
  │  GET  /api/file      下载产物
  │  GET  /api/thumbnail 封面代理
  │  POST /api/summary   创建 AI 总结任务
  │  GET  /api/summary   轮询/读取总结结果
  │  POST /api/summary/chat  基于字幕追问
  ▼
FastAPI (app.main)
  ├── api.py         路由层 + 入参校验 + 错误归一
  ├── downloader.py  yt-dlp 调用、平台识别、清晰度选择、进度 hook
  ├── douyin.py      抖音定制提取逻辑
  ├── tasks.py       任务字典 / 信号量 / TTL 清理协程
  ├── summary/       AI 总结：字幕、限流、DeepSeek、任务状态、问答
  └── config.py      路径、并发、TTL、格式选择器等配置
        │
        ├── yt-dlp (Python API)
        ├── ffmpeg (子进程)
        ├── DeepSeek V4-Flash
        └── var/downloads/<task_id>/  临时工作目录
```

关键设计点：

- **任务模型**：`DownloadTask` 是一个 dataclass，承载 `status / pct / speed / eta / stage / file_path / error` 等字段，统一序列化给前端。
- **总结模型**：`SummaryTask` 独立承载 `status / pct / segments / summary_text / outline_markdown / mindmap_markdown / chat_messages / error`，不影响下载任务。
- **并发控制**：使用 `asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)` 限制同时执行的下载数，避免单机被打爆。
- **生命周期**：FastAPI `lifespan` 在启动时拉起下载任务和总结任务清理协程，每 60 秒扫描一次过期任务。
- **静态托管**：若 `frontend/dist` 存在则自动挂载，部署时只暴露后端一个端口即可。

## 4. 关键代码结构

```text
backend/
├── app/
│   ├── main.py         FastAPI 入口、CORS、lifespan、静态托管
│   ├── api.py          路由：health / info / download / progress / cancel / file / thumbnail
│   ├── downloader.py   yt-dlp 封装、清晰度选择器、进度 hook、平台识别
│   ├── douyin.py       抖音定制提取器
│   ├── tasks.py        任务字典、信号量、取消、TTL 清理
│   ├── summary/        AI 总结模块
│   │   ├── api.py          路由：summary / chat / delete
│   │   ├── subtitles.py    字幕抽取、语言优先级、清洗、分段
│   │   ├── llm_client.py   DeepSeek OpenAI-compatible 调用
│   │   ├── pipeline.py     总结异步流程和追问
│   │   ├── tasks.py        SummaryTask 字典和 TTL 清理
│   │   ├── rate_limit.py   IP 每日限流
│   │   ├── prompts.py      摘要/思维导图/对话 prompt
│   │   └── settings.py     DeepSeek 与限流配置
│   └── config.py       路径、并发、TTL、格式选择器
├── requirements.txt
└── var/downloads/      运行时临时目录（已在 .gitignore）

frontend/
├── index.html
├── src/
│   ├── main.js         交互逻辑、轮询、进度渲染
│   ├── summary.js      AI 总结入口、Tab、对话、Markmap 渲染
│   └── styles.css      响应式与营销视觉
├── package.json        Vite 配置
└── dist/               构建产物（已在 .gitignore）

docs/
├── requirements-analysis.md
├── technical-design.md
└── project-summary.md  本文件
```

## 5. 关键配置项

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `FVD_TEMP_DIR` | `backend/var/downloads` | 临时下载目录，可用环境变量覆盖 |
| `TASK_TTL_SECONDS` | `30 * 60` | 任务保留时间，过期清理 |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | 同时进行的下载任务上限 |
| `MAX_URL_LENGTH` | `2048` | 单条 URL 长度上限 |
| `MAX_DURATION_SECONDS` | `4 * 60 * 60` | 单视频最长 4 小时，防止大文件冲爆磁盘 |
| `DEFAULT_FORMAT` | `bv*[height<=1080]+ba/b[height<=1080]` | 默认 1080p 选择器 |
| `DEEPSEEK_API_KEY` | 无 | AI 总结必填，可放系统环境变量或 `backend/.env` |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek OpenAI-compatible API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | AI 总结默认模型 |
| `SUMMARY_DAILY_LIMIT_PER_IP` | `5` | 每 IP 每日 AI 总结次数 |
| `SUMMARY_MAX_DURATION_SECONDS` | `40 * 60` | 免费 AI 总结单视频最长 40 分钟 |
| `SUMMARY_TASK_TTL_SECONDS` | `30 * 60` | AI 总结任务和结果保留时间 |

## 6. 接口速查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| POST | `/api/info` | 解析视频信息 |
| POST | `/api/download` | 创建下载任务，返回 `task_id` |
| GET | `/api/progress/{task_id}` | 轮询任务进度 |
| POST | `/api/cancel/{task_id}` | 取消任务 |
| GET | `/api/file/{task_id}` | 下载完成后的文件 |
| GET | `/api/thumbnail` | 封面代理（带 Referer 白名单） |
| POST | `/api/summary` | 创建 AI 总结任务，返回 `summary_id` |
| GET | `/api/summary/{summary_id}` | 轮询总结进度或读取总结结果 |
| POST | `/api/summary/{summary_id}/chat` | 基于字幕内容继续追问 |
| DELETE | `/api/summary/{summary_id}` | 主动删除总结任务 |

## 7. 已踩过的坑与对应方案

- **抖音封面加载失败**：抖音 / 小红书 / Bilibili 等存在 Referer 防盗链，前端直链加载会 403。通过后端 `/api/thumbnail` 代理 + 白名单域名 + 平台 Referer 解决。
- **ffmpeg 合并依赖**：高画质往往需要分别下载视频流和音频流再用 `ffmpeg` 合并，部署环境必须预装 `ffmpeg` 二进制。
- **进度回调性能**：`yt-dlp` 的 `progress_hooks` 调用频率较高，hook 内只更新内存字段并刷新 `updated_at`，避免在 hook 里做磁盘 IO。
- **任务孤儿目录**：异常退出会留下临时目录，统一通过 `cleanup_expired_tasks` 协程兜底清理；显式 `cancel/remove_task` 也会立即 `rmtree`。
- **跨域**：开发态前端 5173 与后端 8000 分离，通过 `CORSMiddleware` 显式放行 `localhost:5173 / 127.0.0.1:5173`，生产态由后端托管静态资源后无需 CORS。
- **`.env` 未自动加载**：AI 总结需要 `DEEPSEEK_API_KEY`，已在 `summary/settings.py` 中补充 `backend/.env` 读取逻辑，避免本地每次手动设置系统环境变量。
- **字幕编码与格式差异**：YouTube、Bilibili 字幕可能是 `json3`、`json`、`vtt`、`srt` 等格式，`summary/subtitles.py` 做了多格式解析和简单去重聚合。
- **无效 URL 创建错误任务**：曾出现 `POST /api/summary` 对无效 URL 返回 200 并创建后台任务的问题，已改为创建任务前同步校验 URL，错误直接返回 400。

## 8. 已知限制

- 任务状态、进度仅存内存，进程重启后丢失；适合单机 MVP，不适合多副本部署。
- AI 总结结果和对话也仅存内存，默认 30 分钟后清理，暂不支持历史记录。
- AI 总结 MVP 只使用平台原生字幕，不做 ASR；无字幕视频会提示暂不支持。
- DeepSeek 调用会把字幕内容发送给第三方模型服务，生产环境需要在页面和服务条款中明确提示。
- 暂未支持用户上传 cookies，因此部分需要登录态、会员或地区限制的视频可能解析失败或仅能拿到低画质。
- 不绕过 DRM，不缓存用户视频，所有产物默认在 30 分钟后清理。
- 没有用户系统，Pro 档位目前仅是 UI 占位。

## 9. 后续可演进方向

1. **持久化任务**：把下载和总结任务字典换成 Redis / SQLite，支持多副本与重启续跑。
2. **ASR 兜底**：无字幕视频自动抽取音频并转写。
3. **用户体系 + Pro 付费**：登录、配额、4K / 批量下载 / 更长视频总结等高级能力落地。
4. **导出能力**：AI 总结结果导出 Markdown / PDF / Word，或同步 Notion / Obsidian。
5. **批量与播放列表**：把单链接扩展为播放列表整包下载和批量总结。
6. **Cookies 上传**：让用户在前端粘贴自己的 cookies，解决会员、私密视频解析。
7. **观测性**：接入结构化日志、Prometheus 指标，监控并发数、失败率、平均下载/总结时长。
8. **CDN / 对象存储**：对完成的产物落 S3 / OSS，签名 URL 直发用户，释放服务器带宽。
9. **`yt-dlp` 自动升级**：`yt-dlp` 与平台是猫鼠游戏，需要定期升级或在容器里跑自更新任务。

## 10. 本地运行速记

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# 可选：在 backend/.env 配置 DEEPSEEK_API_KEY=sk-...
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev   # 开发态：http://127.0.0.1:5173
npm run build # 生产态：构建产物由后端自动托管
```

依赖：Python 3.10+、Node.js 18+、`ffmpeg` 二进制。
