(function () {
  "use strict";

  async function fetchPortalData() {
    if (!window.HT_PORTAL_REAL_DATA) {
      throw new Error("未读取到指标数据，请通过“启动数据门户.bat”启动本地服务后重新打开页面。");
    }

    return clone(window.HT_PORTAL_REAL_DATA);
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
    triggerSync
  };
})();
