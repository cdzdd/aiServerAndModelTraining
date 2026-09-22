# todo-003：前端框架、登录流程与角色页面

| 字段 | 值 |
|---|---|
| id | todo-003 |
| 状态 | pending |
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

- [ ] 核对 001 已合入，登记前端路由聚合文件所有权；整理三种角色的可见入口和未登录重定向规则。
- [ ] 先写 session 与 router guard 测试，覆盖刷新恢复登录、401 清除状态、非授权路由；运行并确认目标行为尚未实现而失败。
- [ ] 实现同源 API 客户端、CSRF 获取/附带流程、统一错误状态和 Cookie 会话恢复；日志不记录登录密码。
- [ ] 实现登录与注册表单、提交禁用、字段错误、退出；恢复跳转只接受站内路径，避免开放重定向。
- [ ] 实现全局布局和角色导航、管理员用户列表/角色/启停页面，定义业务 feature 挂载约定；普通用户看不到管理入口，最后管理员保护错误可理解。
- [ ] 为加载、空列表、权限不足、网络失败提供可理解界面；手机窄屏可完成登录和基本导航。
- [ ] 用契约 mock 执行组件与浏览器测试；本任务可凭前端壳、路由、请求封装及组件/契约测试独立合入，真实登录/用户管理联调由 016、真实聊天身份联调由 009 完成，不能宣称本任务已验证真实登录。
- [ ] 执行 lint/typecheck/test/build，进行独立评审；记录真实结果并提交 `in_review`，按 WORKFLOW 合并收尾。

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

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未实施；前端页面和测试尚不存在。
- 按 [WORKFLOW](../WORKFLOW.md) 记录 mock/真实联调范围，独立评审后到 `in_review`；合入权威 main 且检查通过后统一置为 `done`。
