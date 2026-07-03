(function () {
  "use strict";

  const state = {
    data: null,
    charts: {},
    observedCharts: new Set(),
    resizeObserver: null
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
    if (window.lucide) {
      window.lucide.createIcons();
    }
    bindEvents();
    await loadData();
    setupResizeObserver();
    window.addEventListener("resize", resizeCharts);
  }

  function bindEvents() {
    document.querySelectorAll("[data-section]").forEach((button) => {
      button.addEventListener("click", () => activateSection(button.dataset.section));
    });
    document.querySelectorAll("[data-tab-target]").forEach((button) => {
      button.addEventListener("click", () => activateTab(button));
    });
    document.querySelectorAll("[data-export-block]").forEach((button) => {
      button.addEventListener("click", () => exportBlockCsv(button.dataset.exportBlock));
    });

    element("aiDauRegion").addEventListener("change", renderAiDauChart);
    element("aiAvgRegion").addEventListener("change", renderAiAvgTimeChart);
  }

  async function loadData() {
    try {
      state.data = await window.HTDataSync.fetchPortalData();
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
    activateSection(getInitialSection());
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

  function activateSection(section) {
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.section === section);
    });
    document.querySelectorAll(".section-pane").forEach((pane) => {
      pane.classList.toggle("active", pane.dataset.pane === section);
    });
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
    return ["ai", "beike", "detail"].includes(requested) ? requested : "ai";
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
