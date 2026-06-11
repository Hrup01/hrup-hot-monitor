const state = {
  meta: null,
  dashboard: null,
  watchTerms: [],
  filters: {
    sort: "score_desc",
    levels: [],
    sources: [],
    search: "",
    minScore: 0,
    timeRange: "all",
    newOnly: false,
    resonanceOnly: false,
  },
  detailsExpandedAll: false,
  filtersInitialized: false,
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatCount(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "-";
  if (num >= 100000000) return `${(num / 100000000).toFixed(1).replace(/\.0$/, "")}亿`;
  if (num >= 10000) return `${(num / 10000).toFixed(1).replace(/\.0$/, "")}万`;
  return `${Math.round(num)}`;
}

function toTimestamp(value) {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function levelClass(level) {
  return String(level || "LOW").toLowerCase();
}

function levelRank(level) {
  return {
    LOW: 1,
    MEDIUM: 2,
    HIGH: 3,
    URGENT: 4,
  }[String(level || "LOW").toUpperCase()] || 1;
}

function trendClass(trendLabel) {
  if (trendLabel === "上升") return "up";
  if (trendLabel === "下降") return "down";
  return "flat";
}

function formatMetricChips(metrics = {}) {
  const entries = [
    ["likes", "点赞"],
    ["replies", "回复"],
    ["reposts", "转发"],
    ["bookmarks", "收藏"],
    ["views", "浏览"],
  ];
  const chips = entries
    .filter(([key]) => Number(metrics[key] || 0) > 0)
    .map(([key, label]) => `<span>${escapeHtml(label)} ${escapeHtml(formatCount(metrics[key]))}</span>`);
  return chips.join("");
}

function formatEvidenceMeta(item) {
  const parts = [];
  if (item.source) parts.push(`<span>${escapeHtml(item.source)}</span>`);
  if (item.published_at) parts.push(`<span>发于 ${escapeHtml(formatTime(item.published_at))}</span>`);
  if (item.fetched_at) parts.push(`<span>抓取 ${escapeHtml(formatTime(item.fetched_at))}</span>`);
  if (Number(item.interaction_total || 0) > 0) parts.push(`<span>互动 ${escapeHtml(formatCount(item.interaction_total))}</span>`);
  return parts.join("");
}

function renderStats(dashboard) {
  const stats = dashboard.stats || {};
  $("totalHotspots").textContent = stats.total_hotspots ?? 0;
  $("todayNew").textContent = stats.today_new ?? 0;
  $("urgentHotspots").textContent = stats.urgent_hotspots ?? 0;
  $("watchTermCount").textContent = stats.watch_terms ?? 0;
  $("refreshLabel").textContent = dashboard.refresh_label || "自动更新";
  $("notifyCount").textContent = (state.meta?.state?.notifications || []).length || 0;
}

function renderEmptyState(message = "添加监控词后点击立即扫描，HotPulse 会把多源信号整理成热点流。") {
  $("hotspotList").innerHTML = `
    <article class="empty-state">
      <div class="empty-orbit" aria-hidden="true"></div>
      <h2>还没有匹配到热点</h2>
      <p>${escapeHtml(message)}</p>
    </article>
  `;
}

function renderReasonPoints(points = []) {
  return points
    .filter(Boolean)
    .map((point) => `<span>${escapeHtml(point)}</span>`)
    .join("");
}

function renderEvidenceList(evidence = []) {
  if (!evidence.length) return "";
  return evidence.map((item) => `
    <article class="evidence-item">
      <div class="evidence-head">
        <div>
          <p class="evidence-title">${item.url
            ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source || "原始证据")}</a>`
            : escapeHtml(item.source || "原始证据")}</p>
          <div class="evidence-meta">${formatEvidenceMeta(item)}</div>
        </div>
      </div>
      <p>${escapeHtml(item.raw_description || item.text || "暂无原始描述")}</p>
      ${formatMetricChips(item.metrics || {}) ? `<div class="metric-row">${formatMetricChips(item.metrics || {})}</div>` : ""}
    </article>
  `).join("");
}

function renderHotspots(hotspots, totalCount) {
  const list = $("hotspotList");
  $("detailToggleAll").textContent = state.detailsExpandedAll ? "折叠全部理由" : "展开全部理由";
  $("filterSummary").textContent = `显示 ${hotspots.length} / ${totalCount}`;
  if (!hotspots.length) {
    renderEmptyState("当前筛选条件下没有匹配结果，试着放宽等级、来源或时间范围。");
    return;
  }

  list.innerHTML = hotspots.map((item) => {
    const tags = (item.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("");
    const title = item.url
      ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>`
      : escapeHtml(item.title);
    const metricChips = formatMetricChips(item.interactions || {});
    const trendClassName = trendClass(item.trend_label);
    const trendLabel = item.trend_label || "平稳";
    const trendText = item.trend_delta > 0 ? `+${item.trend_delta}` : `${item.trend_delta || 0}`;
    const evidenceHtml = renderEvidenceList(item.evidence || []);
    const badges = [
      `<span class="level-badge">${escapeHtml(item.level || "LOW")}</span>`,
      `<span class="source-badge">${escapeHtml(item.source || "unknown")}</span>`,
      `<span>${escapeHtml(`覆盖 ${item.source_count ?? 1} 源`)}</span>`,
      `<span class="trend-badge ${trendClassName}">${escapeHtml(`趋势 ${trendLabel} ${trendText}`)}</span>`,
    ];
    if (item.is_new) badges.push(`<span class="signal-badge is-new">24h 新热点</span>`);
    if (item.is_resonating) badges.push(`<span class="signal-badge is-resonating">多源共振</span>`);
    return `
      <article class="hot-card ${levelClass(item.level)}">
        <div class="hot-meta">
          ${badges.join("")}
          ${tags}
        </div>
        <h2>${title}</h2>
        <div class="desc-grid">
          <div class="desc-block">
            <span>原始描述</span>
            <p>${escapeHtml(item.raw_description || item.title || "暂无原始描述")}</p>
          </div>
          <div class="desc-block ai">
            <span>AI 摘要</span>
            <p>${escapeHtml(item.ai_summary || item.summary || "暂无 AI 摘要")}</p>
          </div>
        </div>
        ${metricChips ? `<div class="metric-row">${metricChips}</div>` : ""}
        <footer>
          <span>热度 ${escapeHtml(item.score ?? "-")}%</span>
          <span>发布时间 ${escapeHtml(formatTime(item.published_at || item.first_seen_at || item.analyzed_at))}</span>
          <span>抓取时间 ${escapeHtml(formatTime(item.fetched_at || item.last_seen_at || item.analyzed_at))}</span>
          <span>最近 ${escapeHtml(formatTime(item.last_seen_at || item.analyzed_at))}</span>
          <span>${escapeHtml(item.mode || "")}</span>
        </footer>
        <details class="reason-details" ${state.detailsExpandedAll ? "open" : ""}>
          <summary>相关性理由</summary>
          <div class="reason-body">
            <p class="reason-text">${escapeHtml(item.reason || "暂无 AI 相关性理由")}</p>
            ${item.reason_points?.length ? `<div class="reason-points">${renderReasonPoints(item.reason_points)}</div>` : ""}
            <div class="evidence-list">
              ${evidenceHtml || `<article class="evidence-item"><p>暂无可展示的原始证据。</p></article>`}
            </div>
          </div>
        </details>
      </article>
    `;
  }).join("");
}

