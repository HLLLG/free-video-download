const SUMMARY_MAX_DURATION_SECONDS = 40 * 60;

const summaryState = {
  taskId: null,
  pollingTimer: null,
  result: null,
  activeTab: "outline",
  sendingChat: false,
  mindmapFullscreen: false,
};

let runtime = null;
const MARKMAP_DEPS = [
  "https://cdn.jsdelivr.net/npm/d3@7.9.0",
  "https://cdn.jsdelivr.net/npm/markmap-lib@0.18.12/dist/browser/index.iife.min.js",
  "https://cdn.jsdelivr.net/npm/markmap-view@0.18.12/dist/browser/index.min.js",
];
let markmapLoaderPromise = null;
let mindmapEscBound = false;

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  let html = "";
  let inList = false;

  const closeList = () => {
    if (inList) {
      html += "</ul>";
      inList = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeList();
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 2, 6);
      html += `<h${level}>${escapeHtml(heading[2])}</h${level}>`;
      continue;
    }
    const item = line.match(/^[-*]\s+(.+)$/);
    if (item) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${escapeHtml(item[1])}</li>`;
      continue;
    }
    closeList();
    html += `<p>${escapeHtml(line)}</p>`;
  }
  closeList();
  return html;
}

function escapeScriptContent(value) {
  return String(value || "").replace(/<\/script/gi, "<\\/script");
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      existing.addEventListener("load", resolve, { once: true });
      existing.addEventListener("error", reject, { once: true });
      if (existing.dataset.loaded === "true") resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.addEventListener("load", () => {
      script.dataset.loaded = "true";
      resolve();
    });
    script.addEventListener("error", reject);
    document.head.appendChild(script);
  });
}

function renderMindmapFallback(lines) {
  return `<div class="mindmap-tree">${lines
    .map((line) => {
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        return `<div class="mindmap-node depth-${heading[1].length}">${escapeHtml(heading[2])}</div>`;
      }
      const item = line.match(/^[-*]\s+(.+)$/);
      if (item) {
        return `<div class="mindmap-node depth-4">${escapeHtml(item[1])}</div>`;
      }
      return `<div class="mindmap-node depth-5">${escapeHtml(line)}</div>`;
    })
    .join("")}</div>`;
}

function renderMindmap(markdown) {
  const lines = String(markdown || "")
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean);
  if (!lines.length) return "<p>暂无思维导图内容。</p>";
  return `
    <div class="mindmap-toolbar">
      <button class="ghost-btn small" type="button" data-mindmap-action="fullscreen">
        <i data-lucide="maximize-2"></i><span>全屏查看</span>
      </button>
      <span class="mindmap-toolbar-divider"></span>
      <button class="ghost-btn small" type="button" data-mindmap-action="download-png">
        <i data-lucide="image-down"></i><span>下载 PNG</span>
      </button>
      <button class="ghost-btn small" type="button" data-mindmap-action="download-svg">
        <i data-lucide="file-down"></i><span>下载 SVG</span>
      </button>
      <button class="ghost-btn small" type="button" data-mindmap-action="download-md">
        <i data-lucide="file-text"></i><span>下载 Markdown</span>
      </button>
    </div>
    <div class="mindmap-visual">
      <svg class="markmap-svg" data-markmap-source="${encodeURIComponent(markdown)}"></svg>
    </div>
    <div class="mindmap-fallback">
      ${renderMindmapFallback(lines)}
    </div>
  `;
}

async function ensureMarkmapLoaded() {
  if (!markmapLoaderPromise) {
    markmapLoaderPromise = MARKMAP_DEPS.reduce(
      (chain, url) => chain.then(() => loadScript(url)),
      Promise.resolve(),
    );
  }
  await markmapLoaderPromise;
  return window.markmap;
}

function scheduleMindmapRender(container) {
  const root = container || document;
  const svgEl = root.querySelector(".markmap-svg");
  const visual = root.querySelector(".mindmap-visual");
  if (!svgEl || !visual) return;
  const source = decodeURIComponent(svgEl.dataset.markmapSource || "");
  if (!source) return;

  ensureMarkmapLoaded()
    .then((mm) => {
      if (!mm || !mm.Transformer || !mm.Markmap) return;

      // 给 SVG 一个明确的像素尺寸，避免 d3 在 % 单位上 getBBox 报错
      const rect = visual.getBoundingClientRect();
      const width = Math.max(320, Math.round(rect.width || visual.clientWidth || 800));
      const height = Math.max(320, Math.round(rect.height || visual.clientHeight || 520));
      svgEl.setAttribute("width", String(width));
      svgEl.setAttribute("height", String(height));
      svgEl.style.width = `${width}px`;
      svgEl.style.height = `${height}px`;

      const transformer = new mm.Transformer();
      const { root: rootData } = transformer.transform(source);
      // 复用同一个 SVG 节点，避免 reflow
      if (svgEl.__markmapInstance) {
        try {
          svgEl.__markmapInstance.destroy();
        } catch (_) {
          /* ignore */
        }
      }
      const instance = mm.Markmap.create(svgEl, undefined, rootData);
      svgEl.__markmapInstance = instance;
      visual.classList.add("loaded");
      // markmap 默认是 "fit"，再触发一次确保自适应
      requestAnimationFrame(() => {
        try {
          instance.fit();
        } catch (_) {
          /* ignore */
        }
      });
    })
    .catch((error) => {
      console.warn("[mindmap] markmap render failed", error);
      visual.classList.remove("loaded");
    });
}

function bindMindmapToolbar(container) {
  const root = container || document;
  root.querySelectorAll("[data-mindmap-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.mindmapAction;
      if (action === "fullscreen") openMindmapFullscreen();
      else if (action === "download-png") downloadMindmapAsPng();
      else if (action === "download-svg") downloadMindmapAsSvg();
      else if (action === "download-md") downloadMindmapAsMarkdown();
    });
  });
}

function getMindmapTitle() {
  const title = summaryState.result?.title || "思维导图";
  const safe = String(title).replace(/[\\/:*?"<>|\r\n\t]+/g, " ").trim() || "思维导图";
  return safe.length > 80 ? safe.slice(0, 80) : safe;
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function findCurrentMindmapSvg() {
  const fullscreenSvg = document.querySelector("#mindmapFullscreen .markmap-svg");
  if (fullscreenSvg) return fullscreenSvg;
  return document.querySelector(".mindmap-visual .markmap-svg");
}

// 把 markmap 用 foreignObject + <div> 排出来的文字，改写成原生 SVG <text> 节点。
// 原因：Chrome 对含 foreignObject 的 SVG 鉴权更严，drawImage 后 canvas 会被
// 标记为 tainted，toBlob 直接返回 null；下载 PNG 因此静默失败。
function rasterizeForeignObjectsToText(svgEl) {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const fos = Array.from(svgEl.querySelectorAll("foreignObject"));
  for (const fo of fos) {
    const x = parseFloat(fo.getAttribute("x") || "0") || 0;
    const y = parseFloat(fo.getAttribute("y") || "0") || 0;
    const w = parseFloat(fo.getAttribute("width") || "0") || 0;
    const h = parseFloat(fo.getAttribute("height") || "0") || 0;
    // markmap 里 div 可能含多个文本节点（粗体 / 链接），这里粗暴拼接成一行
    const text = (fo.textContent || "").replace(/\s+/g, " ").trim();
    if (!text) {
      fo.remove();
      continue;
    }
    const fontSize = Math.max(11, Math.min(20, h ? h * 0.6 : 14));
    const baselineY = h ? y + h * 0.72 : y + fontSize;

    const textEl = document.createElementNS(SVG_NS, "text");
    textEl.setAttribute("x", String(x + 4));
    textEl.setAttribute("y", String(baselineY));
    if (w) textEl.setAttribute("textLength", String(Math.max(1, w - 8)));
    textEl.setAttribute("lengthAdjust", "spacingAndGlyphs");
    textEl.setAttribute(
      "font-family",
      'Inter, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif',
    );
    textEl.setAttribute("font-size", String(fontSize));
    textEl.setAttribute("fill", "#172033");
    textEl.setAttribute("dominant-baseline", "alphabetic");
    textEl.textContent = text;

    fo.parentNode.replaceChild(textEl, fo);
  }
}

function inlineSvgStyles(originalSvg, { rasterizeForeign = false } = {}) {
  const clone = originalSvg.cloneNode(true);
  if (!clone.getAttribute("xmlns")) clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  if (!clone.getAttribute("xmlns:xlink")) clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");

  const bbox = originalSvg.getBoundingClientRect();
  const width = Math.max(1, Math.round(bbox.width || 1280));
  const height = Math.max(1, Math.round(bbox.height || 720));
  if (!clone.getAttribute("viewBox")) clone.setAttribute("viewBox", `0 0 ${width} ${height}`);
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));

  if (rasterizeForeign) {
    rasterizeForeignObjectsToText(clone);
  }

  const styleEl = document.createElementNS("http://www.w3.org/2000/svg", "style");
  styleEl.textContent = `
    .markmap-foreign { font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif; color: #172033; }
    .markmap-foreign div { color: #172033; }
    .markmap-foreign a { color: #5b5bff; }
    .markmap-link { fill: none; }
  `;
  clone.insertBefore(styleEl, clone.firstChild);

  return { clone, width, height };
}

function svgToString(svgEl) {
  return new XMLSerializer().serializeToString(svgEl);
}

function downloadMindmapAsMarkdown() {
  const markdown = summaryState.result?.mindmap_markdown;
  if (!markdown) return;
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  triggerDownload(blob, `${getMindmapTitle()}-思维导图.md`);
}

function downloadMindmapAsSvg() {
  const svg = findCurrentMindmapSvg();
  if (!svg) {
    showSummaryStatus("思维导图还没渲染完成，请稍后再试", "error");
    return;
  }
  const { clone } = inlineSvgStyles(svg);
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n${svgToString(clone)}`;
  const blob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
  triggerDownload(blob, `${getMindmapTitle()}-思维导图.svg`);
}

// 把字符串 SVG 转成 base64 data URI，避免 Chrome 对 blob:// 的 SVG 设防。
function svgToDataUri(xml) {
  // 先 encodeURIComponent 处理中文等多字节字符，再用 unescape 还原成字节流给 btoa
  const utf8Bytes = unescape(encodeURIComponent(xml));
  return `data:image/svg+xml;base64,${btoa(utf8Bytes)}`;
}

function rasterSvgToPngBlob(xml, width, height) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      try {
        const scale = Math.max(2, window.devicePixelRatio || 1);
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(width * scale));
        canvas.height = Math.max(1, Math.round(height * scale));
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => {
          if (!blob) {
            reject(new Error("canvas.toBlob 返回 null（canvas 可能被 tainted）"));
            return;
          }
          resolve(blob);
        }, "image/png");
      } catch (err) {
        reject(err);
      }
    };
    image.onerror = (event) => {
      reject(new Error("SVG 图像加载失败：" + (event?.message || "image onerror")));
    };
    image.src = svgToDataUri(xml);
  });
}

