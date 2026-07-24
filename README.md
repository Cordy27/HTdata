# 华泰互联网数据模板

网页数据来自 `templates` 文件夹中的固定 Excel 填写模板。

## 新闻与公众号同步

新闻同步入口为 `python tools/sync_news.py`。生产环境由 CloudBase Event Function `ht-news-sync` 定时调用；GitHub Actions 仅保留 Pages 发布和显式人工灾备入口。热榜、RSS 和微信公众号在同一轮任务中完成标题关键词筛选、CloudBase 入库、AI 评分和增量快报。

云函数使用 `Python3.10`，线上处理函数为 `index.main`（兼容入口转发到 `main_handler`），每天北京时间 `11:03`、`15:03`、`21:03` 运行。部署包通过 `python tools/build_news_sync_function.py` 生成到 `cloudfunctions/ht-news-sync/`，定时表达式为七段格式 `0 3 11,15,21 * * * *`。

公众号采集依赖 CloudBase CloudRun 服务 `wechat-article-exporter`。`ht-news-sync` 需要以下云函数环境变量：

- `CLOUDBASE_ENV_ID`
- `CLOUDBASE_API_KEY`
- `AI_API_KEY`
- `AI_BASE_URL`
- `AI_MODEL`
- `WECHAT_EXPORTER_BASE_URL`
- `WECHAT_COLLECTOR_API_KEY`

常规同步由 handler 固定启用 `AI_REQUIRED=1`，确保 AI 评分或快报失败时函数不会静默成功。密钥只进入 CloudBase 函数配置，不进入部署包或仓库。

GitHub Actions 的显式人工灾备入口仍使用以下 GitHub Secrets：

- `CLOUDBASE_ENV_ID`
- `CLOUDBASE_API_KEY`（也兼容 `CLOUDBASE_ACCESS_TOKEN` 或 `CLOUDBASE_TOKEN`）
- `AI_API_KEY`
- `AI_BASE_URL`
- `AI_MODEL`
- `WECHAT_EXPORTER_BASE_URL`
- `WECHAT_COLLECTOR_API_KEY`

公众号白名单位于 `config/news-sources.json`。确认后的 `fakeid` 和运行游标保存在 CloudBase MySQL 表 `ht_news_wechat_accounts`。微信 Cookie 和 token 仅保存在 CloudBase 服务端会话集合中，不进入本仓库或 GitHub Secrets。

CloudRun 最小实例数为 `0`。CloudBase 定时云函数直接调用采集服务，公众号客户端会对网络超时及 HTTP 502/503/504 做有限退避重试，以覆盖缩容到零后的冷启动。GitHub Actions 的 `/api/health` 预热仅保留给显式人工灾备刷新；只执行 `force_news_brief` 时直接使用已入库新闻，不依赖采集服务预热。

微信公众号文章接口的 `size` 表示消息组数，一组可能包含多篇文章。生产配置使用 `pageSize=5` 并继续按 `begin/size` 分页，在不改变游标语义的前提下限制单次正文抓取时长，避免大批量正文请求超过云函数的 60 秒账号级读取上限。

新闻库使用 `storageMaxItems` 控制数据库保留量，门户页面仍固定读取最新 180 条，避免首次接入多个公众号时因展示上限裁掉已命中的入库记录。

数据库初始化及增量迁移文件：

- `schema/cloudbase-news.sql`
- `schema/cloudbase-news-wechat-migration.sql`
- `schema/cloudbase-news-content-api-migration.sql`
- `schema/cloudbase-news-batch-migration.sql`

完整需求、技术方案和执行状态见 `specs/wechat-official-account-news/`。

## 新闻查询 API

对外只读接口部署为 CloudBase HTTP 云函数 `ht-news-api`：

- 地址：`https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api`
- 鉴权：除 `GET /health` 外，使用 `Authorization: Bearer <NEWS_API_KEY>`
- 数据范围：配置中的全部 RSS 与白名单微信公众号文章；服务端强制排除热榜和内部数据
- 关键词：作为查询参数，支持标题、摘要、正文以及 `any`、`all`、`phrase` 模式
- 正文：详情和批量接口可读取纯文本；HTML 仅在显式请求时返回

主要路由：

- `GET /api/v1/sources`
- `GET /api/v1/news`
- `GET /api/v1/news/increments`（默认最新非空抓取批次，可用 `batchId` 回查）
- `POST /api/v1/news/search`
- `GET /api/v1/news/{id}`
- `POST /api/v1/news/batch`

普通查询默认每页 30 条、最多 100 条，并返回不透明游标；带正文批量最多 20 条，带 HTML 批量最多 5 条。增量接口按 `first_seen_run_id` 返回每次同步首次入库的 RSS/公众号文章，零增量运行不会成为默认最新批次，批次历史与新闻数据统一保留 180 天。完整参数、响应结构和错误码见 `cloudfunctions/ht-news-api/openapi.yaml` 与 `specs/news-agent-query-api/`。生产 API Key 只保存在本地忽略文件和云函数环境变量中，不得提交或写入文档。

## 模板位置

- `templates/AI产品数据填写模板.xlsx`
- `templates/贝壳数据填写模板.xlsx`

## AI 产品模板

填写文件：`templates/AI产品数据填写模板.xlsx`

填写页：`ChatGPT美国DAU数据`

填写方式：

- `Date` 列填写日期。
- 每个产品保留一组固定列：`US DAU`、`US人均时长`、`Global DAU`、`Global人均时长`。
- 新增 AI 产品时，复制同样的四列结构。
- 不要修改 `Date` 列、产品分组行和指标表头。

## 贝壳模板

填写文件：`templates/贝壳数据填写模板.xlsx`

填写页：

- `QM核心App数据`
- `QM-贝壳找房`

填写方式：

- `QM核心App数据` 填写核心 App 的 `WAU` 和 `使用总时长`。
- `QM-贝壳找房` 填写城市 `WAU`、历年 `WAU`、历年人均单日使用时长。
- 时间列按日期顺序填写。
- 核心 App、城市、年份分别保留在各自分项表内，不要混合到同一张表。
- 不要修改 sheet 名称、分项标题和第一列口径。
