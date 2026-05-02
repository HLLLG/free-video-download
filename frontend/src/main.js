import "./styles.css";
import { initSummaryFeature, resetSummary, startSummaryAuto } from "./summary.js";

const MEMBERSHIP_STORAGE_KEY = "fvd.membership";
const DEFAULT_FREE_SUMMARY_MAX_DURATION_SECONDS = 40 * 60;
const DEFAULT_PRO_SUMMARY_MAX_DURATION_SECONDS = 120 * 60;

const state = {
  info: null,
  selectedQuality: "1080p",
  pollingTimer: null,
  currentTaskId: null,
  membership: loadStoredMembership(),
};

const $ = (selector) => document.querySelector(selector);

const els = {
  url: $("#videoUrl"),
  parseBtn: $("#parseBtn"),
  downloadBtn: $("#downloadBtn"),
  statusBox: $("#statusBox"),
  parseGrid: $("#parseGrid"),
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
  membershipBadge: $("#membershipBadge"),
  membershipPanel: $("#membershipPanel"),
  membershipTitle: $("#membershipTitle"),
  membershipMeta: $("#membershipMeta"),
  membershipKeyValue: $("#membershipKeyValue"),
  copyMembershipKeyBtn: $("#copyMembershipKeyBtn"),
  restoreModal: $("#restoreModal"),
  closeRestoreModal: $("#closeRestoreModal"),
  restoreForm: $("#restoreForm"),
  restoreEmail: $("#restoreEmail"),
  restoreKey: $("#restoreKey"),
  restoreStatus: $("#restoreStatus"),
  buyButtons: Array.from(document.querySelectorAll("[data-buy-plan]")),
  openRestoreButtons: Array.from(document.querySelectorAll("[data-open-restore]")),
};

function refreshIcons() {
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }
}

function formatCount(value) {
  if (value === null || value === undefined) return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return null;
  if (number >= 1_0000_0000) return `${(number / 1_0000_0000).toFixed(1)}亿`;
  if (number >= 1_0000) return `${(number / 1_0000).toFixed(1)}万`;
  return String(number);
}