function renderTerms(dashboard) {
  state.watchTerms = dashboard.watch_terms || [];
  $("watchTerms").value = state.watchTerms.join("\n");
  $("termChips").innerHTML = state.watchTerms.map((term) => `<span>${escapeHtml(term)}</span>`).join("");
  $("query").value = dashboard.active_query || "";
}

function renderStatus(meta) {
  const rows = [
    { label: "OpenRouter", value: meta.openrouter_ready ? "已连接" : "未配置", ok: meta.openrouter_ready },
    { label: "TwitterAPI", value: meta.twitterapi_ready ? "已连接" : "未配置", ok: meta.twitterapi_ready },
    { label: "最近错误", value: meta.dashboard?.last_error || "暂无", ok: !meta.dashboard?.last_error },
  ];
  $("sourceStatus").innerHTML = rows.map((row) => `
    <div class="status-pill ${row.ok ? "ok" : "warn"}">
      <span></span>
      ${escapeHtml(row.label)}: ${escapeHtml(row.value)}
    </div>
  `).join("");
}

function dashboardFromLegacy(meta) {
  const source = meta.state || {};
  const results = [source.latest_result, ...(source.history || [])].filter(Boolean);
  const seen = new Set();
  const hotspots = [];
  results.forEach((result) => {
    (result.highlights || []).slice(0, 8).forEach((item, index) => {
      const title = (item.text || result.headline || "").trim();
      if (!title || seen.has(title)) return;
      seen.add(title);
      const score = Number(item.score || result.hot_score || 0);
      const level = score >= 90 ? "URGENT" : score >= 70 ? "HIGH" : score >= 50 ? "MEDIUM" : "LOW";
      hotspots.push({
        id: `${result.analyzed_at || "legacy"}-${index}`,
        level,
        score,
        source: item.source || "unknown",
        source_count: 1,
        sources: [item.source || "unknown"],
        topic: result.query || source.query || "",
        title,
        summary: result.summary || result.risk || "正在观察信号走势。",
        ai_summary: result.summary || result.risk || "正在观察信号走势。",
        raw_description: item.text || result.headline || "",
        tags: (result.keywords || []).slice(0, 3),
        url: item.url || "",
        author: item.author || "",
        analyzed_at: result.analyzed_at || source.last_checked_at,
        first_seen_at: result.analyzed_at || source.last_checked_at,
        last_seen_at: result.analyzed_at || source.last_checked_at,
        published_at: result.analyzed_at || source.last_checked_at,
        fetched_at: result.analyzed_at || source.last_checked_at,
        mode: result.mode || "unknown",
        is_new: false,
        is_resonating: false,
        trend_label: "平稳",
        trend_delta: 0,
        reason: result.reason || result.summary || result.risk || "",
        reason_points: result.reason_points || [],
        evidence: [],
        interactions: item.metrics || {},
      });
    });
  });
  const terms = [...(source.manual_keywords || [])];
  if (source.query && !terms.includes(source.query)) terms.unshift(source.query);
  return {
    brand: "HotPulse",
    subtitle: "AI 热点雷达",
    active_query: source.query || "",
    watch_terms: terms,
    source_options: [...new Set(hotspots.map((item) => item.source))].sort(),
    filter_defaults: {
      sort: "score_desc",
      levels: [],
      sources: [],
      search: "",
      min_score: 0,
      time_range: "all",
      new_only: false,
      resonance_only: false,
    },
    stats: {
      total_hotspots: hotspots.length,
      today_new: 0,
      urgent_hotspots: hotspots.filter((item) => item.level === "HIGH" || item.level === "URGENT").length,
      watch_terms: terms.length,
    },
    hotspots,
    refresh_label: `每 ${Math.max(1, Math.floor((meta.poll_seconds || 1800) / 60))} 分钟自动更新`,
    last_checked_at: source.last_checked_at,
    last_error: source.last_error,
  };
}

