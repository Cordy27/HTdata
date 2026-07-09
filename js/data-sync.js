(function () {
  "use strict";

  let cloudbaseDb = null;

  async function fetchPortalData() {
    if (!window.HT_PORTAL_REAL_DATA) {
      throw new Error("未读取到指标数据，请通过“启动数据门户.bat”启动本地服务后重新打开页面。");
    }

    return clone(window.HT_PORTAL_REAL_DATA);
  }

  async function fetchNewsData() {
    if (window.cloudbase && window.HT_CLOUDBASE_CONFIG) {
      try {
        return await fetchCloudbaseNewsData();
      } catch (error) {
        console.warn("CloudBase 新闻数据读取失败", error);
      }
    }
    if (!window.HT_NEWS_DATA) {
      return emptyNewsData();
    }

    return clone(window.HT_NEWS_DATA);
  }

  async function fetchCloudbaseNewsData() {
    const db = getCloudbaseDb();
    const [itemsResult, briefsResult] = await Promise.all([
      db.from("ht_news_items").select("*").order("latest_seen_at", { ascending: false }).limit(180),
      db.from("ht_news_briefs").select("*").order("run_at", { ascending: false }).limit(3)
    ]);
    if (itemsResult.error) {
      throw new Error(itemsResult.error.message || "新闻明细读取失败");
    }
    if (briefsResult.error) {
      throw new Error(briefsResult.error.message || "日报读取失败");
    }
    const items = (itemsResult.data || []).map(dbRowToNewsItem);
    const briefs = (briefsResult.data || []).map(dbRowToBrief).sort((a, b) => String(a.runAt || "").localeCompare(String(b.runAt || "")));
    return {
      meta: {
        version: `CloudBase-${new Date().toISOString()}`,
        lastUpdated: latestTime(items, briefs),
        lookbackDays: 7,
        itemCount: items.length,
        fetchedCount: 0,
        newCount: 0,
        issueCount: 0,
        briefCount: briefs.length,
        storage: "CloudBase",
        sourceProject: "TrendRadar / newsnow compatible sources",
        sourceProjectUrl: "https://github.com/sansan0/TrendRadar"
      },
      groups: buildNewsGroups(items),
      sources: buildNewsSources(items),
      briefs,
      items
    };
  }

  function getCloudbaseDb() {
    if (cloudbaseDb) {
      return cloudbaseDb;
    }
    const config = window.HT_CLOUDBASE_CONFIG || {};
    const app = window.cloudbase.init({
      env: config.env,
      region: config.region || "ap-shanghai",
      accessKey: config.accessKey,
      auth: { detectSessionInUrl: true }
    });
    cloudbaseDb = app.rdb();
    return cloudbaseDb;
  }

  function dbRowToNewsItem(row) {
    return {
      id: row.id || "",
      title: row.title || "",
      url: row.url || "",
      sourceId: row.source_id || "",
      sourceName: row.source_name || "",
      sourceType: row.source_type || "",
      rank: row.rank_num,
      tags: parseJsonList(row.tags_json),
      matchedTerms: parseJsonList(row.matched_terms_json),
      summary: row.summary || "",
      publishedAt: displayDate(row.published_at),
      firstSeenAt: displayDate(row.first_seen_at),
      latestSeenAt: displayDate(row.latest_seen_at),
      collectedAt: displayDate(row.collected_at),
      observations: Number(row.observations || 1),
      aiScore: row.ai_score,
      aiReason: row.ai_reason || ""
    };
  }

  function dbRowToBrief(row) {
    const items = parseJsonList(row.items_json);
    return {
      id: row.id || "",
      runAt: displayDate(row.run_at),
      windowStart: displayDate(row.window_start),
      windowEnd: displayDate(row.window_end),
      candidateCount: Number(row.candidate_count || 0),
      selectedCount: Number(row.selected_count || 0),
      title: row.title || "",
      summary: row.summary || "",
      items,
      promptVersion: row.prompt_version || "",
      model: row.model || ""
    };
  }

  function buildNewsGroups(items) {
    const counts = new Map();
    items.forEach((item) => {
      (item.tags || []).forEach((tag) => counts.set(tag, (counts.get(tag) || 0) + 1));
    });
    return Array.from(counts, ([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag, "zh-CN"));
  }

  function buildNewsSources(items) {
    const bySource = new Map();
    items.forEach((item) => {
      const key = item.sourceId || item.sourceName || "";
      if (!key) {
        return;
      }
      if (!bySource.has(key)) {
        bySource.set(key, {
          sourceId: item.sourceId,
          sourceName: item.sourceName,
          sourceType: item.sourceType,
          count: 0
        });
      }
      bySource.get(key).count += 1;
    });
    return Array.from(bySource.values()).sort((a, b) => b.count - a.count || a.sourceName.localeCompare(b.sourceName, "zh-CN"));
  }

  function latestTime(items, briefs) {
    const values = [
      ...items.map((item) => item.latestSeenAt || item.publishedAt || item.collectedAt),
      ...briefs.map((brief) => brief.runAt)
    ].filter(Boolean).sort();
    return values[values.length - 1] || "";
  }

  function parseJsonList(value) {
    if (Array.isArray(value)) {
      return value;
    }
    if (!value) {
      return [];
    }
    try {
      const parsed = JSON.parse(String(value));
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function displayDate(value) {
    if (!value) {
      return "";
    }
    return String(value).replace("T", " ").replace(/\.\d+Z?$/, "").replace(/Z$/, "");
  }

  function emptyNewsData() {
    return {
      meta: {
        lastUpdated: "",
        itemCount: 0,
        fetchedCount: 0,
        lookbackDays: 7,
        issueCount: 0
      },
      groups: [],
      sources: [],
      briefs: [],
      items: []
    };
  }

  async function triggerSync() {
    const response = await fetch("/__sync", { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || payload.stderr || "指标数据更新失败");
    }
    return payload;
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  window.HTDataSync = {
    fetchPortalData,
    fetchNewsData,
    triggerSync
  };
})();
