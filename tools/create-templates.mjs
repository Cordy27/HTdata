import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const templateDir = path.join(rootDir, "templates");
const previewDir = path.join(templateDir, "previews");

const blueDark = "#003f7d";
const blue = "#0076bd";
const cyan = "#0a9bdc";
const pale = "#eaf4ff";
const pale2 = "#f6faff";
const line = "#b7d6f2";
const ink = "#062a54";
const muted = "#5f7895";
const inputFill = "#fff7dd";

const DATE_COLUMNS = 77;
const BEIKE_TOTAL_COLUMNS = 80;
const seed = await loadSeedData();

await fs.mkdir(templateDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

function setTitle(sheet, title, subtitle, colCount) {
  sheet.showGridLines = false;
  sheet.getRangeByIndexes(0, 0, 1, colCount).merge();
  sheet.getCell(0, 0).values = [[title]];
  sheet.getCell(0, 0).format = {
    fill: blueDark,
    font: { bold: true, color: "#ffffff", size: 16 },
    wrapText: true
  };
  sheet.getRangeByIndexes(1, 0, 1, colCount).merge();
  sheet.getCell(1, 0).values = [[subtitle]];
  sheet.getCell(1, 0).format = {
    fill: pale,
    font: { color: muted, size: 10 },
    wrapText: true
  };
  sheet.getRangeByIndexes(0, 0, 2, colCount).format.borders = { preset: "outside", style: "thin", color: line };
}

function styleHeader(range, fill = blueDark) {
  range.format = {
    fill,
    font: { bold: true, color: "#ffffff" },
    wrapText: true
  };
  range.format.borders = { preset: "all", style: "thin", color: line };
}

function styleSubheader(range) {
  range.format = {
    fill: pale,
    font: { bold: true, color: blueDark },
    wrapText: true
  };
  range.format.borders = { preset: "all", style: "thin", color: line };
}

function styleGrid(range) {
  range.format.borders = { preset: "all", style: "thin", color: line };
}

function setWidths(sheet, widths) {
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, 1100, 1).format.columnWidth = width;
  });
}

function freezeRows(sheet, rows) {
  try {
    sheet.freezePanes.freezeRows(rows);
  } catch {
    // The workbook remains usable if the renderer skips pane state.
  }
}

function addInstructions(workbook, title, subtitle, rows) {
  const sheet = workbook.worksheets.add("填写说明");
  setTitle(sheet, title, subtitle, 7);
  sheet.getRange("A4:G4").values = [["模块", "填写方式", "读取规则", "必填", "单位", "维护口径", "备注"]];
  styleHeader(sheet.getRange("A4:G4"));
  sheet.getRangeByIndexes(4, 0, rows.length, 7).values = rows;
  styleGrid(sheet.getRangeByIndexes(4, 0, rows.length, 7));
  sheet.getRangeByIndexes(4, 0, rows.length, 7).format.wrapText = true;
  setWidths(sheet, [18, 38, 40, 10, 14, 34, 30]);
  freezeRows(sheet, 4);
}

function addValidation(workbook, rows) {
  const sheet = workbook.worksheets.add("数据校验");
  setTitle(sheet, "数据校验", "同步脚本会按相同口径读取；本页用于人工录入前复核。", 5);
  sheet.getRange("A4:E4").values = [["检查项", "规则", "严重性", "处理建议", "备注"]];
  styleHeader(sheet.getRange("A4:E4"));
  sheet.getRangeByIndexes(4, 0, rows.length, 5).values = rows;
  styleGrid(sheet.getRangeByIndexes(4, 0, rows.length, 5));
  sheet.getRangeByIndexes(4, 0, rows.length, 5).format.wrapText = true;
  setWidths(sheet, [24, 48, 12, 42, 26]);
  freezeRows(sheet, 4);
}

function addDictionary(workbook, rows) {
  const sheet = workbook.worksheets.add("字段字典");
  setTitle(sheet, "字段字典", "新增产品、App、城市或指标时，先在这里记录口径。", 6);
  sheet.getRange("A4:F4").values = [["字段", "允许值", "单位", "口径说明", "是否可扩展", "备注"]];
  styleHeader(sheet.getRange("A4:F4"));
  sheet.getRangeByIndexes(4, 0, rows.length, 6).values = rows;
  styleGrid(sheet.getRangeByIndexes(4, 0, rows.length, 6));
  sheet.getRangeByIndexes(4, 0, rows.length, 6).format.wrapText = true;
  setWidths(sheet, [18, 28, 12, 42, 14, 28]);
  freezeRows(sheet, 4);
}

function styleEditableArea(sheet, startRow, startCol, rowCount, colCount) {
  const area = sheet.getRangeByIndexes(startRow, startCol, rowCount, colCount);
  area.format = { fill: inputFill };
  area.format.borders = { preset: "all", style: "thin", color: line };
  return area;
}