function applyDashboardDefaults(dashboard, force = false) {
  if (state.filtersInitialized && !force) return;
  const defaults = dashboard.filter_defaults || {};
  state.filters = {
    sort: defaults.sort || "score_desc",
    levels: [...(defaults.levels || [])],
    sources: [...(defaults.sources || [])],
    search: defaults.search || "",
    minScore: Number(defaults.min_score || 0),
    timeRange: defaults.time_range || "all",
    newOnly: Boolean(defaults.new_only),
    resonanceOnly: Boolean(defaults.resonance_only),
  };
  state.filtersInitialized = true;
}

function buildChip(name, value, checked) {
  return `
    <label class="toggle-chip ${checked ? "active" : ""}">
      <input type="checkbox" data-filter-group="${escapeHtml(name)}" value="${escapeHtml(value)}" ${checked ? "checked" : ""} />
      <span>${escapeHtml(value)}</span>
    </label>
  `;
}

function renderFilterControls(dashboard) {
  const hotspots = dashboard.hotspots || [];
  const sourceOptions = (dashboard.source_options || [])
    .filter(Boolean)
    .filter((value, index, array) => array.indexOf(value) === index)
    .sort((a, b) => a.localeCompare(b, "zh-CN"));
  const levelOptions = ["URGENT", "HIGH", "MEDIUM", "LOW"];
  $("sortOrder").value = state.filters.sort;
  $("minScore").value = String(state.filters.minScore);
  $("timeRange").value = state.filters.timeRange;
  $("searchFilter").value = state.filters.search;
  $("newOnly").checked = state.filters.newOnly;
  $("resonanceOnly").checked = state.filters.resonanceOnly;
  $("levelFilters").innerHTML = levelOptions
    .map((level) => buildChip("levels", level, state.filters.levels.includes(level)))
    .join("");
  $("sourceFilters").innerHTML = sourceOptions
    .map((source) => buildChip("sources", source, state.filters.sources.includes(source)))
    .join("");
  const maxCoverage = hotspots.reduce((max, item) => Math.max(max, item.source_count || 1), 1);
  $("filterSummary").textContent = `显示 0 / ${hotspots.length}，最高覆盖 ${maxCoverage} 源`;
}

