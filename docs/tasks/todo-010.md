# todo-010：人工接管、客服接单与会话关闭

| 字段 | 值 |
|---|---|
| id | todo-010 |
| 状态 | in_review |
| depends_on | todo-009 |
| 并行可行性 | 可与 011 并行；chat 共享模型/路由聚合改动必须串行协调，本任务拥有交接状态机 |
| 负责目录 | `backend/app/modules/handoff/`、`frontend/src/features/handoff/`、必要 chat 状态衔接 |

## 范围、文件与接口

依据 [CONTRACTS](../CONTRACTS.md)实现用户转人工、最小队列、客服原子接单、人工回复与关闭。会话从 `bot` 进入 `queued`、接单后 `human`、结束为 `closed`；其他允许转换以契约为准。

- 创建 `backend/app/modules/handoff/{models,schemas,service,router}.py`、对应迁移。
- 创建 `frontend/src/features/handoff/{QueuePage.vue,AgentConversationPage.vue,api.ts}`。
- 创建 `backend/tests/handoff/{test_state_transitions,test_http_handoff}.py`、`frontend/e2e/handoff.spec.ts`。
- 消费 009 会话/文字消息入口和生成取消控制；提供 `/api/v1/handoffs` 路由族、接单和关闭行为，精确路径按 CONTRACTS。
- 未接单客服只能看到有限排队元数据，不能读取完整历史；接单后才获得该会话访问权。转人工、接单、关闭事件同期写入审计，012 再查询汇总。

## 分步执行

- [x] 核对 009 状态与取消机制，冻结合法转换表、接单权限和队列字段；登记共享 chat 文件修改人。
- [x] 先写两客服同时接单、重复接单、越权读取、转人工期间流仍在输出的竞争测试；运行确认目标行为失败。
- [x] 创建交接记录与迁移，实现用户发起转人工、队列最小信息查询；请求者只能操作自己的会话。
- [x] 用数据库事务及条件更新/锁实现单一客服接单；失败竞争者返回契约冲突，不能都获得会话权限。
- [x] 将状态切换与生成取消联动：queued/human 不再启动 AI，进入人工后迟到模型分片不能提交为最终成功消息。
- [x] 实现客服回复、关闭和管理员允许的管理行为；所有内容查询复用 009 授权，写入转人工/接单/关闭审计事件。
- [x] 实现用户等待状态、客服队列和会话工作台；用户继续发来的文字能被接单客服看到，显示清楚当前对话主体。
- [x] 执行并发数据库测试与双浏览器角色 E2E；独立评审状态竞争、最少信息与审计完整性，修复后重跑受影响检查。
- [ ] 记录真实命令和结果，提交 `in_review`；按 WORKFLOW 合并并统一更新状态。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 两名 agent 同时领取同一 queued 会话 | 只有一名成功；数据库只有一个 assignee，另一名无历史访问权 |
| 未接单 agent 直接请求完整会话 | 被拒绝，排队列表也不泄露完整消息/文件 |
| bot 正在生成时用户转人工 | 会话进入 queued，AI 被取消，迟到分片不能标 complete |
| human 状态用户与接单客服往返文字 | 双方可见正确历史，provider 调用数不增加 |
| 关闭后继续回复或重复关闭 | 按契约拒绝或幂等处理，无重复审计与非法状态回退 |

```powershell
# backend
uv run pytest tests/handoff -q
uv run pytest tests/chat tests/handoff -q
uv run ruff check .
# frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e -- --config playwright.chat.config.ts handoff.spec.ts
```

接单竞争测试必须使用两个独立数据库会话并发执行；串行调用两次不足以证明原子性。

## 已知问题与外部阻塞

需要至少两份测试客服身份；可在测试 fixture 中创建，不需要真实外部客服系统。通知短信、邮件、第三方工单系统与客服绩效体系不在范围。

## 工作记录与完成标准

