# 实施任务

- [x] 1. 完成技术方案与仓库边界确认
  - 固定 CloudRun 容器、GitHub Actions 调度、CloudBase NoSQL 会话与 MySQL 游标方案
  - 明确两个仓库的修改范围和环境变量
  - _需求：1、7、8_

- [x] 2. 实现 CloudRun 会话持久化
  - 新增 CloudBase NoSQL 会话仓库
  - 保留本地 Nitro KV 回退
  - 登录成功后自动绑定当前采集会话
  - _需求：1、7_

- [x] 3. 实现 CloudRun 内部采集 API
  - 实现 API-key 鉴权
  - 实现 health、session、search、articles 接口
  - 增加参数限制与安全错误响应
  - _需求：1、2、3、7_

- [x] 4. 调整 CloudRun 容器与部署文档
  - 确认 PORT、Dockerfile、环境变量和健康检查
  - 增加 CloudBase 部署说明
  - _需求：1、7_

- [x] 5. 实现公众号新闻来源适配器
  - 增加白名单配置与 7 个账号
  - 实现分页、标题关键词筛选、字段映射和失败隔离
  - _需求：2、3、4、5_

- [x] 6. 实现来源游标持久化
  - 新增 cursor 表结构
  - 实现游标读取、成功更新与失败保留
  - _需求：3、7_

- [x] 7. 实现统一 AI 候选去重
  - 对公众号、热榜、RSS 候选执行近似去重
  - 在快报条目中保留关联来源
  - _需求：6_

- [x] 8. 接入 GitHub Actions
  - 给现有新闻任务注入 CloudRun URL 和采集密钥
  - 保持单次统一抓取和一次 AI 快报
  - _需求：8_

- [x] 9. 完善本地测试
  - CloudRun 构建与接口测试
  - 新闻适配器、游标、去重和编排测试
  - _需求：1-8_

- [x] 10. 部署 CloudBase 资源
  - MCP 登录和环境绑定
  - 创建 NoSQL 会话集合、初始化 MySQL 游标表并检查权限
  - 部署和验证 CloudRun
  - _需求：1、7_

- [x] 11. 解析公众号 fakeid 并执行端到端验证
  - 状态：7 个账号解析完成；CloudRun `004`、GitHub Actions、CloudBase 入库和 AI 快报均已验证
  - 扫码登录
  - 搜索并确认 7 个公众号
  - 更新配置并运行同步
  - 验证入库、AI 评分和快报
  - _需求：2-8_

- [x] 12. 并行测试与代码审查
  - 分配独立测试和 review
  - 修复发现的问题并重复验证
  - _需求：1-8_

- [ ] 13. 启用 CloudRun scale-to-zero 与冷启动保护
  - 将最小实例数从 1 调整为 0，保留 1 vCPU / 2 GiB 和最大实例 2
  - 在 GitHub Actions 真实新闻同步前增加 120 秒预算健康预热
  - 给公众号文章请求增加仅针对瞬时错误的有限重试
  - 完成本地、真实 Actions、CloudRun 配置与 CloudBase 数据审计
  - _需求：7、8_