function matchesTimeRange(item) {
  if (state.filters.timeRange === "all") return true;
  const current = Date.now();
  const target = toTimestamp(item.last_seen_at || item.analyzed_at);
  if (!target) return false;
  const diff = current - target;
  if (state.filters.timeRange === "24h") return diff <= 24 * 3600 * 1000;
  if (state.filters.timeRange === "7d") return diff <= 7 * 24 * 3600 * 1000;
  return true;
}

function matchesSearch(item) {
  const search = state.filters.search.trim().toLowerCase();
  if (!search) return true;
  const haystack = [
    item.title,
    item.summary,
    item.topic,
    ...(item.tags || []),
    ...(item.sources || []),
  ].join(" ").toLowerCase();
  return haystack.includes(search);
}

function applyFilters() {
  const hotspots = state.dashboard?.hotspots || [];
  const filtered = hotspots.filter((item) => {
    if (state.filters.levels.length && !state.filters.levels.includes(item.level)) return false;
    if (state.filters.sources.length && !state.filters.sources.includes(item.source)) return false;
    if (Number(item.score || 0) < state.filters.minScore) return false;
    if (state.filters.newOnly && !item.is_new) return false;
    if (state.filters.resonanceOnly && !item.is_resonating) return false;
    if (!matchesTimeRange(item)) return false;
    if (!matchesSearch(item)) return false;
    return true;
  });

  filtered.sort((a, b) => {
    switch (state.filters.sort) {
      case "time_desc":
        return toTimestamp(b.last_seen_at || b.analyzed_at) - toTimestamp(a.last_seen_at || a.analyzed_at) || Number(b.score || 0) - Number(a.score || 0);
      case "level_desc":
        return levelRank(b.level) - levelRank(a.level) || Number(b.score || 0) - Number(a.score || 0);
      case "coverage_desc":
        return Number(b.source_count || 0) - Number(a.source_count || 0) || Number(b.score || 0) - Number(a.score || 0);
      case "score_desc":
      default:
        return Number(b.score || 0) - Number(a.score || 0) || toTimestamp(b.last_seen_at || b.analyzed_at) - toTimestamp(a.last_seen_at || a.analyzed_at);
    }
  });

  renderHotspots(filtered, hotspots.length);
}