async function renderWorkbook(workbook, slug, sheets) {
  const previewRanges = {
    "ChatGPT美国DAU数据": "A1:J60",
    "QM核心App数据": "A1:CB14",
    "QM-贝壳找房": "A1:CB38",
  };
  for (const sheetName of sheets) {
    const preview = await workbook.render({
      sheetName,
      range: previewRanges[sheetName],
      autoCrop: "all",
      scale: 1,
      format: "png"
    });
    await fs.writeFile(
      path.join(previewDir, `${slug}-${sheetName}.png`),
      new Uint8Array(await preview.arrayBuffer())
    );
  }
}

async function loadSeedData() {
  const dataFile = path.join(rootDir, "data", "portal-data.js");
  try {
    const text = await fs.readFile(dataFile, "utf8");
    const prefix = "window.HT_PORTAL_REAL_DATA = ";
    if (!text.startsWith(prefix)) {
      return null;
    }
    return JSON.parse(text.slice(prefix.length).replace(/;\s*$/, ""));
  } catch {
    return null;
  }
}

function buildAiTemplateRows() {
  const records = seed?.ai?.records || [];
  const byKey = new Map(records.map((item) => [`${item.date}|${item.product}|${item.region}|${item.metric}`, item.value]));
  const dates = Array.from(new Set(records.map((item) => item.date))).sort();
  return dates.map((dateText) => [
    dateText,
    byKey.get(`${dateText}|ChatGPT|US|DAU`) ?? null,
    byKey.get(`${dateText}|ChatGPT|US|AvgTime`) ?? null,
    byKey.get(`${dateText}|ChatGPT|Global|DAU`) ?? null,
    byKey.get(`${dateText}|ChatGPT|Global|AvgTime`) ?? null,
    null,
    byKey.get(`${dateText}|Gemini|US|DAU`) ?? null,
    byKey.get(`${dateText}|Gemini|US|AvgTime`) ?? null,
    byKey.get(`${dateText}|Gemini|Global|DAU`) ?? null,
    byKey.get(`${dateText}|Gemini|Global|AvgTime`) ?? null
  ]);
}

function getBlockRows(block) {
  if (!block?.rows?.length) {
    return [];
  }
  const columns = block.columns || [];
  return block.rows.map((row) => columns.map((column) => row[column] ?? null));
}

function writeTemplateBlock(sheet, startRowOneBased, block, fallbackTitle, rowLabels, includeWowYoy) {
  const startRow = startRowOneBased - 1;
  const dateColumns = (block?.dateColumns || []).slice(0, DATE_COLUMNS);
  const header = Array(BEIKE_TOTAL_COLUMNS).fill("");
  header[0] = fallbackTitle;
  dateColumns.forEach((dateText, index) => {
    header[index + 1] = dateText;
  });
  if (includeWowYoy) {
    header[78] = "WoW";
    header[79] = "YoY";
  }
  sheet.getRangeByIndexes(startRow, 0, 1, BEIKE_TOTAL_COLUMNS).values = [header];
  styleSubheader(sheet.getRangeByIndexes(startRow, 0, 1, BEIKE_TOTAL_COLUMNS));

  const blockRows = block?.rows?.length ? block.rows : rowLabels.map((label) => ({ [block?.label || "label"]: label }));
  const labelKey = block?.label || Object.keys(blockRows[0] || {})[0] || "label";
  const values = blockRows.map((sourceRow) => {
    const row = Array(BEIKE_TOTAL_COLUMNS).fill(null);
    row[0] = sourceRow[labelKey] ?? "";
    dateColumns.forEach((dateText, index) => {
      row[index + 1] = sourceRow[dateText] ?? null;
    });
    if (includeWowYoy) {
      row[78] = sourceRow.WoW ?? null;
      row[79] = sourceRow.YoY ?? null;
    }
    return row;
  });
  sheet.getRangeByIndexes(startRow + 1, 0, values.length, BEIKE_TOTAL_COLUMNS).values = values;
  styleGrid(sheet.getRangeByIndexes(startRow + 1, 0, values.length, BEIKE_TOTAL_COLUMNS));
  sheet.getRangeByIndexes(startRow, 1, 1, DATE_COLUMNS).setNumberFormat("yyyy-mm-dd");
  sheet.getRangeByIndexes(startRow + 1, 1, values.length, DATE_COLUMNS).setNumberFormat("#,##0.00");
  if (includeWowYoy) {
    sheet.getRangeByIndexes(startRow + 1, 78, values.length, 2).setNumberFormat("0.00%");
  }
}

