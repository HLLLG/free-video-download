import "./styles.css";

const state = {
  info: null,
  selectedQuality: "1080p",
  pollingTimer: null,
  currentTaskId: null,
};

const $ = (selector) => document.querySelector(selector);

const els = {
  url: $("#videoUrl"),
  parseBtn: $("#parseBtn"),
  downloadBtn: $("#downloadBtn"),
  statusBox: $("#statusBox"),
  resultCard: $("#resultCard"),
  progressCard: $("#progressCard"),
  thumbnail: $("#thumbnail"),
  thumbWrap: document.querySelector(".thumb-wrap"),
  platformBadge: $("#platformBadge"),
  videoTitle: $("#videoTitle"),
  metaStats: $("#metaStats"),
  qualityList: $("#qualityList"),
  progressTitle: $("#progressTitle"),
  progressPct: $("#progressPct"),
  progressBar: $("#progressBar"),
  speedText: $("#speedText"),
  etaText: $("#etaText"),
  fileLink: $("#fileLink"),
  cancelBtn: $("#cancelBtn"),
  proModal: $("#proModal"),
  closeModal: $("#closeModal"),
};

function refreshIcons() {
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }
}

function setIcon(parent, iconName) {
  parent.innerHTML = `<i data-lucide="${iconName}"></i>`;
  refreshIcons();
}

function formatCount(value) {
  if (value === null || value === undefined) return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return null;
  if (number >= 1_0000_0000) return `${(number / 1_0000_0000).toFixed(1)}亿`;
  if (number >= 1_0000) return `${(number / 1_0000).toFixed(1)}万`;
  return String(number);
}

function showStatus(message, type = "info") {
  els.statusBox.textContent = message;
  els.statusBox.classList.remove("hidden", "error");
  if (type === "error") {
    els.statusBox.classList.add("error");
  }
}

function hideStatus() {
  els.statusBox.classList.add("hidden");
}

