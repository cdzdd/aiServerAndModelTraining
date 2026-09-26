# 本地开发与检查

要求：Node.js 24 LTS、Python 3.12、uv 0.12.17、Docker Desktop（Windows 使用 Linux 容器）。安装新工具后重新打开终端，确认 `node`、`uv`、`docker` 可从 PATH 调用。以下命令在当前任务的独立 worktree 根目录运行，Windows PowerShell 和 Linux/macOS 终端均适用。

## 1. 每个 worktree 的配置

先按 [WORKFLOW](../docs/WORKFLOW.md) 领取任务、记录未占用端口。复制 `.env.example` 为 `.env`（PowerShell 使用 `Copy-Item .env.example .env`，Linux/macOS 使用 `cp .env.example .env`）。

- 为 `COMPOSE_PROJECT_NAME` 填入唯一名称，例如 `qa-todo-002-a31f20`。
- 填写分配的 `API_PORT`、`WEB_PORT`、`DB_PORT`，同时修改两个数据库 URL 中的端口。
- 用 `node -e "console.log(require('node:crypto').randomBytes(32).toString('hex'))"` 分别生成数据库密码和会话密钥。数据库密码在 `POSTGRES_PASSWORD`、`DATABASE_URL`、`TEST_DATABASE_URL` 三处保持一致。
- `qa_dev` 用于开发，`qa_test` 用于测试。二者在首次创建数据库卷时初始化；不要把测试 URL 指向正式数据库。
- `.env`、`.local/`、依赖目录均不进入 Git。不要在日志、截图或 PR 中复制连接串和密钥。

Compose 只包含数据库，固定 PostgreSQL 16.15 / pgvector 0.8.6 的已验证镜像摘要，端口仅绑定本机。项目名决定容器和数据卷的归属；不得跨 worktree 复用名称。更改 `.env` 密码不会自动更改已有卷里的 PostgreSQL 密码；保留原配置或执行明确的数据库密码变更，不能用删卷代替排错。

## 2. 安装与启动

```text
uv sync --directory backend --frozen --extra dev
npm ci --prefix frontend
npm exec --prefix frontend -- playwright install chromium
node scripts/dev.mjs db-up
uv run --directory backend --frozen alembic upgrade head
```

分别打开两个终端，保持运行：

```text
node scripts/dev.mjs api
node scripts/dev.mjs web
```

访问 `http://127.0.0.1:<WEB_PORT>` 进入服务中心；服务连接检查在 `/status`。页面路由与接入约定见 [前端说明](../frontend/README.md)。API 存活检查为 `http://127.0.0.1:<API_PORT>/health/live`，就绪检查为 `/health/ready`。

Vite 开发服务器把 `/api` 和 `/health` 代理到本 worktree 的 API 端口，不需要跨域白名单。生产同域反向代理将在部署任务实现；当前这些命令是本地开发入口。

停止数据库：`node scripts/dev.mjs db-stop`，保留数据卷。停止前后端：在对应终端按 Ctrl+C。

## 3. 统一验收

关闭占用本 worktree API/Web 端口的开发进程，然后运行：

```text
node scripts/dev.mjs check
```

该命令执行 Ruff、完整 pytest（真实 PostgreSQL/pgvector）、连续两次 Alembic 升级、前端 lint/typecheck/Vitest/build/Playwright。Playwright 自行启动 API 和 Vite，禁止借用已有服务，以免误测其他 worktree。测试数据使用独立库中的随机 schema，测试结束只清理自己创建的 schema。

当前采用 [WORKFLOW 10.1](../docs/WORKFLOW.md) 的本地验收模式：此入口与任务专项检查是代码 PR 的合并依据，需保留提交对应的脱敏结果和独立评审。GitHub 工作流暂时仅手动触发，本地通过不等于云端 CI 已通过。纯文档 PR 做格式、链接与事实检查。

迁移命令会升级当前 `DATABASE_URL` 的数据库；执行检查前确认它属于本 worktree。CI 使用全新临时 PostgreSQL 服务和固定测试配置，无需模型密钥、GPU 或云服务。

单项排错可以在 `backend/` 运行 `uv run --frozen pytest -q`、`uv run --frozen ruff check .`；在 `frontend/` 运行 `npm run lint`、`npm run typecheck`、`npm run test -- --run`、`npm run build`、`npm run test:e2e`。

## 4. 下载与 Windows 环境问题

依赖下载失败时先检查网络与已经配置的代理。需要代理的命令只临时设置 `HTTPS_PROXY`/`HTTP_PROXY`（或 npm 的 `--https-proxy`），不把个人代理写入仓库或全局配置。新装 uv 后当前旧终端可能找不到它；重开终端后重试。

Docker Desktop 的 socket 报错不能通过重置数据库解决。保留日志和现有数据，先确认 Docker 服务是否能启动、测试容器能否运行；镜像下载失败和引擎启动失败应分别检查。

## 5. 文档解析 worker（todo-006）

上传 PDF/DOCX/TXT/Markdown 后由独立 worker 解析，单文件上限 20 MiB。API 不在请求中执行解析。使用同一 worktree 的数据库和上传目录，另开终端运行 `node scripts/dev.mjs worker`；停止 worker 后已保存任务不丢失，重启会重新领取租约过期任务。006 只领取 parse 任务，成功页面显示“解析完成，待建立索引”，index 任务由 007 处理。

worker 启动前需要真实 tokenizer。以下命令下载项目指定公开模型的固定修订到本 worktree 的忽略目录（约 96 MB，MIT 许可；不会调用云模型）：

```powershell
uv run --directory backend --frozen python -c "from pathlib import Path; from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-small-zh-v1.5', revision='7999e1d3359715c523056ef9478215996d62a620', local_dir=str(Path('../.local/models/bge-small-zh-v1.5').resolve()), allow_patterns=['*.json','*.txt','model.safetensors','1_Pooling/config.json'])"
```

把下载目录中 `tokenizer.json` 的**绝对路径**填到 `.env` 的 `EMBEDDING_TOKENIZER_PATH`。路径可指向本机其他已验证的只读模型缓存，但数据库、上传与测试输出仍必须隔离。模型修订与 512 维输出依据见 [契约](../docs/CONTRACTS.md)。普通自动化测试使用固定 tokenizer fixture；真实 tokenizer/模型检查另记录，不能混为一谈。

解析子进程有时间与内存限制；扫描 PDF 无文本时明确失败，不执行 OCR。重复上传按同库内容去重；替换版本不会提前取代旧的有效版本。下载每次都校验当前身份、知识库权限和文档状态，不提供公共文件路径。
