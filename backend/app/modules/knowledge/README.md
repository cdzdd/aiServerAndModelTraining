# 知识库、成员与 FAQ

todo-005 实现单一组织内的知识库与 FAQ 管理。接口均使用现有服务端会话；写请求要求同源 Origin/Referer 和 X-CSRF-Token。所有知识接口响应设置 Cache-Control: no-store。

## 权限

| 资源或操作 | 匿名 | user / agent | admin |
| --- | --- | --- | --- |
| 启用的公开知识库、启用 FAQ | 401 | 可读 | 可读、可管理 |
| 启用的受限知识库 | 401 | 当前成员可读，否则 404 | 可读、可管理 |
| 停用知识库详情及 FAQ | 401 | 404 | 普通读取也为 404 |
| 创建或修改知识库、成员、FAQ | CSRF / 登录校验拒绝 | 403 | 允许 |
| 成员名单 | 401 | 403 | 允许 |
| 停用知识库元信息 | 401 | 403 | 专用管理列表可查看并重新启用 |

成员资格由每次服务端请求查询，不保存在登录快照或前端角色中。公开库的成员名单不限制其公开读取；如需按名单限制，先将 visibility 改为 restricted。被停用的用户由认证模块拒绝，重新启用后需重新登录。

## 输入和状态

- 知识库 name 去首尾空格后 1–100 字符，description 最多 2000 字符；默认 restricted。创建不接受 is_active、version 等服务端字段。
- FAQ question 去首尾空格后 1–500 字符，answer 为 1–10000 字符；默认启用。禁止空文本、NUL、无效 Unicode、额外字段、null 修改值和字符串布尔值。
- PATCH 知识库或 FAQ 要求 expected_version；至少修改一个有效字段。成员整体替换要求 user_ids 和 expected_version，最多 1000 个不同 UUID；不存在的账号返回 422。
- 版本冲突返回 409，拒绝整次写入，用户需重新加载后修改。知识库写入与成员替换锁定同一行，FAQ 写入按知识库、FAQ 的顺序加锁。
- DELETE /faqs/{id} 是软停用：内容保留，版本递增；再次删除已停用 FAQ 为无修改的 204。管理员可通过 PATCH 重新启用。知识库通过 PATCH is_active=false 停用，本任务没有物理删除知识库接口。
- 普通 FAQ 列表只含启用内容，管理员在启用库中可查看并恢复停用 FAQ。列表均按契约分页。

## 后续模块接入

service.readable_knowledge_bases(actor) 返回 SQLAlchemy SELECT，只含当前身份可读且启用的知识库。
service.effective_faqs(actor, kb_ids) 返回 SELECT，只含上述范围内启用且 indexed_version=version 的 FAQ；空 kb_ids 不退化为全库。

创建 FAQ 的 indexed_version 为 null。任何内容或启停变更递增 version；不修改旧 indexed_version，因此旧版本立即不满足有效条件。005 不生成向量，也不创建假的成功索引任务。007 负责产生共同 Chunk、执行实际索引，并在提交时重新核对版本、有效状态和权限；查询还必须联接同一版本的 Chunk，不能仅凭 marker 声称已有向量。

所有知识库、成员和 FAQ 写入与 audit_events 在同一事务提交。审计只记录对象 ID、版本、成员数量和被修改的字段名，不记录问题、答案、知识库名称/说明或成员名单正文。

## 本地验证

在独立 worktree 配好 .env 和数据库后，运行 node scripts/dev.mjs check。
专项后端测试：uv run --directory backend --frozen pytest tests/knowledge -q。
浏览器专项：npm run test:e2e --prefix frontend -- e2e/knowledge.spec.ts。

浏览器测试连接真实本地 FastAPI/PostgreSQL，通过 tests/knowledge/seed_browser.py 创建随机命名的虚构 admin/user/agent 账号；它不是生产管理员引导入口，不可对生产环境运行。合成账号与资料保留在本 worktree 的隔离开发数据库中，生产应用不会自动生成演示资料。
