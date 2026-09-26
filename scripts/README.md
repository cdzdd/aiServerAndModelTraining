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

## 6. 本地向量索引与检索（todo-007）

后端冻结依赖包含 SentenceTransformers 5.2.0、Transformers 4.57.6 与 PyTorch 2.9.1；Windows/Linux 的 Torch 来自官方 CPU 索引，不需要 CUDA。使用 `uv sync --frozen --extra dev --directory backend` 安装，首次安装需要下载模型运行依赖。模型本身仍按上一节固定修订单独下载。

把模型目录绝对路径填入 `.env` 的 `EMBEDDING_MODEL_PATH`，`EMBEDDING_TOKENIZER_PATH` 指向该目录内的 tokenizer.json。只读模型缓存可以跨 worktree 共用；数据库、上传目录与写入输出各自隔离。模型文件会在首次加载时核验，不接受任意同名模型目录。

分别运行 `node scripts/dev.mjs worker`（解析）与 `node scripts/dev.mjs index-worker`（向量索引）。两者都使用当前 worktree 的环境；完成解析的文档先显示待索引，只有向量全部写入、有效版本切换成功才显示已建立索引。失败后管理页面可重试，旧有效版本继续检索；FAQ 新增/编辑自动创建对应版本索引任务。

需要处理一项任务后退出时，在 backend 目录运行 `uv run --frozen python -m app.modules.retrieval.indexing --once`。常驻 worker 不会无限自动重试失败任务。更换 embedding 模型需明确迁移并重建，本版本固定模型、修订和维度；错误元数据索引不会用于计算相似度。

内部异步 `retrieval.service.search` 为后续 RAG 提供有权限的结果，无独立公开搜索 API。默认 Top-K 5、余弦阈值 `RETRIEVAL_THRESHOLD=0.65` 是初始值，需代表性问题集校准。普通测试使用固定向量并查询真实 pgvector；真实 BGE smoke 另记样本、查询、得分、耗时及限制，不能把固定向量测试当作模型质量验证。

真实 BGE 专项检查显式运行（默认 pytest 不自动收集该较重 smoke）：在已配置专用 TEST_DATABASE_URL 和上述模型路径的 worktree，执行 `uv run --frozen --directory backend pytest tests/retrieval/smoke_real_model.py -q -s`。它在临时 schema 使用虚构中文资料，调用真实上传/解析/index handler/语义查询并验证撤权；输出 `.local/real-retrieval-smoke.json`，不调用云模型。默认阈值由 0.75 调整为 0.65 是因为此小样例的相关图书馆问题约 0.660，其他相关问题约 0.777/0.815，无关问题最高约 0.264；这不是代表性质量评测。

## 7. RAG 内部服务（todo-008）

`rag.service.stream_answer(actor, kb_ids, question, history)` 消费现有 provider 和授权检索，返回 delta/citations/done/error。008 不新增公开问答接口或会话存储；聊天页面与持久历史在 009 接入。

首版只展示模型选择且经服务端核实的原文摘录。引用校验、当前权限/版本复核完成前不展示上游内容；首段出现较晚。无证据时明确说明无依据；模型截断、超时或资料变化时返回错误。改写和回答共用 60 秒与最多 512 输出 tokens，无透明重试。默认 `.env` 仍为 Mock，不能把其固定文字当作真实知识答案。

真实云 smoke 使用本 worktree 忽略目录中的独立配置，显式选择已授权的提供商和模型；不改默认测试模式，不把密钥写入命令行、Git 或前端。DeepSeek 的 `MODEL_DISABLE_THINKING=true` 沿用已验证配置，实际输入/输出 usage 有则记录，缺失保持未知。测试中的虚构资料与样例回答不代表生产知识质量。

已授权真实云调用后，将独立云配置存入本 worktree 的 `.local/deepseek-rag.env`（不得提交），在 PowerShell 显式运行：

```powershell
$env:RAG_SMOKE_CONFIG = Join-Path (Get-Location) '.local/deepseek-rag.env'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
uv run --frozen --directory backend pytest tests/rag/smoke_real_rag.py -q -s
```

该专项默认不会被 pytest 收集。它使用临时数据库 schema、虚构资料、真实上传/解析/BGE/检索与 DeepSeek，覆盖引用、多轮、FAQ、资料内恶意指令、无依据、越权、超长查询和生成期间来源变化。输出 `.local/real-rag-smoke.json`，含实际调用次数、usage 和逐例延时。云服务测试需要调用授权；不要通过普通统一检查隐式触发。
## 8. 聊天与会话恢复（todo-009）

登录后从“问答”进入会话，选择可见知识库后提问。配置好 BGE 目录及已建立索引的资料才有真实检索；默认 Mock 不产生可信知识答案。云模型沿用服务器侧 MODEL_* 配置，不传给浏览器。请求限额按上一节契约的已接受 RAG 请求计数，包括取消/失败；默认每分钟 10、上海自然日 60，同会话 1 个、全局 2 个生成。

服务仅运行一个 API 进程。启动时把上次遗留的生成中消息恢复为失败并保留历史/用量；恢复失败时 readiness 为 503，聊天写入不可用，修复数据库后重新启动。客户端停止或断网会取消上游；重新打开会话只取历史，不自动重试收费请求。

`node scripts/dev.mjs check` 除既有浏览器套件外，串行运行独立聊天套件 `npm run test:e2e -- --config playwright.chat.config.ts`。该套件启动 tests/chat/e2e_app.py 测试工厂，只替换 RAG，认证/CSRF、数据库、会话接口与前端均走真实实现；正常应用没有测试开关。单跑时在 frontend 执行该命令，不能与同 worktree 默认套件同时占用端口。云 API 不由自动化检查触发。
已授权真实云验证时，可复用第 7 节的 `RAG_SMOKE_CONFIG`，显式运行 `uv run --frozen --directory backend pytest tests/chat/smoke_real_chat.py -q -s`。它保留真实应用 RAG/检索与认证/聊天路由，完成上传解析、真实 BGE 索引、首问/追问、持久历史、重复键及撤权投影检查，输出 `.local/real-chat-smoke.json`。默认统一检查不收集此文件，不调用云模型。

人工接管浏览器专项沿用聊天专用入口：`npm run test:e2e -- --config playwright.chat.config.ts handoff.spec.ts`（在 frontend 目录）。该配置运行真实认证、数据库及生产交接路由，模型输出来自测试工厂；统一 check 同时包含聊天和人工接管场景。
