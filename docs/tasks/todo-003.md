# todo-003：前端框架、登录流程与角色页面

| 字段 | 值 |
|---|---|
| id | todo-003 |
| 状态 | in_review |
| depends_on | todo-001 |
| 并行可行性 | 可与 002、004 并行；先用契约 mock 完成，真实认证联调等待 002 合入 |
| 负责目录 | `frontend/src/{app,router,shared}/`、`frontend/src/features/{auth,users}/`、角色布局与前端测试 |

## 范围、文件与接口

依据 [ARCHITECTURE](../ARCHITECTURE.md)、[CONTRACTS](../CONTRACTS.md)建立 Vue 3 + TypeScript + Element Plus 应用布局、用户会话状态、登录/注册页面和 user/agent/admin 导航。未来业务页面有明确挂载点，尚未完成的能力不展示为可用功能。

- 创建 `frontend/src/router/index.ts`、`frontend/src/app/AppLayout.vue`、`frontend/src/shared/api/client.ts`、`frontend/src/shared/api/errors.ts`。
- 创建 `frontend/src/features/auth/{LoginPage.vue,RegisterPage.vue,session.ts}`、`frontend/src/features/users/{UserListPage.vue,UserEditor.vue,api.ts}`、`frontend/src/features/users/UserEditor.test.ts`、`frontend/src/features/auth/session.test.ts`、`frontend/src/router/guards.test.ts`、`frontend/e2e/auth-shell.spec.ts`。
- 消费 002 的 `/api/v1/auth/{register,login,logout,me,csrf}` 契约；依赖图不要求 002，故本任务自动测试由假服务提供完全相同响应。
- API 客户端发送 Cookie、按契约附带 CSRF、统一处理 401/403/网络错误；不存储认证令牌到 localStorage。
- 管理员用户页面消费 `GET /api/v1/admin/users`、`PATCH /api/v1/admin/users/{id}`，提供角色/启停操作；本任务同样使用契约 mock，真实用户管理联调归 016。
- 提供导航和页面容器给 005、009、010、011、012；前端路由守卫只负责体验，不能代替后端鉴权。

## 分步执行

- [x] 核对 001 已合入，登记前端路由聚合文件所有权；整理三种角色的可见入口和未登录重定向规则。
- [x] 先写 session 与 router guard 测试，覆盖刷新恢复登录、401 清除状态、非授权路由；运行并确认目标行为尚未实现而失败。
- [x] 实现同源 API 客户端、CSRF 获取/附带流程、统一错误状态和 Cookie 会话恢复；日志不记录登录密码。
- [x] 实现登录与注册表单、提交禁用、字段错误、退出；恢复跳转只接受站内路径，避免开放重定向。
- [x] 实现全局布局和角色导航、管理员用户列表/角色/启停页面，定义业务 feature 挂载约定；普通用户看不到管理入口，最后管理员保护错误可理解。
- [x] 为加载、空列表、权限不足、网络失败提供可理解界面；手机窄屏可完成登录和基本导航。
- [x] 用契约 mock 执行组件与浏览器测试；本任务可凭前端壳、路由、请求封装及组件/契约测试独立合入，真实登录/用户管理联调由 016、真实聊天身份联调由 009 完成，不能宣称本任务已验证真实登录。
- [x] 执行 lint/typecheck/test/build，进行独立评审；记录真实结果并提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 未登录直接打开受保护路由 | 跳至登录；登录后只回到合法站内目标 |
| 刷新已登录页面 | 通过 `/auth/me` 恢复身份，加载期间不闪现管理员内容 |
| user 输入管理员页面地址 | 显示无权限或回到允许页面，不能靠改前端状态获得后端权限 |
| 401、403、断网 | 分别显示登录失效、权限不足、可重试网络状态；不无限重试 |
| 登录与退出前后检查浏览器存储 | localStorage/sessionStorage 不存在认证凭据；退出后私有界面清除 |
| 管理员在契约 mock 中修改用户角色/启停 | 发送字段与契约一致，更新列表并显示后端拒绝最后管理员变更的错误 |

```powershell
# frontend
npm run test -- --run src/features/auth/session.test.ts src/router/guards.test.ts src/features/users/UserEditor.test.ts
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e -- e2e/auth-shell.spec.ts
```

