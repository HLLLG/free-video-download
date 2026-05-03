# 项目总结：Free Video Download

> 沉淀版本：MVP 视频下载 + AI 视频总结 + 思维导图全屏/下载 + 字幕下载 + B 站登录态字幕 + Pro 会员（Stripe 一次性购买）
> 最近更新：2026-05-03（封面代理修复、B 站网页 412 兜底、Free 每日总结限额默认 3 次、Pro 升级弹窗体验）

## 1. 项目定位

Free Video Download 是一个基于 `yt-dlp` 的万能视频下载站 MVP。用户在浏览器中粘贴公开视频链接，即可解析视频信息、选择清晰度、查看异步下载进度，并在完成后下载到本地。当前版本已经新增 AI 视频总结能力：对带字幕的视频生成视频总览、结构化要点、时间戳字幕、思维导图，并支持基于字幕内容继续追问。**Pro 会员**已通过 **Stripe Checkout（一次性付款，不自动续费）** 落地：支付成功后发放会员密钥，前端写入 `localStorage` 并在请求头携带 `X-Membership-Key`，后端用 SQLite 校验有效期并解锁高级权益。项目目标是把命令行工具 `yt-dlp` 与 AI 学习助手能力包装成对普通用户友好的 Web 产品，并继续迭代移动端等增长空间。

## 2. 已完成的能力

### 2.1 解析与下载

- 单链接视频解析：返回标题、封面、作者、时长、平台标签等结构化信息。
- 清晰度选择：内置 `best / 1080p / 720p / 480p / 仅音频` 等格式；**`4K` 为 Pro 专享**，开通后在解析页可选中真实下载（后端校验请求头会员密钥与有效期）。
- 异步下载任务：每次下载创建独立任务 ID，前端通过轮询 `/api/progress/{task_id}` 获取进度、速度、ETA 与阶段文案。
- 任务取消：支持显式取消，进度 hook 检测取消标志后中止 `yt-dlp`。
- 文件下发：下载完成后通过 `/api/file/{task_id}` 以 `application/octet-stream` 返回，浏览器直接保存。
- 临时文件治理：每个任务一个独立工作目录，任务完成、取消或超出 TTL 后由后台协程统一清理。

### 2.2 平台与兼容性

- 通用平台：YouTube、Bilibili、TikTok、X / Twitter、Instagram、Facebook、Vimeo、Twitch、微博、快手、小红书等。
- B 站主域兼容：用户粘贴 `https://bilibili.com/...`（无 `www`）时，前端解析、下载与 AI 总结入口、以及后端 `validate_url` / 下载任务会统一归一为 `https://www.bilibili.com/...`，与 `yt-dlp` 的 B 站提取器习惯一致，减少解析失败。
- **B 站 Open API 兜底（`backend/app/bilibili.py`）**：当 B 站网页被风控返回 `HTTP 412` 等、导致 `yt-dlp` 无法拉取视频页时，**解析与下载**优先走 `api.bilibili.com` 的 `view` + `playurl` 公开接口拉元信息与可播放流，再用 `ffmpeg` 合并 DASH 视频/音频或转码仅音频；失败时再回退 `yt-dlp`，以兼容番剧、课程等非常规页。
- 抖音定制：内置 `douyin` 提取器分支，处理抖音常见的反爬与封面 Referer 问题。
- 封面代理：`/api/thumbnail` 仅放行白名单 CDN，并按平台注入 Referer，解决跨域与防盗链导致的封面加载失败；注意需避免与 FastAPI `Request` 命名冲突，否则代理会 500 导致封面不显示。
- 合并输出：默认通过 `ffmpeg` 合并音视频为 `mp4`。

### 2.3 前端体验

