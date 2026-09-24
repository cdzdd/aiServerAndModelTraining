# todo-005：多知识库、FAQ 与授权管理

| 字段 | 值 |
|---|---|
| id | todo-005 |
| 状态 | in_progress |
| depends_on | todo-002、todo-003 |
| 并行可行性 | 可与 016 并行；本任务拥有知识模型和对应迁移，部署任务不得并行修改这些结构 |
| 负责目录 | `backend/app/modules/knowledge/`、`frontend/src/features/knowledge/`、知识库迁移与测试 |

## 范围、文件与接口

阅读 [ARCHITECTURE](../ARCHITECTURE.md)、[CONTRACTS](../CONTRACTS.md)、[WORKFLOW](../WORKFLOW.md)。实现单一组织内多个知识库的管理、授权与 FAQ CRUD；FAQ 后续作为可检索知识源。文档上传与解析属于 006。

- 创建 `backend/app/modules/knowledge/{models,schemas,service,router,permissions}.py`。
- 创建 `frontend/src/features/knowledge/{KnowledgeListPage.vue,KnowledgeDetailPage.vue,FaqEditor.vue,api.ts}`。
- 创建 `backend/tests/knowledge/test_knowledge_access.py`、`test_faqs.py`、`frontend/src/features/knowledge/FaqEditor.test.ts`、`frontend/e2e/knowledge.spec.ts`，添加独立迁移。
- 消费 002 当前用户/CSRF/授权规则与 003 API 客户端；产出 `/api/v1/knowledge-bases`、知识库详情、`/api/v1/knowledge-bases/{id}/faqs` 及授权接口，精确请求以 CONTRACTS 为准。
- 给 006/007 提供统一知识范围与有效 FAQ 查询；任何 FAQ 修改后的索引更新遵循契约，不能让撤权或删除内容继续检索到。

## 分步执行

- [ ] 核对 002、003 已合入，以 user/agent/admin 和授予/撤销访问状态建立知识资源权限表。
- [ ] 先写知识库/FAQ CRUD、跨知识库访问、篡改知识库 ID 与撤权测试，运行确认目标行为尚未实现而失败。
- [ ] 实现知识库、授权、FAQ 模型及迁移，明确删除行为和 FAQ 有效状态；所有查询先限定用户可见范围。
- [ ] 实现后端 CRUD、输入长度/空内容校验和权限检查；创建 FAQ 时不信任前端传入的创建者、归属或角色；知识库、成员与 FAQ 修改同步调用 001 审计入口。
- [ ] 实现知识库列表、详情、FAQ 编辑与授权管理页面；复用 003 的身份与错误处理，首次完成 002/003 真实联调。
- [ ] 实现撤权/删除后的即时服务端约束；FAQ 编辑递增 version、indexed_version 不匹配时不可检索、停用即时排除；007 接管共同 chunk/index 链路，本任务不伪造已建向量索引。
- [ ] 执行后端集成、前端组件与跨角色 E2E；核对敏感资源不能通过直连 API 访问。
- [ ] 独立评审权限、迁移和契约兼容性；更新真实工作记录并提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| admin 创建两个知识库并赋予不同访问范围 | 各用户只看到允许的库，FAQ 不串库 |
| user 修改请求中的知识库 ID | 无权限时拒绝，数据库没有越权写入 |
| 有管理权限者新增/编辑/停用 FAQ | 页面和 API 状态一致；空问题/答案被明确拒绝 |
| 撤销访问后继续使用原会话请求详情/FAQ | 服务端立即拒绝，不依赖刷新前端角色 |
| 创建、编辑、删除请求不带合法 CSRF | 被拒绝；合法同源请求成功 |
| 修改知识库/成员/FAQ | 有脱敏审计记录；创建/编辑 FAQ 显示待索引，不误报可检索 |

```powershell
# backend
uv run pytest tests/knowledge/test_knowledge_access.py tests/knowledge/test_faqs.py -q
uv run pytest
uv run ruff check .
uv run alembic upgrade head
uv run alembic heads
# frontend
npm run test -- --run src/features/knowledge/FaqEditor.test.ts
npm run lint
npm run typecheck
npm run build
npm run test:e2e -- e2e/knowledge.spec.ts
```

## 已知问题与外部阻塞

真实知识分类和访问名单需用户提供；可用合成知识库验证功能，但上线前应由管理者核对授权。FAQ 与文档的检索合流在 007 完成，本任务仅提供持久化内容与稳定版本信息。

## 工作记录与完成标准

- 2026-09-24（UTC）接手：已读取 AGENTS、README、任务索引、WORKFLOW、架构与契约；fetch 后确认权威 `origin/main` 为 `0c346150f572dfa524a8f55a1b4d04adf0812fa4`，前置 todo-002、003 均已合并并收尾为 done，主工作区干净。
- 已通过 Git common directory 的协调记录原子领取；负责人为本次 Codex 接手对话。原生独立 worktree：`C:/Users/Administrator/.codex/worktrees/todo-005-knowledge/aiSoftwareAttempt`；功能分支：`feat/todo-005-knowledge`。
- 环境预检：Node 24.11.0、uv 0.12.17、Docker Engine 29.8.0 可用，GitHub CLI 已认证且 fetch 成功。初次沙箱限制导致的访问失败已在授权后复核；尚未完成本 worktree 的依赖安装、数据库隔离与 Python 3.12 验证。
- 开发依据：仅管理员管理知识库、成员和 FAQ；user/agent 只读获授权内容；撤权即时生效，FAQ 变更递增版本并显示待索引。默认使用明确标注为虚构的校园服务样例；真实分类、资料和成员名单可后续提供，不阻塞功能开发验收。
- 本次为用户要求的阶段性进度提交：尚未实现业务代码，未运行本任务测试、独立评审或 PR 合并。下一步准备隔离环境，先建立权限与 FAQ 行为失败测试，再实现并按本地验收规范完成评审、功能 PR 和独立状态收尾 PR。
- 满足 [WORKFLOW](../WORKFLOW.md) 后任务分支置 `in_review`；合入权威 main 且检查通过，才统一更新 `done`。
