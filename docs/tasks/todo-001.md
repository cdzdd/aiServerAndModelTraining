# todo-001：工程骨架、工具链、CI 与本地依赖

| 字段 | 值 |
|---|---|
| id | todo-001 |
| 状态 | in_review |
| depends_on | 无 |
| 并行可行性 | 本任务先行；未合入前其余任务可预读规格，不在相同骨架上并行开发 |
| 负责目录 | `backend/` 基础配置、`frontend/` 基础配置、`infra/compose.dev.yaml`、`scripts/`、`.github/workflows/` |

**阅读顺序：**[总计划](../IMPLEMENTATION_PLAN.md)、[架构](../ARCHITECTURE.md)、[契约](../CONTRACTS.md)、[协作流程](../WORKFLOW.md)。下述工程文件已实现；本地验收记录见工作记录，GitHub CI/合并状态按真实结果更新。

## 范围与文件

建立可运行的最小 FastAPI 与 Vue 应用、隔离 PostgreSQL 16 + pgvector、本地配置示例与统一检查入口。Node 24 LTS、Python 3.12、uv；锁定依赖。暂不实现登录、知识库、聊天或模型调用。

- 创建 `backend/pyproject.toml`、`backend/uv.lock`、`backend/app/main.py`、`backend/app/core/config.py`、`backend/app/core/database.py`、`backend/app/core/models.py`、`backend/app/core/audit.py`。
- 创建 `backend/alembic.ini`、`backend/migrations/env.py`、`backend/migrations/versions/`、`backend/tests/conftest.py`、`backend/tests/test_health.py`、`backend/tests/test_audit.py`。
- 创建 `frontend/package.json`、`frontend/package-lock.json`、`frontend/vite.config.ts`、`frontend/src/main.ts`、`frontend/src/App.vue`、`frontend/src/App.test.ts`、`frontend/playwright.config.ts`、`frontend/e2e/health.spec.ts`。
- 创建 `infra/compose.dev.yaml`、根 `.env.example`、`.gitignore`、`.github/workflows/ci.yml` 与 `scripts/README.md`。
- 创建架构指定模块目录；提供后续业务立即需要的 `AuditEvent` 与 `record_audit` 基础，不预建其他无用途抽象类、业务模型或占位接口。

## 接口依赖

消费 ARCHITECTURE 的目录与配置约定、CONTRACTS 的健康检查/错误格式。提供应用工厂、数据库会话入口、`AuditEvent`/`record_audit`、测试客户端、前端测试启动入口和 CI 命令给所有后续任务。健康端点为 `/health/live`、`/health/ready`；数据库连接与上传根目录必须可在不同 worktree 分开。

## 分步执行

- [x] 在独立 worktree 记录领取状态；核对 Node 24、Python 3.12、Docker 和 uv 是否可用，缺失项记录实际原因。
- [x] 先建立最少 Python/前端项目配置、开发依赖、测试运行器与锁文件并安装，确认 pytest/Vitest 可运行；这一步只搭测试环境，不写健康/审计/页面实现，并补充 README 中工作目录说明。
- [x] 写 `test_health.py` 断言健康端点返回约定状态及 JSON，`test_audit.py` 断言审计落库/请求关联与脱敏，`App.test.ts` 断言最小页面可渲染；运行确认失败来自目标行为缺失，而非 uv/pytest/Vitest 缺失或环境损坏。
- [x] 实现最小应用入口、配置加载、数据库会话和同步落库审计入口；健康检查不泄露连接串、密钥或主机敏感信息，审计 metadata 只收脱敏字段。
- [x] 编写仅含开发数据库的 Compose，固定 PostgreSQL 16 与 pgvector 兼容镜像，增加数据库健康检查；用唯一项目名和端口启动隔离实例。
- [x] 配置 Alembic、pytest、Ruff、前端 lint/typecheck/Vitest/build、Playwright 最小连通检查；记录本地代理 `/api` 与同源生产区别。
- [x] 在干净依赖环境执行冻结安装、全部基础检查和数据库连通验证；确认两个不同 Compose 项目不会共用数据库卷或端口。
- [x] 将相同命令接入 CI；CI 使用测试配置和 PostgreSQL 服务，不依赖真实云模型/GPU/生产密钥。
- [x] 进行独立评审，修复可复现问题；更新实际命令、结果和提交记录，提交功能变更并置为 `in_review`，按 WORKFLOW 合并后统一收尾。

## 验收场景

| 场景 | 可判定结果 |
|---|---|
| 从干净 worktree 安装锁定依赖 | 后端冻结安装和前端 `npm ci` 成功，不修改锁文件 |
| 应用和依赖正常 | 健康检查符合 CONTRACTS，前端最小页面可见，数据库执行简单查询成功 |
| 必需配置缺失 | 启动给出明确配置名且不打印密钥；不默默指向生产数据库 |
| 两个工作树同时开发 | 使用不同 Compose 项目和端口，各自写入数据互不影响 |
| CI 中没有模型密钥 | 基础测试、静态检查和构建仍可通过 |
| 调用审计入口写入测试事件 | 保存 action/actor/target/outcome/request_id/时间，敏感凭据不进入 metadata |

## 测试文件与命令

后端文件：`backend/tests/test_health.py`、`backend/tests/test_audit.py`。前端文件：`frontend/src/App.test.ts`、`frontend/e2e/health.spec.ts`。这是工程连通与审计边界验收，不为每个配置键编写镜像式测试。