- Vite + 原生 HTML/CSS/JS 单页：无重型框架依赖，构建产物可直接由后端托管。
- 营销型首页：突出 "粘贴 → 解析 → 下载" 三步流；定价区已接入 **Stripe 购买月卡/年卡**、顶部会员徽章、支付成功回跳与「恢复会员」弹窗（邮箱 + 会员密钥）；**解析成功后**进入「左栏视频信息 + 下载 / 右栏 AI 总结」双栏布局（桌面端左栏 `sticky`，窄屏自动单列），首屏信息密度已压缩（Hero 间距与标题字号、输入卡加宽）。
- **解析后自动总结**：点击「立即解析」成功后自动创建 AI 总结任务，无需再点一次；左栏保留「重新生成总结」供失败重试或手动重跑。
- **Pro 升级弹窗**：月卡/年卡同屏展示、权益清单前置；**免费总结次数用尽**时，从 AI 总结错误区「升级 Pro」进入会展示**专属标题与说明**；年卡相对月卡按价格自动显示**省约 X%** 提示；解析后的紧凑模式下，顶部「升级 Pro」直接打开弹窗（不再仅依赖滚动到已隐藏的定价区）。
- **紧凑模式**：首次解析成功后为 `body` 增加 `compact-mode`，隐藏营销区（`#features` / `#pricing` / FAQ 等），减少滚动干扰。
- 移动端适配：响应式布局，适配主流手机尺寸。
- 进度可视化：下载进度合并进左侧视频卡内；右侧展示总结进度与 Tab（要点 / 字幕 / 思维导图 / 对话）。

### 2.4 AI 视频总结

- 总结入口：解析成功后自动触发；左栏「重新生成总结」可手动重试。
- 字幕来源：通过 `yt-dlp` 读取平台原生字幕，优先中文，其次英文；无字幕视频暂不支持。
- 总结产物：生成视频总览、结构化 Markdown 要点、带时间戳字幕和 Markmap 思维导图。
- AI 追问：基于已抽取字幕调用 DeepSeek 回答问题，并尽量引用时间戳依据。
- 模型接入：使用 DeepSeek V4-Flash（`deepseek-v4-flash`），通过 OpenAI Chat Completions 兼容协议调用，显式关闭 thinking mode。
- 限流策略：按 IP 内存限流，环境变量 `SUMMARY_DAILY_LIMIT_PER_IP` 控制每日次数；**代码默认值为 `3` 次/天**（未显式设置环境变量时）；`<=0` 表示关闭限额（便于联调）。**有效 Pro 会员**（请求头 `X-Membership-Key` 或登录态对应有效 Pro）**跳过每日次数限制**。单视频最长：免费用户由 `SUMMARY_MAX_DURATION_SECONDS` 限制（默认 40 分钟）；Pro 用户由 `PRO_SUMMARY_MAX_DURATION_SECONDS` 限制（默认 120 分钟）。
- B 站错误分流：当 `yt-dlp` 拿不到字幕时，后端会调用 `/x/web-interface/nav` 校验 `SESSDATA` 是否仍被 B 站识别为登录，区分 **未配置 Cookie / Cookie 被 B 站拒绝（风控或过期）/ Cookie 有效但视频无 CC 字幕轨** 三类文案；避免把「小号被风控」误判成「视频没字幕」。
- 运营自检：`GET /api/summary/bilibili/cookie-status` 返回当前 `.env` 中 B 站 Cookie 的登录态摘要（`uname` / `mid`，不暴露 Cookie 原文）。路由需放在动态 `/{summary_id}` 之前，避免被当成 `summary_id="bilibili"`。
- 任务治理：总结任务与结果保存在内存中，默认 30 分钟 TTL，由独立清理协程回收。

### 2.5 思维导图：全屏与高清下载

