## 使用边界

News API 只提供已入库 RSS 和白名单微信公众号文章的数据读取。它不触发采集、不刷新来源、不生成摘要或日报，也不会返回热榜、采集会话、内部账号、游标原文或日志。

## 基础地址与发现

服务地址：`https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api`

- [OpenAPI 3.1](https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api/openapi.yaml)
- [Agent guide (llms.txt)](https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api/llms.txt)
- [Health check](https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api/health)

`/health`、OpenAPI 和 Agent guide 可公开读取。所有数据接口必须使用服务端发放的 API Key。

## 鉴权

在所有受保护请求中发送：

```http
Authorization: Bearer <NEWS_API_KEY>
```

将 Key 保存在 Agent 的密钥管理或环境变量中。不要写入源码、URL、浏览器存储、提示词或日志。页面中的调试控制台只在当前页面内存中使用输入的 Key。

## Agent 工作流

1. 使用 `GET /api/v1/sources` 发现可用 RSS 与微信公众号来源。
2. 需要逐批处理新入库新闻时，先调用 `GET /api/v1/news/increments` 获取最新非空批次，再通过 `previousBatchId` 向前读取历史批次。
3. 简单查询使用 `GET /api/v1/news`；多关键词、多来源或复杂过滤使用 `POST /api/v1/news/search`。
4. 默认请求 `view=standard`。仅在任务确实需要正文时请求 `view=full`；只有明确需要时才设置 `includeHtml=true`。
5. 将 `data.page.nextCursor` 视为不透明值原样带回，并保持所有过滤条件和排序不变。增量批次翻页时必须同时固定 `batchId`。
6. 已知单篇 ID 使用详情接口；已知多个 ID 时才使用批量接口。

## 接口目录

| Method | Path | 权限 | 用途 |
| --- | --- | --- | --- |
| GET | `/health` | Public | 健康检查 |
| GET | `/api/v1/sources` | Bearer Key | 来源发现 |
| GET | `/api/v1/news` | Bearer Key | URL 参数检索 |
| GET | `/api/v1/news/increments` | Bearer Key | 按抓取批次读取首次入库新闻 |
| POST | `/api/v1/news/search` | Bearer Key | 结构化检索 |
| GET | `/api/v1/news/{id}` | Bearer Key | 单篇正文读取 |
| POST | `/api/v1/news/batch` | Bearer Key | 已知 ID 批量读取 |

## 搜索

`GET /api/v1/news` 支持 `q`、`keywords`、`keywordMode`、`phrase`、`sourceTypes`、`sourceIds`、`sourceNames`、`publishedFrom`、`publishedTo`、`changedAfter`、`minAiScore`、`sortField`、`sortDirection`、`limit`、`cursor`、`view` 和 `includeHtml`。

关键词默认搜索标题、摘要和正文。`keywordMode` 支持 `any`、`all`、`phrase`；`phrase` 模式应使用 `phrase` 参数或以空格连接关键词。

```bash
curl --request GET \
  'https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api/api/v1/news?phrase=WAIC+具身智能&keywordMode=phrase&view=standard&limit=30' \
  --header 'Authorization: Bearer $NEWS_API_KEY'
```

复杂查询使用 `POST /api/v1/news/search`：

```json
{
  "keywords": ["WAIC", "具身智能"],
  "keywordMode": "any",
  "sourceTypes": ["rss", "wechat"],
  "view": "standard",
  "page": { "limit": 30 }
}
```

## 抓取批次增量

不提供 `batchId` 时，接口默认返回最近一个实际产生 RSS 或白名单公众号新增文章的批次：

```bash
curl --request GET \
  'https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api/api/v1/news/increments?view=standard&limit=30' \
  --header 'Authorization: Bearer $NEWS_API_KEY'
```

查询指定历史批次时传入响应中的 `data.batch.id` 或 `data.batch.previousBatchId`：

```bash
curl --request GET \
  'https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api/api/v1/news/increments?batchId=run_20260724090000_deadbeef&view=full&limit=20' \
  --header 'Authorization: Bearer $NEWS_API_KEY'
```

`data.batch` 包含 `id`、`runAt`、`newCount`、`status` 和 `previousBatchId`。`status=partial` 表示该轮存在部分来源失败，但返回的文章已经成功入库。零增量运行不会成为默认最新批次。

批次内分页继续使用 `data.page.nextCursor`。后续请求必须同时传入当前 `data.batch.id` 作为 `batchId`，否则服务端拒绝游标请求。批次历史与新闻记录均保留 180 天。

## 正文与批量读取

详情接口默认返回纯文本正文和 `contentStatus`。`includeHtml=true` 只在内容可用时返回已清洗的 `contentHtml`。

批量接口按请求 ID 的顺序返回结果：

```json
{
  "ids": ["article-id-1", "article-id-2"],
  "includeContent": true,
  "includeHtml": false,
  "view": "full"
}
```

## 分页、视图与限制

- 普通搜索默认 30 条，`compact` 与 `standard` 最多 100 条。
- `full` 搜索默认且最多 20 条；请求 HTML 时同样使用 `full`。
- 纯元数据批量最多 100 条；返回正文最多 20 条；返回 HTML 最多 5 条。
- 对宽泛的正文搜索应增加时间或来源限制。
- 服务端始终限制为 RSS 和微信公众号数据范围。

视图字段稳定：`compact` 用于扫描；`standard` 用于常规检索；`full` 返回 `contentText`。`contentHtml` 只在显式 `includeHtml=true` 时出现。

## 内容状态与错误处理

`contentStatus` 可能是 `available`、`partial`、`pending` 或 `unavailable`。后面三种是数据状态，不代表 API 调用失败。

| Code | 处理方式 |
| --- | --- |
| `INVALID_ARGUMENT` / `INVALID_CURSOR` | 修正参数或游标，不要原样重试。 |
| `UNAUTHORIZED` | 检查 Bearer Key。 |
| `NEWS_NOT_FOUND` | 文章不存在或不在允许的数据范围。 |
| `BATCH_NOT_FOUND` | 批次不存在、已过保留期或没有公开 RSS/公众号增量。 |
| `QUERY_TOO_BROAD` / `RESPONSE_TOO_LARGE` | 缩小时间、来源或条数，移除 HTML。 |
| `DATABASE_UNAVAILABLE` / `INTERNAL_ERROR` | 仅在 `retryable=true` 时指数退避重试。 |

所有响应均使用 `ok`、`data` 或 `error`、`meta` 包装。`meta` 包含 `requestId`、`generatedAt` 和 `schemaVersion`；搜索响应额外包含 `data.page.nextCursor` 与 `hasMore`。
