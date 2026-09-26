# todo-009：会话历史、流式问答与引用界面

| 字段 | 值 |
|---|---|
| id | todo-009 |
| 状态 | in_review |
| depends_on | todo-008、todo-003 |
| 并行可行性 | 可与 013、014 并行；本任务拥有 chat 模型和状态机，其他任务通过 RAG/provider 边界协作 |
| 负责目录 | `backend/app/modules/chat/`、`frontend/src/features/chat/`、聊天迁移与 E2E |

## 范围、文件与接口

依据 [CONTRACTS](../CONTRACTS.md)建立会话、消息、历史和流式问答 UI。会话状态为 `bot/queued/human/closed`；消息状态为 `generating/complete/failed/cancelled`。本任务实现 bot 主流程并保留约定交接状态，实际人工接单在 010。

- 创建 `backend/app/modules/chat/{models,schemas,service,router}.py` 和独立迁移。
- 创建 `frontend/src/features/chat/{ChatPage.vue,ConversationList.vue,MessageList.vue,CitationPanel.vue,stream.ts,api.ts}`。
- 创建 `backend/tests/chat/{test_conversation_access,test_message_stream,test_history,test_usage_limits}.py`、`frontend/src/features/chat/stream.test.ts`、`frontend/e2e/chat.spec.ts`。
- 消费 008 的 `actor/kb_ids/question/history` RAG 输入与事件，003 的 Cookie/CSRF API 客户端，002 的归属/接单权限。
- 产出会话 CRUD、`GET /api/v1/conversations/{id}/messages`、`POST /api/v1/conversations/{id}/messages/stream`；流使用 fetch、Cookie、CSRF，事件为 `meta/delta/citations/done/error`，meta 返回两条消息 ID。
- `POST /api/v1/conversations/{id}/messages` 用于 queued/human 文字消息，暂停 AI。精确请求、幂等键与状态转换以契约为准。

## 分步执行

- [x] 核对依赖合入，确认消息持久化、幂等、取消与资源授权契约；建立用户 A/B、接单客服和管理员 fixture。
- [x] 先写会话越权、流事件顺序、重复请求、中途断连与历史恢复测试；前端写网络分片拆分测试，运行确认目标行为失败。
- [x] 创建会话/消息模型与迁移，实现仅本人、接单客服、管理员可见的列表/详情/历史查询；限制传给 RAG 的授权历史。
- [x] 实现 stream POST，先持久化用户/助手占位再发 meta，后续 delta/citations/done/error 与状态写入遵循契约；每个生成请求产生可追溯事件和耗时记录，会话删除等变更同期调用审计入口。
- [x] 实现幂等、同会话并发控制、按用户/时间窗口的调用限流和输出/用量上限；先检查并原子预留额度再调用模型，失败按契约结算。断连取消上游并写 cancelled/failed，重开只读历史。
- [x] 实现历史列表、输入框、流式渲染、停止/失败提示和引用侧栏；Markdown 渲染禁止执行原始脚本，下载引用重新经过权限校验。
- [x] 实现 queued/human 下文字发送而不调用 AI；closed 会话按契约拒绝继续发送，为 010 提供唯一可复用状态入口。
- [x] 使用真实 002 认证完成“登录→新会话→多轮→引用→刷新历史→取消/重试”的 E2E 与越权测试，模型可用受控 fixture；独立评审并记录真实认证和模型替身的边界。
- [x] 更新任务记录和接口文档差异，提交 `in_review`；按 WORKFLOW 完成合并与统一收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 正常发送问题并刷新页面 | meta 先于 delta；最终消息为 complete；刷新得到同一持久消息，无重复内容 |
| user B 或未接单 agent 猜测 A 的会话 ID | 历史、发消息和流接口均拒绝，无历史文本或引用泄露 |
| 相同幂等键双击发送 | 只创建约定的一组消息/生成请求，不重复计费与写入 |
| 浏览器取消/网络断开后重新进入 | 上游停止；消息显示 cancelled/failed，读取历史不会再次生成 |
| queued/human 会话发送文字 | 保存文字供人工处理，provider 调用次数为 0；closed 状态禁止非法继续发送 |
| 删除会话或生成失败 | 保留脱敏审计/请求关联，审计不能包含 Cookie 或模型密钥 |
| 两个并发请求争抢最后一次测试额度 | 只有允许额度内的请求调用 provider，超限返回 429；缺失 token usage 标未知，不当零无限放行 |

流协议断言示例：解析完整事件序列后，首项为 `meta` 且包含 `user_message_id`、`assistant_message_id`；成功流恰有一次 `done`，失败流不可同时以成功 `done` 结束。实际断言应针对 CONTRACTS 的字段结构。

```powershell
# backend
uv run pytest tests/chat/test_conversation_access.py tests/chat/test_message_stream.py tests/chat/test_history.py tests/chat/test_usage_limits.py -q
uv run pytest
uv run ruff check .
# frontend
npm run test -- --run src/features/chat/stream.test.ts
npm run lint
npm run typecheck
npm run build
npm run test:e2e -- --config playwright.chat.config.ts
```