function normalizeVideoUrl(rawUrl) {
  const value = rawUrl.trim();
  if (!value) return value;
  try {
    const url = new URL(value);
    if (url.hostname.toLowerCase() === "bilibili.com") {
      url.hostname = "www.bilibili.com";
    }
    return url.toString();
  } catch {
    return value;
  }
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

function formatExpiry(value) {
  if (!value) return "未开通";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function createCheckoutIntentKey(planType) {
  if (window.crypto?.randomUUID) {
    return `checkout_${planType}_${window.crypto.randomUUID()}`;
  }
  return `checkout_${planType}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function loadStoredMembership() {
  try {
    const raw = window.localStorage.getItem(MEMBERSHIP_STORAGE_KEY);
    if (!raw) {
      return {
        hasMembership: false,
        isPro: false,
        email: null,
        membershipKey: "",
        proExpiresAt: null,
        summaryMaxDurationSeconds: DEFAULT_FREE_SUMMARY_MAX_DURATION_SECONDS,
      };
    }
    const parsed = JSON.parse(raw);
    return normalizeMembership(parsed);
  } catch {
    return {
      hasMembership: false,
      isPro: false,
      email: null,
      membershipKey: "",
      proExpiresAt: null,
      summaryMaxDurationSeconds: DEFAULT_FREE_SUMMARY_MAX_DURATION_SECONDS,
    };
  }
}

function normalizeMembership(data = {}, existing = {}) {
  const membershipKey = String(data.membershipKey || data.membership_key || existing.membershipKey || "").trim();
  const email = String(data.email || existing.email || "").trim() || null;
  const hasMembership = Boolean(
    (data.hasMembership ?? data.has_membership) ?? (membershipKey || email),
  );
  const isPro = Boolean(data.isPro ?? data.is_pro);
  const proExpiresAt = data.proExpiresAt || data.pro_expires_at || null;
  const summaryMaxDurationSeconds =
    Number(data.summaryMaxDurationSeconds ?? data.summary_max_duration_seconds) ||
    (isPro ? DEFAULT_PRO_SUMMARY_MAX_DURATION_SECONDS : DEFAULT_FREE_SUMMARY_MAX_DURATION_SECONDS);

  return {
    hasMembership,
    isPro,
    email,
    membershipKey,
    proExpiresAt,
    summaryMaxDurationSeconds,
  };
}

function persistMembership(membership) {
  if (!membership?.membershipKey && !membership?.email) {
    window.localStorage.removeItem(MEMBERSHIP_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(MEMBERSHIP_STORAGE_KEY, JSON.stringify(membership));
}

function updateMembershipState(data = {}, { persist = true } = {}) {
  state.membership = normalizeMembership(data, state.membership);
  if (persist) {
    persistMembership(state.membership);
  }
  if (!state.membership.hasMembership && !state.membership.membershipKey) {
    window.localStorage.removeItem(MEMBERSHIP_STORAGE_KEY);
  }
  renderMembershipState();
  if (state.info?.qualities) {
    renderQualities(state.info.qualities);
  }
}

function clearMembershipState() {
  state.membership = normalizeMembership({
    has_membership: false,
    is_pro: false,
    email: null,
    membership_key: "",
    pro_expires_at: null,
    summary_max_duration_seconds: DEFAULT_FREE_SUMMARY_MAX_DURATION_SECONDS,
  });
  window.localStorage.removeItem(MEMBERSHIP_STORAGE_KEY);
  renderMembershipState();
  if (state.info?.qualities) {
    renderQualities(state.info.qualities);
  }
}

function renderMembershipState() {
  const membership = state.membership;
  if (els.membershipBadge) {
    els.membershipBadge.className = `membership-badge ${
      membership.isPro ? "pro" : membership.hasMembership ? "expired" : "free"
    }`;
    if (membership.isPro) {
      els.membershipBadge.innerHTML = `<i data-lucide="badge-check"></i><span>Pro 已开通</span>`;
    } else if (membership.hasMembership) {
      els.membershipBadge.innerHTML = `<i data-lucide="alert-circle"></i><span>会员已过期</span>`;
    } else {
      els.membershipBadge.innerHTML = `<i data-lucide="sparkles"></i><span>Free</span>`;
    }
  }

  if (els.membershipPanel) {
    if (!membership.hasMembership) {
      els.membershipPanel.classList.add("hidden");
    } else {
      els.membershipPanel.classList.remove("hidden");
      if (membership.isPro) {
        els.membershipTitle.textContent = "Pro 会员已开通";
        els.membershipMeta.textContent = `当前邮箱：${membership.email || "未记录"}，有效期至 ${formatExpiry(
          membership.proExpiresAt,
        )}。`;
      } else {
        els.membershipTitle.textContent = "会员凭证已恢复";
        els.membershipMeta.textContent = `当前邮箱：${membership.email || "未记录"}。会员已过期，可继续购买续期。`;
      }
      els.membershipKeyValue.textContent = membership.membershipKey || "尚未生成";
      els.copyMembershipKeyBtn.disabled = !membership.membershipKey;
    }
  }

  els.buyButtons.forEach((button) => {
    const plan = button.dataset.buyPlan;
    if (membership.isPro) {
      button.disabled = false;
      button.querySelector("span")?.replaceChildren(
        document.createTextNode(plan === "yearly" ? "继续续期 365 天" : "继续续期 30 天"),
      );
      return;
    }
    button.disabled = false;
    button.querySelector("span")?.replaceChildren(
      document.createTextNode(plan === "yearly" ? "立即购买年卡" : "立即购买月卡"),
    );
  });

  document.body.classList.toggle("is-pro", membership.isPro);
  refreshIcons();
}

function buildRequestHeaders(extraHeaders = {}, includeJson = false) {
  const headers = new Headers(extraHeaders);
  if (includeJson && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (state.membership?.membershipKey && !headers.has("X-Membership-Key")) {
    headers.set("X-Membership-Key", state.membership.membershipKey);
  }
  return headers;
}

async function requestJson(url, options = {}) {
  const hasBody = options.body !== undefined && options.body !== null;
  const response = await fetch(url, {
    ...options,
    headers: buildRequestHeaders(options.headers, hasBody),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "请求失败，请稍后重试");
  }
  return data;
}

async function refreshMembershipStatus({ silent = false } = {}) {
  if (!state.membership?.membershipKey) {
    renderMembershipState();
    return;
  }
  try {
    const data = await requestJson("/api/membership/status");
    if (!data.has_membership) {
      clearMembershipState();
      return;
    }
    updateMembershipState(data);
  } catch (error) {
    if (!silent) {
      showStatus(error.message, "error");
    }
  }
}

function openProModal() {
  els.proModal.classList.remove("hidden");
}

function closeProModal() {
  els.proModal.classList.add("hidden");
}

function openRestoreModal() {
  els.restoreStatus.classList.add("hidden");
  els.restoreStatus.textContent = "";
  els.restoreStatus.classList.remove("error");
  if (state.membership?.email) {
    els.restoreEmail.value = state.membership.email;
  }
  if (state.membership?.membershipKey) {
    els.restoreKey.value = state.membership.membershipKey;
  }
  els.restoreModal.classList.remove("hidden");
}

function closeRestoreModal() {
  els.restoreModal.classList.add("hidden");
}

function showRestoreStatus(message, type = "info") {
  els.restoreStatus.textContent = message;
  els.restoreStatus.classList.remove("hidden", "error");
  if (type === "error") {
    els.restoreStatus.classList.add("error");
  }
}

function getAllowedQuality(qualities) {
  return qualities.find((item) => !item.pro || state.membership.isPro);
}

function renderQualities(qualities) {
  els.qualityList.innerHTML = "";
  const firstAllowed = getAllowedQuality(qualities);
  const selectedStillAllowed = qualities.some(
    (item) => item.key === state.selectedQuality && (!item.pro || state.membership.isPro),
  );
  if (!selectedStillAllowed) {
    state.selectedQuality = firstAllowed?.key || "1080p";
  }

  for (const item of qualities) {
    const locked = item.pro && !state.membership.isPro;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `quality-option${item.key === state.selectedQuality ? " active" : ""}${
      locked ? " locked" : ""
    }`;
    const sizeBadge = item.size_text ? `<em class="quality-size">≈ ${item.size_text}</em>` : "";
    button.innerHTML = `
      <div class="quality-option-head">
        <strong>${item.label}${item.pro ? " · Pro" : ""}</strong>
        ${sizeBadge}
      </div>
      <span>${item.description}</span>
    `;
    button.addEventListener("click", () => {
      if (locked) {
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
  els.parseGrid.classList.remove("hidden");
  document.body.classList.add("compact-mode");
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
  const url = normalizeVideoUrl(els.url.value);
  if (!url) {
    showStatus("请先粘贴视频链接。", "error");
    return;
  }
  els.url.value = url;

  stopPolling();
  state.currentTaskId = null;
  els.parseBtn.disabled = true;
  els.downloadBtn.disabled = false;
  els.fileLink.classList.add("hidden");
  els.cancelBtn.classList.add("hidden");
  els.progressCard.classList.add("hidden");
  resetSummary();
  showStatus("正在解析视频信息...");

  try {
    const info = await requestJson("/api/info", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    renderInfo(info);
    showStatus("解析成功，AI 正在自动生成视频总结...");
    startSummaryAuto();
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    els.parseBtn.disabled = false;
  }
}

async function startDownload() {
  const url = state.info?.webpage_url || normalizeVideoUrl(els.url.value);
  if (!url || !state.info) {
    showStatus("请先解析视频链接。", "error");
    return;
  }
  const selectedOption = (state.info.qualities || []).find((item) => item.key === state.selectedQuality);
  if (selectedOption?.pro && !state.membership.isPro) {
    openProModal();
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

async function startCheckout(planType) {
  const button = els.buyButtons.find((item) => item.dataset.buyPlan === planType);
  const intentKey = createCheckoutIntentKey(planType);
  els.buyButtons.forEach((item) => {
    item.disabled = true;
  });
  showStatus("正在创建 Stripe 支付订单...");
  try {
    const data = await requestJson("/api/stripe/create-checkout", {
      method: "POST",
      headers: { "X-Checkout-Intent-Key": intentKey },
      body: JSON.stringify({ plan_type: planType }),
    });
    if (!data.checkout_url) {
      throw new Error("支付链接创建失败，请稍后重试");
    }
    window.location.href = data.checkout_url;
  } catch (error) {
    showStatus(error.message, "error");
    els.buyButtons.forEach((item) => {
      item.disabled = false;
    });
    if (button) button.disabled = false;
  }
}

async function handleRestoreSubmit(event) {
  event.preventDefault();
  const email = els.restoreEmail.value.trim();
  const membershipKey = els.restoreKey.value.trim();
  if (!email || !membershipKey) {
    showRestoreStatus("请填写邮箱和会员密钥。", "error");
    return;
  }
  showRestoreStatus("正在校验会员信息...");
  try {
    const data = await requestJson("/api/membership/activate", {
      method: "POST",
      body: JSON.stringify({ email, membership_key: membershipKey }),
    });
    updateMembershipState(data);
    closeRestoreModal();
    if (data.is_pro) {
      showStatus(`会员恢复成功，Pro 有效期至 ${formatExpiry(data.pro_expires_at)}。`);
    } else {
      showStatus("会员密钥验证成功，但当前会员已过期。你可以直接续期。");
    }
  } catch (error) {
    showRestoreStatus(error.message, "error");
  }
}

async function copyMembershipKey() {
  if (!state.membership?.membershipKey) return;
  try {
    await navigator.clipboard.writeText(state.membership.membershipKey);
    showStatus("会员密钥已复制，请妥善保存。");
  } catch {
    showStatus("复制失败，请手动选中会员密钥复制。", "error");
  }
}

async function handleCheckoutResult() {
  const params = new URLSearchParams(window.location.search);
  const checkoutState = params.get("checkout");
  const sessionId = params.get("session_id");
  if (checkoutState === "cancelled") {
    showStatus("你已取消支付，稍后仍可继续购买。");
    window.history.replaceState({}, "", window.location.pathname + window.location.hash);
    return;
  }
  if (checkoutState !== "success" || !sessionId) {
    return;
  }

  showStatus("支付成功，正在确认会员状态...");
  try {
    const data = await requestJson(`/api/stripe/checkout-success?session_id=${encodeURIComponent(sessionId)}`);
    updateMembershipState(data);
    els.membershipPanel?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    showStatus(
      `支付成功，Pro 已开通至 ${formatExpiry(data.pro_expires_at)}。会员密钥已自动保存，请同时自行备份。`,
    );
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    window.history.replaceState({}, "", window.location.pathname + window.location.hash);
  }
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
els.restoreModal.addEventListener("click", (event) => {
  if (event.target === els.restoreModal) closeRestoreModal();
});
els.closeRestoreModal.addEventListener("click", closeRestoreModal);
els.restoreForm.addEventListener("submit", handleRestoreSubmit);
els.copyMembershipKeyBtn.addEventListener("click", copyMembershipKey);
els.url.addEventListener("keydown", (event) => {
  if (event.key === "Enter") parseVideo();
});
els.buyButtons.forEach((button) => {
  button.addEventListener("click", () => startCheckout(button.dataset.buyPlan));
});
els.openRestoreButtons.forEach((button) => {
  button.addEventListener("click", openRestoreModal);
});
els.membershipBadge?.addEventListener("click", () => {
  if (state.membership.hasMembership) {
    els.membershipPanel?.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  document.querySelector("#pricing")?.scrollIntoView({ behavior: "smooth", block: "start" });
});

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", refreshIcons);
} else {
  refreshIcons();
}

renderMembershipState();
void refreshMembershipStatus({ silent: true });
void handleCheckoutResult();

initSummaryFeature(state, {
  requestJson,
  showStatus,
  refreshIcons,
  normalizeVideoUrl,
});
