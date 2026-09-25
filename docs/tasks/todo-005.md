# todo-005：多知识库、FAQ 与授权管理

| 字段 | 值 |
|---|---|
| id | todo-005 |
| 状态 | in_review |
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

- [x] 核对 002、003 已合入，以 user/agent/admin 和授予/撤销访问状态建立知识资源权限表。
- [x] 先写知识库/FAQ CRUD、跨知识库访问、篡改知识库 ID 与撤权测试，运行确认目标行为尚未实现而失败。
- [x] 实现知识库、授权、FAQ 模型及迁移，明确删除行为和 FAQ 有效状态；所有查询先限定用户可见范围。
- [x] 实现后端 CRUD、输入长度/空内容校验和权限检查；创建 FAQ 时不信任前端传入的创建者、归属或角色；知识库、成员与 FAQ 修改同步调用 001 审计入口。
- [x] 实现知识库列表、详情、FAQ 编辑与授权管理页面；复用 003 的身份与错误处理，首次完成 002/003 真实联调。
- [x] 实现撤权/删除后的即时服务端约束；FAQ 编辑递增 version、indexed_version 不匹配时不可检索、停用即时排除；007 接管共同 chunk/index 链路，本任务不伪造已建向量索引。
- [x] 执行后端集成、前端组件与跨角色 E2E；核对敏感资源不能通过直连 API 访问。
- [x] 独立评审权限、迁移和契约兼容性；更新真实工作记录并提交 `in_review`，按 WORKFLOW 合并收尾。

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
- 上一条对应已推送的阶段提交 `d65f6cc`，不是当前实现状态。其后完成隔离环境：API 8105、Web 5205、DB 15437，Compose project `qa-todo-005-279a22`；独立 .env、数据库卷、backend/.venv 与 frontend/node_modules，不复用其他任务配置。
- 冻结安装 `uv sync --directory backend --frozen --extra dev`、`npm ci --prefix frontend`、Chromium 安装均成功，Python 为 3.12.14；npm audit 报告 0 vulnerabilities。原始日志位于忽略的 .local/，不提交私有连接配置。
- 红绿证据：新增后端 32 项测试在实现前失败（缺失知识接口/有效 FAQ 查询）；FAQ 编辑器 4 项组件测试在空组件时失败；知识浏览器 2 项用例在页面未接入时失败。实现后分别通过，并补充带既有用户的 002→005 升级、降级保留用户和重新升级检查。
- 实现说明与权限矩阵见 [knowledge/README](../../backend/app/modules/knowledge/README.md)。增加管理员专用的停用库列表以支持恢复；普通详情仍排除停用库。FAQ PATCH 同样要求 expected_version，避免覆盖别人的编辑；精确请求已同步 CONTRACTS。本任务没有向量索引和文档上传。
- 2026-09-24 UTC（本地已跨至 09-25），`node scripts/dev.mjs check` 完整运行通过：Ruff、181 pytest、两次 Alembic upgrade、ESLint、vue-tsc、37 Vitest、Vite build、17 Chromium Playwright。浏览器知识用例为真实前后端/数据库链路，包括 user/agent 撤权、非法直连写入、停用恢复与文本转义；桌面和窄屏截图保存在 .local/。最终代码提交后仍将记录对应 SHA 和独立评审结果。
- 测试中修正了非法 Unicode 的 HTTP 构造方式，以及浏览器等待账号加载/SPA 路由完成的时序；没有通过放宽业务断言掩盖权限错误。保留既有 anyio 弃用、Node shell/颜色环境警告，未修改冻结依赖。云端 CI 本轮未运行，不伪记为通过。
- 满足 [WORKFLOW](../WORKFLOW.md) 后任务分支置 `in_review`；合入权威 main 且检查通过，才统一更新 `done`。

### 用户要求暂停（2026-09-25，Asia/Shanghai）

- 用户明确要求暂停，等明早由用户再次发出开始指令后继续；不设置自动恢复或定时任务。
- 最新统一验收为 `.local/full-check-3.log`：exit 0，181 pytest、37 Vitest、17 Playwright，静态检查、构建及迁移通过；`alembic heads` 为单一 `005_knowledge`。该验收对应当前尚未提交的工作树，不能称为远端提交已验收。
- 业务实现、测试和说明文档保留在本 worktree，尚未进行功能提交、独立评审、创建功能 PR 或合并。GitHub 上只有阶段进度提交 `d65f6cc`。
- 任务继续保持 `in_progress`，任务领取记录保留。释放本对话的 shared-files 短时锁，避免暂停期间阻塞其他任务；恢复后重新核实最新 main、claims、共享文件协调与工作树差异。
- 恢复顺序：核实现场 → 检查窄屏截图 → 提交当前功能 → 独立评审并修复必要问题 → 对最终提交验收 → 功能 PR 合并 → 独立状态收尾 PR → 同步 main、释放领取记录。不得跳过评审或将本地通过写成云端 CI 通过。

### 恢复与功能提交（2026-09-25）

- 用户明确要求继续；已核验原领取与工作树，origin/main 仍为 0c346150f572dfa524a8f55a1b4d04adf0812fa4，无其他活跃共享文件锁。恢复本任务共享文件锁并启动 Docker Desktop。
- 已核对最后一次窄屏截图，当前页面与测试代码在暂停后没有变化。功能提交保存已通过 full-check-3 的代码树；恢复后的完整验收与独立评审仍在继续，状态保持 in_review，未宣称完成或合并。
### 独立评审与修复（2026-09-25）

- 评审范围：`0c346150f572dfa524a8f55a1b4d04adf0812fa4..1470f48e90f86badb00da9224433800bbf114e27`，独立只读评审者 `review_todo005`。无 Critical 或 Minor；一项 Important：E2E 假定新知识库在第一页，历史样例累积后会误失败。
- 已在本任务 DB 15437/qa_dev 中建立 21 个精确记录 ID 的临时前置排序样例；旧测试真实失败 2 项（目标不在第一页），修复分页定位后相同环境 2 项通过。未改变业务权限或放宽断言。临时样例仅按其精确 ID 清理，不删除其他数据。
- 评审未发现权限、并发版本或迁移方面的合并阻塞；排除的上传、向量/索引、真实生产容量与授权名单、云端 CI 均属于已批准的后续范围或外部条件，不宣称完成。最终完整检查仍需对应修复后的提交。
