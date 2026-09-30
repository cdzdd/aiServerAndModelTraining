# 本地运行与使用说明

本轮提供在本机使用的运行版。访问 **http://127.0.0.1:5246**；只能从这台电脑访问，没有公网地址。请始终使用这个地址，不要改为 localhost，否则登录写入的来源校验会拒绝请求。本地 HTTP 使用开发会话配置；公网 HTTPS、证书、生产发布及备份恢复还未验收。

## 启动与停止

需要 Docker Desktop 已启动并使用 Linux 容器，Node.js 24、Git，以及已下载的固定 BGE 模型。使用本任务的独立目录：

```powershell
Set-Location 'C:\Users\Administrator\.codex\worktrees\todo-016-local-runtime\aiSoftwareAttempt'
node scripts/deploy/local-run.mjs build
node scripts/deploy/local-run.mjs start
node scripts/deploy/local-run.mjs status
```

首次构建会下载镜像和锁定依赖，耗时取决于网络；后续会复用缓存。启动会先等待数据库，再执行迁移，最后启动网页、API、解析和索引 worker。报错后停止继续启动并保留卷；检查错误原因后重试。看到 api、web、db 为 healthy、两个 worker 持续运行后，打开上面的网页。`start` 不会自动构建新代码，修改后先运行 `build`。

停止当前运行版并保留数据库、上传文件和账号：

```powershell
node scripts/deploy/local-run.mjs stop
```

再次执行 `start` 可恢复服务。停止只影响 `<COMPOSE_PROJECT_NAME>-runtime` 这一套容器，不停止其他任务的数据库、Docker Desktop 或模型服务。不要执行删卷命令。只删除容器并不等于备份；本轮未承诺备份恢复。

## 配置与模型

