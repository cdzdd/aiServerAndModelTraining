# todo-016：早期预发布部署与公网基础链路

| 字段 | 值 |
|---|---|
| id | todo-016 |
| 状态 | in_review |
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

- 2026-10-01 已领取本地阶段；独立 worktree `C:\Users\Administrator\.codex\worktrees\todo-016-local-runtime\aiSoftwareAttempt`，分支 `feat/todo-016-local-runtime`，根对话维护实时领取与正式评审/PR流程。
- 本轮按用户明确授权停在本地运行版与使用说明；公网服务器、DNS、HTTPS、生产发布仍未执行。本地阶段证据见下文，不将本地认证等同公网 Secure Cookie 验收。
- 按 [WORKFLOW](../WORKFLOW.md) 提交配置和真实预发布证据；功能分支 `in_review`，合入权威 main 且检查通过后统一置 `done`。

## 2026-10-01 本地阶段实施与真实验证

用户本轮只授权本地运行，公网采购、DNS、部署与生产发布排除在本轮。实施计划见 [todo-016-local-plan](todo-016-local-plan.md)，中文使用说明见 [local-run](../operations/local-run.md)。整体保持 `in_review`；原公网 HTTPS 验收仍为 pending，未合入 main，PR/最终集成证据由根对话补充。

- 新增最小前后端镜像、固定实际解析的基础镜像 digest、`compose.local.yaml` 与 `Caddyfile.local`。只有 web 发布 `127.0.0.1:5246`；api/db 无宿主发布端口。一个 API 进程、独立 parse/index worker、持久 PostgreSQL/uploads 卷、只读固定 BGE 挂载、非 root 只读应用容器和 3×10 MB 容器日志轮转。
- `node scripts/deploy/local-run.mjs build|start|stop|status|logs|admin|smoke` 为本地入口；先等待数据库、串行迁移再启动应用，失败不继续启动；stop 保留卷。start/smoke 同时核实宿主 URL，不能用内部 healthy 掩盖网页端口不可达。cloud 配置拒绝启动，不触发付费调用。
- 本地 `.env`、端口与数据卷独立；PUBLIC_ORIGIN 固定本机 HTTP、APP_ENV 明确 development，原 production HTTPS/强会话密钥校验保留。Ollama 宿主受控入口与013/014最终集成仍待根对话完成，本阶段 Mock 不作为真实回答质量验收。
- 小范围修正首页已经开放的功能入口与 frontend/README 的旧未开放文案；更新一条旧 auth-shell 断言验证真实客服入口。新首页入口使用不同名称，避免与侧栏定位歧义。

实际运行记录（Windows，Node 24.11.0、Python 3.12.14、Docker Engine 29.8.0，基线0f5832279978983c959deff434990ca1b7ec7c9f加本分支改动）：

| 命令/检查 | 真实结果 |
| --- | --- |
| `node --test scripts/deploy/local-run.test.mjs` | 8通过；先观察缺失模块/宿主检查的RED，再实现GREEN，覆盖迁移失败停止、保留卷、拒绝cloud与真实宿主可达性/SPA误路由 |
| `uv run --frozen --directory backend pytest tests/deploy/test_smoke.py -q` | 3通过；真实临时HTTP服务验证健康、readiness失败及API不被SPA吞掉，先RED后GREEN |
| `uv run --frozen --directory backend ruff check ../scripts/deploy/smoke.py tests/deploy` | 通过 |
| `node scripts/dev.mjs check` | exit0；678 pytest、114 Vitest、18默认浏览器、4聊天/人工/反馈、1统计浏览器；既有依赖弃用与颜色提示保留，无云模型调用 |
| `node scripts/deploy/local-run.mjs build` | 后端/前端镜像实际成功；首次npm下载ECONNRESET失败后保留缓存重试成功，不更改锁文件 |
| resolved Compose静态核对 | 通过；脱敏核对loopback、api/db不发布端口、持久卷、只读模型、日志轮转，不打印配置密钥 |
| `node scripts/deploy/local-run.mjs start` / `smoke` | 数据库迁移成功，API/web/db healthy、两个worker持续运行且RestartCount=0；内部与宿主健康/深链接/API404路由通过 |
| `uv run --frozen --directory backend python ../scripts/deploy/smoke.py http://127.0.0.1:5246 --auth` | 真实注册、登录、身份恢复、HttpOnly/SameSite=Lax、非法CSRF403、正常退出及退出后401通过；仅创建一个标注的合成普通账号，不保存或输出密码 |
| 本任务 `stop` → `start` 后持久核对 | 合成账号数量保持1、上传卷临时标记保持；核对后只移除本检查的标记，数据卷保留 |

本机 Docker 首次创建 web 时曾发生 HostConfig 有 loopback绑定而 NetworkSettings.Ports 为空，Compose内部健康无法发现。只重启本任务web后映射恢复；已增加宿主验证并在使用说明记录排错，未重置Docker或停止其他任务服务。

当前运行URL是 `http://127.0.0.1:5246`；没有公网HTTPS或生产验收结果。上述代码检查为本地证据，不表示云端CI已运行。管理员初始化交由用户隐藏密码输入；真实Ollama问答、root独立评审、PR、main合并及本地使用版本更新仍待最终记录。

## 2026-10-01 最终本地集成准备（进行中）

- 已合入权威 `origin/main` 的 todo-014（`b6b5f9c`），按 shared-files 原子锁把 8 项 Node 部署测试和独立 smoke Ruff 纳入 `node scripts/dev.mjs check`；README 已链接中文运行指南，CI 使用该统一入口，无需新增空成功检查。
- 本任务私有模型配置已设为 Ollama 0.35.0 / `qwen3:4b-instruct-2507-q4_K_M`，`OLLAMA_NUM_CTX=4096`、读超时120秒、disable_thinking=false。Docker宿主入口使用 `host.docker.internal:11434`，Ollama继续仅监听 `127.0.0.1:11434`；模型服务连通由根对话已实测，016网页真实回答仍待最终镜像验收，不冒用014独立模型证据。
- 按用户授权在专属本地运行数据库通过现有 `bootstrap_admin --stdin-password` 受控标准输入创建演示管理员；普通/客服账号走真实注册与管理员角色修改。随机强密码仅保留ignored本机账号文件并限制当前Windows用户访问，未进入参数、日志或仓库。未绕过browser seed限制；已有普通验收账号与数据不删除。
- 上传明确标为虚构的图书馆教学TXT，通过真实parse-worker、BGE CPU index-worker达到ready；最终知识回答、引用、持久历史、人工与反馈统计闭环等待013最新main集成及GPU协调。
- 新鲜专项验证：8 Node测试、3真实HTTP smoke测试、Ruff、Node语法和`git diff --check`通过。尚未重跑最终完整check；旧678/114/18+4+1只证明5414009之前实现树，不能当作此次集成树通过。