## 已知问题与外部阻塞

002 未合入时只可声称契约 mock 验证通过；真实认证/用户管理验收由 016 承接，真实会话身份链路由 009 承接。002 不是本任务独立合入的隐藏依赖。无需真实模型密钥或生产域名。

## 工作记录与完成标准

- 2026-09-22 领取：owner f3857500-7549-43ca-92f2-50b78656e381；分支 feat/todo-003-frontend；原生 worktree C:/Users/Administrator/.codex/worktrees/todo-003-frontend/aiSoftwareAttempt；基点 35cc22f。已核对 origin/main 的 001 done，原子领取并登记前端路由所有权。
- 隔离环境：API 8103、Web 5203、DB 15436；Compose qa-todo-003-f38575。冻结安装 uv/npm 成功，基线 Vitest 6 passed。
- 按 [WORKFLOW](../WORKFLOW.md) 记录 mock/真实联调范围，独立评审后到 `in_review`；合入权威 main 且检查通过后统一置为 `done`。

- 实现：登录/注册、服务端会话恢复、Cookie/CSRF 客户端、错误/字段提示、user/agent/admin 首页与导航、管理员分页列表及显示名/角色/启停编辑；健康检查迁至 /status，保留真实后端连通用例。挂载说明见 [frontend/README](../../frontend/README.md)。
- 依赖：固定 vue-router 4.6.4，无新增状态管理库。共享依赖与路由入口持锁提交，已和 todo-002 协调；002 负责 Vite 同源代理修复与真实认证协议用例，本任务不覆盖其文件。
- 测试驱动：session 初始 9 failed；guards 12 failed/1 passed；UserEditor 2 failed；浏览器首次受保护路由未跳登录而失败。最小实现后 30 Vitest、10 Playwright 通过。
- 独立评审：frontend_review 审查 35cc22f..2bcc1f3；发现两项 Important：迟到 401 清除新登录身份、编辑器在保存时被替换导致结果/自降权同步丢失；无 Critical/Minor。补 3 项会话竞态和 2 项浏览器回归，均先观察到失败后修复。请求绑定会话代次；保存中禁用编辑切换和分页；自账号 PATCH 响应在接口层同步身份，离开页面后仍生效。修复提交 c53df3f，回归与完整检查复核通过，无遗留评审问题。
- 评审边界裁定：真实认证 Cookie/后端鉴权联调按原范围交由 016；完整数据库验收由主对话实际执行，评审者未重复冒称执行。未额外取消任何任务验收。
- 最终代码验收：2026-09-22，Windows 11、Node 24.11.0/npm 11.6.1、Python 3.12.14/uv 0.12.17、隔离 PostgreSQL 16.15/pgvector 0.8.6。在 c53df3f078666d2968c96eb33734bd7d495b9d4a 上运行 node scripts/dev.mjs check，exit 0：Ruff、19 pytest、两次 Alembic upgrade head、ESLint、vue-tsc、33 Vitest、Vite build、14 Playwright 全通过。
- 冻结安装：uv sync --directory backend --frozen --extra dev 与 npm ci --prefix frontend 成功；新增依赖首次官方 registry 直连 ECONNRESET，使用已运行本机代理临时重试后成功，没有提交代理配置。npm audit 为 0 vulnerabilities。
- 浏览器范围：13 项认证/用户管理契约模拟用例 + 1 项真实 FastAPI/PostgreSQL 健康检查。覆盖登录/注册、刷新/退出、角色隔离、安全返回地址、401/403/断网恢复、表单提交禁用/422字段提示、空列表、用户修改、最后管理员错误、窄屏和竞态。桌面与 375px 窄屏截图检查无横向溢出。
- 已知限制：真实登录/用户管理页面联调仍由 016、聊天身份由 009 承接；未部署公网。现有 Starlette/anyio 与 Node 脚本弃用警告保留，检查 exit 0；不宣称云端 CI 通过。
- 状态：本地验收 + GitHub PR；当前 in_review，功能 PR 和独立收尾 PR 实际合入后才为 done。原生 worktree 保留，脱敏原始日志在忽略的 .local/。