- 思维导图工具栏：在 "思维导图" Tab 顶部增加 `全屏查看 / 下载 PNG / 下载 SVG / 下载 Markdown` 按钮组，覆盖 "看不清" 与 "拿走再用" 两种诉求。
- 全屏模式：使用原生 `<dialog>` 模态铺满视口（高度 `90vh`），内嵌一份独立的 Markmap 实例，按 `ESC` 或点击关闭按钮即可退出，期间 `body` 加 `no-scroll` 防止页面背景滚动。
- 渲染稳定性：直接使用 `markmap-lib` + `markmap-view` IIFE 包，按容器实际像素宽高显式设置 `<svg width/height>`，规避 `markmap-autoloader` 在 `width="100%"` 时触发 d3 `getBBox()` 报 `NotSupportedError: Could not resolve relative length` 的已知问题。
- 高清 PNG 下载：克隆当前 Markmap 的 SVG → 将 `<foreignObject>` 内嵌 HTML 文字改写为原生 SVG `<text>`（避免 Chrome 将含 foreignObject 的 SVG 画进 canvas 后标记为 tainted，导致 `canvas.toBlob('image/png')` 返回 `null`、下载无反应）→ 序列化为 UTF-8 后用 base64 `data:image/svg+xml` 喂给 `Image`（优于部分环境下对 `blob:` SVG 的额外限制）→ 白底绘制到 2 倍 `devicePixelRatio` 的 `<canvas>` → `toBlob('image/png')` → 触发下载；若主路径仍失败则保留 foreignObject 再试一次兜底。文件名按视频标题安全转义。
- SVG / Markdown 下载：SVG 直接序列化输出，Markdown 是任务自带的 `mindmap_markdown` 原文，方便用户在 Markmap、Obsidian、Notion 等工具里二次编辑。

### 2.6 Pro 会员与 Stripe 支付（MVP）

- **计费**：一次性购买（非订阅）：月卡 30 天 / 年卡 365 天，价格与货币由 Stripe Product/Price 决定（站点文案为 ¥9.9 / ¥99 CNY 档位）。
- **支付流程**：`POST /api/stripe/create-checkout` 创建 Checkout Session（`mode=payment`），前端跳转 Stripe 托管页；成功后 Stripe 回调 `POST /api/stripe/webhook`（`checkout.session.completed`）并重定向回前端 `?checkout=success&session_id=...`，前端再调 `GET /api/stripe/checkout-success` 拉取会员信息。
- **幂等**：订单表 `orders.stripe_session_id` 唯一；同一 session 重复处理不会重复延长会员。
- **身份**：无账号密码；以 **邮箱（Stripe 收集）+ 会员密钥（后端生成 `secrets.token_urlsafe`）** 识别用户；换设备可通过 `POST /api/membership/activate` 恢复。
- **存储**：`backend/var/app.db`（可用 `FVD_DATABASE_PATH` 覆盖），启动时 `init_database()` 建表。
- **Pro 权益当前实现**：4K 下载；AI 总结不限每日次数；单视频总结最长 120 分钟（与免费 40 分钟区分）。

### 2.7 字幕文件单独下载

- 新增 `GET /api/summary/{summary_id}/subtitle?format=srt|vtt|txt` 接口，从内存中的 `SubtitleSegment` 列表实时格式化为 SRT / VTT / TXT 文本。
- `Content-Disposition` 同时输出 ASCII fallback 名和 RFC 5987 `filename*=UTF-8''…`，保证中英文标题在主流浏览器正确保存。
- 字幕 Tab 同步增加 `下载 SRT / 下载 VTT / 下载 TXT` 三个按钮，复用同一个接口。

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
  ├── api.py         路由层 + 入参校验 + 错误归一（含 membership 子路由）
  ├── database.py    SQLite 初始化（aiosqlite）
  ├── membership/    Pro：Stripe、订单与用户、会员校验依赖
  ├── downloader.py  yt-dlp 调用、平台识别、清晰度选择、进度 hook
  ├── douyin.py      抖音定制提取逻辑
  ├── tasks.py       任务字典 / 信号量 / TTL 清理协程
  ├── summary/       AI 总结：字幕、限流、DeepSeek、任务状态、问答
  └── config.py      路径、并发、TTL、格式选择器、加载 backend/.env
        │
        ├── yt-dlp (Python API)
        ├── ffmpeg (子进程)
        ├── DeepSeek V4-Flash
        ├── var/downloads/<task_id>/  临时下载工作目录
        └── var/app.db（默认）        会员与订单（SQLite）