async function downloadMindmapAsPng() {
  const svg = findCurrentMindmapSvg();
  if (!svg) {
    showSummaryStatus("思维导图还没渲染完成，请稍后再试", "error");
    return;
  }

  // 主路径：把 foreignObject 改写成原生 SVG <text>，规避 Chrome 把 canvas
  // 标记为 tainted 导致 toBlob 静默返回 null 的问题。
  const primary = inlineSvgStyles(svg, { rasterizeForeign: true });
  try {
    const blob = await rasterSvgToPngBlob(svgToString(primary.clone), primary.width, primary.height);
    triggerDownload(blob, `${getMindmapTitle()}-思维导图.png`);
    return;
  } catch (err) {
    console.warn("[mindmap] PNG 主路径失败，尝试保留 foreignObject 重试", err);
  }

  // 兜底路径：保留 foreignObject 原样再试一次，万一某些环境其实没问题
  const fallback = inlineSvgStyles(svg, { rasterizeForeign: false });
  try {
    const blob = await rasterSvgToPngBlob(svgToString(fallback.clone), fallback.width, fallback.height);
    triggerDownload(blob, `${getMindmapTitle()}-思维导图.png`);
  } catch (err) {
    console.error("[mindmap] PNG 兜底路径也失败", err);
    showSummaryStatus("PNG 导出失败，请改用 SVG 下载", "error");
  }
}