function updateView(meta) {
  state.meta = meta;
  state.dashboard = meta.dashboard || dashboardFromLegacy(meta);
  $("brandName").textContent = state.dashboard.brand || "HotPulse";
  $("brandSubtitle").textContent = state.dashboard.subtitle || "AI 热点雷达";
  renderStats(state.dashboard);
  renderTerms(state.dashboard);
  renderStatus(meta);
  applyDashboardDefaults(state.dashboard);
  renderFilterControls(state.dashboard);
  applyFilters();
}

async function loadState() {
  const response = await fetch("/api/state");
  const meta = await response.json();
  updateView(meta);
}

async function saveConfig() {
  const terms = $("watchTerms").value
    .split(/\n|,|，/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 20);
  await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: $("query").value.trim(),
      watch_terms: terms,
    }),
  });
  await loadState();
}

async function runAnalysis() {
  const button = $("runNow");
  button.disabled = true;
  button.classList.add("is-loading");
  button.querySelector("span:last-child").textContent = "扫描中";
  try {
    await saveConfig();
    const response = await fetch("/api/run");
    const data = await response.json();
    if (!data.ok) {
      throw new Error(data.error || "扫描失败");
    }
    await loadState();
  } catch (error) {
    $("filterSummary").textContent = "扫描失败";
    $("hotspotList").innerHTML = `
      <article class="empty-state error">
        <h2>扫描失败</h2>
        <p>${escapeHtml(error.message || "请稍后再试")}</p>
      </article>
    `;
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.querySelector("span:last-child").textContent = "立即扫描";
  }
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `${name}Panel`);
  });
}

function bindFilterEvents() {
  $("sortOrder").addEventListener("change", (event) => {
    state.filters.sort = event.target.value;
    applyFilters();
  });
  $("minScore").addEventListener("input", (event) => {
    state.filters.minScore = Number(event.target.value || 0);
    applyFilters();
  });
  $("timeRange").addEventListener("change", (event) => {
    state.filters.timeRange = event.target.value;
    applyFilters();
  });
  $("searchFilter").addEventListener("input", (event) => {
    state.filters.search = event.target.value;
    applyFilters();
  });
  $("newOnly").addEventListener("change", (event) => {
    state.filters.newOnly = event.target.checked;
    applyFilters();
  });
  $("resonanceOnly").addEventListener("change", (event) => {
    state.filters.resonanceOnly = event.target.checked;
    applyFilters();
  });
  $("resetFilters").addEventListener("click", () => {
    applyDashboardDefaults(state.dashboard || {}, true);
    renderFilterControls(state.dashboard || {});
    applyFilters();
  });
  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    const group = target.dataset.filterGroup;
    if (!group) return;
    const collection = new Set(state.filters[group]);
    if (target.checked) collection.add(target.value);
    else collection.delete(target.value);
    state.filters[group] = [...collection];
    renderFilterControls(state.dashboard || {});
    applyFilters();
  });
}

function bindEvents() {
  $("runNow").addEventListener("click", runAnalysis);
  $("searchNow").addEventListener("click", runAnalysis);
  $("saveTerms").addEventListener("click", saveConfig);
  $("detailToggleAll").addEventListener("click", () => {
    state.detailsExpandedAll = !state.detailsExpandedAll;
    applyFilters();
  });
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });
  bindFilterEvents();
  $("enablePush").addEventListener("click", async () => {
    if (!("Notification" in window)) {
      $("pushState").textContent = "浏览器不支持通知";
      return;
    }
    const permission = await Notification.requestPermission();
    $("pushState").textContent = permission === "granted" ? "通知已开启" : "通知未开启";
  });

  const events = new EventSource("/api/events");
  events.addEventListener("notification", (event) => {
    const payload = JSON.parse(event.data).data;
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(payload.title, { body: payload.body });
    }
    loadState();
  });
  events.addEventListener("result", loadState);
}

loadState()
  .then(bindEvents)
  .catch((error) => {
    $("hotspotList").innerHTML = `
      <article class="empty-state error">
        <h2>页面初始化失败</h2>
        <p>${escapeHtml(error.message)}</p>
      </article>
    `;
  });