```

关键设计点：

- **任务模型**：`DownloadTask` 是一个 dataclass，承载 `status / pct / speed / eta / stage / file_path / error` 等字段，统一序列化给前端。
- **会员数据**：SQLite 持久化用户邮箱、`membership_key`、`pro_expires_at` 与订单记录；应用启动时 `init_database()` 建表。
- **总结模型**：`SummaryTask` 独立承载 `status / pct / segments / summary_text / outline_markdown / mindmap_markdown / chat_messages / error`，不影响下载任务。
- **并发控制**：使用 `asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)` 限制同时执行的下载数，避免单机被打爆。
- **生命周期**：FastAPI `lifespan` 在启动时拉起下载任务和总结任务清理协程，每 60 秒扫描一次过期任务。
- **静态托管**：若 `frontend/dist` 存在则自动挂载，部署时只暴露后端一个端口即可。

## 4. 关键代码结构

```text
backend/
├── app/
│   ├── main.py         FastAPI 入口、CORS、lifespan、静态托管、启动时 init_database
│   ├── database.py     SQLite schema 与连接
│   ├── api.py          路由：health / info / download / progress / cancel / file / thumbnail + membership
│   ├── membership/     Stripe Checkout、Webhook、会员激活与状态
│   ├── downloader.py   yt-dlp 封装、清晰度选择器、进度 hook、平台识别
│   ├── douyin.py       抖音定制提取器
│   ├── tasks.py        任务字典、信号量、取消、TTL 清理
│   ├── summary/        AI 总结模块
│   │   ├── api.py          路由：summary / chat / subtitle / delete
│   │   ├── bilibili_auth.py B 站登录态 Cookie：写 Netscape cookies.txt、Referer / UA 注入、/x/web-interface/nav 登录态校验
│   │   ├── subtitles.py    字幕抽取、语言优先级、清洗、分段
│   │   ├── export.py       SubtitleSegment → SRT / VTT / TXT 导出与文件名清洗
│   │   ├── llm_client.py   DeepSeek OpenAI-compatible 调用
│   │   ├── pipeline.py     总结异步流程和追问
│   │   ├── tasks.py        SummaryTask 字典和 TTL 清理
│   │   ├── rate_limit.py   IP 每日限流
│   │   ├── prompts.py      摘要/思维导图/对话 prompt
│   │   └── settings.py     DeepSeek 与限流配置
│   └── config.py       路径、并发、TTL、格式选择器、加载 .env
├── requirements.txt   含 stripe、aiosqlite
└── var/                downloads（临时）与 app.db（默认数据库，可按配置）

frontend/
├── index.html
├── src/
│   ├── main.js         交互逻辑、轮询、进度渲染、会员状态与 Stripe 跳转
│   ├── summary.js      AI 总结入口、Tab、对话、Markmap 渲染
│   └── styles.css      响应式与营销视觉
├── package.json        Vite 配置
└── dist/               构建产物（已在 .gitignore）

开发说明：`frontend/vite.config.js` 将 `/api` 代理到后端；**当前仓库默认代理 `http://127.0.0.1:8001`**（避免 Windows 上 `uvicorn --reload` 偶发遗留 `127.0.0.1:8000` 幽灵监听导致请求打到旧进程）。生产由后端单端口托管静态资源，无需代理。本地若仍用 8000，可将 `vite.config.js` 的 `target` 改回 `8000`。

