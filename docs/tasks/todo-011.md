# todo-011：回答反馈与处理闭环

| 字段 | 值 |
|---|---|
| id | todo-011 |
| 状态 | done |
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

- [x] 核对 009 已合入，确认可评价消息类型、重复评价规则、理由字段及允许处理角色。
- [x] 先写正常评价、重复提交、篡改 message_id、状态转换和处理权限测试，运行确认目标行为尚未实现而失败。
- [x] 创建反馈模型及约束，关联原始消息和必要版本元数据；定义删除/保留策略使统计不会因前端动作无意失真。
- [x] 实现反馈创建/更新/读取服务；不相信客户端的 user_id 或会话归属，拒绝空白超长纠错内容。
- [x] 实现有授权的处理列表、详情、处理说明与状态转换；写入审计，避免双击处理产生重复变更。
- [x] 在消息界面加入评价和纠错入口，后台提供筛选/详情/处理；显示提交成功、重复状态与错误反馈。
- [x] 执行真实会话下的“提问→评价→处理→回看”E2E 和跨用户越权验证；确认反馈不会自动改变知识答案。
- [x] 独立评审数据归属、重复规则和审计，执行检查并记录；提交 `in_review`，按 WORKFLOW 合并收尾。

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
- 开发阶段011暂接009且仅应用于临时测试 schema；010 的功能 PR #21 / 收尾 PR #22 实际合入后，已整合 origin/main 301f99e，将尚未发布011改接010。public 开发库真实执行009→010→011，重复 upgrade head 与 alembic check 均通过，迁移图仅一个011 head。整合提交2f974186be9c03c4bd60c4357ee4ac827d63ef75；反馈+人工专项后端79项通过（13.37s），相关前端39项及类型检查通过。真实反馈E2E、跨模块并发回归、独立完整评审与统一验收仍待完成。
### 2026-09-26 集成与浏览器专项验收

- 新增真实PG两连接跨模块并发回归：管理员关闭人工会话与处理旧AI回答反馈，分别验证两个操作先取得锁；通过 pg_blocking_pids 确认 User 锁等待，两项均通过且状态/审计一致。后端独立评审另实测同时创建不同评价仅一行一审计，以及删除会话后等待中的反馈提交404；相关19项测试通过（5.53s）。
- 前端14项组件测试、类型检查和ESLint通过；真实浏览器 feedback.spec.ts 1项通过，覆盖提问→评价→管理员处理→本人回看→修改重开→再次提问知识不变、他人404/403。桌面和390px手机截图已检查，无横向溢出。此专项使用真实认证/API/PostgreSQL及专用可复现RAG测试fixture，不代表新增云模型调用。
- 独立评审发现管理员失权后旧反馈内容仍显示，已修复401/403/404清理、同ID角色变化和过期请求防护并加入回归；评审者原始失败用例已通过。完整统一检查及最终评审记录随后补充，当前尚未合并。
### 2026-09-26 最终本地验收与独立评审

- 验收代码提交：3d08f8d69011e3fa5b054062a8b44492903636aa，已整合权威main 301f99e6845a1b8673f1ac7f511135cea09fb914。Windows、Node24.11.0、Python3.12.14、uv0.12.17、Docker29.8.0；冻结依赖安装，隔离PostgreSQL15451/API8121/Web5221。
- `node scripts/dev.mjs check` 退出0：Ruff、609项pytest（75.87s）、Alembic连续两次upgrade、ESLint、类型检查、103项Vitest、生产构建、18项基础Playwright（15.5s）和4项聊天/人工/反馈Playwright（38.2s）全部通过。原始日志留在本worktree `.local/check-final.log`；既有Starlette/AnyIO与Node弃用提示不影响退出结果。
- 独立评审者未参与011实现，完整检查32个变更文件，对3d08f8d出具APPROVED。权限清理修复后3项独立组件复现通过；另有19项后端专项及2组独立真实PG边界验证。文件SHA256与命令保存在 `.local/feedback-full-review.md`。无剩余评审阻断。
- 仍采用WORKFLOW10.1本地验收+GitHub PR；云端CI未运行，未伪写成功检查。本次专项无新增云调用，模型真实接通证据沿用008/009独立记录。此后仅验收文档更改复用上述代码检查；功能PR与main合并状态待实际结果追加。

### 实际合并与收尾

- 功能 PR [#23](https://github.com/cdzdd/aiServerAndModelTraining/pull/23) 已正常 squash 合入 origin/main，功能合并 SHA：49f0c740648512c788b1a9c2b6147259884a58d1。合并后完整树与验收PR head一致，检查证据沿用3d08f8d；后续仅文档更改。
- 本状态收尾通过独立PR，合并后为done。保留任务分支、原生worktree与忽略的验证/截图记录；不删除数据库数据或共享模型缓存。
- 无未解决任务阻塞；云端CI按已批准模式未运行。