async function buildAiTemplate() {
  const workbook = Workbook.create();
  addInstructions(workbook, "AI 产品数据填写模板", "按模板宽表结构填写，文件名固定，无需带日期。", [
    ["ChatGPT美国DAU数据", "第 1 行为产品分组，第 2 行为指标表头；第 3 行开始逐日填写。", "读取 Date、US DAU、US人均时长、Global DAU、Global人均时长。", "是", "DAU=mn；人均时长=min", "ChatGPT、Gemini 可继续扩展为同样 4 列一组。", "不要删除 Date 列或改变表头文字。"],
    ["字段字典", "记录产品、地区、指标和单位。", "不直接参与同步，但用于维护口径。", "建议", "", "新增 AI 产品时复制一组 4 列。", ""],
  ]);

  const sheet = workbook.worksheets.add("ChatGPT美国DAU数据");
  sheet.showGridLines = false;
  sheet.getRange("B1:E1").merge();
  sheet.getRange("G1:J1").merge();
  sheet.getRange("B1").values = [["ChatGPT"]];
  sheet.getRange("G1").values = [["Gemini"]];
  sheet.getRange("A2:J2").values = [[
    "Date",
    "US DAU (mn)",
    "US人均时长(min)",
    "Global DAU (mn)",
    "Global人均时长(min)",
    "",
    "US DAU (mn)",
    "US人均时长(min)",
    "Global DAU (mn)",
    "Global人均时长(min)"
  ]];
  const aiRows = buildAiTemplateRows();
  if (aiRows.length) {
    sheet.getRangeByIndexes(2, 0, aiRows.length, 10).values = aiRows;
  }
  styleHeader(sheet.getRange("A1:J2"));
  sheet.getRange("F1:F1100").format = { fill: "#ffffff" };
  styleEditableArea(sheet, 2, 0, Math.max(aiRows.length, 1000), 5);
  styleEditableArea(sheet, 2, 6, Math.max(aiRows.length, 1000), 4);
  sheet.getRangeByIndexes(2, 0, Math.max(aiRows.length, 1000), 1).setNumberFormat("yyyy-mm-dd");
  sheet.getRangeByIndexes(2, 1, Math.max(aiRows.length, 1000), 4).setNumberFormat("#,##0.00");
  sheet.getRangeByIndexes(2, 6, Math.max(aiRows.length, 1000), 4).setNumberFormat("#,##0.00");
  setWidths(sheet, [15, 16, 18, 18, 20, 4, 16, 18, 18, 20]);
  freezeRows(sheet, 2);

  addDictionary(workbook, [
    ["Product", "ChatGPT", "", "OpenAI ChatGPT", "是", ""],
    ["Product", "Gemini", "", "Google Gemini", "是", ""],
    ["Region", "US", "", "美国地区", "是", ""],
    ["Region", "Global", "", "全球地区", "是", ""],
    ["Metric", "DAU", "mn", "日活用户，单位百万", "是", ""],
    ["Metric", "AvgTime", "min", "人均使用时长，单位分钟", "是", ""],
  ]);

  addValidation(workbook, [
    ["日期", "Date 列必须是真实日期，按日追加。", "高", "补齐日期后再同步", ""],
    ["产品列组", "每个产品必须包含 US DAU、US人均时长、Global DAU、Global人均时长四列。", "高", "新增产品时复制完整四列", ""],
    ["单位", "DAU 使用 mn，人均时长使用 min。", "中", "不要把百分比或文本填入数值区", ""],
  ]);

  await renderWorkbook(workbook, "ai-template", ["ChatGPT美国DAU数据", "填写说明", "字段字典", "数据校验"]);
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(templateDir, "AI产品数据填写模板.xlsx"));
}

function addBeikeBlock(sheet, startRowOneBased, title, rowLabels, includeWowYoy) {
  const startRow = startRowOneBased - 1;
  const headers = Array(BEIKE_TOTAL_COLUMNS).fill("");
  headers[0] = title;
  if (includeWowYoy) {
    headers[78] = "WoW";
    headers[79] = "YoY";
  }
  sheet.getRangeByIndexes(startRow, 0, 1, BEIKE_TOTAL_COLUMNS).values = [headers];
  styleSubheader(sheet.getRangeByIndexes(startRow, 0, 1, BEIKE_TOTAL_COLUMNS));

  const labelRows = rowLabels.map((label) => {
    const row = Array(BEIKE_TOTAL_COLUMNS).fill(null);
    row[0] = label;
    return row;
  });
  sheet.getRangeByIndexes(startRow + 1, 0, rowLabels.length, BEIKE_TOTAL_COLUMNS).values = labelRows;
  styleGrid(sheet.getRangeByIndexes(startRow + 1, 0, rowLabels.length, BEIKE_TOTAL_COLUMNS));
  sheet.getRangeByIndexes(startRow + 1, 1, rowLabels.length, DATE_COLUMNS).format = { fill: inputFill };
  sheet.getRangeByIndexes(startRow, 1, 1, DATE_COLUMNS).format = { fill: inputFill };
  sheet.getRangeByIndexes(startRow, 1, 1, DATE_COLUMNS).setNumberFormat("yyyy-mm-dd");
  sheet.getRangeByIndexes(startRow + 1, 1, rowLabels.length, DATE_COLUMNS).setNumberFormat("#,##0.00");
  if (includeWowYoy) {
    sheet.getRangeByIndexes(startRow + 1, 78, rowLabels.length, 2).setNumberFormat("0.00%");
    sheet.getRangeByIndexes(startRow + 1, 78, rowLabels.length, 2).format = { fill: inputFill };
  }
}