docs/
├── requirements-analysis.md
├── technical-design.md
├── ai-summary-design.md
└── project-summary.md  本文件
```

## 5. 关键配置项

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `FVD_TEMP_DIR` | `backend/var/downloads` | 临时下载目录，可用环境变量覆盖 |
| `FVD_VAR_DIR` | `backend/var` | 运行时 var 根目录 |
| `FVD_DATABASE_PATH` | `backend/var/app.db` | SQLite 数据库路径 |
| `STRIPE_SECRET_KEY` | 无 | Stripe 服务端密钥，`backend/.env` |
| `STRIPE_PRICE_MONTHLY` / `STRIPE_PRICE_YEARLY` | 无 | Dashboard 创建的 Price ID（`price_...`） |
| `STRIPE_WEBHOOK_SECRET` | 无 | Webhook 签名校验（Stripe CLI `listen` 或 Dashboard 端点） |
| `STRIPE_APP_BASE_URL` | 空 | 前端 origin，用于 Checkout success/cancel URL；不设则从请求 Referer/Origin 推断 |
| `PRO_SUMMARY_MAX_DURATION_SECONDS` | `120 * 60` | Pro 单视频总结最长秒数 |
| `TASK_TTL_SECONDS` | `30 * 60` | 任务保留时间，过期清理 |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | 同时进行的下载任务上限 |
| `MAX_URL_LENGTH` | `2048` | 单条 URL 长度上限 |
| `MAX_DURATION_SECONDS` | `4 * 60 * 60` | 单视频最长 4 小时，防止大文件冲爆磁盘 |
| `DEFAULT_FORMAT` | `bv*[height<=1080]+ba/b[height<=1080]` | 默认 1080p 选择器 |
| `DEEPSEEK_API_KEY` | 无 | AI 总结必填，可放系统环境变量或 `backend/.env` |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek OpenAI-compatible API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | AI 总结默认模型 |
| `SUMMARY_DAILY_LIMIT_PER_IP` | `3`（次/天） | 每 IP 每日 AI 总结次数；`<=0` 表示关闭限额；可覆盖为其他正整数 |
| `SUMMARY_MAX_DURATION_SECONDS` | `40 * 60` | 免费 AI 总结单视频最长 40 分钟 |
| `SUMMARY_TASK_TTL_SECONDS` | `30 * 60` | AI 总结任务和结果保留时间 |
| `BILIBILI_SESSDATA` | 空 | B 站登录态 Cookie，解锁 AI 字幕 / AI 翻译 / 部分 UP 上传字幕；不配置时只能拿无需登录的 B 站字幕 |
| `BILIBILI_BILI_JCT` | 空 | B 站可选 CSRF Cookie，与 SESSDATA 配套使用，降低风控概率 |
| `BILIBILI_BUVID3` | 空 | B 站可选设备 Cookie，与 SESSDATA 配套使用 |

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
| GET | `/api/summary/bilibili/cookie-status` | 运营自检：当前 B 站 `SESSDATA` 是否被识别为登录（不返回 Cookie 原文） |
| POST | `/api/stripe/create-checkout` | 创建 Stripe Checkout Session（Body: `plan_type`: `monthly` \| `yearly`；Header: `X-Checkout-Intent-Key` 幂等） |
| GET | `/api/stripe/checkout-success` | 支付成功后校验 session 并返回会员信息 |
| POST | `/api/stripe/webhook` | Stripe Webhook，校验签名并幂等发放会员 |
| POST | `/api/membership/activate` | 邮箱 + 会员密钥恢复校验 |
| GET | `/api/membership/status` | Header `X-Membership-Key` 查询会员状态 |
| GET | `/api/summary/{summary_id}` | 轮询总结进度或读取总结结果 |
| GET | `/api/summary/{summary_id}/subtitle?format=srt\|vtt\|txt` | 下载字幕文件，自动按视频标题命名 |
| POST | `/api/summary/{summary_id}/chat` | 基于字幕内容继续追问 |
| DELETE | `/api/summary/{summary_id}` | 主动删除总结任务 |

## 7. 已踩过的坑与对应方案

- **抖音封面加载失败**：抖音 / 小红书 / Bilibili 等存在 Referer 防盗链，前端直链加载会 403。通过后端 `/api/thumbnail` 代理 + 白名单域名 + 平台 Referer 解决。
- **封面代理 500（`Request` 命名冲突）**：`api.py` 中 `urllib.request.Request` 与 Starlette `Request` 同名覆盖时，构造上游请求会抛错。通过将 urllib 的 `Request` 别名为 `URLRequest` 并显式使用，避免 500 与封面「一直加载中」。
- **B 站网页 412 / 验证码页**：部分环境下 `yt-dlp` 拉取 `bilibili.com` 视频页会 `HTTP 412`，解析与下载会失败。通过 `bilibili.py` 调 Open API 拿 `playurl` 与直链，绕开网页 HTML 解析；仍失败再回退 `yt-dlp`。
- **ffmpeg 合并依赖**：高画质往往需要分别下载视频流和音频流再用 `ffmpeg` 合并，部署环境必须预装 `ffmpeg` 二进制。
- **进度回调性能**：`yt-dlp` 的 `progress_hooks` 调用频率较高，hook 内只更新内存字段并刷新 `updated_at`，避免在 hook 里做磁盘 IO。
- **任务孤儿目录**：异常退出会留下临时目录，统一通过 `cleanup_expired_tasks` 协程兜底清理；显式 `cancel/remove_task` 也会立即 `rmtree`。
- **跨域**：开发态前端 5173 与后端分离，Vite 将 `/api` 代理到后端（默认 `127.0.0.1:8001`）；`CORSMiddleware` 显式放行 `localhost:5173 / 127.0.0.1:5173`，生产态由后端托管静态资源后无需 CORS。
- **Windows 开发：`uvicorn --reload` 与 8000 端口**：偶发多个进程同时 `LISTEN` 同一端口，或 `127.0.0.1:8000` 出现「幽灵」监听，导致浏览器/代理仍命中旧代码（例如旧的每日限额逻辑）。缓解：换用其他端口启动后端（如 `8001`），并与 `frontend/vite.config.js` 的 `proxy.target` 对齐；或重启机器清理 socket。
- **`.env` 未自动加载**：AI 总结需要 `DEEPSEEK_API_KEY`，已在 `summary/settings.py` 中补充 `backend/.env` 读取逻辑，避免本地每次手动设置系统环境变量。
- **字幕编码与格式差异**：YouTube、Bilibili 字幕可能是 `json3`、`json`、`vtt`、`srt` 等格式，`summary/subtitles.py` 做了多格式解析和简单去重聚合。
- **无效 URL 创建错误任务**：曾出现 `POST /api/summary` 对无效 URL 返回 200 并创建后台任务的问题，已改为创建任务前同步校验 URL，错误直接返回 400。
- **Markmap `NotSupportedError`**：`markmap-autoloader@0.18` 默认生成 `width="100%" height="100%"` 的 SVG，d3 在初次 `getBBox()` 时会抛 `Failed to read the 'value' property from 'SVGLength': Could not resolve relative length`，且每次切 Tab 都会重渲染加重问题。改为直接调用 `markmap-lib` + `markmap-view` 的 IIFE 包，按容器实际宽高显式设置 `<svg width/height>` 后稳定渲染；销毁旧实例避免 SVG 节点叠加。
- **Markmap PNG 导出「点了没反应」**：Markmap 用 `<foreignObject>` 嵌 `<div>` 排文字；Chrome 等浏览器把该 SVG `drawImage` 到 canvas 后 canvas 变为 tainted，`toBlob` 得到 `null`，用户侧表现为点击「下载 PNG」无文件、状态提示也不醒目。`summary.js` 在导出前把 foreignObject 换成 `<text>`，并用 `data:image/svg+xml;base64,...` 加载 SVG，主路径 + 保留 foreignObject 兜底双轨。
- **Bilibili 字幕**：B 站把字幕分为 "UP 主上传字幕 / AI 自动生成字幕 / AI 翻译字幕" 三类，绝大多数情况下三类都需要登录态（`/x/player/v2` 返回 `need_login_subtitle: true`）。当前版本通过 `backend/.env` 接受运营方 **共享小号** 的 `BILIBILI_SESSDATA`、`BILIBILI_BILI_JCT`、`BILIBILI_BUVID3`，由 `backend/app/summary/bilibili_auth.py` 包装成 yt-dlp 能吃的 Netscape `cookies.txt` 临时文件并只对 B 站 URL 生效，其他平台不串味。语言优先级补了 `ai-zh` / `ai-en` 覆盖 AI 字幕；同时过滤掉 yt-dlp 给 B 站塞的合成 `danmaku` 语种，避免它被当成真字幕导致 "字幕内容为空" 掩盖真因。Cookie 缺失时返回明确文案 "站点未配置 B 站登录态 Cookie"，不会回归到 YouTube 等其他平台。**当拿不到字幕时**，`bilibili_auth.check_cookie_login()` 调 `/x/web-interface/nav` 区分「Cookie 被 B 站拒绝」与「视频本身无 CC 字幕」；B 站可能对共享小号间歇性风控，同一 `SESSDATA` 在短时间内可能出现 `isLogin` 抖动。**未来仍计划用浏览器扩展形态复用用户自己的登录态，避免共享小号被风控**。
- **Bilibili 弹幕被 yt-dlp 当字幕**：yt-dlp 的 `BiliBili` 提取器会无条件在 `subtitles` 字典加一个 `danmaku` 语种，指向 `comment.bilibili.com/{cid}.xml` 弹幕文件。匿名抓 B 站时，`_select_subtitle_track` 会把它当成 "唯一可用字幕" 选中，结果用 VTT/SRT 解析器解出 0 段。`subtitles.py` 增加 `EXCLUDED_LANGUAGES = {"danmaku", "live_chat"}` 在选轨阶段过滤掉。

## 8. 已知限制

- 任务状态、进度仅存内存，进程重启后丢失；适合单机 MVP，不适合多副本部署。
- AI 总结结果和对话也仅存内存，默认 30 分钟后清理，暂不支持历史记录。
- AI 总结 MVP 只使用平台原生字幕，不做 ASR；无字幕视频会提示暂不支持。
- B 站字幕必须在 `backend/.env` 配置运营方共享小号的 `BILIBILI_SESSDATA` 才能解锁；Cookie 由所有用户共用，号被风控大家都受影响，且通常 1-3 个月需手动续期。后续仍计划走浏览器扩展形态复用用户自己的登录态。
- DeepSeek 调用会把字幕内容发送给第三方模型服务，生产环境需要在页面和服务条款中明确提示。
- 暂未支持用户上传 cookies，因此部分需要登录态、会员或地区限制的视频可能解析失败或仅能拿到低画质。
- 不绕过 DRM，不缓存用户视频，所有产物默认在 30 分钟后清理。
- 会员身份依赖浏览器保存的 **会员密钥** + 用户记忆的邮箱用于恢复；非完整账号体系，密钥泄露存在被盗用风险（MVP 取舍）。

## 9. 后续可演进方向

1. **持久化任务**：把下载和总结任务字典换成 Redis / SQLite，支持多副本与重启续跑。
2. **ASR 兜底**：无字幕视频（包括 B 站需要登录的视频）自动抽取音频并转写，候选方案有 SiliconFlow `FunAudioLLM/SenseVoiceSmall`（中文友好、免费额度）、本地 `faster-whisper` 等。
3. **浏览器扩展形态**：把核心能力封装为 Chrome / Edge 扩展，直接复用用户当前浏览器里的登录态，安全地拿到 B 站 AI 字幕、会员视频、私密视频等需要 Cookie 才能访问的内容。
4. **用户体系深化**：可选邮箱 OTP / OAuth 登录，替代纯密钥模型；配额与风控细化。
5. **导出能力**：AI 总结结果导出 Markdown / PDF / Word，或同步 Notion / Obsidian。
6. **批量与播放列表**：把单链接扩展为播放列表整包下载和批量总结。
7. **观测性**：接入结构化日志、Prometheus 指标，监控并发数、失败率、平均下载/总结时长。
8. **CDN / 对象存储**：对完成的产物落 S3 / OSS，签名 URL 直发用户，释放服务器带宽。
9. **`yt-dlp` 自动升级**：`yt-dlp` 与平台是猫鼠游戏，需要定期升级或在容器里跑自更新任务。

## 10. 本地运行速记

```bash
# 后端（端口可按需调整；与 frontend/vite.config.js 中 proxy target 保持一致）
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# 可选：在 backend/.env 配置 DEEPSEEK_API_KEY=sk-...
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

