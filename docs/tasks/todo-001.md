# todo-001：工程骨架、工具链、CI 与本地依赖

| 字段 | 值 |
|---|---|
| id | todo-001 |
| 状态 | pending |
| depends_on | 无 |
| 并行可行性 | 本任务先行；未合入前其余任务可预读规格，不在相同骨架上并行开发 |
| 负责目录 | `backend/` 基础配置、`frontend/` 基础配置、`infra/compose.dev.yaml`、`scripts/`、`.github/workflows/` |

**阅读顺序：**[总计划](../IMPLEMENTATION_PLAN.md)、[架构](../ARCHITECTURE.md)、[契约](../CONTRACTS.md)、[协作流程](../WORKFLOW.md)。本任务所有文件都是拟创建目标，尚未安装或验证。

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

- [ ] 在独立 worktree 记录领取状态；核对 Node 24、Python 3.12、Docker 和 uv 是否可用，缺失项记录实际原因。
- [ ] 先建立最少 Python/前端项目配置、开发依赖、测试运行器与锁文件并安装，确认 pytest/Vitest 可运行；这一步只搭测试环境，不写健康/审计/页面实现，并补充 README 中工作目录说明。
- [ ] 写 `test_health.py` 断言健康端点返回约定状态及 JSON，`test_audit.py` 断言审计落库/请求关联与脱敏，`App.test.ts` 断言最小页面可渲染；运行确认失败来自目标行为缺失，而非 uv/pytest/Vitest 缺失或环境损坏。
- [ ] 实现最小应用入口、配置加载、数据库会话和同步落库审计入口；健康检查不泄露连接串、密钥或主机敏感信息，审计 metadata 只收脱敏字段。
- [ ] 编写仅含开发数据库的 Compose，固定 PostgreSQL 16 与 pgvector 兼容镜像，增加数据库健康检查；用唯一项目名和端口启动隔离实例。
- [ ] 配置 Alembic、pytest、Ruff、前端 lint/typecheck/Vitest/build、Playwright 最小连通检查；记录本地代理 `/api` 与同源生产区别。
- [ ] 在干净依赖环境执行冻结安装、全部基础检查和数据库连通验证；确认两个不同 Compose 项目不会共用数据库卷或端口。
- [ ] 将相同命令接入 CI；CI 使用测试配置和 PostgreSQL 服务，不依赖真实云模型/GPU/生产密钥。
- [ ] 进行独立评审，修复可复现问题；更新实际命令、结果和提交记录，提交功能变更并置为 `in_review`，按 WORKFLOW 合并后统一收尾。

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
docker compose -f infra/compose.dev.yaml -p <唯一worktree项目名> config
docker compose -f infra/compose.dev.yaml -p <唯一worktree项目名> up -d db
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

预期失败与通过必须各自记录真实输出摘要；当前没有执行这些命令。

## 已知问题与外部阻塞

Docker/WSL2、Python 3.12 与 uv 的可用性需开发时核实；仅已知本机有 Node 24.11.0/npm 11.6.1。依赖下载需要网络。远程仓库尚未建立时不能伪造 GitHub CI 结果，可先本地验证并记录远程验证阻塞。

## 工作记录

- 领取：未领取；负责人、worktree、分支、commit、PR 均未产生。
- 执行：未开始；测试、构建和 CI 均未执行。
- 完成标准：遵循 [WORKFLOW](../WORKFLOW.md)；功能分支最多到 `in_review`，功能合入权威 main 且检查通过后才由收尾记录更新为 `done`。
