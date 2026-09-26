# todo-012：日志审计查询与管理统计

| 字段 | 值 |
|---|---|
| id | todo-012 |
| 状态 | in_review |
| depends_on | todo-005、todo-010、todo-011 |
| 并行可行性 | 可与 015 实验并行；统计模块不修改既有业务状态机，缺失的审计写入须回到所属模块修复 |
| 负责目录 | `backend/app/modules/analytics/`、`frontend/src/features/analytics/`、审计查询和脱敏测试 |

## 范围、文件与接口

依据 [CONTRACTS](../CONTRACTS.md)聚合已有业务事件，提供管理员审计查询与 ECharts 统计页面。审计写入在 002/005/006/009/010/011 同期实现；本任务检查完整性、实现查询和统计，不把上线前事件缺失当作正常行为。

- 创建 `backend/app/modules/analytics/{schemas,repository,service,router}.py`。
- 创建 `frontend/src/features/analytics/{DashboardPage.vue,AuditLogPage.vue,api.ts}`。
- 创建 `backend/tests/analytics/{test_metrics,test_audit_access,test_log_redaction}.py`、`frontend/src/features/analytics/DashboardPage.test.ts`、`frontend/e2e/admin-stats.spec.ts`。
- 消费知识库/会话/接管/反馈表及审计事件；产出 `/api/v1/admin/stats` 与契约审计查询路由。
- 指标包含问答量、失败/拒答、人工接管、反馈及知识入库状态等契约定义集合；明确时间范围、时区、分子分母和空值。费用只有真实价格配置和 token 数据齐全时才计算，未知值不能当 0。

## 分步执行

- [ ] 核对依赖合入，逐项检查关键操作是否已有审计写入；发现缺失时列出所属模块补丁，不默默用日志猜测补数。
- [ ] 先写固定数据集的指标计算、时间边界、零分母、非管理员访问和密钥脱敏测试，运行确认目标行为失败。
- [ ] 明确定义每项指标的来源、时区和过滤规则，实现只读聚合查询；失败/取消消息不能计作成功回答。
- [ ] 实现管理员审计筛选、分页和详情，最小化展示敏感内容；审计记录保留操作者、资源、动作、结果和时间，默认不存完整密码/密钥或无必要聊天原文。
- [ ] 实现结构化请求/错误日志关联与脱敏测试，确保 provider 错误也不泄露 Authorization；日志保留策略写入部署说明。
- [ ] 用 ECharts 实现趋势与分类统计，空数据有明确状态；前端显示与后端同一指标口径，不自行计算另一套分母。
- [ ] 用人工可核对的固定数据逐项对照 API 与 UI 数值，并验证匿名/user/agent 均不能越权查看管理员统计或审计。
- [ ] 执行相关测试与静态检查，独立评审查询效率、隐私最小化和统计口径；记录并提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 固定 10 条成功、2 条失败、1 条取消的生成记录 | 成功/失败/总量按已记录口径得到可手算结果，不把取消算成功 |
| 跨日边界与不同时区显示 | 归属日期与契约时区一致，筛选范围无重复/漏计 |
| 没有会话或反馈 | 图表显示空状态，比率为空/约定值，不出现 NaN/除零错误 |
| user/agent 直连 admin 统计和审计接口 | 拒绝；前端隐藏菜单不能作为唯一保护 |
| 认证失败、云 API 错误与文件处理异常写日志 | 保留 request_id 和错误类别，不含密码、Cookie、密钥或 Authorization |

```powershell
# backend
uv run pytest tests/analytics/test_metrics.py tests/analytics/test_audit_access.py tests/analytics/test_log_redaction.py -q
uv run pytest
uv run ruff check .
# frontend
npm run test -- --run src/features/analytics/DashboardPage.test.ts
npm run lint
npm run typecheck
npm run build
npm run test:e2e -- --config playwright.analytics.config.ts e2e/admin-stats.spec.ts
```

## 已知问题与外部阻塞

真实成本统计需要用户提供所用模型的价格与生效日期；未提供时展示受理请求数/Token数据与“费用未知”。日志保留时长和生产磁盘预算需部署负责人确定，不能无限保存原始聊天内容。

## 工作记录与完成标准

- 2026-09-26 按用户七项批次授权开始。005/010/011均已done，基线origin/main509ffda04247856010e098b8e4186adbc45e38b1；已复用原生独立worktree todo-012-analytics/aiSoftwareAttempt，分支feat/todo-012-analytics，DB15452/API8122/Web5222。实时领取记录归本批次owner。
- 按本机.local/analytics-plan.md、analytics-api-plan.md、analytics-frontend-plan.md实施：基于现有持久记录的只读统计、严格审计投影与结构化关联日志，采用上海时区/半开区间，未知usage及费用不造数。A后端、B日志、C前端，root整合共享文件/迁移/依赖/验收/PR。此为开工记录，最终验证见下文。
- 按 [WORKFLOW](../WORKFLOW.md) 提交指标口径与测试证据；分支 `in_review`，合入权威 main 且检查通过后统一更新 `done`。

