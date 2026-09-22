# todo-010：人工接管、客服接单与会话关闭

| 字段 | 值 |
|---|---|
| id | todo-010 |
| 状态 | pending |
| depends_on | todo-009 |
| 并行可行性 | 可与 011 并行；chat 共享模型/路由聚合改动必须串行协调，本任务拥有交接状态机 |
| 负责目录 | `backend/app/modules/handoff/`、`frontend/src/features/handoff/`、必要 chat 状态衔接 |

## 范围、文件与接口

依据 [CONTRACTS](../CONTRACTS.md)实现用户转人工、最小队列、客服原子接单、人工回复与关闭。会话从 `bot` 进入 `queued`、接单后 `human`、结束为 `closed`；其他允许转换以契约为准。

- 创建 `backend/app/modules/handoff/{models,schemas,service,router}.py`、对应迁移。
- 创建 `frontend/src/features/handoff/{QueuePage.vue,AgentConversationPage.vue,api.ts}`。
- 创建 `backend/tests/handoff/{test_claim_race,test_access,test_state_transitions}.py`、`frontend/e2e/handoff.spec.ts`。
- 消费 009 会话/文字消息入口和生成取消控制；提供 `/api/v1/handoffs` 路由族、接单和关闭行为，精确路径按 CONTRACTS。
- 未接单客服只能看到有限排队元数据，不能读取完整历史；接单后才获得该会话访问权。转人工、接单、关闭事件同期写入审计，012 再查询汇总。

## 分步执行

- [ ] 核对 009 状态与取消机制，冻结合法转换表、接单权限和队列字段；登记共享 chat 文件修改人。
- [ ] 先写两客服同时接单、重复接单、越权读取、转人工期间流仍在输出的竞争测试；运行确认目标行为失败。
- [ ] 创建交接记录与迁移，实现用户发起转人工、队列最小信息查询；请求者只能操作自己的会话。
- [ ] 用数据库事务及条件更新/锁实现单一客服接单；失败竞争者返回契约冲突，不能都获得会话权限。
- [ ] 将状态切换与生成取消联动：queued/human 不再启动 AI，进入人工后迟到模型分片不能提交为最终成功消息。
- [ ] 实现客服回复、关闭和管理员允许的管理行为；所有内容查询复用 009 授权，写入转人工/接单/关闭审计事件。
- [ ] 实现用户等待状态、客服队列和会话工作台；用户继续发来的文字能被接单客服看到，显示清楚当前对话主体。
- [ ] 执行并发数据库测试与双浏览器角色 E2E；独立评审状态竞争、最少信息与审计完整性，修复后重跑受影响检查。
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
uv run pytest tests/handoff/test_claim_race.py tests/handoff/test_access.py tests/handoff/test_state_transitions.py -q
uv run pytest tests/chat tests/handoff -q
uv run ruff check .
# frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e -- e2e/handoff.spec.ts
```

接单竞争测试必须使用两个独立数据库会话并发执行；串行调用两次不足以证明原子性。

## 已知问题与外部阻塞

需要至少两份测试客服身份；可在测试 fixture 中创建，不需要真实外部客服系统。通知短信、邮件、第三方工单系统与客服绩效体系不在范围。

## 工作记录与完成标准

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未实施；未验证并发接单或 AI 取消。
- 按 [WORKFLOW](../WORKFLOW.md) 保存竞争测试与角色 E2E 证据；功能分支仅到 `in_review`，合入权威 main 且检查通过后统一收尾为 `done`。
