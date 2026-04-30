# Free Video Download

一个基于 Python + FastAPI + yt-dlp 的万能视频下载站 MVP。用户可以粘贴公开视频链接，解析视频信息，选择清晰度，查看异步下载进度，并在完成后保存到本地。

## 功能

- 单链接视频解析。
- 标题、封面、作者、时长、平台展示。
- 1080p / 720p / 480p / 仅音频等清晰度选择。
- 异步下载任务和进度轮询。
- 下载完成后返回文件。
- 临时文件自动清理。
- 营销型首页、Pro 付费能力预留、移动端适配。

## 本地开发

### 后端

需要 Python 3.10+ 和 ffmpeg。

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

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

前端构建产物会输出到 `frontend/dist`，后端启动时会自动挂载静态页面。

## 文档

- [需求分析](docs/requirements-analysis.md)
- [方案设计](docs/technical-design.md)
- [项目总结](docs/project-summary.md)

## 注意事项

- `yt-dlp` 支持平台很多，但部分平台或高画质资源可能需要 cookies、登录态或会员权限。
- MVP 暂不支持用户上传 cookies。
- 大文件会消耗磁盘空间，生产环境请配置独立临时目录、并发限制和更严格的清理策略。
- 生产环境建议定期升级 `yt-dlp`。

## 免责声明

本项目只是 `yt-dlp` 的可视化封装。所有视频内容版权归原作者和平台所有，请仅下载你有权获取和保存的内容。本站不绕过 DRM，不鼓励违反平台条款或版权规则的使用方式，也不长期缓存用户视频。