- 2026-09-26 按用户七项批次授权开始；依赖009功能PR #19及收尾PR #20已合入，基点32c82516918f22ee009b1254f91df726b5d2e46d。独立worktree：C:/Users/Administrator/.codex/worktrees/todo-010-handoff/aiSoftwareAttempt；分支feat/todo-010-handoff。root协调共享文件和最终验收/PR，分工实现独立模块。
- 按本机 .local/handoff-plan.md 与 handoff-frontend-plan.md 实施：不重复创建 chat 状态机；排队只暴露最小元数据，接单以数据库事务串行竞争，提交后取消旧生成。实际验证结果如下。
- 按 [WORKFLOW](../WORKFLOW.md) 保存竞争测试与角色 E2E 证据；功能分支仅到 `in_review`，合入权威 main 且检查通过后统一收尾为 `done`。

### 2026-09-26 实施和专项记录

- Handoff 仅保存唯一会话的申请/接单/关闭时间与身份，复用 Conversation 唯一状态和 chat.transition_mode。010 迁移 parent009，空库升级、重复升级和 alembic check 均通过；未新增依赖或外部客服服务。
- 后端先有缺失服务 RED，首批实现及测试接口修正后 11 项通过；补真实 HTTP、身份变更、回滚和 CSRF/ready 后 20 项通过。真正两个独立 PostgreSQL 连接/PID 并发接单，只有一胜一409；重复申请只产生一个交接记录和审计。
- 两个真实本地 Uvicorn/httpx 场景覆盖真实认证/数据库：实际 RetrievalService + RAGService + 挂起的受控 provider，在第二连接转人工后，独立连接先观察到 queued，再取消 provider；旧流不发 delta/done且持久消息 cancelled。三 Cookie 客户端验证人工留言/回复/关闭与未接单者404，RAG 调用始终为 0。测试服务均已停止；本任务未新增云模型调用。
- 独立评审发现 P2：陌生用户关闭既有交接为403、未知ID为404，泄露存在性。先新增5项回归得到4失败/1通过，再修复为先校验当前会话可见性；非客服接单在查记录前统一403。全套 handoff 25 项通过（3.68s），精简重复判断后相关身份/存在性9项通过；独立原复现已复核通过。
- 前端重点覆盖生成期间申请、等待/处理中轮询、双向文字及关闭。根代理提前审查指出旧回复/关闭结果会影响切换后的页面、自动刷新丢弃已加载旧页、关闭失败后轮询停止，已由前端补回归并修复；最终 UI、浏览器和独立评审结论如下。
- 独立评审另以真实两连接复现 close/reply 锁环（40P01）：关闭先锁 Conversation 后因外键读取 User，回复先锁 User 再等 Conversation。现统一 User→Conversation→Handoff；request/claim/close 均在首次会话锁前稳定当前身份。新增 close/reply、request/reserve 竞争和三种写入期间账号停用等待测试，全部 handoff 专项30项通过，锁专项5项重复通过；独立无 monkeypatch 的 PostgreSQL 锁等待复验也通过。
- 前端独立评审的 Queue 迟到接单导航、ChatPage 卸载后同会话重入引发旧轮询均已修复；实例/身份作用域检查覆盖成功、失败、409及finally，合法尾斜杠路由仍正常。原3项 RouterView 复现全部通过。客服工作台客户消息标签修正为“用户”，不误称“我”；桌面及390px截图目视核对、无横向滚动。
- `/root/review_rag` 全范围独立评审 APPROVED，无未解决重要问题；报告 `.local/handoff-full-review.md` 保存复现与29个文件版本。前端最终组件专项31项、typecheck/lint通过，真实人工接管浏览器2项通过；全量检查额外覆盖最终标签断言。
- 最终 `node scripts/dev.mjs check` 退出0：Ruff、558项pytest（65.27s）、两次迁移upgrade、ESLint、TypeScript、92项Vitest、构建、18项通用Playwright（15.5s）与3项聊天/接管Playwright（28.5s）全部通过。Windows、Node24.11.0、Python3.12.14、uv0.12.17、Docker29.8.0及隔离PostgreSQL/pgvector，冻结依赖；原始日志`.local/check-final.log`。既有Starlette/Node弃用及颜色变量警告未影响退出结果。
- 本地验收 + GitHub PR模式；云端CI未运行。该任务未新增DeepSeek调用，真实公网代理/外部客服系统均非本任务范围；功能PR实际合并后另建状态收尾PR。
- 通过完整本地验收的代码提交：1d4ecd5a688ab9e390dcdbe0ced0f2803e51f613；后续此条仅补文档，核对格式/链接/事实后复用该代码检查，PR头将另记录。
