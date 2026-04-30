const SUMMARY_MAX_DURATION_SECONDS = 40 * 60;

const summaryState = {
  taskId: null,
  pollingTimer: null,
  result: null,
  activeTab: "outline",
  sendingChat: false,
};
const MARKMAP_AUTOLOADER_URL = "https://cdn.jsdelivr.net/npm/markmap-autoloader@0.18.12";
let markmapLoaderPromise = null;

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
    <div class="mindmap-visual">
      <div class="markmap">
        <script type="text/template">${escapeScriptContent(markdown)}</script>
      </div>
    </div>
    <div class="mindmap-fallback">
      ${renderMindmapFallback(lines)}
    </div>
  `;
}

function scheduleMindmapRender() {
  if (summaryState.activeTab !== "mindmap") return;
  const visual = document.querySelector(".mindmap-visual");
  if (!visual) return;
  markmapLoaderPromise ||= loadScript(MARKMAP_AUTOLOADER_URL);
  markmapLoaderPromise
    .then(() => {
      const loader = window.markmap?.autoLoader;
      if (loader && typeof loader.renderAll === "function") {
        loader.renderAll();
        visual.classList.add("loaded");
      }
    })
    .catch(() => {
      visual.classList.remove("loaded");
    });
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
  return `<div class="transcript-list">${segments
    .map(
      (segment) => `
        <div class="transcript-item">
          <span class="transcript-time">${escapeHtml(segment.start_text)} - ${escapeHtml(segment.end_text)}</span>
          <p>${escapeHtml(segment.text)}</p>
        </div>
      `,
    )
    .join("")}</div>`;
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
  } else if (summaryState.activeTab === "mindmap") {
    elements.panel.innerHTML = renderMindmap(task.mindmap_markdown || "");
    scheduleMindmapRender();
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

function pollSummary(elements, taskId) {
  stopPolling();
  summaryState.pollingTimer = setInterval(async () => {
    try {
      const task = await elements.requestJson(`/api/summary/${taskId}`);
      setProgress(elements, task);
      if (task.status === "error") {
        stopPolling();
        elements.showStatus(task.error || "AI 总结失败，请稍后重试。", "error");
      }
      if (task.status === "done") {
        stopPolling();
        elements.showStatus("AI 总结完成，可以查看要点、字幕、思维导图和继续追问。");
        renderResult(elements, task);
      }
      elements.refreshIcons();
    } catch (error) {
      stopPolling();
      elements.showStatus(error.message, "error");
    }
  }, 1000);
}

async function startSummary(elements, appState) {
  const url = elements.url.value.trim();
  if (!url || !appState.info) {
    elements.showStatus("请先解析视频链接。", "error");
    return;
  }
  if (appState.info.duration && appState.info.duration > SUMMARY_MAX_DURATION_SECONDS) {
    elements.showStatus("当前免费版仅支持总结 40 分钟以内的视频。", "error");
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
    pollSummary(elements, task.summary_id);
  } catch (error) {
    elements.showStatus(error.message, "error");
  } finally {
    elements.button.disabled = false;
  }
}

export function initSummaryFeature(appState, helpers) {
  const elements = {
    url: $("#videoUrl"),
    button: $("#summaryBtn"),
    card: $("#summaryCard"),
    title: $("#summaryTitle"),
    pct: $("#summaryPct"),
    bar: $("#summaryBar"),
    stage: $("#summaryStage"),
    result: $("#summaryResult"),
    panel: $("#summaryTabPanel"),
    tabs: Array.from(document.querySelectorAll("[data-summary-tab]")),
    ...helpers,
  };

  if (!elements.button || !elements.card) return;

  elements.button.addEventListener("click", () => startSummary(elements, appState));
  elements.tabs.forEach((button) => {
    button.addEventListener("click", () => switchTab(elements, button.dataset.summaryTab));
  });
}