## 已知问题与外部阻塞

真实云模型链路沿用 004/008 配置；CI 采用固定事件服务。反向代理下流式延迟与断连传播在 016/017 补外网验证，本任务必须先有本地 HTTP 集成证据。

生产调用/输出/每日预算由部署者提供，测试使用很小固定上限和可控时钟验证边界。任何费用预算计算必须使用明确价格配置；无价格时限制请求数与 token 上限，不伪造金额。

## 工作记录与完成标准

- 2026-09-26 按用户七项批次授权续领；worktree `C:/Users/Administrator/.codex/worktrees/todo-009-chat/aiSoftwareAttempt`，分支 `feat/todo-009-chat`，基点 `64c100b66b666bda0e3196fefe74c1a4e903cd29`，依赖 003/008 已实际合入。
- 执行本机 `.local/chat-plan.md`；后端持久化、流式接口、前端分工实施，根代理协调共享迁移/配置与统一验收。限额按已接受的 RAG 请求计数（一次改写+回答仍一次），失败/取消不退还，不冒充云供应商调用计费。正文以安全文本显示；当前权限失效的历史引用隐藏整条助手证据并排除出模型历史。管理员可审阅/受控删除，不代用户发起 AI。详细验收证据见下文；功能与状态收尾尚待真实 PR 合并。
- 按 [WORKFLOW](../WORKFLOW.md) 保存事件/状态验证和评审证据；功能分支 `in_review`，合入权威 main 且检查通过后统一更新 `done`。

### 2026-09-26 实施和专项验证

- 实现会话/消息/生成用量三张表与 009 迁移。使用唯一幂等键、会话生成令牌、用户行锁和持久请求额度；按上海自然日限制请求数，失败/取消不退还，实际 token 缺失仍为 null。运行限制为单 API 进程，每会话 1 个、全局默认 2 个生成。
- 流使用真实 Cookie/CSRF 和 POST SSE，发送前复核当前身份、归属、会话状态及来源。完成状态提交后才发送 done；实际 HTTP 断连取消上游，启动恢复遗留生成。正文以文本显示；在可见 delta 前绑定来源快照，撤权后历史隐藏整条证据但保留存储记录。
- 接入历史分页、会话切换/删除、引用鉴权下载、停止及新键重试；queued/human 留言不调用模型，closed 只读。管理员审阅不冒充原用户生成。
- 专项：流协议及真实 Uvicorn/httpx/PG 断连测试 22 项通过；额度测试 18 项通过（含两独立连接反序时间竞争与锁后采样回归）；启动/健康专项 15 项通过。专用浏览器 E2E 1 项通过，真实认证、上传、数据库、下载和撤权，只替换 RAG 输出/向量。桌面及 390px 窄屏截图人工检查无横向溢出。
- 显式运行 `uv run --frozen --directory backend pytest tests/chat/smoke_real_chat.py -q -s` 两次，各 1 项通过（16.04s、9.05s）。使用实际 CPU BGE 固定 revision 和 DeepSeek，完成上传解析/索引、首问、追问、刷新、重复键拒绝及撤权。两轮合计 6 次真实云调用，实际 1734 prompt + 156 completion = 1890 tokens；第二轮在最终来源绑定修复后执行。样本为合成中文 TXT，不能据此声称已完成代表性质量或生产负载评测；未配置价格，不估算金额。
- 独立评审 `/root/review_rag` 已批准；P1 取消后来源丢失、P2 并发额度时间反序、错误提示被历史刷新清空、引用侧栏保留旧原文均已修复。原始真实 PG/RAG 复现及独立后端 12 项、前端 25 项复验通过，无未解决重要问题。脱敏报告在本 worktree `.local/chat-full-review.md`。
- 首次统一检查 Ruff 通过、pytest 527 通过/1 失败，定位为旧知识库权限测试假设目标必在第一页。仅修正测试为逐页断言并加入 20 个排序靠前公共库，保留权限和即时撤销检查；最终统一验收结果另记，不把首次失败算通过。
- 当前模式为本地验收 + GitHub PR，云端 CI 未运行；反向代理/公网断连仍留待 016/017 部署验收。
- 最终 `node scripts/dev.mjs check` 退出 0：Ruff、528 项 pytest（61.72s）、两次迁移 upgrade、ESLint、TypeScript、71 项 Vitest、构建、18 项通用 E2E（15.5s）与 1 项聊天 E2E（12.6s）均通过。环境：Windows、Node 24.11.0、uv 0.12.17、Python 3.12.14、Docker 29.8.0、独立 PostgreSQL/pgvector；冻结依赖。现有 Starlette/Node 弃用及颜色环境警告未影响退出结果。日志为本机 .local/check-final.log，云端 CI 未运行。