### 2026-09-26 实施与专项验证

- 只读统计按GenerationUsage受理时间及各业务真实时间聚合，使用独立REPEATABLE READ/READ ONLY快照并复核管理员；成功登录、请求/独立提问者、完整/失败/取消/生成中、无答案、耗时/usage缺失、人工、反馈与入库均明确口径。费用保持未知，不估算调用账单。审计按真实生产动作和严格值白名单投影，原值不直接返回。
- 统计/审计初始10行为RED后GREEN，随后补齐快照并发、权限变化、时间/空值/软删及真实动作/元数据边界。独立检查发现数字时间戳被接受、UTC/上海日期转换与末日循环越界，均实证RED后修复。最终后端专项47项通过（25.22s）。固定数据为14请求/3提问用户/10完整/2失败/1取消/1生成中，区分20%无答案与75%满意度。
- 日志初始4行为RED后实现请求上下文、显式SSE关联、后台真实租约关联与提交后失败日志；19专项通过（7.75s），受影响组合172项通过/1项真实分词器配置未加载而跳过，随后最终统一check加载worktree配置，全部675项通过且无跳过，覆盖该真实分词器测试。保留异常类别但不输出正文/凭据，日志输出故障不改变业务结果；仅修正一个既有测试stub以包含真实reservation必需的request_id。
- 前端11组件测试、类型与lint通过；真实浏览器专项1项通过（9.0s），独立随机schema、正式create_app、启动后固定数据，覆盖数值/上海半开范围/真实角色403/旧脏审计原值脱敏；仅清理自身测试schema。桌面/390px截图及趋势图原图已检查。日期重试保留已应用范围、审计筛选重试保留目标页、零数据图表明确空态；均有RED→GREEN回归。
- ECharts官方npm核实6.1.0后固定版本；冻结npm ci通过且锁文件未变化，依赖审计0问题。012迁移仅增加审计(created_at,id)和用量accepted_at索引，实际空库升级、重复升级、alembic check通过且单head012。小样本EXPLAIN选择SeqScan（usage14/audit5，0.016/0.013ms），不据此宣称规模性能。
- root协调入口、迁移、依赖、契约/使用文档和统一检查。Windows/Node24.11.0/Python3.12.14/uv0.12.17/Docker29.8.0，DB15452/API8122/Web5222独立。完整检查及最终独立批准见下文；云端CI按WORKFLOW10.1未运行，无新增云模型调用。
### 2026-09-26 最终本地验收与独立评审

- 验证代码提交：`e10d08c912d14f47b8878c84641282be41fafa18`，基于 `origin/main` `509ffda04247856010e098b8e4186adbc45e38b1`。后续仅本任务记录更改，代码、依赖、迁移与运行配置均未改变，复用本次代码验收。
- 冻结安装：`uv sync --frozen --extra dev --directory backend`、`npm --prefix frontend ci` 均退出0；最后一次npm ci安装307包、审计308包、0漏洞，锁文件哈希未变化。
- 在本worktree执行 `node scripts/dev.mjs check`，退出0：Ruff通过；pytest **675 passed**（110.21s，无跳过）；Alembic upgrade head连续两次通过；ESLint、vue-tsc通过；Vitest **114 passed / 19 files**；生产构建通过；默认Playwright **18 passed**（15.7s）、聊天/人工/反馈 **4 passed**（34.0s）、统计审计 **1 passed**（9.3s）。共23个浏览器测试。
- 统一检查使用本worktree的独立数据库与配置，实际加载指定BGE分词器；真实云模型未在012重复调用。此前008/009已完成真实BGE/DeepSeek链路验证。本次统一检查没有以未运行的云端CI代替本地证据。
- 独立评审 `review_rag` 对上述代码提交 **APPROVED**，完整阅读40个变更文件及相关现有调用方；未解决发现为0。审计筛选后失败重试页码与极端日期溢出均用原始复现验证修复；额外核实只读快照连接归还、多请求同会话不重复计数、366个完整24小时的跨度对应367上海日期的边界。独立证据包含22项日志/真实数据库检查、最终13项日期/数据库检查、11正式组件测试及1原始前端复现通过。
- 既有Starlette/Node弃用提醒和管理员统计懒加载图表块541.73kB（gzip183.97kB）的构建提示均不导致失败；不据小数据集宣称生产规模性能。费用未知和生产日志保留配置限制如上，均已明确展示/文档化，不阻塞本任务验收。
- 原始日志、评审与截图保留在忽略的 `.local/check-final.log`、`.local/analytics-full-review.md`、`.local/admin-stats-desktop.png`、`.local/admin-stats-mobile.png`、`.local/admin-trend-mobile.png`。任务仍为 `in_review`，待功能PR及独立状态收尾PR实际合入后标记 `done`。
