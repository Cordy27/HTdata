# RSS 与微信公众号聚合查询 API 实施计划

- [x] 1. 确认产品边界
- [x] 2. 扩展数据库正文结构和查询索引并验证安全规则
- [x] 3. 修改 RSS 全量采集、正文提取和失败隔离
- [x] 4. 修改公众号全量采集和 collector 正文接口
- [x] 5. 保持热榜、门户和 AI 快报兼容，数据保留改为 180 天
- [x] 6. 实现 ht-news-api HTTP 云函数、鉴权、查询、游标、批量和 OpenAPI
- [x] 7. 执行 Python、collector、HTTP Function 和现有回归测试
- [x] 8. 独立执行安全、搜索分页、迁移兼容审计并修复
- [x] 9. 应用 MySQL 迁移、更新 collector、部署 HTTP Function 并真实验收
- [x] 10. 更新 README、审计记录和任务状态
- [x] 11. 确认抓取批次增量产品口径和 first_seen_run_id 关联方案
- [x] 12. 增加批次字段、历史回填和 180 天运行记录清理
- [x] 13. 修改同步链路生成 run_id 并标记公开首次入库新闻
- [x] 14. 实现 GET /api/v1/news/increments、批次游标和错误契约
- [x] 15. 更新 OpenAPI、llms.txt、门户 Markdown 和请求控制台
- [x] 16. 执行本地回归、CloudBase 迁移部署和线上端到端验收
