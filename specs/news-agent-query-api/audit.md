# RSS 与微信公众号聚合查询 API 审计记录

## 结论

实现、迁移、部署和真实环境验收已完成。最终独立审计未发现剩余高风险或中风险问题；发现的问题均已修复并重新测试。

## 已修复事项

- RSS/Hacker News 外链正文抓取增加逐跳 DNS 公网校验、固定解析 IP、原始 Host/TLS SNI 和重定向复核，防止 SSRF 与 DNS 重绑定。
- 微信正文增加流式字节上限、超时中止、HTML/XSS 清洗，并移除 URL 凭据、会话参数和危险协议。
- 正文列统一为 `utf8mb4_0900_ai_ci`，支持 emoji 和其他四字节字符。
- API 时间过滤统一转换为上海时区 MySQL `DATETIME`；发布时间排序使用非空 `effective_published_at`。
- 来源扫描包含主键，避免 CloudBase REST 对重复投影行去重后造成来源计数错误。
- 游标绑定查询条件、排序和快照；篡改或跨过滤器使用会被拒绝。
- 查询、详情和批量均在仓储层强制限制为 RSS 与公众号，不接受客户端绕过。
- 批量、关键词、来源、正文和响应字节数均设置上限；默认响应不返回 HTML。
- 历史正文回填排除已有正文的 partial 记录，避免有限回填队列被重复占用。
- 公众号 collector 响应增加总字节上限；正文分页从 20 个消息组降为 5 个消息组。分页严格使用 `page.nextBegin` 按消息组推进，不受单组展开文章数量影响。
- 正文页增加 45 秒总预算，未完成正文降级为 unavailable 但保留全部元数据。`wechat-article-exporter-008` 生产实测 `size=20` 展开 96 篇并在 47.8 秒返回 200，其中 53 篇正文可用、43 篇按预算降级。
- `wechatRecoveryOnly` 在云函数入口和同步服务层均要求明确的账号 ID，避免服务层直调扩大恢复范围。

## 测试与真实验收

- 门户完整 Python 测试：71 项通过。
- 查询 HTTP 云函数测试：29 项通过。
- 微信 exporter 测试：32 项通过；Nuxt 生产构建成功。
- CloudRun：`wechat-article-exporter-008`，1 vCPU / 2 GiB，`MinNum=0`、`MaxNum=2`。
- 单账号云头条恢复：34.8 秒完成，26 篇候选、7 条新增入库、0 个问题。
- 公网 API：健康检查 200，无 Key 401；16 个来源且仅包含 rss/wechat；列表、第二页游标、详情正文、批量和正文关键词搜索均成功；默认不返回 HTML。
- 批次增量 API：默认最新批次、指定 `batchId` 和 `previousBatchId` 均返回 200；最新真实同步批次写入 72 条公开新闻，API 映射为 `partial`，抽样正文可读取。
- 最终批次一致性：公开新闻均有 `first_seen_run_id`，不存在孤立批次引用，`public_new_count` 与实际批次新闻数全部一致。

## 部署资源

- CloudBase 环境：`test-4gcfvxy0640ef41a`
- 同步函数：`ht-news-sync`，Python3.10 Event Function，处理函数 `index.main`
- 查询函数：`ht-news-api`，Nodejs18.15 HTTP Function，端口 9000
- API 地址：`https://test-4gcfvxy0640ef41a.service.tcloudbase.com/news-api`

密钥仅保存在 CloudBase 环境变量或被 Git 忽略的本地环境文件中，未写入仓库。
