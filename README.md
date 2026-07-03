# 华泰互联网组真实数据门户

本门户通过固定 Excel 填写模板自动同步生成网页数据包，页面只展示模板中的真实数据。

## 目录说明

- `data/`：同步后生成 `portal-data.js`，网页只读取这个数据包
- `templates/AI产品数据填写模板.xlsx`：AI 产品数据填写模板
- `templates/贝壳数据填写模板.xlsx`：贝壳 QM 数据填写模板
- `tools/sync_data.py`：读取固定模板并生成 `data/portal-data.js`
- `tools/server.py`：启动本地服务，启动前自动同步
- `启动数据门户.bat`：Windows 一键启动入口

## 启动

双击 `启动数据门户.bat`。

服务启动时会自动：

1. 读取 `templates/AI产品数据填写模板.xlsx` 和 `templates/贝壳数据填写模板.xlsx`。
2. 生成 `data/portal-data.js`。
3. 启动本地服务并打开门户。

默认地址是 `http://127.0.0.1:8090/`。如果端口被占用，脚本会自动顺延使用后续端口。

## 数据读取规则

AI 数据：

- 只读取 `templates/AI产品数据填写模板.xlsx`。
- AI 模板为产品分组宽表：ChatGPT、Gemini 各 4 列，分别填写 US DAU、US 人均时长、Global DAU、Global 人均时长。
- 网页明细按指标拆为 `AI 产品 DAU` 和 `AI 产品人均时长` 两张宽表。

贝壳数据：

- 只读取 `templates/贝壳数据填写模板.xlsx`。
- 不读取也不复刻原 Excel 的 sheet1/2 图表输出页。
- 贝壳模板按分表宽表维护，其中 `QM核心App数据`、`QM-贝壳找房` 是同步脚本读取的固定模板页。
- 网页明细直接拆为 `核心 App WAU`、`核心 App 使用总时长`、`城市 WAU`、`历年 WAU`、`历年人均单日使用时长` 五张表。

## 手动同步

在本目录运行：

```powershell
python tools/sync_data.py
```

平时直接重新启动 `启动数据门户.bat` 即会先自动同步，再打开看板。

## 图表视窗

每个图表都带有滑动窗口和缩放视窗：底部/侧边滑块用于拖动时间区间，鼠标滚轮或触控板可缩放，图表右下角可拖拽调整窗口大小。明细表也支持滚动和拖拽调整视窗。