```powershell
# 根目录：替换唯一项目名
docker compose --env-file .env -f infra/compose.dev.yaml -p <唯一worktree项目名> config
docker compose --env-file .env -f infra/compose.dev.yaml -p <唯一worktree项目名> up -d db
# backend
uv sync --frozen --extra dev
uv run pytest tests/test_health.py tests/test_audit.py -q
uv run pytest
uv run ruff check .
# frontend
npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e
```

统一入口为 `node scripts/dev.mjs check`，详见 [scripts/README.md](../../scripts/README.md)。下方保留实际红灯、绿灯和集成验证证据。

## 已知问题与外部阻塞

- 本地无阻塞。Starlette 1.6.0 的 TestClient 引用 anyio 旧别名，有一条上游弃用警告；测试通过且未屏蔽警告。前端间接依赖有弃用提示，`npm audit` 当前为 0 vulnerabilities。
- GitHub 已使用用户指定的 cdzdd 登录，仓库 `cdzdd/aiServerAndModelTraining` 公开、拥有 ADMIN 权限；规划基线首次推送成功。功能 PR [#1](https://github.com/cdzdd/aiServerAndModelTraining/pull/1) 已建立；GitHub Actions 因账号账单锁定未启动，等待用户解除限制后重试，尚未标记 done。
- 本任务只交付开发基础，没有登录、知识问答、模型推理或公开网址部署。

## 工作记录

- 领取：2026-09-22，当前 Codex 对话；分支 `feat/todo-001-foundation`，原生 worktree `C:/Users/Administrator/.codex/worktrees/todo-001-foundation/aiSoftwareAttempt`，基点 `d0b1a1e`。任务领取、共享文件锁和端口分配保存在 Git common directory 的本机协调记录。
- GitHub：SSH 原身份 cdzdd4 无写权限；按用户选择完成 cdzdd 浏览器授权，本仓库改为 HTTPS 并配置本地凭据助手。`main` 规划基线已上传，后续更改走 PR。
- 工具：Node 24.11.0/npm 11.6.1、uv 0.12.17、Python 3.12.14。Python 和前端锁定依赖均在全新依赖环境安装成功。
- Docker：定位并备份损坏的运行时 socket 后恢复；用户随后要求升级。官方安装包校验 SHA256 与签名后升级 Desktop 4.92.0，Engine/CLI 29.8.0、Compose 5.5.1；新版 `hello-world` exit 0。升级前后 10 个镜像、20 个数据卷按标识核对无缺失；未重置、删除数据或重启电脑。
- 数据库：PostgreSQL 16.15 / pgvector 0.8.6；Compose 和 CI 固定相同已验证镜像 digest。开发库 qa_dev、测试库 qa_test，主机数据库端口 15433，仅绑定 127.0.0.1。
- 隔离：两个独立 Compose project，端口 15433/15434、不同命名卷；分别写入 environment-0/environment-1 后互不影响。验证脚本首轮因父进程环境变量优先于第二 env 文件而端口冲突，修正验证脚本后通过；第二实例已停止，测试创建的 schema 已清理。
- 后端红绿：先建立测试运行器，健康测试首次 8 failed（目标 app 尚未实现）后通过；审计与迁移首次因实现缺失失败；后续错误格式、审计连接串脱敏、405 Allow 头和迁移一致性均记录实际失败后修复。最终完整 pytest 为 19 passed。
- 前端红绿：6 项连接状态/异常/重试组件测试先失败后通过；干净 `npm ci` 成功，audit 0；桌面和窄屏检查无横向溢出。
- 统一验收：2026-09-22 执行 `node scripts/dev.mjs check`，exit 0；Ruff 通过、pytest 19 passed、两次 Alembic upgrade head 通过、ESLint/vue-tsc 通过、Vitest 6 passed、Vite build 通过、Playwright Chromium 1 passed（真实网页→Vite代理→FastAPI→PostgreSQL）。另外 `alembic check` 无模型差异，唯一迁移 head 为 001_audit_foundation。
- 评审：独立只读评审指出 DATABASE_URL/TEST_DATABASE_URL 未脱敏以及 HTTP 异常头丢失；已补回归并修复，复核无剩余阻塞。根目录 `.env`、生成文件、模型/上传数据均被忽略，真实秘密不进入版本管理。
- CI：工作流使用全新 PostgreSQL 服务，冻结安装、同一检查入口，不依赖云模型/GPU/生产密钥；文档 PR 同样运行必要检查。本地已通过；远程运行 [35714271910](https://github.com/cdzdd/aiServerAndModelTraining/actions/runs/35714271910) 在启动任何步骤前失败。GitHub 注解原文："The job was not started because your account is locked due to a billing issue." 不绕过检查或合并 main；账号恢复后重跑最新 PR 提交的 CI。
- 功能提交：`0c88e221db8037da8e59f360dfa3f318e0ecfe0c`；功能 PR：[#1](https://github.com/cdzdd/aiServerAndModelTraining/pull/1)。尚未合并，无功能合并 SHA。恢复入口：先核对 PR 最新 head 和账号限制，CI 通过后按 WORKFLOW 合并与另建状态收尾 PR，不重新实现基础工程。
- 完成标准：遵循 [WORKFLOW](../WORKFLOW.md)；功能分支保持 `in_review`，功能合入权威 main 且检查通过后才由收尾 PR 更新为 `done`。
