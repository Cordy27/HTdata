(function () {
  "use strict";

  const state = {
    data: null,
    news: null,
    activeSection: "ai",
    activeNewsTag: "全部",
    activeNewsSource: "全部",
    charts: {},
    observedCharts: new Set(),
    resizeObserver: null,
    shareDataUrl: "",
    shareConfig: null,
    shareUrl: "",
    previewBriefId: "",
    previewBriefText: "",
    previewBriefSmsText: ""
  };

  const colors = {
    blueDark: "#003f7d",
    blue: "#0076bd",
    cyan: "#0a9bdc",
    teal: "#16a085",
    red: "#e6461f",
    gold: "#f08a24",
    muted: "#5f7895",
    line: "#b7d6f2"
  };

  const palette = [colors.blueDark, colors.cyan, colors.blue, colors.teal, "#6e91b8", colors.gold, colors.red, "#546f91", "#9aaec3"];

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    const accessState = getAccessState();
    if (!accessState.allowed) {
      renderAccessGate(accessState);
      return;
    }
    if (window.lucide) {
      window.lucide.createIcons();
    }
    initSidebarState();
    bindEvents();
    await loadData();
    setupResizeObserver();
    window.addEventListener("resize", resizeCharts);
  }

  function bindEvents() {
    element("sidebarToggle").addEventListener("click", toggleSidebar);
    element("sharePageButton").addEventListener("click", () => openShareModal());
    document.querySelectorAll("[data-share-close]").forEach((button) => {
      button.addEventListener("click", closeShareModal);
    });
    document.querySelectorAll("[data-brief-preview-close]").forEach((button) => {
      button.addEventListener("click", closeBriefPreviewModal);
    });
    element("copyShareLink").addEventListener("click", copyShareLink);
    element("downloadShareImage").addEventListener("click", downloadShareImage);
    element("copyBriefPreviewText").addEventListener("click", copyBriefPreviewText);
    element("copyBriefSmsText").addEventListener("click", copyBriefSmsText);
    element("shareBriefPreviewImage").addEventListener("click", shareBriefPreviewImage);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !element("shareModal").hidden) {
        closeShareModal();
      }
      if (event.key === "Escape" && !element("briefPreviewModal").hidden) {
        closeBriefPreviewModal();
      }
    });
    document.querySelectorAll("[data-section]").forEach((button) => {
      button.addEventListener("click", () => activateSection(button.dataset.section));
    });
    document.querySelectorAll("[data-tab-target]").forEach((button) => {
      button.addEventListener("click", () => activateTab(button));
    });
    document.querySelectorAll("[data-export-block]").forEach((button) => {
      button.addEventListener("click", () => exportBlockCsv(button.dataset.exportBlock));
    });
    document.addEventListener("click", (event) => {
      const briefShareButton = event.target.closest("[data-share-brief-id]");
      if (briefShareButton) {
        openBriefShareModal(briefShareButton.dataset.shareBriefId || "");
        return;
      }
      const briefCopyButton = event.target.closest("[data-copy-brief-id]");
      if (briefCopyButton) {
        copyBriefText(briefCopyButton.dataset.copyBriefId || "", "full", briefCopyButton);
        return;
      }
      const briefPreviewButton = event.target.closest("[data-preview-brief-id]");
      if (briefPreviewButton) {
        openBriefPreviewModal(briefPreviewButton.dataset.previewBriefId || "");
        return;
      }
      const briefCard = event.target.closest("[data-brief-card-id]");
      if (briefCard && !event.target.closest("a, button")) {
        openBriefPreviewModal(briefCard.dataset.briefCardId || "");
        return;
      }
      const button = event.target.closest("[data-news-tag]");
      if (!button) {
        return;
      }
      state.activeNewsTag = button.dataset.newsTag || "全部";
      renderNewsSection();
    });

    element("aiDauRegion").addEventListener("change", renderAiDauChart);
    element("aiAvgRegion").addEventListener("change", renderAiAvgTimeChart);
  }

  async function loadData() {
    try {
      state.data = await window.HTDataSync.fetchPortalData();
      state.news = await window.HTDataSync.fetchNewsData();
      renderAll();
    } catch (error) {
      renderLoadError(error.message);
    }
  }

  function renderAll() {
    renderKpis("aiKpiGrid", state.data.ai.kpis || []);
    renderKpis("beikeKpiGrid", state.data.beike.kpis || []);
    renderAiDauChart();
    renderAiAvgTimeChart();
    renderBeikeCharts();
    renderPageTables();
    renderDetailTables();
    renderNewsSection();
    activateSection(getInitialSection(), { updateUrl: false });
    focusRequestedBrief();
    resizeCharts();
  }

  function renderKpis(id, kpis) {
    const html = kpis.map((item) => {
      const tone = item.change > 0 ? "pos" : item.change < 0 ? "neg" : "neutral";
      const sign = item.change > 0 ? "+" : "";
      const changeText = item.change === null || item.change === undefined
        ? "环比 --"
        : `${sign}${formatNumber(item.change, 2)}%`;
      return `
        <article class="kpi">
          <div class="label">${escapeHtml(item.label)}</div>
          <div class="value">${formatKpiValue(item.value)}<small>${escapeHtml(item.unit || "")}</small></div>
          <div class="note"><span class="change ${tone}">${changeText}</span> ${escapeHtml(item.note || "")}</div>
        </article>
      `;
    }).join("");
    element(id).innerHTML = html || emptyState("暂无可用核心指标。");
  }

  function renderAiDauChart() {
    if (!state.data) {
      return;
    }
    const region = element("aiDauRegion").value;
    renderLineChart({
      id: "aiDauChart",
      records: getAiRecords({ region, metric: "DAU" }),
      groupKey: "product",
      valueName: "DAU",
      yUnit: "百万",
      windowSize: 260
    });
  }

  function renderAiAvgTimeChart() {
    if (!state.data) {
      return;
    }
    const region = element("aiAvgRegion").value;
    renderLineChart({
      id: "aiAvgTimeChart",
      records: getAiRecords({ region, metric: "AvgTime" }),
      groupKey: "product",
      valueName: "人均使用时长",
      yUnit: "分钟",
      windowSize: 260
    });
  }

  function renderBeikeCharts() {
    renderLineChart({
      id: "beikeCoreWauChart",
      records: getBeikeCoreRecords("WAU"),
      groupKey: "app",
      valueName: "WAU",
      yUnit: "万人",
      windowSize: 40
    });
    renderLineChart({
      id: "beikeCoreDurationChart",
      records: getBeikeCoreRecords("Duration"),
      groupKey: "app",
      valueName: "使用总时长",
      yUnit: "万分钟",
      windowSize: 40
    });
    renderBeikeCityChart();
    renderYearlyLineChart("beikeYearlyWauChart", "WAU", "万人");
    renderYearlyLineChart("beikeYearlyAvgTimeChart", "AvgTime", "分钟");
  }

  function renderBeikeCityChart() {
    const latest = (state.data.beike.cityLatest || [])
      .filter((item) => item.metric === "WAU")
      .sort((a, b) => b.value - a.value);
    const chart = getChart("beikeCityChart");
    if (!chart) {
      return;
    }
    chart.setOption({
      color: [colors.cyan],
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      toolbox: buildToolbox(true),
      grid: { left: 64, right: 44, top: 28, bottom: 36 },
      xAxis: {
        type: "value",
        axisLabel: { color: colors.muted },
        splitLine: { lineStyle: { color: "#e4eff9" } }
      },
      yAxis: {
        type: "category",
        data: latest.map((item) => item.city),
        axisLabel: { color: colors.muted },
        axisLine: { lineStyle: { color: colors.line } }
      },
      dataZoom: buildVerticalZoom(latest.length, 8),
      series: [{
        name: "WAU",
        type: "bar",
        data: latest.map((item) => round(item.value, 2)),
        itemStyle: { borderRadius: [0, 4, 4, 0] }
      }]
    }, true);
  }

  function renderYearlyLineChart(id, metric, yUnit) {
    const records = (state.data.beike.yearlyRecords || []).filter((item) => item.metric === metric);
    renderLineChart({
      id,
      records,
      groupKey: "year",
      valueName: metricLabel(metric),
      yUnit,
      windowSize: 40,
      xFormatter: monthDay
    });
  }

  function renderPageTables() {
    const aiBlocks = state.data.ai.blocks || {};
    const beikeBlocks = state.data.beike.blocks || {};
    renderBlockTable("aiPageDauTable", "aiPageDauCaption", aiBlocks.dau);
    renderBlockTable("aiPageAvgTimeTable", "aiPageAvgTimeCaption", aiBlocks.avgTime);
    renderBlockTable("beikePageCoreWauTable", "beikePageCoreWauCaption", getDisplayBlock("beike.coreWau", beikeBlocks.coreWau));
    renderBlockTable("beikePageCoreDurationTable", "beikePageCoreDurationCaption", getDisplayBlock("beike.coreDuration", beikeBlocks.coreDuration));
    renderBlockTable("beikePageCityWauTable", "beikePageCityWauCaption", getDisplayBlock("beike.cityWau", beikeBlocks.cityWau));
    renderBlockTable("beikePageYearlyWauTable", "beikePageYearlyWauCaption", getDisplayBlock("beike.yearlyWau", beikeBlocks.yearlyWau));
    renderBlockTable("beikePageYearlyAvgTimeTable", "beikePageYearlyAvgTimeCaption", getDisplayBlock("beike.yearlyAvgTime", beikeBlocks.yearlyAvgTime));
  }

  function renderDetailTables() {
    const aiBlocks = state.data.ai.blocks || {};
    const beikeBlocks = state.data.beike.blocks || {};
    renderBlockTable("aiDauTable", "aiDauCaption", aiBlocks.dau);
    renderBlockTable("aiAvgTimeTable", "aiAvgTimeCaption", aiBlocks.avgTime);
    renderBlockTable("beikeCoreWauTable", "beikeCoreWauCaption", getDisplayBlock("beike.coreWau", beikeBlocks.coreWau));
    renderBlockTable("beikeCoreDurationTable", "beikeCoreDurationCaption", getDisplayBlock("beike.coreDuration", beikeBlocks.coreDuration));
    renderBlockTable("beikeCityWauTable", "beikeCityWauCaption", getDisplayBlock("beike.cityWau", beikeBlocks.cityWau));
    renderBlockTable("beikeYearlyWauTable", "beikeYearlyWauCaption", getDisplayBlock("beike.yearlyWau", beikeBlocks.yearlyWau));
    renderBlockTable("beikeYearlyAvgTimeTable", "beikeYearlyAvgTimeCaption", getDisplayBlock("beike.yearlyAvgTime", beikeBlocks.yearlyAvgTime));
  }

  function renderNewsSection() {
    const news = state.news || { meta: {}, groups: [], sources: [], items: [] };
    const items = news.items || [];
    renderNewsBriefTimeline(news.briefs || []);
    renderNewsTabs(news.groups || []);
    renderNewsSourceRail(news.sources || []);
    renderNewsList(getFilteredNewsItems(items));
    const meta = news.meta || {};
    element("newsUpdatedAt").textContent = meta.lastUpdated
      ? `最近更新：${meta.lastUpdated}，统计区间：近 ${meta.lookbackDays || 7} 天`
      : "最近更新：--";
  }

  function renderNewsBriefTimeline(briefs) {
    const container = element("newsBriefTimeline");
    const timeline = (briefs || []).slice(-3).sort((a, b) => String(a.runAt || "").localeCompare(String(b.runAt || "")));
    if (!timeline.length) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }
    container.hidden = false;
    container.innerHTML = `
      <div class="news-brief-head">
        <div>
          <span class="panel-kicker">增量快报</span>
          <h4>最近三次运行摘要</h4>
        </div>
        <span>旧 → 新</span>
      </div>
      <div class="news-brief-track">
        ${timeline.map((brief, index) => {
          const previewText = formatBriefForwardText(brief, { maxItems: 2, includeLinks: false, compact: true });
          return `
            <article class="news-brief-card" data-brief-card-id="${escapeHtml(brief.id || "")}">
              <div class="news-brief-index">${index + 1}</div>
              <time>${escapeHtml(compactDateTime(brief.runAt || ""))}</time>
              <h5>${escapeHtml(brief.title || "增量信息快报")}</h5>
              <pre class="news-brief-forward-preview">${escapeHtml(previewText)}</pre>
              <footer class="news-brief-actions">
                <button class="ghost-button news-brief-action" data-preview-brief-id="${escapeHtml(brief.id || "")}" type="button">
                  <i data-lucide="eye"></i><span>预览</span>
                </button>
                <button class="ghost-button news-brief-action" data-copy-brief-id="${escapeHtml(brief.id || "")}" type="button">
                  <i data-lucide="copy"></i><span>复制文本</span>
                </button>
                <button class="ghost-button news-brief-action" data-share-brief-id="${escapeHtml(brief.id || "")}" type="button">
                  <i data-lucide="image"></i><span>分享图片</span>
                </button>
              </footer>
            </article>
          `;
        }).join("")}
      </div>
    `;
    if (window.lucide) {
      window.lucide.createIcons();
    }
  }

  function renderNewsTabs(groups) {
    const tabs = [{ tag: "全部", count: (state.news?.items || []).length }, ...groups];
    if (!tabs.some((item) => item.tag === state.activeNewsTag)) {
      state.activeNewsTag = "全部";
    }
    element("newsTagTabs").innerHTML = tabs.map((item) => `
      <button class="tab-button ${item.tag === state.activeNewsTag ? "active" : ""}" data-news-tag="${escapeHtml(item.tag)}" type="button">
        ${escapeHtml(item.tag)}<span>${Number(item.count || 0).toLocaleString("zh-CN")}</span>
      </button>
    `).join("");
  }

  function renderNewsSourceRail(sources) {
    const sourceItems = [
      { sourceName: "全部", count: (state.news?.items || []).length },
      ...sources
    ];
    if (!sourceItems.some((item) => item.sourceName === state.activeNewsSource)) {
      state.activeNewsSource = "全部";
    }
    const html = sourceItems.map((item) => `
      <button class="source-chip ${item.sourceName === state.activeNewsSource ? "active" : ""}" data-news-source="${escapeHtml(item.sourceName)}" type="button">
        <span>${escapeHtml(item.sourceName)}</span>
        <strong>${Number(item.count || 0).toLocaleString("zh-CN")}</strong>
      </button>
    `).join("");
    element("newsSourceList").innerHTML = html || emptyState("暂无来源分布。");
    element("newsSourceList").querySelectorAll("[data-news-source]").forEach((button) => {
      button.addEventListener("click", () => {
        state.activeNewsSource = button.dataset.newsSource || "全部";
        renderNewsSection();
      });
    });
  }

  function getFilteredNewsItems(items) {
    return items.filter((item) => {
      const tagMatched = state.activeNewsTag === "全部" || (item.tags || []).includes(state.activeNewsTag);
      const sourceMatched = state.activeNewsSource === "全部" || item.sourceName === state.activeNewsSource;
      return tagMatched && sourceMatched;
    });
  }

  function renderNewsList(items) {
    if (!items.length) {
      element("newsList").innerHTML = emptyState("暂无匹配资讯。");
      return;
    }
    element("newsList").innerHTML = items.map((item) => {
      const timeText = item.publishedAt || item.latestSeenAt || item.collectedAt || "";
      const rankText = item.rank ? `#${item.rank}` : item.sourceType || "RSS";
      const terms = (item.matchedTerms || []).slice(0, 4);
      const scoreText = item.aiScore !== null && item.aiScore !== undefined ? `重要度 ${formatNumber(item.aiScore, 0)}` : "";
      return `
        <article class="news-card">
          <header class="news-card-head">
            <span class="news-source">${escapeHtml(item.sourceName || "--")}</span>
            <span class="news-rank">${escapeHtml(rankText)}</span>
            ${scoreText ? `<span class="news-score">${escapeHtml(scoreText)}</span>` : ""}
            <time>${escapeHtml(compactDateTime(timeText))}</time>
          </header>
          <a class="news-title" href="${escapeHtml(item.url || "#")}" target="_blank" rel="noopener noreferrer">
            ${escapeHtml(item.title || "--")}
          </a>
          ${item.summary ? `<p>${escapeHtml(item.summary)}</p>` : ""}
          <footer class="news-card-tags">
            ${(item.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
            ${terms.map((term) => `<em>${escapeHtml(term)}</em>`).join("")}
          </footer>
        </article>
      `;
    }).join("");
  }

  function renderBlockTable(tableId, captionId, block) {
    if (!block) {
      renderTable(tableId, []);
      element(captionId).textContent = "";
      return;
    }
    const rows = (block.rows || []).map((row) => {
      const normalized = {};
      (block.columns || Object.keys(row)).forEach((key) => {
        normalized[key] = formatTableValue(row[key], key);
      });
      return normalized;
    });
    renderTable(tableId, rows, block.columns);
    const rowCount = (block.rows || []).length;
    const seriesCount = (block.entityColumns || block.dateColumns || []).length || Math.max((block.columns || []).length - 1, 0);
    const seriesLabel = block.orientation === "dateRows" ? "项序列" : "个时间字段";
    element(captionId).textContent = `${rowCount.toLocaleString("zh-CN")} 条记录，${seriesCount.toLocaleString("zh-CN")} ${seriesLabel}，单位：${block.unit || "--"}`;
  }

  function renderLineChart({ id, records, groupKey, valueName, yUnit, windowSize = 80, xFormatter }) {
    const chart = getChart(id);
    if (!chart) {
      return;
    }
    const dates = Array.from(new Set(records.map((item) => item.date))).sort();
    const groups = Array.from(new Set(records.map((item) => item[groupKey]))).sort((a, b) => String(a).localeCompare(String(b), "zh-CN"));
    if (!dates.length || !groups.length) {
      chart.setOption({
        title: { text: "暂无可用数据", left: "center", top: "middle", textStyle: { color: colors.muted, fontSize: 14 } },
        xAxis: { show: false },
        yAxis: { show: false },
        series: []
      }, true);
      return;
    }
    const xLabels = xFormatter ? dates.map(xFormatter) : dates;
    const series = groups.map((group, index) => {
      const byDate = new Map(records.filter((item) => item[groupKey] === group).map((item) => [item.date, item.value]));
      return {
        name: String(group),
        type: "line",
        smooth: true,
        symbolSize: 4,
        connectNulls: false,
        lineStyle: { width: 2 },
        data: dates.map((date) => byDate.has(date) ? round(byDate.get(date), 4) : null),
        color: palette[index % palette.length]
      };
    });
    chart.setOption({
      color: palette,
      tooltip: { trigger: "axis" },
      toolbox: buildToolbox(false),
      legend: { top: 0, type: "scroll", textStyle: { color: colors.muted } },
      grid: { left: 56, right: 24, top: 48, bottom: 76 },
      xAxis: {
        type: "category",
        data: xLabels,
        axisLabel: { color: colors.muted, hideOverlap: true },
        axisLine: { lineStyle: { color: colors.line } }
      },
      yAxis: {
        type: "value",
        name: yUnit,
        nameTextStyle: { color: colors.muted },
        axisLabel: { color: colors.muted },
        splitLine: { lineStyle: { color: "#e4eff9" } }
      },
      dataZoom: buildHorizontalZoom(dates.length, windowSize),
      series,
      aria: { enabled: true, description: valueName }
    }, true);
  }

  function getAiRecords({ region, metric }) {
    return (state.data.ai.records || []).filter((item) => item.region === region && item.metric === metric);
  }

  function getBeikeCoreRecords(metric) {
    return (state.data.beike.coreRecords || []).filter((item) => item.metric === metric);
  }

  function renderTable(id, rows, explicitHeaders) {
    const table = element(id);
    if (!rows.length) {
      table.innerHTML = `<tbody><tr><td>${emptyState("暂无匹配样本。")}</td></tr></tbody>`;
      return;
    }
    const headers = explicitHeaders && explicitHeaders.length ? explicitHeaders : Object.keys(rows[0]);
    table.innerHTML = `
      <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr>${headers.map((header) => tableCell(row[header], header)).join("")}</tr>
        `).join("")}
      </tbody>
    `;
  }

  function tableCell(value, header) {
    const text = value ?? "";
    const cls = valueClass(text, header);
    return `<td class="${cls}">${escapeHtml(text)}</td>`;
  }

  function valueClass(value, header) {
    if (!["环比", "WoW", "YoY"].includes(header)) {
      return "";
    }
    return typeof value === "string" && value.startsWith("+") ? "pos" : typeof value === "string" && value.startsWith("-") ? "neg" : "";
  }

  function activateSection(section, options = {}) {
    state.activeSection = section;
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.section === section);
    });
    document.querySelectorAll(".section-pane").forEach((pane) => {
      pane.classList.toggle("active", pane.dataset.pane === section);
    });
    updateShareButton(section);
    if (options.updateUrl !== false) {
      syncSectionUrl(section);
    }
    setTimeout(resizeCharts, 0);
  }

  function activateTab(button) {
    const group = button.closest("[data-tab-group]");
    const panelName = button.dataset.tabTarget;
    if (!group || !panelName) {
      return;
    }
    group.querySelectorAll("[data-tab-target]").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    const scope = group.closest(".tabbed-panel") || document;
    scope.querySelectorAll("[data-tab-panel]").forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.tabPanel === panelName);
    });
    setTimeout(resizeCharts, 0);
  }

  function getInitialSection() {
    const requested = new URLSearchParams(window.location.search).get("section");
    return ["ai", "beike", "news", "detail"].includes(requested) ? requested : "ai";
  }

  function syncSectionUrl(section) {
    if (!["ai", "beike", "news", "detail"].includes(section)) {
      return;
    }
    const url = new URL(window.location.href);
    url.searchParams.set("section", section);
    if (section !== "news") {
      url.searchParams.delete("brief");
    }
    window.history.replaceState({}, "", url.toString());
  }

  function updateShareButton(section) {
    const button = element("sharePageButton");
    if (!button) {
      return;
    }
    const hidden = section === "news";
    button.hidden = hidden;
    button.style.display = hidden ? "none" : "";
    button.setAttribute("aria-hidden", hidden ? "true" : "false");
    button.tabIndex = hidden ? -1 : 0;
    if (section === "news") {
      return;
    }
    const label = {
      ai: "分享 AI 产品",
      beike: "分享贝壳",
      detail: "分享明细"
    }[section] || "分享";
    const text = button.querySelector("span");
    if (text) {
      text.textContent = label;
    }
  }

  function initSidebarState() {
    const collapsed = window.localStorage.getItem("htSidebarCollapsed") === "1";
    setSidebarCollapsed(collapsed);
  }

  function toggleSidebar() {
    setSidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
  }

  function setSidebarCollapsed(collapsed) {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    window.localStorage.setItem("htSidebarCollapsed", collapsed ? "1" : "0");
    const button = element("sidebarToggle");
    if (!button) {
      return;
    }
    const label = collapsed ? "展开侧边栏" : "收起侧边栏";
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
    button.innerHTML = `<i data-lucide="${collapsed ? "panel-left-open" : "panel-left-close"}"></i>`;
    if (window.lucide) {
      window.lucide.createIcons();
    }
    setTimeout(resizeCharts, 220);
  }

  function exportBlockCsv(blockKey) {
    const block = getDisplayBlock(blockKey, getBlockByKey(blockKey));
    if (!block) {
      return;
    }
    const csvRows = [];
    const rows = block.rows || [];
    const headers = block.columns || (rows[0] ? Object.keys(rows[0]) : []);
    csvRows.push([block.title || "指标明细"]);
    csvRows.push(headers);
    rows.forEach((row) => csvRows.push(headers.map((header) => formatTableValue(row[header], header))));
    const csv = csvRows.map((row) => row.map(csvCell).join(",")).join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${safeFileName(block.title || "指标明细")}_${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function getBlockByKey(blockKey) {
    const aiBlocks = state.data.ai.blocks || {};
    const beikeBlocks = state.data.beike.blocks || {};
    return {
      "ai.dau": aiBlocks.dau,
      "ai.avgTime": aiBlocks.avgTime,
      "beike.coreWau": beikeBlocks.coreWau,
      "beike.coreDuration": beikeBlocks.coreDuration,
      "beike.cityWau": beikeBlocks.cityWau,
      "beike.yearlyWau": beikeBlocks.yearlyWau,
      "beike.yearlyAvgTime": beikeBlocks.yearlyAvgTime
    }[blockKey];
  }

  function getDisplayBlock(blockKey, block) {
    if (!block || !blockKey || !blockKey.startsWith("beike.")) {
      return block;
    }
    return transposeDateBlock(block);
  }

  function transposeDateBlock(block) {
    const labelKey = block.label || (block.columns || [])[0];
    const dateColumns = block.dateColumns || (block.columns || []).slice(1).filter(isIsoDateKey);
    const entityColumns = (block.rows || []).map((row) => row[labelKey]).filter((value) => value !== undefined && value !== null && value !== "");
    const rows = dateColumns.map((dateText) => {
      const row = { 日期: dateText };
      (block.rows || []).forEach((sourceRow) => {
        const entity = sourceRow[labelKey];
        if (entity !== undefined && entity !== null && entity !== "") {
          row[entity] = sourceRow[dateText];
        }
      });
      return row;
    });
    return {
      ...block,
      columns: ["日期", ...entityColumns],
      rows,
      entityColumns,
      orientation: "dateRows"
    };
  }

  function renderLoadError(message) {
    ["aiKpiGrid", "beikeKpiGrid"].forEach((id) => {
      const node = document.getElementById(id);
      if (node) {
        node.innerHTML = emptyState(message);
      }
    });
  }

  function getAccessState() {
    const config = window.HT_ACCESS_CONFIG || {};
    const expected = normalizeAccessSegment(config.accessPath || "");
    const segments = window.location.pathname.split("/").filter(Boolean).map(normalizeAccessSegment);
    const routeSegments = window.location.hostname.endsWith(".github.io") && segments.length > 0
      ? segments.slice(1)
      : segments;
    const current = routeSegments.length === 1 ? routeSegments[0] : "";
    return {
      allowed: Boolean(expected && current === expected),
      expected,
      current,
      portalName: config.portalName || "华泰互联网",
      gateTitle: config.gateTitle || "欢迎访问数据门户",
      gateMessage: config.gateMessage || "请联系管理员获取最新访问链接。"
    };
  }

  function normalizeAccessSegment(value) {
    return String(value || "").trim().replace(/^\/+|\/+$/g, "");
  }

  function renderAccessGate(accessState) {
    document.body.className = "access-body";
    document.body.innerHTML = `
      <main class="access-gate" aria-label="访问提示">
        <section class="access-panel">
          <div class="access-brand">
            <div class="brand-mark">HT</div>
            <div>
              <span>${escapeHtml(accessState.portalName)}</span>
              <strong>研究数据门户</strong>
            </div>
          </div>
          <div class="access-icon" aria-hidden="true"><i data-lucide="lock-keyhole"></i></div>
          <h1>${escapeHtml(accessState.gateTitle)}</h1>
          <p>${escapeHtml(accessState.gateMessage)}</p>
          <div class="access-actions">
            <button class="primary-button" id="copyAccessUrl" type="button">
              <i data-lucide="copy"></i><span>复制当前地址</span>
            </button>
            <button class="ghost-button" id="reloadAccessPage" type="button">
              <i data-lucide="refresh-cw"></i><span>刷新</span>
            </button>
          </div>
          <div class="access-note" id="accessCopyNote">如需开通访问，请将当前地址发送给管理员核对。</div>
        </section>
      </main>
    `;
    if (window.lucide) {
      window.lucide.createIcons();
    }
    document.getElementById("copyAccessUrl").addEventListener("click", async () => {
      const note = document.getElementById("accessCopyNote");
      try {
        await navigator.clipboard.writeText(window.location.href);
        note.textContent = "当前地址已复制。";
      } catch (error) {
        note.textContent = "复制失败，请手动复制浏览器地址栏。";
      }
    });
    document.getElementById("reloadAccessPage").addEventListener("click", () => {
      window.location.reload();
    });
  }

  async function openBriefShareModal(briefId) {
    const config = getBriefShareConfig(briefId);
    if (!config) {
      return;
    }
    await openShareModal(config);
  }

  function openBriefPreviewModal(briefId) {
    const brief = findBriefById(briefId);
    if (!brief) {
      return;
    }
    const modal = element("briefPreviewModal");
    const text = formatBriefForwardText(brief);
    const smsText = formatBriefSmsText(brief);
    state.previewBriefId = brief.id || briefId;
    state.previewBriefText = text;
    state.previewBriefSmsText = smsText;
    element("briefPreviewTitle").textContent = brief.title || "资讯快报";
    element("briefPreviewMeta").textContent = `${brief.runAt || "--"} · ${brief.selectedCount || (brief.items || []).length || 0} 条入选`;
    element("briefPreviewText").value = text;
    modal.hidden = false;
    document.body.classList.add("modal-open");
    if (window.lucide) {
      window.lucide.createIcons();
    }
    setTimeout(() => element("briefPreviewText").focus(), 30);
  }

  function closeBriefPreviewModal() {
    element("briefPreviewModal").hidden = true;
    if (element("shareModal").hidden) {
      document.body.classList.remove("modal-open");
    }
  }

  async function copyBriefPreviewText() {
    await copyTextToClipboard(state.previewBriefText || "", element("copyBriefPreviewText"), "复制全文");
  }

  async function copyBriefSmsText() {
    await copyTextToClipboard(state.previewBriefSmsText || "", element("copyBriefSmsText"), "复制短信版");
  }

  async function copyBriefText(briefId, mode = "full", button = null) {
    const brief = findBriefById(briefId);
    if (!brief) {
      return;
    }
    const text = mode === "sms" ? formatBriefSmsText(brief) : formatBriefForwardText(brief);
    await copyTextToClipboard(text, button, button ? button.innerText.trim() : "复制文本");
  }

  async function shareBriefPreviewImage() {
    const briefId = state.previewBriefId;
    closeBriefPreviewModal();
    await openBriefShareModal(briefId);
  }

  async function copyTextToClipboard(text, button, originalLabel) {
    if (!text) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      if (button) {
        setButtonLabel(button, "已复制");
        setTimeout(() => setButtonLabel(button, originalLabel), 1400);
      }
    } catch (error) {
      if (button) {
        setButtonLabel(button, "复制失败");
        setTimeout(() => setButtonLabel(button, originalLabel), 1400);
      }
    }
  }

  function setButtonLabel(button, label) {
    const text = button?.querySelector("span");
    if (text) {
      text.textContent = label;
    }
  }

  async function openShareModal(configOverride = null) {
    const modal = element("shareModal");
    const canvas = element("shareCanvas");
    const config = configOverride && configOverride.section ? configOverride : getShareConfig(state.activeSection);
    const shareUrl = config.shareUrl || buildShareUrl(config.section);
    state.shareConfig = config;
    state.shareUrl = shareUrl;
    state.shareDataUrl = "";
    modal.hidden = false;
    document.body.classList.add("modal-open");
    element("shareDialogTitle").textContent = `生成${config.shortTitle}图片`;
    element("shareLinkText").textContent = shareUrl;
    drawPosterLoading(canvas, config, shareUrl);
    if (window.lucide) {
      window.lucide.createIcons();
    }
    await nextFrame();
    resizeCharts();
    await nextFrame();
    try {
      await renderSharePoster(canvas, config, shareUrl);
      state.shareDataUrl = canvas.toDataURL("image/png");
    } catch (error) {
      drawPosterError(canvas, config, error, shareUrl);
      state.shareDataUrl = "";
    }
  }

  function closeShareModal() {
    element("shareModal").hidden = true;
    document.body.classList.remove("modal-open");
  }

  async function copyShareLink() {
    const url = state.shareUrl || buildShareUrl(state.activeSection);
    try {
      await navigator.clipboard.writeText(url);
      element("shareLinkText").textContent = "链接已复制：" + url;
    } catch (error) {
      element("shareLinkText").textContent = "复制失败，请手动复制：" + url;
    }
  }

  function downloadShareImage() {
    const canvas = element("shareCanvas");
    const dataUrl = state.shareDataUrl || canvas.toDataURL("image/png");
    const link = document.createElement("a");
    const config = state.shareConfig || getShareConfig(state.activeSection);
    link.href = dataUrl;
    link.download = `${safeFileName(config.shortTitle)}_${new Date().toISOString().slice(0, 10)}.png`;
    link.click();
  }

  function buildShareUrl(section, options = {}) {
    const url = new URL(window.location.href);
    const routeSection = section === "newsBrief" ? "news" : section;
    url.searchParams.set("section", routeSection);
    if (options.briefId) {
      url.searchParams.set("brief", options.briefId);
    } else {
      url.searchParams.delete("brief");
    }
    return url.toString();
  }

  function getBriefShareConfig(briefId) {
    const brief = findBriefById(briefId);
    if (!brief) {
      return null;
    }
    return {
      section: "newsBrief",
      shortTitle: brief.title || "资讯快报",
      title: brief.title || "增量资讯快报",
      subtitle: "华泰互联网 · 资讯快报",
      headerLabel: "快报摘要",
      qrLabel: "扫码查看快报",
      footerText: "信息来源：公开新闻源；快报由模型基于增量新闻生成，仅用于信息跟踪。",
      theme: "#b1121b",
      accent: colors.blueDark,
      dateText: brief.runAt || state.news?.meta?.lastUpdated || formatToday(),
      brief,
      shareUrl: buildShareUrl("news", { briefId: brief.id || briefId })
    };
  }

  function findBriefById(briefId) {
    const id = String(briefId || "");
    return (state.news?.briefs || []).find((brief) => String(brief.id || "") === id);
  }

  function getShareConfig(section) {
    const dateText = state.data?.meta?.lastUpdated || state.news?.meta?.lastUpdated || formatToday();
    const configs = {
      ai: {
        section: "ai",
        shortTitle: "AI 产品",
        title: "AI 产品核心指标",
        subtitle: "华泰互联网 · 数据监测",
        theme: colors.blueDark,
        accent: colors.red,
        dateText,
        kpis: state.data?.ai?.kpis || [],
        charts: [
          { id: "aiDauChart", title: "ChatGPT 与 Gemini DAU" },
          { id: "aiAvgTimeChart", title: "ChatGPT 与 Gemini 人均使用时长" }
        ]
      },
      beike: {
        section: "beike",
        shortTitle: "贝壳",
        title: "贝壳核心指标",
        subtitle: "华泰互联网 · 数据监测",
        theme: colors.blueDark,
        accent: colors.red,
        dateText,
        kpis: state.data?.beike?.kpis || [],
        charts: [
          { id: "beikeCoreWauChart", title: "核心 App WAU" },
          { id: "beikeCoreDurationChart", title: "核心 App 使用总时长" },
          { id: "beikeCityChart", title: "贝壳找房城市 WAU" },
          { id: "beikeYearlyWauChart", title: "贝壳找房历年 WAU" },
          { id: "beikeYearlyAvgTimeChart", title: "贝壳找房历年人均单日使用时长" }
        ]
      },
      news: {
        section: "news",
        shortTitle: "行业资讯",
        title: "互联网行业资讯快报",
        subtitle: "华泰互联网 · 新闻聚合",
        headerLabel: "页面摘要",
        qrLabel: "扫码查看页面",
        theme: "#b1121b",
        accent: colors.blueDark,
        dateText: state.news?.meta?.lastUpdated || dateText,
        newsItems: getFilteredNewsItems(state.news?.items || []),
        briefs: state.news?.briefs || [],
        groups: state.news?.groups || [],
        sources: state.news?.sources || []
      },
      detail: {
        section: "detail",
        shortTitle: "指标明细",
        title: "指标明细",
        subtitle: "华泰互联网 · 数据监测",
        theme: colors.blueDark,
        accent: colors.red,
        dateText,
        kpis: [...(state.data?.ai?.kpis || []).slice(0, 2), ...(state.data?.beike?.kpis || []).slice(0, 2)],
        charts: [
          { id: "aiDauChart", title: "AI 产品 DAU" },
          { id: "beikeCoreWauChart", title: "贝壳核心 App WAU" }
        ]
      }
    };
    return configs[section] || configs.ai;
  }

  async function renderSharePoster(canvas, config, shareUrl) {
    const width = 1080;
    const chartCount = (config.charts || []).length;
    const chartColumns = getPosterChartColumns(config);
    const chartHeight = chartColumns === 2 ? (config.section === "beike" ? 270 : 292) : (config.section === "beike" ? 300 : 330);
    const chartRows = Math.ceil(chartCount / chartColumns);
    const height = config.section === "news"
      ? 1760
      : config.section === "newsBrief"
        ? getNewsBriefPosterHeight(config)
        : Math.max(1180, 470 + chartRows * (chartHeight + 34) + 150);
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    drawPosterBase(ctx, width, height, config);
    drawPosterHeader(ctx, config, shareUrl, width);
    if (config.section === "news") {
      drawNewsPoster(ctx, config, width, height);
    } else if (config.section === "newsBrief") {
      drawNewsBriefPoster(ctx, config, width, height);
    } else {
      await drawDataPoster(ctx, config, width, height, chartHeight, chartColumns);
    }
    drawPosterFooter(ctx, config, width, height);
  }

  function drawPosterLoading(canvas, config, shareUrl = buildShareUrl(state.activeSection)) {
    canvas.width = 1080;
    canvas.height = 760;
    const ctx = canvas.getContext("2d");
    drawPosterBase(ctx, canvas.width, canvas.height, config);
    drawPosterHeader(ctx, config, shareUrl, canvas.width);
    ctx.fillStyle = "#5f7895";
    ctx.font = posterFont(26, 600);
    ctx.fillText("正在生成分享图片...", 58, 360);
  }

  function drawPosterError(canvas, config, error, shareUrl = buildShareUrl(state.activeSection)) {
    const ctx = canvas.getContext("2d");
    drawPosterBase(ctx, canvas.width, canvas.height, config);
    drawPosterHeader(ctx, config, shareUrl, canvas.width);
    ctx.fillStyle = colors.red;
    ctx.font = posterFont(24, 700);
    ctx.fillText("图片生成失败", 58, 360);
    ctx.fillStyle = "#5f7895";
    ctx.font = posterFont(20, 400);
    drawWrappedText(ctx, error?.message || "请刷新页面后重试。", 58, 402, 900, 30, 3);
  }

  function drawPosterBase(ctx, width, height, config) {
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = config.theme;
    ctx.lineWidth = 22;
    ctx.strokeRect(11, 11, width - 22, height - 22);
    ctx.fillStyle = config.theme;
    ctx.fillRect(22, 22, width - 44, 18);
    ctx.fillRect(22, height - 58, width - 44, 36);
  }

  function drawPosterHeader(ctx, config, shareUrl, width) {
    const x = 58;
    ctx.fillStyle = config.theme;
    ctx.font = posterFont(28, 700);
    ctx.fillText(config.subtitle, x, 88);
    ctx.fillStyle = "#1b1f23";
    ctx.font = posterSerifFont(48, 800);
    ctx.fillText(fitText(ctx, config.title, width - 300), x, 144);
    ctx.fillStyle = "#5f7895";
    ctx.font = posterFont(20, 500);
    ctx.fillText(`更新时间：${config.dateText || "--"}`, x, 184);
    ctx.fillStyle = config.theme;
    ctx.fillRect(x, 214, width - 116, 34);
    ctx.fillStyle = "#ffffff";
    ctx.font = posterFont(20, 700);
    ctx.fillText(config.headerLabel || "页面摘要", x + 14, 237);
    drawQrCode(ctx, shareUrl, width - 180, 64, 112);
    ctx.fillStyle = "#5f7895";
    ctx.font = posterFont(15, 500);
    ctx.fillText(config.qrLabel || "扫码查看页面", width - 184, 194);
  }

  async function drawDataPoster(ctx, config, width, height, chartHeight, chartColumns) {
    const x = 58;
    let y = 280;
    const contentWidth = width - 116;
    drawKpiPosterGrid(ctx, (config.kpis || []).slice(0, 4), x, y, width - 116, config);
    y += 178;
    const charts = config.charts || [];
    const gap = 18;
    const columns = Math.max(1, chartColumns || 1);
    const cardWidth = columns === 1 ? contentWidth : (contentWidth - gap) / 2;
    for (let index = 0; index < charts.length; index += 1) {
      const col = index % columns;
      const row = Math.floor(index / columns);
      const left = x + col * (cardWidth + gap);
      const top = y + row * (chartHeight + 34);
      await drawChartPosterCard(ctx, charts[index], left, top, cardWidth, chartHeight, config);
    }
    if (!charts.length) {
      drawEmptyPosterBlock(ctx, "暂无可用图表。", x, y, width - 116, 220);
    }
  }

  function getPosterChartColumns(config) {
    const count = (config.charts || []).length;
    return count >= 2 && ["ai", "beike", "detail"].includes(config.section) ? 2 : 1;
  }

  function getNewsBriefPosterHeight(config) {
    const itemCount = (config.brief?.items || []).length;
    return Math.max(1260, 580 + itemCount * 176 + 150);
  }

  function drawNewsPoster(ctx, config, width) {
    const x = 58;
    let y = 282;
    drawNewsStats(ctx, config, x, y, width - 116);
    y += 156;
    y = drawBriefPosterSummary(ctx, config, x, y, width - 116);
    ctx.fillStyle = config.theme;
    ctx.font = posterFont(22, 800);
    ctx.fillText("重点新闻", x, y);
    y += 18;
    const items = (config.newsItems || []).slice(0, 9);
    if (!items.length) {
      drawEmptyPosterBlock(ctx, "暂无匹配资讯。", x, y + 18, width - 116, 220);
      return;
    }
    items.forEach((item, index) => {
      const rowTop = y + index * 112;
      const stripe = index % 2 === 0 ? "#fff3f1" : "#ffffff";
      ctx.fillStyle = stripe;
      ctx.fillRect(x, rowTop + 16, width - 116, 92);
      ctx.fillStyle = config.theme;
      ctx.fillRect(x, rowTop + 16, 7, 92);
      ctx.fillStyle = "#1b1f23";
      ctx.font = posterFont(21, 800);
      drawWrappedText(ctx, item.title || "--", x + 20, rowTop + 46, width - 168, 27, 2);
      ctx.fillStyle = "#5f7895";
      ctx.font = posterFont(16, 500);
      const tags = (item.tags || []).slice(0, 2).join(" / ");
      const meta = `${item.sourceName || "--"}  ${compactDateTime(item.publishedAt || item.latestSeenAt || item.collectedAt)}${tags ? "  " + tags : ""}`;
      ctx.fillText(meta, x + 20, rowTop + 96);
    });
  }

  function drawBriefPosterSummary(ctx, config, x, y, width) {
    const briefs = (config.briefs || []).slice(-3).sort((a, b) => String(a.runAt || "").localeCompare(String(b.runAt || "")));
    if (!briefs.length) {
      return y;
    }
    ctx.fillStyle = config.theme;
    ctx.font = posterFont(22, 800);
    ctx.fillText("增量快报", x, y);
    y += 18;
    const cardWidth = (width - 24) / 3;
    briefs.forEach((brief, index) => {
      const left = x + index * (cardWidth + 12);
      ctx.fillStyle = "#fff7f6";
      ctx.fillRect(left, y + 14, cardWidth, 160);
      ctx.strokeStyle = "#efc3bd";
      ctx.lineWidth = 1;
      ctx.strokeRect(left, y + 14, cardWidth, 160);
      ctx.fillStyle = config.theme;
      ctx.font = posterFont(15, 800);
      ctx.fillText(compactDateTime(brief.runAt || ""), left + 14, y + 42);
      ctx.fillStyle = "#1b1f23";
      ctx.font = posterFont(18, 800);
      drawWrappedText(ctx, brief.title || "增量信息快报", left + 14, y + 72, cardWidth - 28, 23, 2);
      ctx.fillStyle = "#5f7895";
      ctx.font = posterFont(15, 500);
      drawWrappedText(ctx, brief.summary || "--", left + 14, y + 122, cardWidth - 28, 21, 2);
    });
    return y + 204;
  }

  function drawNewsBriefPoster(ctx, config, width) {
    const x = 58;
    const contentWidth = width - 116;
    const brief = config.brief || {};
    let y = 286;
    ctx.fillStyle = "#fff7f6";
    ctx.fillRect(x, y, contentWidth, 142);
    ctx.strokeStyle = "#efc3bd";
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, contentWidth, 142);
    ctx.fillStyle = config.theme;
    ctx.font = posterFont(20, 800);
    ctx.fillText("增量快报", x + 18, y + 34);
    ctx.fillStyle = "#1b1f23";
    ctx.font = posterFont(22, 700);
    drawWrappedText(ctx, brief.summary || "本轮暂无可展示摘要。", x + 18, y + 72, contentWidth - 36, 31, 3);

    y += 184;
    const metaRows = [
      ["运行时间", brief.runAt || "--"],
      ["统计窗口", `${brief.windowStart || "--"} 至 ${brief.windowEnd || brief.runAt || "--"}`],
      ["筛选结果", `${brief.selectedCount || (brief.items || []).length || 0} 条入选 / ${brief.candidateCount || 0} 条候选`]
    ];
    metaRows.forEach((row, index) => {
      const left = x + index * ((contentWidth - 24) / 3 + 12);
      const boxWidth = (contentWidth - 24) / 3;
      ctx.fillStyle = index % 2 === 0 ? "#f4f9ff" : "#ffffff";
      ctx.fillRect(left, y, boxWidth, 72);
      ctx.strokeStyle = "#b7d6f2";
      ctx.strokeRect(left, y, boxWidth, 72);
      ctx.fillStyle = "#5f7895";
      ctx.font = posterFont(15, 700);
      ctx.fillText(row[0], left + 14, y + 24);
      ctx.fillStyle = "#1b1f23";
      ctx.font = posterFont(17, 700);
      drawWrappedText(ctx, row[1], left + 14, y + 52, boxWidth - 28, 22, 1);
    });

    y += 118;
    ctx.fillStyle = config.theme;
    ctx.font = posterFont(24, 800);
    ctx.fillText("外发快讯", x, y);
    y += 20;
    const items = brief.items || [];
    if (!items.length) {
      drawEmptyPosterBlock(ctx, "本轮暂无入选快讯。", x, y + 18, contentWidth, 220);
      return;
    }
    items.forEach((item, index) => {
      const top = y + index * 176 + 18;
      ctx.fillStyle = index % 2 === 0 ? "#ffffff" : "#fbfdff";
      ctx.fillRect(x, top, contentWidth, 154);
      ctx.strokeStyle = "#d9e8f4";
      ctx.strokeRect(x, top, contentWidth, 154);
      ctx.fillStyle = config.theme;
      ctx.fillRect(x, top, 8, 154);
      ctx.fillStyle = config.theme;
      ctx.font = posterFont(18, 800);
      ctx.fillText(String(index + 1).padStart(2, "0"), x + 24, top + 36);
      ctx.fillStyle = "#fff3f1";
      ctx.fillRect(x + contentWidth - 92, top + 18, 58, 28);
      ctx.strokeStyle = "#efc3bd";
      ctx.strokeRect(x + contentWidth - 92, top + 18, 58, 28);
      ctx.fillStyle = config.theme;
      ctx.font = posterFont(16, 800);
      ctx.fillText(formatNumber(item.score || 0, 0), x + contentWidth - 76, top + 38);
      ctx.fillStyle = "#1b1f23";
      ctx.font = posterFont(23, 800);
      drawWrappedText(ctx, getBriefItemTitle(item), x + 72, top + 38, contentWidth - 188, 29, 2);
      ctx.fillStyle = "#33445c";
      ctx.font = posterFont(18, 600);
      drawWrappedText(ctx, getBriefItemText(item), x + 72, top + 93, contentWidth - 116, 27, 2);
      ctx.fillStyle = "#5f7895";
      ctx.font = posterFont(15, 600);
      const tags = (item.tags || []).slice(0, 2).join(" / ");
      const meta = `${item.sourceName || "--"}  ${compactDateTime(item.time || "")}${tags ? "  " + tags : ""}`;
      ctx.fillText(fitText(ctx, meta, contentWidth - 116), x + 72, top + 136);
    });
  }

  function drawKpiPosterGrid(ctx, kpis, x, y, width, config) {
    const gap = 12;
    const itemWidth = (width - gap) / 2;
    const itemHeight = 78;
    if (!kpis.length) {
      drawEmptyPosterBlock(ctx, "暂无可用核心指标。", x, y, width, 160);
      return;
    }
    kpis.forEach((item, index) => {
      const col = index % 2;
      const row = Math.floor(index / 2);
      const left = x + col * (itemWidth + gap);
      const top = y + row * (itemHeight + gap);
      ctx.fillStyle = "#f4f9ff";
      ctx.fillRect(left, top, itemWidth, itemHeight);
      ctx.strokeStyle = "#b7d6f2";
      ctx.lineWidth = 1;
      ctx.strokeRect(left, top, itemWidth, itemHeight);
      ctx.fillStyle = "#5f7895";
      ctx.font = posterFont(16, 600);
      ctx.fillText(String(item.label || "--").slice(0, 30), left + 16, top + 26);
      ctx.fillStyle = config.theme;
      ctx.font = posterFont(28, 800);
      ctx.fillText(`${formatKpiValue(item.value)}${item.unit || ""}`, left + 16, top + 62);
      if (item.change !== null && item.change !== undefined) {
        const change = `${item.change > 0 ? "+" : ""}${formatNumber(item.change, 2)}%`;
        ctx.fillStyle = item.change >= 0 ? config.accent : colors.cyan;
        ctx.font = posterFont(18, 800);
        ctx.fillText(change, left + itemWidth - 94, top + 62);
      }
    });
  }

  async function drawChartPosterCard(ctx, chart, x, y, width, height, config) {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(x, y, width, height);
    ctx.strokeStyle = "#b7d6f2";
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, width, height);
    ctx.fillStyle = config.theme;
    ctx.fillRect(x, y, width, 42);
    ctx.fillStyle = "#ffffff";
    ctx.font = posterFont(width < 520 ? 17 : 19, 800);
    drawWrappedText(ctx, chart.title, x + 14, y + 27, width - 28, 22, 1);
    const chartInstance = state.charts[chart.id] || getChart(chart.id);
    if (!chartInstance) {
      drawEmptyPosterBlock(ctx, "暂无可用图表。", x + 16, y + 58, width - 32, height - 76);
      return;
    }
    const dataUrl = chartInstance.getDataURL({
      type: "png",
      pixelRatio: 2,
      backgroundColor: "#ffffff"
    });
    const img = await loadImage(dataUrl);
    drawContainedImage(ctx, img, x + 12, y + 54, width - 24, height - 68);
  }

  function drawNewsStats(ctx, config, x, y, width) {
    const groups = (config.groups || []).slice(0, 4);
    const sources = (config.sources || []).slice(0, 4);
    const itemCount = (state.news?.items || []).length;
    const statRows = [
      ["新闻总量", `${itemCount} 条`],
      ["当前筛选", `${(config.newsItems || []).length} 条`],
      ["分类分布", groups.map((item) => `${item.tag} ${item.count}`).join(" / ") || "--"],
      ["来源分布", sources.map((item) => `${item.sourceName} ${item.count}`).join(" / ") || "--"]
    ];
    statRows.forEach((row, index) => {
      const top = y + index * 34;
      ctx.fillStyle = index % 2 === 0 ? "#fff3f1" : "#ffffff";
      ctx.fillRect(x, top, width, 30);
      ctx.fillStyle = config.theme;
      ctx.font = posterFont(17, 800);
      ctx.fillText(row[0], x + 12, top + 22);
      ctx.fillStyle = "#1b1f23";
      ctx.font = posterFont(17, 600);
      drawWrappedText(ctx, row[1], x + 132, top + 22, width - 150, 24, 1);
    });
  }

  function drawPosterFooter(ctx, config, width, height) {
    ctx.fillStyle = "#ffffff";
    ctx.font = posterFont(16, 500);
    ctx.fillText(config.footerText || "数据来源：公开新闻源及本地数据模板；本图片由数据门户自动生成，仅用于信息跟踪。", 42, height - 34);
  }

  function drawEmptyPosterBlock(ctx, message, x, y, width, height) {
    ctx.fillStyle = "#f4f9ff";
    ctx.fillRect(x, y, width, height);
    ctx.strokeStyle = "#b7d6f2";
    ctx.strokeRect(x, y, width, height);
    ctx.fillStyle = "#5f7895";
    ctx.font = posterFont(20, 600);
    ctx.fillText(message, x + 18, y + 42);
  }

  function drawQrCode(ctx, text, x, y, size) {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(x - 8, y - 8, size + 16, size + 16);
    ctx.strokeStyle = "#d8e5f0";
    ctx.lineWidth = 2;
    ctx.strokeRect(x - 8, y - 8, size + 16, size + 16);
    if (typeof qrcode !== "function") {
      ctx.fillStyle = "#1b1f23";
      ctx.font = posterFont(14, 700);
      ctx.fillText("QR", x + size / 2 - 10, y + size / 2 + 5);
      return;
    }
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    const count = qr.getModuleCount();
    const cell = Math.floor(size / count);
    const qrSize = cell * count;
    const offset = Math.floor((size - qrSize) / 2);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(x, y, size, size);
    ctx.fillStyle = "#1b1f23";
    for (let row = 0; row < count; row += 1) {
      for (let col = 0; col < count; col += 1) {
        if (qr.isDark(row, col)) {
          ctx.fillRect(x + offset + col * cell, y + offset + row * cell, cell, cell);
        }
      }
    }
  }

  function drawContainedImage(ctx, image, x, y, width, height) {
    const scale = Math.min(width / image.width, height / image.height);
    const drawWidth = image.width * scale;
    const drawHeight = image.height * scale;
    const left = x + (width - drawWidth) / 2;
    const top = y + (height - drawHeight) / 2;
    ctx.drawImage(image, left, top, drawWidth, drawHeight);
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = src;
    });
  }

  function drawWrappedText(ctx, text, x, y, maxWidth, lineHeight, maxLines) {
    const chars = Array.from(String(text || ""));
    let line = "";
    let lineCount = 0;
    for (let index = 0; index < chars.length; index += 1) {
      const testLine = line + chars[index];
      if (ctx.measureText(testLine).width > maxWidth && line) {
        lineCount += 1;
        if (lineCount >= maxLines) {
          ctx.fillText(trimToWidth(ctx, line + "...", maxWidth), x, y);
          return lineCount * lineHeight;
        }
        ctx.fillText(line, x, y);
        y += lineHeight;
        line = chars[index];
      } else {
        line = testLine;
      }
    }
    if (line && lineCount < maxLines) {
      ctx.fillText(line, x, y);
    }
    return (lineCount + 1) * lineHeight;
  }

  function trimToWidth(ctx, text, maxWidth) {
    let output = String(text || "").replace(/\.{3}$/g, "");
    while (output.length > 1 && ctx.measureText(output + "...").width > maxWidth) {
      output = output.slice(0, -1);
    }
    return output ? output + "..." : "...";
  }

  function fitText(ctx, text, maxWidth) {
    const output = String(text || "");
    return ctx.measureText(output).width <= maxWidth ? output : trimToWidth(ctx, output + "...", maxWidth);
  }

  function posterFont(size, weight) {
    return `${weight} ${size}px "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif`;
  }

  function posterSerifFont(size, weight) {
    return `${weight} ${size}px "Noto Serif SC", "Microsoft YaHei", serif`;
  }

  function nextFrame() {
    return new Promise((resolve) => {
      window.requestAnimationFrame(() => window.requestAnimationFrame(resolve));
    });
  }

  function formatToday() {
    return new Date().toLocaleString("zh-CN", { hour12: false });
  }

  function getChart(id) {
    if (!state.charts[id]) {
      const node = document.getElementById(id);
      if (!node || !window.echarts) {
        return null;
      }
      state.charts[id] = echarts.init(node);
      observeChartElement(id, node);
    }
    return state.charts[id];
  }

  function resizeCharts() {
    Object.values(state.charts).forEach((chart) => chart.resize());
  }

  function setupResizeObserver() {
    if (!window.ResizeObserver || state.resizeObserver) {
      return;
    }
    state.resizeObserver = new ResizeObserver((entries) => {
      entries.forEach((entry) => {
        const id = entry.target.id;
        if (id && state.charts[id]) {
          state.charts[id].resize();
        }
      });
    });
    document.querySelectorAll(".chart[id]").forEach((node) => observeChartElement(node.id, node));
  }

  function observeChartElement(id, node) {
    if (!state.resizeObserver || state.observedCharts.has(id) || !node) {
      return;
    }
    state.resizeObserver.observe(node);
    state.observedCharts.add(id);
  }

  function buildHorizontalZoom(total, windowSize) {
    const start = getZoomStart(total, windowSize);
    return [
      {
        type: "inside",
        xAxisIndex: 0,
        filterMode: "none",
        zoomOnMouseWheel: true,
        moveOnMouseWheel: true,
        moveOnMouseMove: true
      },
      {
        type: "slider",
        xAxisIndex: 0,
        filterMode: "none",
        height: 22,
        bottom: 14,
        start,
        end: 100,
        brushSelect: true,
        borderColor: colors.line,
        fillerColor: "rgba(10, 155, 220, 0.18)",
        handleStyle: { color: colors.blueDark },
        textStyle: { color: colors.muted }
      }
    ];
  }

  function buildVerticalZoom(total, windowSize) {
    const start = getZoomStart(total, windowSize);
    return [
      {
        type: "inside",
        yAxisIndex: 0,
        filterMode: "none",
        zoomOnMouseWheel: true,
        moveOnMouseWheel: true,
        moveOnMouseMove: true
      },
      {
        type: "slider",
        yAxisIndex: 0,
        filterMode: "none",
        width: 14,
        right: 8,
        top: 44,
        bottom: 34,
        start,
        end: 100,
        brushSelect: true,
        borderColor: colors.line,
        fillerColor: "rgba(10, 155, 220, 0.18)",
        handleStyle: { color: colors.blueDark },
        textStyle: { color: colors.muted }
      }
    ];
  }

  function getZoomStart(total, windowSize) {
    if (!total || total <= windowSize) {
      return 0;
    }
    return Math.max(0, 100 - (windowSize / total) * 100);
  }

  function buildToolbox(vertical) {
    return {
      right: 4,
      top: 0,
      itemSize: 14,
      feature: {
        dataZoom: vertical ? { xAxisIndex: false } : { yAxisIndex: false },
        restore: {}
      },
      iconStyle: { borderColor: colors.muted },
      emphasis: { iconStyle: { borderColor: colors.blueDark } }
    };
  }

  function metricLabel(metric) {
    return {
      DAU: "DAU",
      AvgTime: "人均时长",
      WAU: "WAU",
      Duration: "使用总时长"
    }[metric] || metric;
  }

  function formatTableValue(value, key) {
    if (value === null || value === undefined || value === "") {
      return "";
    }
    if (key === "WoW" || key === "YoY" || key === "环比") {
      return percentText(normalizePercent(value));
    }
    if (typeof value === "number") {
      return formatNumber(value, 2);
    }
    return value;
  }

  function normalizePercent(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return null;
    }
    return Math.abs(number) <= 1 ? number * 100 : number;
  }

  function percentText(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
      return "--";
    }
    const number = Number(value);
    return `${number > 0 ? "+" : ""}${formatNumber(number, 2)}%`;
  }

  function formatKpiValue(value) {
    return typeof value === "number" ? formatNumber(value, 2) : escapeHtml(value);
  }

  function formatNumber(value, digits = 1) {
    return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
  }

  function truncateText(value, maxLength) {
    const text = String(value || "");
    if (text.length <= maxLength) {
      return text;
    }
    return text.slice(0, Math.max(0, maxLength - 1)) + "…";
  }

  function round(value, digits = 2) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return value;
    }
    const factor = 10 ** digits;
    return Math.round(number * factor) / factor;
  }

  function monthDay(value) {
    if (!value || value.length < 10) {
      return value;
    }
    return value.slice(5);
  }

  function compactDateTime(value) {
    if (!value) {
      return "--";
    }
    return String(value).slice(5, 16);
  }

  function getBriefItemTitle(item) {
    return item.flashTitle || item.fact || item.title || "--";
  }

  function getBriefItemText(item) {
    return item.flashText || item.fact || item.reason || item.title || "--";
  }

  function formatBriefForwardText(brief, options = {}) {
    const maxItems = options.maxItems || 6;
    const includeLinks = options.includeLinks !== false;
    const compact = Boolean(options.compact);
    const items = (brief.items || []).slice(0, maxItems);
    const lines = [
      `【华泰互联网资讯快报】${formatForwardDate(brief.runAt)}`,
      ""
    ];
    if (!compact && brief.summary) {
      lines.push(`本轮要点：${cleanForwardSentence(brief.summary)}`, "");
    }
    items.forEach((item, index) => {
      const title = cleanForwardSentence(getBriefItemTitle(item));
      const text = cleanForwardSentence(getBriefItemText(item));
      const source = item.sourceName ? `来源：${item.sourceName}` : "";
      const score = Number.isFinite(Number(item.score)) ? `重要度：${formatNumber(item.score, 0)}` : "";
      const meta = [source, score].filter(Boolean).join("；");
      lines.push(`${index + 1}. ${title}`);
      lines.push(meta ? `${text}（${meta}）` : text);
      if (includeLinks && item.url) {
        lines.push(`原文：${item.url}`);
      }
      if (!compact) {
        lines.push("");
      }
    });
    if (!items.length) {
      lines.push("本轮暂无入选快讯。", "");
    }
    if (!compact) {
      lines.push("说明：以上信息来自公开新闻源，供研究跟踪使用。");
    }
    return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function formatBriefSmsText(brief) {
    const items = (brief.items || []).slice(0, 3);
    const parts = [`【华泰互联网】${formatForwardDate(brief.runAt)}资讯快报`];
    items.forEach((item, index) => {
      const title = cleanForwardSentence(getBriefItemTitle(item));
      const text = cleanForwardSentence(item.smsText || getBriefItemText(item));
      parts.push(`${index + 1}. ${title}：${text}`);
    });
    return truncateText(parts.join("；"), 480);
  }

  function cleanForwardSentence(value) {
    return String(value || "")
      .replace(/\s+/g, " ")
      .replace(/[；;]\s*$/, "")
      .trim();
  }

  function formatForwardDate(value) {
    if (!value) {
      return formatToday();
    }
    const text = String(value);
    if (text.length >= 16) {
      return `${text.slice(5, 7)}月${text.slice(8, 10)}日 ${text.slice(11, 16)}`;
    }
    return text;
  }

  function focusRequestedBrief() {
    const briefId = new URLSearchParams(window.location.search).get("brief");
    if (!briefId) {
      return;
    }
    setTimeout(() => {
      const card = Array.from(document.querySelectorAll("[data-brief-card-id]"))
        .find((node) => node.dataset.briefCardId === briefId);
      if (!card) {
        return;
      }
      card.classList.add("is-focused");
      card.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 120);
  }

  function isIsoDateKey(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));
  }

  function csvCell(value) {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  function safeFileName(value) {
    return String(value || "指标明细").replace(/[\\/:*?"<>|]/g, "_");
  }

  function emptyState(message) {
    return `<div class="empty-state">${escapeHtml(message)}</div>`;
  }

  function element(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
})();
