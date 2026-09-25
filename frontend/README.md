# 前端页面与模块接入

本地安装与统一验收见 [开发说明](../scripts/README.md)。应用入口为 `/`，根据服务端身份进入普通用户、客服或管理员首页。服务连接检查保留在 `/status`。

## 页面与权限

- `/login`、`/register`：登录与注册；已登录时回到角色首页。
- `/user`、`/agent`、`/admin`：分别面向 user、agent、admin 的工作空间。
- `/admin/users`：管理员分页查看账号、编辑显示名称/角色/启停。
- `/forbidden`、`/session-error`：权限不足和可重试的身份恢复失败。
- `/knowledge`、`/knowledge/:id`：可访问知识库、FAQ；管理员可创建/修改/停用知识库、分页选择成员、编辑/停用/恢复 FAQ。
- 未完成的聊天、接单、反馈和统计能力仅以文字说明展示。

前端权限守卫只控制导航体验，所有 API 仍由后端鉴权。会话身份通过 `/auth/me` 恢复；会话 Cookie 由浏览器发送，CSRF token 仅存内存，不写入 localStorage/sessionStorage。写请求先获取 CSRF，登录后换用新 token；CSRF 失败仅在用户再次提交时重新获取，不自动重放写请求。

## 后续功能挂载

1. 页面和接口放在 `src/features/<feature>/`。
2. 在共享文件锁下编辑 `src/router/index.ts`：把业务路由加到 AppLayout 的 children，声明 `meta.roles`。只在功能完成后添加 `src/app/AppLayout.vue` 导航链接。
3. 使用 `session.api.request<T>('/对应路径', {method, body})` 调用同源 `/api/v1`；普通请求默认对 401 清理身份，登录/注册使用 `authenticated:false`。
4. 使用 `errorMessage` 和 `fieldErrors` 呈现错误。422 details 消费 `[{location: [...], code: '...'}]`，不展示服务端内部异常或记录密码。
5. 当前登录返回地址只允许已登记的角色首页和用户管理页；新增可返回页面时同步 `safeRedirect` 的白名单及测试。
6. 新测试会被统一入口自动发现：`src/**/*.test.ts` 和 `e2e/*.spec.ts`。

## 验收边界

todo-003 的认证和用户管理由测试内的契约模拟服务验证，生产应用不包含模拟登录入口或测试账号。真实认证与用户管理联调由 todo-016，聊天身份联调由 todo-009 完成。健康检查浏览器用例仍连接本 worktree 的真实 FastAPI/PostgreSQL。

todo-005 的 knowledge.spec.ts 使用真实登录、CSRF、知识库和成员 API，经 Vite→FastAPI→PostgreSQL 验证三个角色、撤权、内容维护和停用恢复；没有拦截 API 的模拟响应。FAQ 新建/编辑后明确显示“待索引”，本任务不提供问答检索。
