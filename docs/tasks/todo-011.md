# todo-011：回答反馈与处理闭环

| 字段 | 值 |
|---|---|
| id | todo-011 |
| 状态 | in_progress |
| depends_on | todo-009 |
| 并行可行性 | 可与 010 并行；只在反馈模块新增实体，chat 共用字段/路由聚合由指定整合者串行修改 |
| 负责目录 | `backend/app/modules/feedback/`、`frontend/src/features/feedback/`、聊天反馈入口 |

## 范围、文件与接口

依据 [CONTRACTS](../CONTRACTS.md)实现对回答的评价、纠错理由、处理列表、处理状态和说明。反馈关联消息/会话/来源版本，能支持 012 统计和 013 质量分析；反馈不自动写回知识库或进入训练集。

- 创建 `backend/app/modules/feedback/{models,schemas,service,router}.py` 和迁移。
- 创建 `frontend/src/features/feedback/{FeedbackControl.vue,FeedbackListPage.vue,FeedbackDetail.vue,api.ts}`。
- 创建 `backend/tests/feedback/{test_submission,test_access,test_resolution}.py`、`frontend/src/features/feedback/FeedbackControl.test.ts`、`frontend/e2e/feedback.spec.ts`。
- 消费 009 消息与资源授权；产出 `POST /api/v1/messages/{id}/feedback`、`PATCH /api/v1/feedback/{id}`、管理员 `GET/PATCH /api/v1/admin/feedback[/{id}]`（实际为不同路由）。只有消息所属用户可提交自己的反馈，管理员处理，状态为 `open|resolved`。
- 反馈创建、变更和处理同期写审计；012 聚合查询，不回填缺失事件。

## 分步执行

- [ ] 核对 009 已合入，确认可评价消息类型、重复评价规则、理由字段及允许处理角色。
- [ ] 先写正常评价、重复提交、篡改 message_id、状态转换和处理权限测试，运行确认目标行为尚未实现而失败。
- [ ] 创建反馈模型及约束，关联原始消息和必要版本元数据；定义删除/保留策略使统计不会因前端动作无意失真。
- [ ] 实现反馈创建/更新/读取服务；不相信客户端的 user_id 或会话归属，拒绝空白超长纠错内容。
- [ ] 实现有授权的处理列表、详情、处理说明与状态转换；写入审计，避免双击处理产生重复变更。
- [ ] 在消息界面加入评价和纠错入口，后台提供筛选/详情/处理；显示提交成功、重复状态与错误反馈。
- [ ] 执行真实会话下的“提问→评价→处理→回看”E2E 和跨用户越权验证；确认反馈不会自动改变知识答案。
- [ ] 独立评审数据归属、重复规则和审计，执行检查并记录；提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 用户评价自己收到的回答 | 保存正确 message_id、提交者、评价/理由，页面状态持久化 |
| 用户把请求 message_id 改为他人的消息 | 拒绝，无反馈记录和原消息内容泄露 |
| 连续双击或重试同一评价 | 按契约更新/幂等，不能重复增加统计数量 |
| 无处理权限用户修改处理状态 | 拒绝；授权处理者的变更保留时间、身份和说明 |
| 提交反馈后再次询问相同知识 | 不自动把反馈文字当知识或训练数据；原知识内容不变 |

```powershell
# backend
uv run pytest tests/feedback/test_submission.py tests/feedback/test_access.py tests/feedback/test_resolution.py -q
uv run pytest
uv run ruff check .
# frontend
npm run test -- --run src/features/feedback/FeedbackControl.test.ts
npm run lint
npm run typecheck
npm run build
npm run test:e2e -- --config playwright.chat.config.ts feedback.spec.ts
```

## 已知问题与外部阻塞

反馈原因分类与处理用语可使用契约中的最小集合，若用户需扩展则独立评审。不会创建邮件/Slack 通知，不需要第三方工单账号。

## 工作记录与完成标准

- 2026-09-26 按用户七项批次授权开始；依赖009功能PR #19及收尾PR #20已合入，基点32c82516918f22ee009b1254f91df726b5d2e46d。独立worktree：C:/Users/Administrator/.codex/worktrees/todo-011-feedback/aiSoftwareAttempt；分支feat/todo-011-feedback。root协调共享文件和最终验收/PR，分工实现独立模块。
- 执行本机 .local/feedback-plan.md；仅本人完整助手消息可评价，重复提交幂等、真实修改后重开，管理员处理；反馈保留并按当前权限投影原回答。验收结果待记录。
- 按 [WORKFLOW](../WORKFLOW.md) 记录验证与评审；分支到 `in_review`，合入权威 main 且检查通过后统一更新 `done`。

### 2026-09-26 后端实施与专项记录

- Feedback 独立实体唯一(user_id,message_id)，仅本人 complete 助手回复可评价；源版本仅取服务端存储引用的身份字段。相同 POST/PATCH/处理重试幂等，真实修改重开并清理旧处理信息；软删会话后保留反馈统计与处理记录，原用户不可继续读写，管理员也不返回已删原回答。
- API 已接提交/本人读取/修改及管理员列表、详情、处理/重开。现存原回答复用 chat.visible_messages 当前授权投影；评论/处理说明采用严格文本校验、仅作为反馈数据，不写回知识或训练。审计与业务变更同事务，不含评论/处理说明/引文原文。
- Schema 测试 7 项先因缺失实现失败后通过；实际 HTTP 提交及处理行为先为404，再实现至41项通过。补审计写入失败的创建/处理回滚、第二连接提交账号停用/降级、并发作者修改/管理员处理及任意角色仅评价自己回答后，`.venv/Scripts/python.exe -m pytest tests/feedback -q --tb=short`（backend 目录）49项通过（9.71s），Ruff check/format通过。均使用真实 PostgreSQL 随机隔离 schema；未调用云模型。
- 011 迁移开发阶段暂接009，仅用于测试临时 schema。public 开发库保持009，待010实际合入后整合其迁移并将尚未发布011接到010，再做真实升级和统一验收，避免已标记011的库漏掉010表。前端、E2E和独立集成评审仍待完成。