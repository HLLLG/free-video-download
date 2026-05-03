import "./styles.css";
import { initSummaryFeature, resetSummary, startSummaryAuto } from "./summary.js";

const MEMBERSHIP_STORAGE_KEY = "fvd.membership";
const AUTH_STORAGE_KEY = "fvd.auth";
const DEFAULT_FREE_SUMMARY_MAX_DURATION_SECONDS = 40 * 60;
const DEFAULT_PRO_SUMMARY_MAX_DURATION_SECONDS = 120 * 60;
const DEFAULT_AUTH_MIN_PASSWORD_LENGTH = 8;
const PRO_MONTHLY_PRICE = 9.9;
const PRO_YEARLY_PRICE = 99;

const state = {
  info: null,
  selectedQuality: "1080p",
  pollingTimer: null,
  currentTaskId: null,
  auth: loadStoredAuth(),
  membership: null,
};
state.membership = state.auth.loggedIn ? loadStoredMembership() : createFreeMembershipState();
if (!state.auth.loggedIn) {
  window.localStorage.removeItem(MEMBERSHIP_STORAGE_KEY);
}

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
  authModal: $("#authModal"),
  closeAuthModal: $("#closeAuthModal"),
  authEntryBtn: $("#authEntryBtn"),
  authUserWrap: $("#authUserWrap"),
  authUserEmail: $("#authUserEmail"),
  logoutBtn: $("#logoutBtn"),
  authStatus: $("#authStatus"),
  authTabs: Array.from(document.querySelectorAll("[data-auth-tab]")),
  loginForm: $("#loginForm"),
  loginEmail: $("#loginEmail"),
  loginPassword: $("#loginPassword"),
  registerForm: $("#registerForm"),
  registerEmail: $("#registerEmail"),
  registerPassword: $("#registerPassword"),
  registerMembershipKey: $("#registerMembershipKey"),
  proModal: $("#proModal"),
  proModalEyebrow: $("#proModalEyebrow"),
  proModalTitle: $("#proModalTitle"),
  proModalDesc: $("#proModalDesc"),
  proYearlySave: $("#proYearlySave"),
  closeModal: $("#closeModal"),
  membershipBadge: $("#membershipBadge"),
  membershipMenuWrap: $("#membershipMenuWrap"),
  membershipDropdown: $("#membershipDropdown"),
  membershipMenuViewBtn: $("#membershipMenuViewBtn"),
  membershipMenuCopyBtn: $("#membershipMenuCopyBtn"),
  membershipMenuLogoutBtn: $("#membershipMenuLogoutBtn"),
  upgradeProNavBtn: $("#upgradeProNavBtn"),
  restoreMembershipNavBtn: $("#restoreMembershipNavBtn"),
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

function createFreeMembershipState() {
  return {
    hasMembership: false,
    isPro: false,
    email: null,
    membershipKey: "",
    proExpiresAt: null,
    summaryMaxDurationSeconds: DEFAULT_FREE_SUMMARY_MAX_DURATION_SECONDS,
  };
}

function createLoggedOutAuthState() {
  return {
    loggedIn: false,
    email: null,
    authToken: "",
    authExpiresAt: null,
  };
}

function loadStoredMembership() {
  try {
    const raw = window.localStorage.getItem(MEMBERSHIP_STORAGE_KEY);
    if (!raw) {
      return createFreeMembershipState();
    }
    const parsed = JSON.parse(raw);
    return normalizeMembership(parsed);
  } catch {
    return createFreeMembershipState();
  }
}

function loadStoredAuth() {
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return createLoggedOutAuthState();
    const parsed = JSON.parse(raw);
    return normalizeAuth(parsed);
  } catch {
    return createLoggedOutAuthState();
  }
}