async function buildBeikeTemplate() {
  const workbook = Workbook.create();
  addInstructions(workbook, "贝壳数据填写模板", "按模板分表宽表结构填写，文件名固定，无需带日期。", [
    ["QM核心App数据", "第 2 行填写 WAU 时间列；第 9 行填写使用时长时间列。第 3-5、10-12 行为固定 App。", "读取两个分表数据区：WAU（万人）、使用时长（万分钟）。", "是", "万人 / 万分钟", "最后两列可填 WoW、YoY。", "不要修改 sheet 名称和分表标题。"],
    ["QM-贝壳找房", "第 2 行为城市 WAU；第 14 行为历年 WAU；第 27 行为历年人均单日使用时长。", "读取三个分表数据区：城市 WAU、历年 WAU、历年人均时长。", "是", "万人 / 分钟", "城市和年份行保持分表粒度。", "城市中的右轴标记不用保留。"],
  ]);

  const core = workbook.worksheets.add("QM核心App数据");
  core.showGridLines = false;
  writeTemplateBlock(core, 2, seed?.beike?.blocks?.coreWau, "WAU（万人）", ["贝壳找房", "链家", "贝壳租房（右轴）"], true);
  writeTemplateBlock(core, 9, seed?.beike?.blocks?.coreDuration, "使用时长（万分钟）", ["贝壳找房", "链家", "贝壳租房（右轴）"], true);
  setWidths(core, [18, ...Array(DATE_COLUMNS).fill(12), 12, 12]);
  freezeRows(core, 2);

  const beike = workbook.worksheets.add("QM-贝壳找房");
  beike.showGridLines = false;
  beike.getRange("A1").values = [["贝壳找房"]];
  beike.getRange("A1").format = { fill: blueDark, font: { bold: true, color: "#ffffff" } };
  writeTemplateBlock(beike, 2, seed?.beike?.blocks?.cityWau, "WAU（万人）", ["北京", "上海", "天津（右轴）", "四川", "浙江", "江苏", "广东"], true);
  writeTemplateBlock(beike, 14, seed?.beike?.blocks?.yearlyWau, "WAU（万人）", [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026], false);
  writeTemplateBlock(beike, 27, seed?.beike?.blocks?.yearlyAvgTime, "人均单日使用时长（分钟）", [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026], false);
  setWidths(beike, [18, ...Array(DATE_COLUMNS).fill(12), 12, 12]);
  freezeRows(beike, 2);

  addDictionary(workbook, [
    ["App", "贝壳找房", "", "贝壳核心 App", "否", "固定行"],
    ["App", "链家", "", "链家 App", "否", "固定行"],
    ["App", "贝壳租房", "", "贝壳租房 App", "否", "固定行"],
    ["City", "北京 / 上海 / 天津 / 四川 / 浙江 / 江苏 / 广东", "", "城市或省份拆分", "可扩展", "新增城市需在同一分表下新增行。"],
    ["Metric", "WAU", "万人", "周活用户", "否", ""],
    ["Metric", "Duration", "万分钟", "周使用总时长", "否", ""],
    ["Metric", "AvgTime", "分钟", "人均单日使用时长", "否", ""],
    ["Source", "QuestMobile", "", "QM 数据源", "是", ""],
  ]);

  addValidation(workbook, [
    ["日期", "每个分表数据区的时间列必须填写真实日期，建议按周顺序排列。", "高", "补齐日期后再同步", ""],
    ["分表标题", "WAU（万人）、使用时长（万分钟）、人均单日使用时长（分钟）不要改名。", "高", "如需新增指标，新增独立分表", ""],
    ["行粒度", "核心 App、城市、年份分别保留在独立分表内，不混成长表。", "高", "新增行时保持同一分表粒度", ""],
    ["WoW / YoY", "如填写百分比，可直接填 1.2% 或 0.012。", "中", "同步脚本会统一格式化展示", ""],
  ]);

  await renderWorkbook(workbook, "beike-template", ["QM核心App数据", "QM-贝壳找房", "填写说明", "字段字典", "数据校验"]);
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(templateDir, "贝壳数据填写模板.xlsx"));
}

await buildAiTemplate();
await buildBeikeTemplate();

console.log(`Templates saved to ${templateDir}`);
