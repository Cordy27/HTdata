# RSS 与微信公众号聚合查询 API 技术设计

## 架构

```text
RSS feeds -------------------+
                             +-- existing scheduled sync --> CloudBase MySQL
WeChat exporter CloudRun ----+                              |
                                                            v
                                                ht-news-api HTTP Function
                                                            |
                                                            v
                                                     External Agents
```

查询层只读 ht_news_items 和 ht_news_sync_runs；不调用采集器、不生成摘要、不创建后台任务。

## 采集

- RSS 与公众号取消关键词准入，但继续计算 tags/matchedTerms；热榜保持原行为。
- RSS 优先 Feed 正文，不足时有限超时抓取原文。
- 公众号从鉴权内部接口取得正文。
- 单篇失败降级为 partial/unavailable，不阻塞整轮同步。
- 门户和 AI 候选继续使用标签/命中词，避免全量语料改变现有展示。

## 微信 collector

- 继续使用现有 wechat-article-exporter CloudRun 和 WECHAT_COLLECTOR_API_KEY。
- 输出 contentText/contentHtml/contentStatus/contentFetchedAt/contentHash/contentError。
- 不输出 Cookie、token、auth key 或完整上游错误；文章级失败隔离。

## HTTP 云函数

- 名称 ht-news-api；HTTP 类型；Node.js；scf_bootstrap 监听 9000；超时 30 秒。
- 单函数路由，数据库访问层可注入测试。
- /health 外全部 Bearer API Key 鉴权。

## 数据结构

ht_news_items 增加 content_text MEDIUMTEXT、content_html MEDIUMTEXT、content_status VARCHAR(24)、content_fetched_at DATETIME、content_hash CHAR(64)、content_error VARCHAR(500) 和 first_seen_run_id VARCHAR(64)，并增加来源/发布时间/更新时间/批次组合索引。

ht_news_sync_runs 增加 public_new_count INT，用于区分公开 RSS/公众号增量与内部热榜条目。同步开始时生成 run_id；首次入库的公开新闻写入 first_seen_run_id，后续重复观察和正文/评分更新保持该字段不变。历史数据通过 first_seen_at = run_at 回填，批次运行与新闻统一保留 180 天。

中文关键词第一期使用受限时间范围的数据库字符串过滤和应用层组合；部署时单独验证 CloudBase MySQL ngram FULLTEXT 支持，不在未知能力上阻塞基础 API。

## 路由

- GET /health
- GET /api/v1/sources
- GET /api/v1/news
- GET /api/v1/news/increments
- POST /api/v1/news/search
- GET /api/v1/news/{id}
- POST /api/v1/news/batch

公开字段使用 camelCase；_openid、fakeid、同步游标、运行日志和原始 AI 响应不映射到响应。

GET /api/v1/news/increments 在未传 batchId 时解析最近一个 public_new_count > 0 的批次；传 batchId 时直接解析不可变批次。响应包含批次元数据、该批次新闻列表、nextCursor 和 previousBatchId。批次状态 ok 映射为 complete，其他已入库运行映射为 partial；不存在或没有公开增量的批次返回 BATCH_NOT_FOUND。

## 搜索与游标

支持 keywords、keywordMode(any/all/phrase)、keywordFields(title/summary/content)、来源、发布时间、changedAfter、正文状态、标签、命中词、AI 分数、视图和 includeHtml。游标包含排序值、ID、查询哈希和快照时间；过滤条件不匹配时拒绝。

## 正文清洗与安全

删除 script/style/noscript/iframe/object/embed、on* 属性和危险协议；规范化纯文本并基于其计算 SHA-256。服务端强制 source_type 仅 RSS/公众号；限制关键词、时间范围、页大小、ID 和正文响应数；不支持任意 URL 抓取、SQL 片段或调用采集器；日志不记录正文和完整 Authorization。

稳定错误码包括 INVALID_ARGUMENT、INVALID_CURSOR、UNAUTHORIZED、QUERY_TOO_BROAD、NEWS_NOT_FOUND、DATABASE_UNAVAILABLE、INTERNAL_ERROR。

## 测试和部署

覆盖 RSS/公众号全量入库与正文降级、首次入库批次保持、历史回填、API 鉴权/来源限制/关键词/游标/批次增量/批量边界、collector 凭据泄漏、schema 兼容和部署后端到端查询。顺序为本地审计、MySQL 迁移、同步函数更新、HTTP 云函数部署和真实 API 验收。
