window.HT_PORTAL_SAMPLE_DATA = {
  meta: {
    version: "Demo-2026.06.11",
    lastUpdated: "2026-06-11 15:40",
    source: "本地样例数据，等待接入真实同步源"
  },
  kpis: [
    { label: "覆盖公司总市值", value: 18432, unit: "亿元", change: 2.4, note: "较上一交易日" },
    { label: "互联网组合指数", value: 1186.7, unit: "点", change: 1.1, note: "基准日=1000" },
    { label: "重点公司平均 PE", value: 22.8, unit: "x", change: -0.6, note: "TTM 口径" },
    { label: "本周研究动作", value: 17, unit: "条", change: 4, note: "报告 / 路演 / 点评" }
  ],
  dailyBriefs: [
    { tag: "市场", title: "游戏与广告链相对占优", note: "成交热度继续向高现金流、低估值方向集中，建议同步跟踪版号与投放 ROI。" },
    { tag: "运营", title: "本地生活数据等待外部源", note: "预留补贴率、订单频次、即时零售 GMV 三类字段，接入后可自动刷新。" },
    { tag: "财务", title: "财报季模型更新窗口", note: "建议将组内预测表输出为统一 JSON，保持估值表与公司卡片同源。" }
  ],
  marketTrend: {
    dates: ["05-20", "05-21", "05-22", "05-23", "05-26", "05-27", "05-28", "05-29", "05-30", "06-02", "06-03", "06-04", "06-05", "06-06", "06-09", "06-10", "06-11"],
    index: [1112, 1118, 1109, 1125, 1136, 1141, 1132, 1148, 1157, 1162, 1153, 1166, 1174, 1170, 1181, 1176, 1186.7],
    turnover: [286, 302, 278, 315, 338, 356, 332, 368, 389, 402, 376, 395, 421, 408, 446, 432, 458]
  },
  sectors: [
    { name: "游戏", change: 3.8, pe: 18.6, ps: 4.2 },
    { name: "广告营销", change: 2.7, pe: 21.3, ps: 3.1 },
    { name: "电商", change: 1.9, pe: 17.8, ps: 2.0 },
    { name: "本地生活", change: 1.2, pe: 32.4, ps: 4.8 },
    { name: "社交社区", change: 0.6, pe: 24.5, ps: 5.7 },
    { name: "在线娱乐", change: -0.4, pe: 19.9, ps: 2.8 },
    { name: "互联网金融", change: -1.1, pe: 12.4, ps: 1.6 }
  ],
  companies: [
    { name: "腾讯控股", code: "0700.HK", sector: "社交社区", marketCap: 36500, change: 1.8, pe: 21.6, ps: 5.4, turnover30d: 934, owner: "互联网组", focus: "游戏流水与视频号广告", revenueGrowth: 8.2, margin: 31.4 },
    { name: "阿里巴巴-W", code: "9988.HK", sector: "电商", marketCap: 14200, change: 1.1, pe: 12.8, ps: 1.7, turnover30d: 648, owner: "互联网组", focus: "淘天 GMV 与云业务修复", revenueGrowth: 5.9, margin: 15.7 },
    { name: "美团-W", code: "3690.HK", sector: "本地生活", marketCap: 7800, change: 2.6, pe: 28.5, ps: 3.8, turnover30d: 512, owner: "互联网组", focus: "即时零售竞争与利润率", revenueGrowth: 18.4, margin: 8.9 },
    { name: "快手-W", code: "1024.HK", sector: "在线娱乐", marketCap: 3050, change: -0.7, pe: 17.4, ps: 2.4, turnover30d: 286, owner: "互联网组", focus: "电商货币化与广告填充", revenueGrowth: 11.2, margin: 13.8 },
    { name: "网易-S", code: "9999.HK", sector: "游戏", marketCap: 4800, change: 3.4, pe: 16.9, ps: 4.6, turnover30d: 176, owner: "互联网组", focus: "新游上线节奏", revenueGrowth: 7.6, margin: 25.6 },
    { name: "哔哩哔哩-W", code: "9626.HK", sector: "在线娱乐", marketCap: 740, change: -1.9, pe: 0, ps: 1.5, turnover30d: 96, owner: "互联网组", focus: "DAU 与广告加载率", revenueGrowth: 12.9, margin: -4.2 },
    { name: "百度集团-SW", code: "9888.HK", sector: "广告营销", marketCap: 2850, change: 0.9, pe: 11.2, ps: 1.9, turnover30d: 144, owner: "互联网组", focus: "AI 搜索商业化", revenueGrowth: 4.8, margin: 19.5 },
    { name: "京东集团-SW", code: "9618.HK", sector: "电商", marketCap: 3920, change: 1.6, pe: 10.4, ps: 0.4, turnover30d: 218, owner: "互联网组", focus: "低价策略与用户增长", revenueGrowth: 6.6, margin: 4.1 },
    { name: "携程集团-S", code: "9961.HK", sector: "本地生活", marketCap: 3300, change: 2.2, pe: 18.8, ps: 6.0, turnover30d: 122, owner: "互联网组", focus: "出境游恢复与酒店 ADR", revenueGrowth: 14.7, margin: 28.3 },
    { name: "三七互娱", code: "002555.SZ", sector: "游戏", marketCap: 368, change: 4.1, pe: 15.7, ps: 2.9, turnover30d: 78, owner: "互联网组", focus: "小游戏投放 ROI", revenueGrowth: 9.5, margin: 18.1 }
  ],
  traffic: {
    dates: ["2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2E"],
    series: [
      { name: "社交社区", data: [1090, 1118, 1132, 1146, 1160] },
      { name: "电商", data: [870, 902, 935, 928, 956] },
      { name: "在线娱乐", data: [612, 640, 666, 682, 690] },
      { name: "本地生活", data: [486, 521, 548, 572, 590] }
    ]
  },
  monetization: [
    { name: "广告 ARPU", value: 8.6, growth: 10.2 },
    { name: "电商佣金率", value: 3.7, growth: 0.3 },
    { name: "游戏流水增速", value: 12.4, growth: 4.9 },
    { name: "本地生活补贴率", value: 5.1, growth: -1.4 },
    { name: "会员付费率", value: 9.8, growth: 0.8 }
  ],
  operations: [
    { label: "MAU 样本覆盖", value: "42", unit: "个平台", note: "覆盖社交、电商、娱乐、本地生活" },
    { label: "本周新增埋点", value: "11", unit: "项", note: "留给数据源同步后自动生成" },
    { label: "财报模型更新", value: "8", unit: "家公司", note: "建议与组内预测表联动" },
    { label: "待确认异常", value: "3", unit: "条", note: "接口接入后可展示校验结果" }
  ],
  syncQueue: [
    { name: "行情估值", source: "Wind / iFinD", status: "done", time: "09:12" },
    { name: "流量运营", source: "QuestMobile / 第三方", status: "running", time: "等待接口" },
    { name: "财务预测", source: "组内模型导出", status: "waiting", time: "预留" },
    { name: "研究动作", source: "共享台账", status: "waiting", time: "预留" }
  ]
};
