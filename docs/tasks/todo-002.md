# todo-002：身份认证、会话与资源权限

| 字段 | 值 |
|---|---|
| id | todo-002 |
| 状态 | in_progress |
| depends_on | todo-001 |
| 并行可行性 | 可与 003、004 并行；共享路由注册、依赖锁与迁移入口由单一整合者协调 |
| 负责目录 | `backend/app/modules/auth/`、`backend/app/core/security.py`、认证迁移与对应测试 |

## 范围、文件与接口

阅读 [架构](../ARCHITECTURE.md)、[接口契约](../CONTRACTS.md)、[协作流程](../WORKFLOW.md)。提供注册、登录、退出、当前用户、CSRF、后台用户列表/角色/启停 API、首次管理员引导与角色/资源授权基础；角色固定为 `user`、`agent`、`admin`。密码哈希与 Cookie 会话配置按契约实现；普通注册不得自选客服或管理员。

- 创建 `backend/app/modules/auth/{models,schemas,service,router,permissions,bootstrap_admin}.py`、`backend/app/core/security.py`。
- 创建 `backend/tests/auth/test_sessions.py`、`test_csrf.py`、`test_permissions.py`、`test_user_management.py`、`test_login_limits.py` 及一份认证迁移。
- 消费 001 的配置、数据库、审计入口与测试 fixture；产出 `/api/v1/auth/{register,login,logout,me,csrf}`、`GET /api/v1/admin/users`、`PATCH /api/v1/admin/users/{id}` 和 CONTRACTS 指定的 Actor、当前用户依赖、权限函数。
- 知识权限和会话权限在此冻结授权规则；005/009/010 在实际资源查询中调用它们。不能因 `agent` 身份直接读取所有用户会话。
- 不实现找回密码、社交登录、付费组织或 SaaS 多租户。

## 分步执行

- [ ] 领取任务并核对 001 已合入；把角色矩阵和 Cookie/CSRF 行为逐项映射到 CONTRACTS。
- [ ] 先写会话测试：登录、过期、退出、匿名访问、错误密码；写越权注册、缺少 CSRF、用户管理权限及最后一个管理员保护测试，运行确认预期失败。
- [ ] 创建用户/会话模型与迁移，使用 Argon2id；提供本地首次管理员引导 CLI，仅交互隐藏输入或 stdin 接收密码，无默认密码、不写命令参数或日志。
- [ ] 实现认证路由、会话撤销和登录尝试限流；对账户与来源按配置限制，超限返回 429，错误提示不枚举用户名。Cookie 使用 `HttpOnly`、生产 `Secure`，不把令牌返回给前端保存到 localStorage。
- [ ] 实现 CSRF 签发/校验及来源约束；覆盖 JSON 状态请求、表单上传与退出，GET 请求不得承担写操作。
- [ ] 实现角色检查、会话归属/接单客服/管理员规则与知识库授权规则；对不存在和无权对象按统一错误策略处理，避免泄露资源内容。
- [ ] 实现管理员用户列表与 display_name/role/is_active 修改；阻止移除最后有效管理员，角色/停用变更即时约束旧会话；认证及用户管理变更调用 001 审计入口。
- [ ] 用隔离数据库验证迁移、会话过期/撤销及所有角色边界；给 003 提供登录和错误响应契约，给 005/009 提供授权调用示例。
- [ ] 执行测试与静态检查，独立评审 Cookie、CSRF 和越权路径；修复后记录真实结果，提交至 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 断言 |
|---|---|
| user 请求管理员接口 | 按契约返回无权限错误，不执行业务写入 |
| 注册体携带 `role: admin` | 请求被拒绝或只创建 user，绝不能生成 admin |
| 缺少/伪造 CSRF 的状态请求 | 拒绝；合法同源 Cookie 与 CSRF 组合成功 |
| user A 尝试访问 user B 的会话 | 拒绝；未接单 agent 也拒绝；接单 agent/admin 允许 |
| 退出或会话过期后重用 Cookie | `/api/v1/auth/me` 返回未认证，不能继续写入 |
| 管理员停用用户或降级最后一个管理员 | 停用用户旧会话立即失效；最后有效管理员被保护；变更有脱敏审计 |
| 测试配置限流窗口内连续失败登录达到上限 | 下一次请求返回 429，窗口结束后恢复；未知用户与错误密码提示一致 |

HTTP 行为示例：完成登录后检查 `Set-Cookie` 包含 `HttpOnly`；生产配置还应包含 `Secure`。同一 Cookie 请求 `/api/v1/auth/logout` 时移除 CSRF，应被拒绝且会话未被当作合法状态操作处理。响应不得含密码哈希或会话密钥。

```powershell
# backend；数据库先按总计划启动
uv run pytest tests/auth/test_sessions.py tests/auth/test_csrf.py tests/auth/test_permissions.py tests/auth/test_user_management.py tests/auth/test_login_limits.py -q
uv run pytest
uv run ruff check .
uv run alembic upgrade head
uv run alembic heads
```

最后一项应只有一个迁移 head；迁移检查只作用于隔离测试数据库。

首次管理员引导入口计划为在 backend 运行 `uv run python -m app.modules.auth.bootstrap_admin`，通过隐藏交互提示读取密码；其测试必须验证重复引导、密码不回显、已有管理员保护，不在命令参数中传递密码。

## 已知问题与外部阻塞

管理员引导凭据由部署者安全提供。真实邮件系统不在范围。HTTPS Cookie 的公网浏览器行为在 016/017 验证，本任务仍须通过生产配置属性与 CSRF 集成测试。

## 工作记录与完成标准

- 2026-09-22 领取：feat/todo-002-auth；原生 worktree todo-002-auth；基点 origin/main 35cc22f，依赖 001 已 done。实施细化见 [执行计划](todo-002-plan.md)。
- 未实施；无测试或安全检查通过声明。
- 依 [WORKFLOW](../WORKFLOW.md) 交付测试证据和评审结果；功能分支收尾为 `in_review`，合入权威 main 并检查通过后再统一更新 `done`。
- 会话/CSRF 第一轮：新增测试因缺失路由出现 17 failed + 7 fixture errors（404）；实现后完整 pytest 43 passed。基线统一检查 19 pytest + 6 Vitest + 1 Playwright 通过。
- 权限/管理/引导：缺失实现时 35 failed；实现后完整 pytest 79 passed，含真实 PostgreSQL 两管理员并发降级及并发首次引导，最后管理员保护通过。
- 限流/部署：11 个失败场景补齐后全后端 94 passed；额外复现并修复密码验证期间停用账户竞态、已限流来源占用新计数器容量的问题，均有红绿回归。
