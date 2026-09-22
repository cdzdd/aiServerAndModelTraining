# todo-016：早期预发布部署与公网基础链路

| 字段 | 值 |
|---|---|
| id | todo-016 |
| 状态 | pending |
| depends_on | todo-001、todo-002、todo-003 |
| 并行可行性 | 可与 005–008 业务开发并行；独占预发布环境的部署变更，不能两名执行者同时部署同一站点 |
| 负责目录 | `infra/` 部署文件、容器构建文件、`scripts/deploy/`、`docs/operations/`、预发布 smoke |

## 范围、文件与接口

按 [ARCHITECTURE](../ARCHITECTURE.md)在用户授权的 Linux 服务器上用 Docker Compose + Caddy 部署当前基础应用，验证 HTTPS、同源路由、登录会话、迁移、健康检查与持久化。此时知识/RAG/客服可能尚未合入，不能把基础预发布宣称为完整交付。

- 创建 `backend/Dockerfile`、`frontend/Dockerfile`、`.dockerignore`、`infra/compose.prod.yaml`、`infra/Caddyfile`、`infra/.env.production.example`。
- 创建 `scripts/deploy/{deploy.sh,smoke.sh}`、`docs/operations/{deployment.md,preproduction-report.md}`、`frontend/e2e/preproduction.spec.ts`。
- 消费 001 健康/配置和 002/003 真实登录链路；同源反代 `/api` 到后端，静态前端和 API 在同一域名。
- 容器镜像有可追溯版本，不使用漂移的最新镜像作为唯一发布依据；数据库/上传目录为持久卷，密钥不进入镜像或版本库。
- 017 复用本任务配置完成正式部署、全部功能和恢复演练，不另建第二套无关部署体系。

## 分步执行

- [ ] 核对三项依赖已合入，收集 Linux 主机授权、域名/DNS、SSH/部署方式、持久化路径和密钥；缺外部条件时先完成本地构建与检查。
- [ ] 先写预发布 smoke/E2E：健康、HTTPS、登录刷新/退出、非法 CSRF 与前端深链接；本地目标尚不可用时确认预期失败，而不是把 DNS 未提供误当应用测试失败。
- [ ] 编写最小分阶段构建镜像、非调试运行配置与健康检查；后端使用生产启动方式，前端产物由同源反代提供。
- [ ] 编写 Compose 和 Caddy 配置，配置持久数据库/上传卷、内部网络、TLS 与反代；仅暴露必要 HTTP/HTTPS 端口，数据库不开放公网。
- [ ] 编写可重复部署脚本，按镜像版本拉取/启动、检查 readiness、串行执行迁移；失败时停止发布并保留诊断信息，不悄悄清空数据卷。
- [ ] 在本地或隔离测试主机验证镜像/Compose/迁移，然后对授权预发布服务器部署；记录目标、版本、时间与真实结果。
- [ ] 从外网完成 002/003 真实认证与用户管理联调：Secure Cookie、CSRF、刷新/退出、用户列表/角色/启停、最后管理员保护和深链接；凭据不出现在浏览器存储或构建产物中。
- [ ] 重启应用容器验证登录/业务配置行为符合契约、数据库/上传卷仍存在；记录尚未纳入的业务能力和生产补充项。
- [ ] 独立评审部署配置与实际验收证据，提交 `in_review`；按 WORKFLOW 合并收尾，交接 017 使用同一部署路径。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 公网访问指定域名 | HTTPS 证书有效，前端和 API 同源，无混合内容错误 |
| 真实登录后刷新、退出、再访问受保护页 | 身份恢复和撤销正确；Secure/HttpOnly/SameSite 按生产配置生效 |
| 缺少/伪造 CSRF 的写请求 | 服务端拒绝；正常登录/注册链路可用 |
| 直接打开前端深层路由 | 返回应用页面，API 路径仍由后端处理，不被 SPA fallback 吞掉 |
| 重启应用与数据库容器 | 持久数据不丢；readiness 反映依赖状态；迁移失败不会误报部署成功 |

```bash
# Linux 或支持 Docker 的隔离环境；变量先按部署说明设置
docker compose -f infra/compose.prod.yaml --env-file infra/.env.production config
docker compose -f infra/compose.prod.yaml --env-file infra/.env.production build
bash scripts/deploy/deploy.sh
bash scripts/deploy/smoke.sh
# frontend，BASE_URL 指向真实预发布域名
npm run test:e2e -- e2e/preproduction.spec.ts
```

`.env.production` 为部署时创建且忽略的秘密文件，当前不存在；示例文件不得填真实凭据。基础 CI 检查仍按总计划执行；外网记录写明测试 URL 和构建版本。

## 已知问题与外部阻塞

需要服务器、域名/DNS 控制、部署授权及实际密钥；适用地区的联网/备案条件由用户确认。没有这些输入可完成构建配置，不能声称“已上线”。预算、域名购买和服务器采购不自动发生。

## 工作记录与完成标准

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未构建、未部署、没有公网地址或认证验收结果。
- 按 [WORKFLOW](../WORKFLOW.md) 提交配置和真实预发布证据；功能分支 `in_review`，合入权威 main 且检查通过后统一置 `done`。