# 前端
cd frontend
npm install
npm run dev   # 开发态：http://127.0.0.1:5173 ，/api 默认代理到 8001
npm run build # 生产态：构建产物由后端自动托管
```

依赖：Python 3.10+、Node.js 18+、`ffmpeg` 二进制。

## 11. 近期变更摘要（运维速览）

### 2026-05-03

1. **封面代理修复**：`GET /api/thumbnail` 修复 `urllib.request.Request` 与 FastAPI `Request` 命名冲突导致的 500，恢复 B 站等 CDN 封面展示。
2. **Free 总结限额默认值**：`SUMMARY_DAILY_LIMIT_PER_IP` 默认改为 **`3` 次/天**（仍可通过环境变量覆盖；`<=0` 关闭限额）；Pro 用户跳过 IP 日限额。
3. **B 站解析/下载兜底**：新增 `backend/app/bilibili.py`，在网页风控（如 `412`）或 `yt-dlp` 不可用优先使用 **Open API + ffmpeg**；`downloader.parse_video_info` / 下载任务优先走该路径，失败再回退 `yt-dlp`。
4. **升级 Pro 体验**：Pro 弹窗展示月卡+年卡、权益清单；限额场景专属文案；年卡展示相对月卡的节省比例；AI 总结错误区增加「升级 Pro 继续总结」入口。
5. **会员与认证相关**：仓库内同步包含邮箱密码登录、Stripe Checkout、`X-Auth-Token` 等与会员接口联动的后端扩展（详见 `backend/app/membership/`、`database.py`）。

### 2026-05-02

1. **首屏与布局**：解析结果改为左右双栏（视频信息 + AI 总结同屏）；Hero 压缩间距与标题字号、输入区加宽；解析成功后隐藏营销区块（`compact-mode`）；解析成功自动触发 AI 总结，左栏保留「重新生成总结」。
2. **总结限额**：引入按 IP 日限额能力（`SUMMARY_DAILY_LIMIT_PER_IP`）；生产默认值后续在 **2026-05-03** 调整为每天 **3** 次免费总结（仍可通过环境变量覆盖，`<=0` 关闭限额）。
3. **开发代理端口**：`frontend/vite.config.js` 默认将 `/api` 代理到 `http://127.0.0.1:8001`，规避 Windows 上偶发 `127.0.0.1:8000` 幽灵监听导致命中旧后端进程的问题；本地文档与启动命令已对齐 8001。
4. **B 站 Cookie 诊断**：`bilibili_auth.check_cookie_login()` 调用 `/x/web-interface/nav`；`subtitles.extract_subtitles` 在 B 站无可用轨时按登录态分流错误文案；新增 `GET /api/summary/bilibili/cookie-status` 供运营自检。
5. **Pro 会员与 Stripe**：新增 `backend/app/membership/`、`database.py`，Stripe Checkout 一次性付款，Webhook 签名校验与订单幂等；Pro 解锁 4K、总结不限次、最长 120 分钟总结；前端定价区、会员徽章、`X-Membership-Key` 与恢复弹窗；`summary/api` 中静态路由顺序修正，避免 `/bilibili` 被 `/{summary_id}` 吞掉。

### 2026-05-01

1. **B 站 AI 总结需登录字幕**：`backend/.env` 配置 `BILIBILI_SESSDATA`（及可选 `BILIBILI_BILI_JCT` / `BILIBILI_BUVID3`），`summary/bilibili_auth.py` + `subtitles.py` 透传 Cookie、兼容 yt-dlp inline `data` 字幕、过滤 `danmaku` 伪轨；详见上文 §2.4 / §7。
2. **B 站主域**：`bilibili.com`（无 `www`）统一改写为 `www.bilibili.com`，前后端一致，减少解析与下载差异。
3. **思维导图 PNG**：导出前将 Markmap 的 `<foreignObject>` 改为 `<text>`，并用 base64 data URI 加载 SVG 再 raster，修复 Chrome 下 `toBlob` 为 null、点击「下载 PNG」无反应的问题；详见 §2.5 / §7。