function normalizeAuth(data = {}, existing = {}) {
  const email = String(data.email || existing.email || "").trim() || null;
  const authToken = String(data.authToken || data.auth_token || existing.authToken || "").trim();
  const authExpiresAt = data.authExpiresAt || data.auth_expires_at || existing.authExpiresAt || null;
  const loggedIn = Boolean((data.loggedIn ?? data.logged_in) ?? (email && authToken));
  return {
    loggedIn,
    email,
    authToken: loggedIn ? authToken : "",
    authExpiresAt: loggedIn ? authExpiresAt : null,
  };
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
  if (!state.auth.loggedIn || (!membership?.membershipKey && !membership?.email && !membership?.hasMembership)) {
    window.localStorage.removeItem(MEMBERSHIP_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(MEMBERSHIP_STORAGE_KEY, JSON.stringify(membership));
}

function persistAuth(auth) {
  if (!auth?.loggedIn || !auth?.authToken || !auth?.email) {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
}

function updateAuthState(data = {}, { persist = true } = {}) {
  state.auth = normalizeAuth(data, state.auth);
  if (persist) {
    persistAuth(state.auth);
  }
  if (!state.auth.loggedIn) {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
  }
  renderAuthState();
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
  state.membership = createFreeMembershipState();
  window.localStorage.removeItem(MEMBERSHIP_STORAGE_KEY);
  renderMembershipState();
  if (state.info?.qualities) {
    renderQualities(state.info.qualities);
  }
}

function clearAuthState({ clearMembership = true } = {}) {
  state.auth = createLoggedOutAuthState();
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
  renderAuthState();
  if (clearMembership) {
    clearMembershipState();
  }
}

function renderAuthState() {
  const auth = state.auth;
  const isPro = Boolean(state.membership?.isPro);
  if (els.authEntryBtn) {
    els.authEntryBtn.classList.toggle("hidden", auth.loggedIn);
  }
  if (els.authUserWrap) {
    els.authUserWrap.classList.toggle("hidden", !auth.loggedIn);
  }
  if (els.authUserEmail) {
    els.authUserEmail.textContent = auth.email || "-";
  }
  if (els.logoutBtn) {
    els.logoutBtn.classList.toggle("hidden", !auth.loggedIn || isPro);
  }
  if (els.restoreMembershipNavBtn) {
    els.restoreMembershipNavBtn.classList.toggle("hidden", !auth.loggedIn || isPro);
  }
  if (els.upgradeProNavBtn) {
    els.upgradeProNavBtn.classList.toggle("hidden", !auth.loggedIn || isPro);
  }
  if (!isPro) {
    closeMembershipDropdown();
  }
  refreshIcons();
}

function renderMembershipState() {
  const membership = state.membership;
  if (els.restoreMembershipNavBtn) {
    els.restoreMembershipNavBtn.classList.toggle("hidden", !state.auth.loggedIn || membership.isPro);
  }
  if (els.upgradeProNavBtn) {
    els.upgradeProNavBtn.classList.toggle("hidden", !state.auth.loggedIn || membership.isPro);
  }
  if (els.membershipMenuCopyBtn) {
    els.membershipMenuCopyBtn.disabled = !membership.membershipKey;
  }
  if (!membership.isPro) {
    closeMembershipDropdown();
  }
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
    if (!state.auth.loggedIn || !membership.hasMembership) {
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
    if (!state.auth.loggedIn) {
      button.disabled = false;
      button.querySelector("span")?.replaceChildren(document.createTextNode("登录后购买"));
      return;
    }
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

function openMembershipDropdown() {
  if (!state.auth.loggedIn || !state.membership.isPro) return;
  els.membershipDropdown?.classList.remove("hidden");
}

function closeMembershipDropdown() {
  els.membershipDropdown?.classList.add("hidden");
}

function toggleMembershipDropdown() {
  if (!state.auth.loggedIn || !state.membership.isPro) return;
  if (els.membershipDropdown?.classList.contains("hidden")) {
    openMembershipDropdown();
  } else {
    closeMembershipDropdown();
  }
}

function buildRequestHeaders(extraHeaders = {}, includeJson = false) {
  const headers = new Headers(extraHeaders);
  if (includeJson && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (state.auth?.authToken && !headers.has("X-Auth-Token")) {
    headers.set("X-Auth-Token", state.auth.authToken);
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

async function refreshAuthSession({ silent = false } = {}) {
  if (!state.auth?.authToken) {
    renderAuthState();
    return;
  }
  try {
    const data = await requestJson("/api/auth/me");
    updateAuthState(data);
    updateMembershipState(data);
  } catch (error) {
    clearAuthState();
    if (!silent) {
      showStatus(error.message, "error");
    }
  }
}

function showAuthStatus(message, type = "info") {
  els.authStatus.textContent = message;
  els.authStatus.classList.remove("hidden", "error");
  if (type === "error") {
    els.authStatus.classList.add("error");
  }
}

function switchAuthTab(tab) {
  const target = tab === "register" ? "register" : "login";
  els.authTabs.forEach((button) => button.classList.toggle("active", button.dataset.authTab === target));
  els.loginForm.classList.toggle("hidden", target !== "login");
  els.registerForm.classList.toggle("hidden", target !== "register");
  els.authStatus.classList.add("hidden");
  els.authStatus.textContent = "";
  els.authStatus.classList.remove("error");
}

function openAuthModal(tab = "login") {
  switchAuthTab(tab);
  if (state.auth?.email) {
    els.loginEmail.value = state.auth.email;
    els.registerEmail.value = state.auth.email;
  }
  els.authModal.classList.remove("hidden");
}

function closeAuthModal() {
  els.authModal.classList.add("hidden");
}

function applyProModalCopy(context = "default") {
  const copy = context === "summary-limit"
    ? {
        eyebrow: "今日免费额度已用完",
        title: "升级 Pro，立即继续 AI 总结",
        desc: "Free 用户每天最多总结 3 个视频。升级 Pro 后可不限次数总结，并支持最长 120 分钟视频总结。",
      }
    : {
        eyebrow: "Pro 专享",
        title: "选择方案，立即解锁 Pro 权益",
        desc: "开通后立即生效。支付成功后系统会返回会员密钥，可在新设备或新浏览器恢复会员。",
      };
  if (els.proModalEyebrow) els.proModalEyebrow.textContent = copy.eyebrow;
  if (els.proModalTitle) els.proModalTitle.textContent = copy.title;
  if (els.proModalDesc) els.proModalDesc.textContent = copy.desc;
}

function renderYearlySavings() {
  if (!els.proYearlySave) return;
  const yearlyAsMonthly = PRO_MONTHLY_PRICE * 12;
  if (!Number.isFinite(yearlyAsMonthly) || yearlyAsMonthly <= 0 || PRO_YEARLY_PRICE <= 0) {
    els.proYearlySave.textContent = "年卡长期更划算";
    return;
  }
  const saveRate = Math.max(0, (1 - PRO_YEARLY_PRICE / yearlyAsMonthly) * 100);
  els.proYearlySave.textContent = `相比月卡省约 ${Math.round(saveRate)}%`;
}

function openProModal(context = "default") {
  if (!state.auth.loggedIn) {
    openAuthModal("login");
    if (context === "summary-limit") {
      showStatus("今日免费总结次数已用完，请先登录后升级 Pro 继续总结。", "error");
    } else {
      showStatus("请先登录或注册账号，再升级 Pro。", "error");
    }
    return;
  }
  applyProModalCopy(context);
  els.proModal.classList.remove("hidden");
}

function closeProModal() {
  els.proModal.classList.add("hidden");
}

function openRestoreModal() {
  if (!state.auth.loggedIn) {
    openAuthModal("login");
    showStatus("请先登录账号，再恢复会员。", "error");
    return;
  }
  els.restoreStatus.classList.add("hidden");
  els.restoreStatus.textContent = "";
  els.restoreStatus.classList.remove("error");
  if (state.auth?.email) {
    els.restoreEmail.value = state.auth.email;
  } else if (state.membership?.email) {
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

function applyAuthPayload(data) {
  updateAuthState(data);
  updateMembershipState(data);
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  const email = els.loginEmail.value.trim();
  const password = els.loginPassword.value;
  if (!email || !password) {
    showAuthStatus("请填写邮箱和密码。", "error");
    return;
  }
  showAuthStatus("正在登录...");
  try {
    const data = await requestJson("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    applyAuthPayload(data);
    closeAuthModal();
    showStatus("登录成功，已可购买 Pro 会员。");
  } catch (error) {
    showAuthStatus(error.message, "error");
  }
}

async function handleRegisterSubmit(event) {
  event.preventDefault();
  const email = els.registerEmail.value.trim();
  const password = els.registerPassword.value;
  const membershipKey = els.registerMembershipKey.value.trim();
  if (!email || !password) {
    showAuthStatus("请填写邮箱和密码。", "error");
    return;
  }
  if (password.length < DEFAULT_AUTH_MIN_PASSWORD_LENGTH) {
    showAuthStatus(`密码长度至少 ${DEFAULT_AUTH_MIN_PASSWORD_LENGTH} 位。`, "error");
    return;
  }
  showAuthStatus("正在注册账号...");
  try {
    const data = await requestJson("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        membership_key: membershipKey || null,
      }),
    });
    applyAuthPayload(data);
    closeAuthModal();
    showStatus("注册成功，已自动登录。");
  } catch (error) {
    showAuthStatus(error.message, "error");
  }
}

async function handleLogout() {
  try {
    await requestJson("/api/auth/logout", { method: "POST" });
  } catch (_) {
    // Ignore logout API failures and clear local session anyway.
  } finally {
    clearAuthState();
    closeRestoreModal();
    closeProModal();
    showStatus("你已退出登录，当前为 Free 模式。");
  }
}

async function startCheckout(planType) {
  if (!state.auth.loggedIn) {
    openAuthModal("login");
    showStatus("请先登录或注册账号，再购买会员。", "error");
    return;
  }
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
  if (!state.auth.loggedIn) {
    closeRestoreModal();
    openAuthModal("login");
    showStatus("请先登录账号，再恢复会员。", "error");
    return;
  }
  const email = els.restoreEmail.value.trim();
  const membershipKey = els.restoreKey.value.trim();
  if (!email || !membershipKey) {
    showRestoreStatus("请填写邮箱和会员密钥。", "error");
    return;
  }
  if (state.auth.email && email.toLowerCase() !== state.auth.email.toLowerCase()) {
    showRestoreStatus("恢复邮箱需与当前登录邮箱一致。", "error");
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
    closeMembershipDropdown();
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
    if (data.logged_in && data.auth_token) {
      applyAuthPayload(data);
    } else {
      updateMembershipState(data);
    }
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
  if (els.membershipMenuWrap && !els.membershipMenuWrap.contains(event.target)) {
    closeMembershipDropdown();
  }
});

els.parseBtn.addEventListener("click", parseVideo);
els.downloadBtn.addEventListener("click", startDownload);
els.cancelBtn.addEventListener("click", cancelDownload);
els.authEntryBtn?.addEventListener("click", () => openAuthModal("login"));
els.closeAuthModal?.addEventListener("click", closeAuthModal);
els.authModal?.addEventListener("click", (event) => {
  if (event.target === els.authModal) closeAuthModal();
});
els.authTabs.forEach((button) => {
  button.addEventListener("click", () => switchAuthTab(button.dataset.authTab));
});
els.loginForm?.addEventListener("submit", handleLoginSubmit);
els.registerForm?.addEventListener("submit", handleRegisterSubmit);
els.logoutBtn?.addEventListener("click", handleLogout);
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
els.upgradeProNavBtn?.addEventListener("click", openProModal);
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
  if (!state.auth.loggedIn) {
    openAuthModal("login");
    return;
  }
  if (state.membership.isPro) {
    toggleMembershipDropdown();
    return;
  }
  if (state.membership.hasMembership) {
    els.membershipPanel?.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  document.querySelector("#pricing")?.scrollIntoView({ behavior: "smooth", block: "start" });
});
els.membershipMenuViewBtn?.addEventListener("click", () => {
  closeMembershipDropdown();
  els.membershipPanel?.scrollIntoView({ behavior: "smooth", block: "center" });
});
els.membershipMenuCopyBtn?.addEventListener("click", copyMembershipKey);
els.membershipMenuLogoutBtn?.addEventListener("click", async () => {
  closeMembershipDropdown();
  await handleLogout();
});

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", refreshIcons);
} else {
  refreshIcons();
}

renderYearlySavings();
applyProModalCopy("default");
renderAuthState();
renderMembershipState();
void refreshAuthSession({ silent: true });
void handleCheckoutResult();

initSummaryFeature(state, {
  requestJson,
  showStatus,
  refreshIcons,
  normalizeVideoUrl,
  openProModal,
});