function showSummaryStatus(message, type) {
  const helpers = window.__summaryHelpers;
  if (helpers && typeof helpers.showStatus === "function") {
    helpers.showStatus(message, type || "info");
  }
}

function openMindmapFullscreen() {
  if (summaryState.mindmapFullscreen) return;
  const markdown = summaryState.result?.mindmap_markdown || "";
  const overlay = document.createElement("div");
  overlay.id = "mindmapFullscreen";
  overlay.className = "mindmap-fullscreen";
  overlay.innerHTML = `
    <div class="mindmap-fullscreen-head">
      <h3>${escapeHtml(summaryState.result?.title || "思维导图")} · 思维导图</h3>
      <div class="mindmap-fullscreen-actions">
        <button class="ghost-btn small" type="button" data-mindmap-action="download-png">
          <i data-lucide="image-down"></i><span>PNG</span>
        </button>
        <button class="ghost-btn small" type="button" data-mindmap-action="download-svg">
          <i data-lucide="file-down"></i><span>SVG</span>
        </button>
        <button class="ghost-btn small" type="button" data-mindmap-action="download-md">
          <i data-lucide="file-text"></i><span>MD</span>
        </button>
        <button class="ghost-btn small" type="button" data-mindmap-action="close">
          <i data-lucide="x"></i><span>关闭 (ESC)</span>
        </button>
      </div>
    </div>
    <div class="mindmap-fullscreen-body">
      <div class="mindmap-visual">
        <svg class="markmap-svg" data-markmap-source="${encodeURIComponent(markdown)}"></svg>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  document.body.classList.add("no-scroll");
  summaryState.mindmapFullscreen = true;

  overlay.querySelectorAll("[data-mindmap-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.mindmapAction;
      if (action === "close") closeMindmapFullscreen();
      else if (action === "download-png") downloadMindmapAsPng();
      else if (action === "download-svg") downloadMindmapAsSvg();
      else if (action === "download-md") downloadMindmapAsMarkdown();
    });
  });

  if (window.lucide?.createIcons) window.lucide.createIcons();
  scheduleMindmapRender(overlay);

  if (!mindmapEscBound) {
    document.addEventListener("keydown", handleMindmapEscape);
    mindmapEscBound = true;
  }
}

function closeMindmapFullscreen() {
  const overlay = document.getElementById("mindmapFullscreen");
  if (overlay) overlay.remove();
  document.body.classList.remove("no-scroll");
  summaryState.mindmapFullscreen = false;
}

function handleMindmapEscape(event) {
  if (event.key === "Escape" && summaryState.mindmapFullscreen) {
    closeMindmapFullscreen();
  }
}

function stopPolling() {
  if (summaryState.pollingTimer) {
    clearInterval(summaryState.pollingTimer);
    summaryState.pollingTimer = null;
  }
}

function setProgress(elements, task) {
  const pct = task.status === "done" ? 100 : Math.max(0, Math.min(100, Number(task.pct) || 0));
  elements.card.classList.remove("hidden");
  elements.title.textContent = task.title || "AI 视频总结";
  elements.pct.textContent = `${pct.toFixed(0)}%`;
  elements.bar.style.width = `${pct}%`;
  elements.stage.textContent = task.error || task.stage_text || "正在处理...";
  hideNotice(elements);
  if (elements.track) elements.track.classList.remove("hidden");
  if (elements.pct) elements.pct.classList.remove("hidden");
}

function hideNotice(elements) {
  if (!elements?.notice) return;
  elements.notice.classList.add("hidden");
  elements.notice.classList.remove("error");
  elements.notice.innerHTML = "";
}

function showNotice(elements, message, { type = "info" } = {}) {
  if (!elements?.notice) return;
  elements.notice.classList.remove("hidden");
  elements.notice.classList.toggle("error", type === "error");
  elements.notice.innerHTML = message;
  if (window.lucide?.createIcons) window.lucide.createIcons();
}

function resetSummaryUi(elements) {
  stopPolling();
  summaryState.taskId = null;
  summaryState.result = null;
  summaryState.activeTab = "outline";
  summaryState.sendingChat = false;
  if (!elements) return;
  elements.title.textContent = "等待解析视频";
  elements.pct.textContent = "0%";
  elements.bar.style.width = "0%";
  elements.stage.textContent = "解析视频后将自动开始 AI 总结";
  elements.result.classList.add("hidden");
  if (elements.panel) elements.panel.innerHTML = "";
  hideNotice(elements);
}

export function resetSummary() {
  resetSummaryUi(runtime?.elements);
}

export function startSummaryAuto() {
  if (!runtime) return;
  startSummary(runtime.elements, runtime.appState, { mode: "auto" });
}

function switchTab(elements, tabName) {
  summaryState.activeTab = tabName;
  elements.tabs.forEach((button) => button.classList.toggle("active", button.dataset.summaryTab === tabName));
  renderActiveTab(elements);
}

function renderOutline(task) {
  return `
    <div class="summary-overview">
      <h4>视频总览</h4>
      <p>${escapeHtml(task.summary_text || "暂无总览。")}</p>
    </div>
    <div class="summary-markdown">
      ${renderMarkdown(task.outline_markdown || "")}
    </div>
  `;
}

function renderTranscript(task) {
  const segments = task.segments || [];
  if (!segments.length) return "<p>暂无字幕内容。</p>";
  const toolbar = summaryState.taskId
    ? `
      <div class="transcript-toolbar">
        <span class="muted small">下载字幕文件：</span>
        <a class="ghost-btn small" href="/api/summary/${encodeURIComponent(summaryState.taskId)}/subtitle?format=srt">
          <i data-lucide="file-down"></i><span>SRT</span>
        </a>
        <a class="ghost-btn small" href="/api/summary/${encodeURIComponent(summaryState.taskId)}/subtitle?format=vtt">
          <i data-lucide="file-down"></i><span>VTT</span>
        </a>
        <a class="ghost-btn small" href="/api/summary/${encodeURIComponent(summaryState.taskId)}/subtitle?format=txt">
          <i data-lucide="file-text"></i><span>纯文本</span>
        </a>
      </div>
    `
    : "";
  return `
    ${toolbar}
    <div class="transcript-list">${segments
      .map(
        (segment) => `
          <div class="transcript-item">
            <span class="transcript-time">${escapeHtml(segment.start_text)} - ${escapeHtml(segment.end_text)}</span>
            <p>${escapeHtml(segment.text)}</p>
          </div>
        `,
      )
      .join("")}</div>
  `;
}

function renderChat(task) {
  const messages = task.chat_messages || [];
  const items = messages
    .map(
      (message) => `
        <div class="chat-message ${message.role === "user" ? "user" : "assistant"}">
          <span>${message.role === "user" ? "你" : "AI"}</span>
          <p>${escapeHtml(message.content)}</p>
        </div>
      `,
    )
    .join("");
  return `
    <div class="chat-panel">
      <div class="chat-messages">${items || '<p class="muted">可以继续追问这个视频的知识点。</p>'}</div>
      <form id="summaryChatForm" class="chat-form">
        <input id="summaryChatInput" type="text" maxlength="1000" placeholder="例如：这个视频最重要的 3 个知识点是什么？" />
        <button class="primary-btn" type="submit" ${summaryState.sendingChat ? "disabled" : ""}>发送</button>
      </form>
    </div>
  `;
}

function renderActiveTab(elements) {
  const task = summaryState.result;
  if (!task) return;
  if (summaryState.activeTab === "outline") {
    elements.panel.innerHTML = renderOutline(task);
  } else if (summaryState.activeTab === "transcript") {
    elements.panel.innerHTML = renderTranscript(task);
    elements.refreshIcons?.();
  } else if (summaryState.activeTab === "mindmap") {
    elements.panel.innerHTML = renderMindmap(task.mindmap_markdown || "");
    scheduleMindmapRender(elements.panel);
    bindMindmapToolbar(elements.panel);
    elements.refreshIcons?.();
  } else {
    elements.panel.innerHTML = renderChat(task);
    bindChatForm(elements);
  }
}

function renderResult(elements, task) {
  summaryState.result = task;
  elements.result.classList.remove("hidden");
  renderActiveTab(elements);
}

function bindChatForm(elements) {
  const form = $("#summaryChatForm");
  const input = $("#summaryChatInput");
  if (!form || !input) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (summaryState.sendingChat || !summaryState.taskId) return;
    const message = input.value.trim();
    if (!message) return;
    summaryState.sendingChat = true;
    renderActiveTab(elements);
    try {
      const data = await elements.requestJson(`/api/summary/${summaryState.taskId}/chat`, {
        method: "POST",
        body: JSON.stringify({ message }),
      });
      summaryState.result.chat_messages = data.messages || [];
      renderActiveTab(elements);
    } catch (error) {
      elements.showStatus(error.message, "error");
    } finally {
      summaryState.sendingChat = false;
      renderActiveTab(elements);
    }
  });
}

function pollSummary(elements, taskId, { mode = "manual" } = {}) {
  stopPolling();
  summaryState.pollingTimer = setInterval(async () => {
    try {
      const task = await elements.requestJson(`/api/summary/${taskId}`);
      if (summaryState.taskId !== taskId) {
        stopPolling();
        return;
      }
      setProgress(elements, task);
      if (task.status === "error") {
        stopPolling();
        reportSummaryError(elements, task.error || "AI 总结失败，请稍后重试。", { mode });
      }
      if (task.status === "done") {
        stopPolling();
        if (mode !== "auto") {
          elements.showStatus("AI 总结完成，可以查看要点、字幕、思维导图和继续追问。");
        }
        renderResult(elements, task);
      }
      elements.refreshIcons();
    } catch (error) {
      stopPolling();
      reportSummaryError(elements, error.message, { mode });
    }
  }, 1000);
}

function reportSummaryError(elements, message, { mode }) {
  const safe = escapeHtml(message || "AI 总结失败，请稍后重试。");
  showNotice(
    elements,
    `<div><strong>AI 总结暂未完成</strong><p style="margin:6px 0 0;">${safe}</p>` +
      `<p style="margin:8px 0 0;font-size:12px;opacity:.85;">你可以点击左侧的「重新生成总结」按钮再试一次。</p></div>`,
    { type: "error" },
  );
  if (elements.track) elements.track.classList.add("hidden");
  if (elements.pct) elements.pct.classList.add("hidden");
  elements.title.textContent = "AI 总结未完成";
  elements.stage.textContent = "";
  if (mode !== "auto") {
    elements.showStatus(message, "error");
  }
}

async function startSummary(elements, appState, { mode = "manual" } = {}) {
  const url = elements.normalizeVideoUrl(elements.url.value);
  if (!url || !appState.info) {
    if (mode !== "auto") elements.showStatus("请先解析视频链接。", "error");
    return;
  }
  if (appState.info.duration && appState.info.duration > SUMMARY_MAX_DURATION_SECONDS) {
    const msg = "当前视频超过 40 分钟，免费版暂不支持自动总结。可缩短视频或升级 Pro 后再试。";
    if (mode === "auto") {
      elements.card.classList.remove("hidden");
      elements.title.textContent = "AI 总结暂不可用";
      elements.stage.textContent = "";
      if (elements.track) elements.track.classList.add("hidden");
      if (elements.pct) elements.pct.classList.add("hidden");
      elements.result.classList.add("hidden");
      showNotice(
        elements,
        `<div><strong>视频超过 40 分钟</strong><p style="margin:6px 0 0;">${escapeHtml(msg)}</p></div>`,
      );
    } else {
      elements.showStatus(msg, "error");
    }
    return;
  }

  stopPolling();
  summaryState.result = null;
  summaryState.activeTab = "outline";
  elements.button.disabled = true;
  elements.result.classList.add("hidden");
  elements.card.classList.remove("hidden");
  elements.title.textContent = appState.info.title || "AI 视频总结";
  elements.pct.textContent = "0%";
  elements.bar.style.width = "0%";
  elements.stage.textContent = "正在创建 AI 总结任务...";
  hideNotice(elements);
  if (elements.track) elements.track.classList.remove("hidden");
  if (elements.pct) elements.pct.classList.remove("hidden");

  try {
    const task = await elements.requestJson("/api/summary", {
      method: "POST",
      body: JSON.stringify({
        url,
        title: appState.info.title,
        duration: appState.info.duration,
      }),
    });
    summaryState.taskId = task.summary_id;
    elements.stage.textContent = "任务已创建，正在读取字幕...";
    pollSummary(elements, task.summary_id, { mode });
  } catch (error) {
    reportSummaryError(elements, error.message, { mode });
  } finally {
    elements.button.disabled = false;
  }
}

export function initSummaryFeature(appState, helpers) {
  const elements = {
    url: $("#videoUrl"),
    button: $("#summaryBtn"),
    normalizeVideoUrl: helpers.normalizeVideoUrl || ((value) => value.trim()),
    card: $("#summaryCard"),
    title: $("#summaryTitle"),
    pct: $("#summaryPct"),
    bar: $("#summaryBar"),
    track: $("#summaryProgressTrack"),
    stage: $("#summaryStage"),
    notice: $("#summaryNotice"),
    result: $("#summaryResult"),
    panel: $("#summaryTabPanel"),
    tabs: Array.from(document.querySelectorAll("[data-summary-tab]")),
    ...helpers,
  };

  if (!elements.button || !elements.card) return;

  window.__summaryHelpers = helpers;
  runtime = { elements, appState };

  elements.button.addEventListener("click", () => startSummary(elements, appState, { mode: "manual" }));
  elements.tabs.forEach((button) => {
    button.addEventListener("click", () => switchTab(elements, button.dataset.summaryTab));
  });
}

