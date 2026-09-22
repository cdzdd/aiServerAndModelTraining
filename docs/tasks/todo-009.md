# todo-009：会话历史、流式问答与引用界面

| 字段 | 值 |
|---|---|
| id | todo-009 |
| 状态 | pending |
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

- [ ] 核对依赖合入，确认消息持久化、幂等、取消与资源授权契约；建立用户 A/B、接单客服和管理员 fixture。
- [ ] 先写会话越权、流事件顺序、重复请求、中途断连与历史恢复测试；前端写网络分片拆分测试，运行确认目标行为失败。
- [ ] 创建会话/消息模型与迁移，实现仅本人、接单客服、管理员可见的列表/详情/历史查询；限制传给 RAG 的授权历史。
- [ ] 实现 stream POST，先持久化用户/助手占位再发 meta，后续 delta/citations/done/error 与状态写入遵循契约；每个生成请求产生可追溯事件和耗时记录，会话删除等变更同期调用审计入口。
- [ ] 实现幂等、同会话并发控制、按用户/时间窗口的调用限流和输出/用量上限；先检查并原子预留额度再调用模型，失败按契约结算。断连取消上游并写 cancelled/failed，重开只读历史。
- [ ] 实现历史列表、输入框、流式渲染、停止/失败提示和引用侧栏；Markdown 渲染禁止执行原始脚本，下载引用重新经过权限校验。
- [ ] 实现 queued/human 下文字发送而不调用 AI；closed 会话按契约拒绝继续发送，为 010 提供唯一可复用状态入口。
- [ ] 使用真实 002 认证完成“登录→新会话→多轮→引用→刷新历史→取消/重试”的 E2E 与越权测试，模型可用受控 fixture；独立评审并记录真实认证和模型替身的边界。
- [ ] 更新任务记录和接口文档差异，提交 `in_review`；按 WORKFLOW 完成合并与统一收尾。

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
npm run test:e2e -- e2e/chat.spec.ts
```

## 已知问题与外部阻塞

真实云模型链路沿用 004/008 配置；CI 采用固定事件服务。反向代理下流式延迟与断连传播在 016/017 补外网验证，本任务必须先有本地 HTTP 集成证据。

生产调用/输出/每日预算由部署者提供，测试使用很小固定上限和可控时钟验证边界。任何费用预算计算必须使用明确价格配置；无价格时限制请求数与 token 上限，不伪造金额。

## 工作记录与完成标准

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未实施；没有流式、权限、浏览器或历史验证结果。
- 按 [WORKFLOW](../WORKFLOW.md) 保存事件/状态验证和评审证据；功能分支 `in_review`，合入权威 main 且检查通过后统一更新 `done`。