本任务独立 `.env` 已配置，包含数据库和会话密钥，不应分享、提交或复制到其他环境。迁移到新 worktree 时按 [开发配置说明](../../scripts/README.md#1-每个-worktree-的配置) 创建独立 `.env`，分配独立 `COMPOSE_PROJECT_NAME` 与 `WEB_PORT`，生成自己的数据库密码和会话密钥。本地运行卷使用项目名再加 `-runtime`，与开发检查数据库分别保存。

`EMBEDDING_MODEL_PATH` 指向已有 `BAAI/bge-small-zh-v1.5` 固定修订的宿主绝对目录；Windows 可以使用正斜杠。运行版只读挂载该目录，不会自动下载模型。tokenizer 在容器中使用模型目录的 tokenizer.json。BGE 和普通业务容器只使用 CPU，不启动训练。

当前接入 **Ollama 0.35.0 + `qwen3:4b-instruct-2507-q4_K_M`**，无需付费云 API。私有 `.env` 已设置以下非秘密模型项；不要覆盖同一文件中的数据库密码、会话密钥或 BGE 路径：

```dotenv
MODEL_PROVIDER=ollama
MODEL_BASE_URL=http://127.0.0.1:11434
LOCAL_MODEL_BASE_URL=http://host.docker.internal:11434
MODEL_ID=qwen3:4b-instruct-2507-q4_K_M
MODEL_ALLOWED_IDS=["qwen3:4b-instruct-2507-q4_K_M"]
OLLAMA_NUM_CTX=4096
MODEL_READ_TIMEOUT_SECONDS=120
MODEL_DISABLE_THINKING=false
```

`MODEL_BASE_URL` 用于宿主开发入口；容器使用 `LOCAL_MODEL_BASE_URL`，不带 `/v1` 或 `/api/chat` 后缀。本机已实际验证 Docker Desktop 容器能访问仅监听 `127.0.0.1:11434` 的 Ollama，不必把模型端口开放局域网或公网。这一可达性与本机 Docker Desktop 有关，换电脑后须重新验证。`MODEL_DISABLE_THINKING=false` 与当前非思考 Instruct 模型匹配。修改配置后重新执行 `start` 使容器重建；代码变化还需要先 `build`。本地脚本拒绝 cloud，避免意外付费调用。`mock` 仅用于验证操作界面，其固定文字不作为可信答案。

Ollama 使用 todo-014 目录中已下载的便携程序与模型缓存，没有安装系统级 Ollama。当前进程已启动；电脑重启后，如 `http://127.0.0.1:11434/api/version` 不可达，可在 PowerShell 启动同一个本地模型服务：

```powershell
$ollamaRoot = 'C:\Users\Administrator\.codex\worktrees\todo-014-ollama\aiSoftwareAttempt\.local'
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $ollamaRoot 'models\ollama'
Start-Process -FilePath (Join-Path $ollamaRoot 'tools\ollama-v0.35.0\ollama.exe') -ArgumentList 'serve' -WindowStyle Hidden
Invoke-RestMethod 'http://127.0.0.1:11434/api/version'
```

请保留该 todo-014 目录的便携程序和模型缓存，不要在服务已运行时重复启动。模型生成使用本机 GPU，其他模型评测或训练时需串行安排。真实本地网页资料入库与问答验收结果见 [todo-016](../tasks/todo-016.md)；最终记录完成前，模型服务连通不代表整条业务链已验收。

## 第一次使用

当前这台电脑已初始化三类**虚构本地演示账号**（管理员、普通用户、客服），并保留标为虚构的教学资料。用户名和随机强密码仅保存在本任务忽略文件 `.local/runtime-accounts.json`，已限制为当前 Windows 用户可读；可在本机编辑器查看并用于试用，不要分享、截图或提交该文件。账号不会出现在指南或公开仓库中。此前的普通认证验收账号和现有数据也已保留。`admin` 命令在这套运行版会提示管理员已初始化。

如需自己的账号，先在网页注册，再用演示管理员在用户管理分配所需角色。确认自己拥有可用管理员后，可自行停用不再需要的演示管理员；系统会保护最后一个启用管理员。演示账号不能沿用到未来公网环境。

**新建独立环境**时，初始化首个管理员，在本机交互终端执行：

```powershell
node scripts/deploy/local-run.mjs admin
```

按提示输入用户名，密码要求 12–128 字符并输入两次，输入时隐藏。不要把密码放进命令参数或截屏；如果终端无法安全隐藏密码，程序会拒绝继续，换用支持交互终端的 PowerShell。已有管理员时不会重复创建或提升现有账号。

打开网页，以管理员账号登录。普通用户从“注册”创建自己的账号。需要客服时，先注册独立账号，再由管理员在“用户管理”把该账号角色改为客服。管理员可修改显示名称、角色和启用状态；最后一个启用管理员受保护，不能自行停用。建议管理员、普通用户、客服使用不同浏览器或独立浏览器配置；普通窗口共享 Cookie，不能作为账号隔离。

## 资料与问答

1. 管理员进入“知识库”创建库，选择所有已登录用户可读或仅指定成员可读。受限库请先加入需要访问的成员。
2. 在知识库详情维护 FAQ，或上传允许使用的文本 PDF、DOCX、UTF-8 TXT/Markdown。单文件最多 20 MiB；扫描 PDF 不执行 OCR。
3. 等待解析与索引完成，文档显示已建立索引后再提问；“解析完成，待建立索引”仍不能用于回答。FAQ 新增或编辑后也需等待索引完成。失败时查看页面错误并在修复原因后重试。
4. 普通用户进入“问答会话”，选择可见知识库，输入问题。可以查看来源、打开有权访问的原资料、查看历史或停止生成。来源停用、删除或撤权后，历史中的来源访问也会重新鉴权。
5. 无资料或依据不足会明确拒答或澄清；真实模型也可能回答不准确，应核对引用。默认每分钟 10 次、上海自然日 60 次，取消和失败的已受理请求同样计入。每个会话同时一条生成，整套运行版同时最多两条。

## 转人工、反馈与统计

- 用户在问答会话申请转人工后，可留下消息。客服进入“人工客服队列”接单，再在该人工会话回复和关闭服务。客服只读本人已接单会话；管理员可查看队列、审阅及关闭已接单会话，不能代客服接单或冒充用户回复。关闭后页面按实际状态操作。
- 用户对可评价的助手回答提交评价与原因。管理员进入“回答反馈”查看、标记和处理，处理结果保存在系统中。
- 管理员进入“管理统计”，按上海时区日期筛选问答、人工服务和反馈；当前队列和文档状态单独展示。缺失 token 或价格时显示未知，不能将问答次数当作模型调用费用。审计记录可按条件查询。

## 检查与排错

网页“服务连接”应显示连接正常。只读健康与路由检查：

```powershell
node scripts/deploy/local-run.mjs smoke
node scripts/deploy/local-run.mjs logs
```

日志只显示当前运行版最近 100 行。每个容器标准流日志最多 3 个 10 MB 文件；这不限制数据库、资料或审计记录的大小。不要分享 `.env`、完整连接串或资料内容。

| 现象 | 处理 |
| --- | --- |
| Docker 连接失败 | 打开 Docker Desktop，确认 Linux 引擎就绪，再重试；不要删数据库卷 |
| 端口被占用 | 核对分配的 WEB_PORT，停止本任务冲突的网页进程；不要停止其他任务服务 |
| 容器 healthy 但网页打不开、host smoke 失败 | 检查 status 的 web 是否有 127.0.0.1:5246 映射；本机曾出现 Docker 首次创建后未实际发布端口，配置确认正确时在 Docker Desktop 只重启本任务 web 容器，再运行 smoke；不要重置 Docker 或删卷 |
| 镜像或依赖下载失败 | 检查网络与已配置代理；配置中不要写个人代理凭据 |
| model 目录不存在或 index-worker 重启 | 核对 EMBEDDING_MODEL_PATH 是真实固定修订 BGE 目录，Docker Desktop 可访问；不以空目录代替模型 |
| 文档长期待索引 | 查看 parse-worker/index-worker 是否在运行和页面最近任务错误；修复模型/文件问题后使用页面重试 |
| 服务连接未就绪 | 查看 api/db 日志和迁移结果；数据库恢复后重启本任务，不将存活当作就绪 |
| 登录后写入报 CSRF 错误 | 使用固定的 127.0.0.1 地址，刷新后重新操作；不要关闭 CSRF 校验 |
| Ollama 无响应 | 检查本机模型是否安装、运行、允许的模型名与 Docker 可达入口；Mock 只能检查界面链路 |
| 已有卷密码错误 | 修改 .env 不会更改卷内密码；使用原配置或执行明确的密码变更，不删卷代替修复 |

维护者可显式运行认证专项：`uv run --frozen --directory backend python ../scripts/deploy/smoke.py http://127.0.0.1:5246 --auth`。它在当前运行数据库创建一个标注为“本地验收账号”的随机普通用户，验证真实注册、登录、会话、非法 CSRF 与退出；不保存或输出凭据。只读 smoke 不创建账号。

当前可用范围是已合入的账号/知识库/上传解析索引/问答历史/人工客服/反馈/统计与审计。本机真实 Ollama 问答的最终验证结果由任务交付记录注明；容器构建通过或 Mock 操作通过不能替代真实模型验收。公网 HTTPS、生产发布与正式备份恢复留待后续授权阶段。