function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond) return "等待中";
  const units = ["B/s", "KB/s", "MB/s", "GB/s"];
  let value = bytesPerSecond;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[index]}`;
}

function formatEta(seconds) {
  if (!seconds && seconds !== 0) return "--";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return minutes ? `${minutes}分${rest}秒` : `${rest}秒`;
}

async function requestJson(url, options) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "请求失败，请稍后重试");
  }
  return data;
}

function openProModal() {
  els.proModal.classList.remove("hidden");
}

function closeProModal() {
  els.proModal.classList.add("hidden");
}

function renderQualities(qualities) {
  els.qualityList.innerHTML = "";
  const firstFree = qualities.find((item) => !item.pro);
  state.selectedQuality = firstFree?.key || "1080p";

  for (const item of qualities) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `quality-option${item.key === state.selectedQuality ? " active" : ""}${item.pro ? " locked" : ""}`;
    const sizeBadge = item.size_text
      ? `<em class="quality-size">≈ ${item.size_text}</em>`
      : "";
    button.innerHTML = `
      <div class="quality-option-head">
        <strong>${item.label}${item.pro ? " · Pro" : ""}</strong>
        ${sizeBadge}
      </div>
      <span>${item.description}</span>
    `;
    button.addEventListener("click", () => {
      if (item.pro) {
        openProModal();
        return;
      }
      state.selectedQuality = item.key;
      document.querySelectorAll(".quality-option").forEach((node) => node.classList.remove("active"));
      button.classList.add("active");
    });
    els.qualityList.appendChild(button);
  }
}

function renderMetaStats(info) {
  const items = [];
  if (info.platform) items.push({ icon: "globe", text: info.platform });
  if (info.uploader) items.push({ icon: "user", text: info.uploader });
  if (info.duration_text) items.push({ icon: "clock", text: info.duration_text });
  const views = formatCount(info.view_count);
  if (views) items.push({ icon: "eye", text: `${views} 次播放` });
  const likes = formatCount(info.like_count);
  if (likes) items.push({ icon: "thumbs-up", text: `${likes} 赞` });

  els.metaStats.innerHTML = items
    .map((item) => `<li><i data-lucide="${item.icon}"></i><span>${item.text}</span></li>`)
    .join("");
}

function applyThumbnail(info) {
  const wrap = els.thumbWrap;
  wrap.classList.remove("has-image");
  if (!info.thumbnail) {
    els.thumbnail.removeAttribute("src");
    return;
  }
  const proxied = `/api/thumbnail?url=${encodeURIComponent(info.thumbnail)}${
    info.platform_key ? `&platform=${encodeURIComponent(info.platform_key)}` : ""
  }`;
  els.thumbnail.onload = () => wrap.classList.add("has-image");
  els.thumbnail.onerror = () => wrap.classList.remove("has-image");
  els.thumbnail.src = proxied;
}

function renderInfo(info) {
  state.info = info;
  applyThumbnail(info);
  els.platformBadge.innerHTML = `<i data-lucide="globe"></i><span>${info.platform || "Video"}</span>`;
  els.videoTitle.textContent = info.title || "未命名视频";
  renderMetaStats(info);
  renderQualities(info.qualities || []);
  els.resultCard.classList.remove("hidden");
  refreshIcons();
}

function updateProgress(task) {
  els.progressCard.classList.remove("hidden");
  els.progressTitle.textContent = task.title || "正在下载";
  const pct = typeof task.pct === "number" ? Math.min(100, Math.max(0, task.pct)) : 0;
  els.progressPct.textContent = task.status === "done" ? "100%" : `${pct.toFixed(0)}%`;
  els.progressBar.style.width = `${task.status === "done" ? 100 : pct}%`;

  const isActive = task.status !== "done" && task.status !== "error" && task.status !== "cancelled";
  els.cancelBtn.classList.toggle("hidden", !isActive);

  const isPostprocessing = task.stage === "postprocessing" && task.status !== "done";
  if (task.status === "cancelled") {
    els.speedText.innerHTML = `<i data-lucide="x-circle"></i><span>已取消下载</span>`;
    els.etaText.innerHTML = "";
  } else if (isPostprocessing) {
    const stageText = task.stage_text || "正在合并音视频";
    els.speedText.innerHTML = `<i data-lucide="loader-2"></i><span>${stageText}，请稍候</span>`;
    els.etaText.innerHTML = `<i data-lucide="info"></i><span>合并阶段无进度，通常 10~60 秒</span>`;
  } else {
    els.speedText.innerHTML = `<i data-lucide="zap"></i><span>速度：${formatSpeed(task.speed)}</span>`;
    els.etaText.innerHTML = `<i data-lucide="timer"></i><span>剩余：${formatEta(task.eta)}</span>`;
  }
  refreshIcons();

  if (task.status === "error") {
    showStatus(task.error || "下载失败，请换个链接重试", "error");
    stopPolling();
    state.currentTaskId = null;
    els.downloadBtn.disabled = false;
  }

  if (task.status === "cancelled") {
    stopPolling();
    state.currentTaskId = null;
    els.downloadBtn.disabled = false;
  }

  if (task.status === "done") {
    stopPolling();
    state.currentTaskId = null;
    els.downloadBtn.disabled = false;
    els.fileLink.href = `/api/file/${task.task_id}`;
    els.fileLink.classList.remove("hidden");
    showStatus("下载完成，可以保存到本地。");
  }
}

function stopPolling() {
  if (state.pollingTimer) {
    clearInterval(state.pollingTimer);
    state.pollingTimer = null;
  }
}

async function parseVideo() {
  const url = els.url.value.trim();
  if (!url) {
    showStatus("请先粘贴视频链接。", "error");
    return;
  }

  stopPolling();
  state.currentTaskId = null;
  els.parseBtn.disabled = true;
  els.downloadBtn.disabled = false;
  els.fileLink.classList.add("hidden");
  els.cancelBtn.classList.add("hidden");
  els.progressCard.classList.add("hidden");
  showStatus("正在解析视频信息...");

  try {
    const info = await requestJson("/api/info", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    renderInfo(info);
    showStatus("解析成功，请选择清晰度后开始下载。");
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    els.parseBtn.disabled = false;
  }
}

async function startDownload() {
  const url = els.url.value.trim();
  if (!url || !state.info) {
    showStatus("请先解析视频链接。", "error");
    return;
  }

  els.downloadBtn.disabled = true;
  els.fileLink.classList.add("hidden");
  els.cancelBtn.classList.remove("hidden");
  showStatus("已创建下载任务，正在排队...");

  try {
    const task = await requestJson("/api/download", {
      method: "POST",
      body: JSON.stringify({ url, quality: state.selectedQuality }),
    });
    state.currentTaskId = task.task_id;
    els.progressTitle.textContent = "下载任务已启动";
    els.progressCard.classList.remove("hidden");
    pollProgress(task.task_id);
  } catch (error) {
    showStatus(error.message, "error");
    els.downloadBtn.disabled = false;
    els.cancelBtn.classList.add("hidden");
  }
}

async function cancelDownload() {
  const taskId = state.currentTaskId;
  if (!taskId) return;
  els.cancelBtn.disabled = true;
  try {
    await requestJson(`/api/cancel/${taskId}`, { method: "POST" });
    stopPolling();
    state.currentTaskId = null;
    els.cancelBtn.classList.add("hidden");
    els.progressCard.classList.add("hidden");
    els.downloadBtn.disabled = false;
    showStatus("已取消下载，临时文件已清理。");
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    els.cancelBtn.disabled = false;
  }
}

function pollProgress(taskId) {
  stopPolling();
  state.pollingTimer = setInterval(async () => {
    try {
      const task = await requestJson(`/api/progress/${taskId}`);
      updateProgress(task);
    } catch (error) {
      if (state.currentTaskId !== taskId) {
        stopPolling();
        return;
      }
      showStatus(error.message, "error");
      stopPolling();
      state.currentTaskId = null;
      els.downloadBtn.disabled = false;
    }
  }, 1000);
}

document.addEventListener("click", (event) => {
  const scrollTarget = event.target.closest("[data-scroll]");
  if (scrollTarget) {
    const selector = scrollTarget.getAttribute("data-scroll");
    closeProModal();
    document.querySelector(selector)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

els.parseBtn.addEventListener("click", parseVideo);
els.downloadBtn.addEventListener("click", startDownload);
els.cancelBtn.addEventListener("click", cancelDownload);
els.closeModal.addEventListener("click", closeProModal);
els.proModal.addEventListener("click", (event) => {
  if (event.target === els.proModal) closeProModal();
});
els.url.addEventListener("keydown", (event) => {
  if (event.key === "Enter") parseVideo();
});

document.querySelectorAll(".locked").forEach((node) => {
  node.addEventListener("click", openProModal);
});

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", refreshIcons);
} else {
  refreshIcons();
}
