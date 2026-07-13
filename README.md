# 华泰互联网数据模板

网页数据来自 `templates` 文件夹中的固定 Excel 填写模板。

## 新闻与公众号同步

新闻同步入口为 `python tools/sync_news.py`，由 `.github/workflows/pages.yml` 定时调用。热榜、RSS 和微信公众号在同一轮任务中完成标题关键词筛选、CloudBase 入库、AI 评分和增量快报。

公众号采集依赖 CloudBase CloudRun 服务 `wechat-article-exporter`，需要以下 GitHub Secrets：

- `WECHAT_EXPORTER_BASE_URL`
- `WECHAT_COLLECTOR_API_KEY`

公众号白名单位于 `config/news-sources.json`。确认后的 `fakeid` 和运行游标保存在 CloudBase MySQL 表 `ht_news_wechat_accounts`。微信 Cookie 和 token 仅保存在 CloudBase 服务端会话集合中，不进入本仓库或 GitHub Secrets。

数据库初始化及增量迁移文件：

- `schema/cloudbase-news.sql`
- `schema/cloudbase-news-wechat-migration.sql`

完整需求、技术方案和执行状态见 `specs/wechat-official-account-news/`。

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
