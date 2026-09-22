# 开发前准备清单

核对日期：2026-09-22。项目按“先完成可运行工程，再接真实模型，再部署，最后做本地模型实验”的顺序推进。**不需要先购买云服务器、域名或 GPU 服务；没有模型密钥时，可以先用 Mock 模型完成页面、接口、数据库和测试。**

todo-001 已完成工具安装、本地工程验收和 GitHub 接入，具体合并状态见 [任务记录](tasks/todo-001.md)。本文的创建仓库、安装和登录命令保留为新环境参考，本机无需重复执行。当前使用用户提供的公开仓库 `cdzdd/aiServerAndModelTraining`，不自行更改可见性。

**当前验收方式：**用户已授权本地验收 + GitHub PR，云端工作流仅手动触发。账号账单限制不再阻塞符合 [WORKFLOW 10.1](WORKFLOW.md) 的本地验收与普通 PR 合并；仍须满足现有服务端保护。

## 1. 当前电脑已知状态

| 项目 | 已知情况 | 下一步 |
| --- | --- | --- |
| 硬件 | Core Ultra 7 265K、约 31.5 GiB 内存、RTX 5070 Ti 16 GB | 足以开始工程开发；模型容量与训练参数需要实测 |
| Git | 已安装 2.52.0，提交姓名和邮箱已配置 | 沿用现有身份；需要更改时仅改项目级配置 |
| Node.js / npm | v24.11.0 / 11.6.1 | 项目统一 Node 24 LTS，无需降级到 22；具体补丁版在工程初始化时锁定 |
| Python | uv 管理的 3.12.14 已安装并验证 | 各 worktree 独立虚拟环境，保留系统 Python |
| GitHub CLI / uv / Ollama | gh 2.101.0、uv 0.12.17；cdzdd 登录和推送已验证 | Ollama 延后到本地模型阶段；不需要更换 GitHub 账号 |
| Docker | Desktop 4.92.0、Engine 29.8.0、Compose 5.5.1；容器和项目数据库已验证 | 保持运行；各 worktree 使用独立项目名、端口与卷 |
| WSL | Docker 的 WSL 2 后端已正常运行 | 用于训练的 Linux 发行版、CUDA/PyTorch 和 GPU 链路留到 014/015 验证 |

Node 24 在核对日期仍为 LTS；项目统一版本是为了本机、CI、部署环境保持一致。[Node.js 官方发布表](https://nodejs.org/en/about/previous-releases)

## 2. 立即准备：工程与协作

表中勾选表示已完成验收，而不是仅下载了安装包。

### 下一批任务准备

002、003、004 都只依赖 001。先确认权威 `origin/main` 的 001 为 done，再在本工作区开启三个独立对话，分别领取一个任务；无需重新创建仓库、购买服务器或提供真实业务数据。

| 任务 | 当前必须准备 | 可选输入或以后再准备 |
| --- | --- | --- |
| 002 身份认证、会话与权限 | 无需额外用户资料；开发者按现有三角色、Cookie、CSRF 契约实现，测试使用专用账号 | 实际启用时确定首个管理员用户名，密码通过本机隐藏输入设置；现在不用发送密码，也不需要邮箱/短信服务 |
| 003 前端框架、登录与角色页面 | 无需等 002 完成；先按契约 mock 开发与验收 | 可指定显示名称、配色或已有页面偏好；无指定时沿用当前中文页面和 Element Plus。真实认证/用户管理联调由 016 承接 |
| 004 模型接口、Mock 与流式适配 | 无需真实密钥；用 MockProvider 和假 HTTP 服务验证既定 OpenAI-compatible Chat Completions 文字流协议 | 如需提前真实联调，再提供厂商名称、模型 ID、含版本路径的 API base URL 和明确测试预算；API key 仅存本机忽略的环境文件，不能发到 PR 或提交 |

每个开发对话自行创建独立 worktree、冻结安装依赖、生成自己的 `.env`/会话密钥，检查并登记端口、Compose project、数据库卷与上传目录。002 和 004 修改后端依赖、配置、路由入口或共享契约时须持共享文件锁；开发可并行，合并与收尾串行。003 使用 mock 的通过不能表述为真实登录已验证；004 无真实调用时注明云连接未验证，最晚在 017 发布前完成真实验证。

服务器、域名和公开访问配置留到 016/017；FAQ、文档和样例问题按 005/006/013 准备；本地推理与训练环境留到 014/015。这些不是开始 002/003/004 的前置门槛。

| 完成 | 准备项 | 如何准备 | 完成标准 |
| --- | --- | --- | --- |
| [x] | GitHub 账号和仓库 | 已使用用户创建的公开仓库 cdzdd/aiServerAndModelTraining | 所有者、项目名称和可见性已核实，不重复创建 |
| [x] | GitHub 命令行登录 | 已通过浏览器登录 cdzdd | 账号与仓库访问已验证 |
| [x] | 仓库权限 | cdzdd 为仓库所有者，权限为 ADMIN | 已成功推送分支和创建 PR；实际合并仍遵守当前服务端规则 |
| [x] | Git 身份 | 现有 `user.name` 与 `user.email` 已配置并用于提交 | 沿用项目已有提交身份 |
| [x] | Node 24 LTS | 本机 Node 24.11.0/npm 11.6.1 | 前端冻结安装、测试与构建通过 |
| [x] | uv 与 Python 3.12 | uv 0.12.17 管理 Python 3.12.14 | 解释器发现、冻结安装与后端测试通过 |
| [x] | Docker Desktop | 4.92.0，Linux 容器与 WSL 2 后端 | 引擎、hello-world 和项目数据库已验证 |
| [x] | 依赖下载能力 | 已访问 GitHub、npm、Python 包源和容器仓库 | 已完成实际依赖安装与镜像拉取；新 worktree 仍须安装自己的依赖 |

### 2.1 创建私有空仓库

推荐在 [GitHub 新建仓库页面](https://github.com/new) 操作：

1. 选择自己的账号或有权限的组织，填入项目名称。
2. 选择 **Private**。
3. **不要勾选 README、`.gitignore`、License，也不使用模板**。这些文件由当前工作区统一维护，避免远程和本地各自生成第一条提交。
4. 创建后复制 HTTPS 仓库地址，例如 `https://github.com/OWNER/REPO.git`，把这个非敏感地址提供给当前任务。

GitHub 官方也建议导入已有本地仓库时，不在远程初始化 README、License 或 `.gitignore`。[导入本地代码的官方步骤](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)

如果偏好命令行，登录完成后可用下面的替代方式，**网页和命令行二选一，不要重复创建**。先把占位符替换为实际所有者与名称：

```powershell
gh repo create OWNER/REPO --private
```

此命令创建远程空仓库；没有附加 `--push`，不会上传当前目录。[`gh repo create` 官方说明](https://cli.github.com/manual/gh_repo_create)

远程地址确定后，再检查当前工作区是否已有提交、是否已有 `origin`，然后接入并首次推送。不要在已有历史上重复初始化，也不要强制覆盖远程。首次推送成功后，以 `main` 作为后续功能分支的基线。

### 2.2 安装并登录 GitHub CLI

在 PowerShell 中安装：

```powershell
winget install --id GitHub.cli --source winget
```

安装后关闭并重新打开终端窗口，使 PATH 生效，然后执行：

```powershell
gh --version
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh auth status
```

浏览器登录由你本人完成。成功预期：显示正确账号、HTTPS 协议和有效登录；不需要把登录码、密码或令牌发到聊天中。检查状态时使用普通 `gh auth status`，不要运行输出令牌的命令。

官方步骤：[Windows 安装](https://github.com/cli/cli/blob/trunk/docs/install_windows.md)、[浏览器登录](https://cli.github.com/manual/gh_auth_login)、[配置 Git 凭据助手](https://cli.github.com/manual/gh_auth_setup-git)。

登录完成后检查仓库访问权限：

```powershell
gh repo view OWNER/REPO --json nameWithOwner,url,isPrivate,viewerPermission
```

成功预期：仓库名称、可见性与用户选择一致，当前账号具备所需写入权限；本项目现为用户创建的公开仓库，不要求改为私有。组织仓库若使用 SSO 或限制 GitHub Actions，需要由组织管理员完成相应授权。

在当前项目目录检查 Git 身份：

```powershell
git config user.name
git config user.email
```

本轮已确认二者有值。确需修改时，使用项目级配置，避免影响其他仓库：

```powershell
git config --local user.name "YOUR_NAME"
git config --local user.email "YOUR_GIT_COMMIT_EMAIL"
```

### 2.3 `main` 保护与自动合并

下表的云端 CI/required check 项在恢复云端验收时执行；当前按 WORKFLOW 10.1 本地验收。启用临时模式时 main 无强制 check/ruleset，后续合并仍须实时核对；不新增无法运行的 check，也不削弱已经存在的保护。

目标流程是：`feat/...` 功能分支 → PR → 检查通过 → 自动合并到 `main`。接入 GitHub 后完成以下设置：

| 完成 | 配置 | 注意事项 |
| --- | --- | --- |
| [ ] | 允许 GitHub Actions 运行本仓库工作流 | 任务 001 建立 CI 后，先确认一次真实运行 |
| [ ] | `main` 要求通过 PR 合并 | 禁止日常开发直接向 `main` 推送 |
| [ ] | 必需的 CI 检查 | **待任务 001 创建实际 job 后再选取名称**，不可填入臆造的检查名 |
| [ ] | 禁止强制推送、删除主分支 | 不使用管理员绕过来掩盖失败的检查 |
| [ ] | 开启仓库 auto-merge（套餐支持时） | PR 满足检查与其他规则后才自动合并 |
| [ ] | 审批数量符合实际协作方式 | 单人仓库不强制“必须另一人 approve”，避免无人可审批；以后有审阅者再增加 |

私有仓库的分支保护、规则和原生 auto-merge 可用性取决于仓库归属及 GitHub 套餐，不能保证免费私有仓库全部可用。官方说明列出私有仓库支持 GitHub Pro、Team、Enterprise 等套餐。若当前套餐不可用，保留“PR + 按当前模式验收后由任务检查并合并”的操作流程，明确记录尚无服务端强制保护；不擅自修改仓库可见性、不购买套餐，也不绕过现有服务端规则。[分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[PR 自动合并](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/automatically-merging-a-pull-request)

### 2.4 Python 3.12 与依赖工具

本机已有 Python 3.10，保留它。使用 uv 为本项目管理 Python 3.12：

```powershell
winget install --id astral-sh.uv -e
```

重新打开终端后：

```powershell
uv --version
uv python install 3.12
uv python find 3.12
```

成功预期：uv 版本正常，能找到 Python 3.12 路径。工程初始化任务再创建项目配置、虚拟环境及锁文件；此时不需要向全局 Python 安装项目包。后端、训练实验分别使用独立环境，避免深度学习依赖影响 Web 后端。[uv 安装](https://docs.astral.sh/uv/getting-started/installation/)、[uv Python 版本管理](https://docs.astral.sh/uv/concepts/python-versions/)

### 2.5 Docker 与 WSL 验证

先在你自己的终端执行只读检查：

```powershell
wsl --version
wsl --status
wsl --list --verbose
docker version
docker compose version
```

成功预期：WSL 版本和状态可读；用于 Linux 开发的发行版若已安装，应显示 `VERSION 2`；`docker version` 同时有 Client 和 Server 信息。仅打印 Docker CLI 版本不能证明引擎可用。

如缺少 Docker Desktop，按[官方 Windows 安装说明](https://docs.docker.com/desktop/setup/install/windows-install/)安装并启动，采用 Linux 容器。使用 WSL 后端时，检查 Windows 硬件虚拟化已启用，并达到当前 Docker 文档要求的 WSL 版本。核对时要求 WSL 2.1.5 或更高，安装时仍以官方页面为准。

若 WSL 需要更新，按官方流程执行 `wsl --update`；若尚未安装所需发行版，先查看 `wsl --list --online`，再决定是否安装 Ubuntu。安装可能需要管理员权限和重启。Docker Desktop 的 WSL 后端与用于训练的 Ubuntu 环境分开验证，不把“已找到 wsl 命令”记作训练环境完成。[Microsoft WSL 安装与版本检查](https://learn.microsoft.com/en-us/windows/wsl/install)、[Docker WSL 后端](https://docs.docker.com/desktop/features/wsl/)

引擎启动后运行一次测试；首次会下载公开测试镜像：

```powershell
docker run --rm hello-world
```

成功预期：输出容器运行成功提示并退出。数据库镜像、Compose 文件及数据卷由工程任务配置。若仍失败，保留错误类型供排查，不提交包含凭据的 Docker 配置文件。

## 3. 接入 RAG 前准备：模型与资料

| 完成 | 准备项 | 具体内容 | 完成标准 |
| --- | --- | --- | --- |
| [ ] | 一个可用模型提供商 | 确认 API endpoint、模型名称、调用权限和费用限额；密钥保存在本机 | 后端能完成一次受控请求，记录延迟与错误处理结果 |
| [ ] | 本地中文 embedding 模型 | 按架构使用 bge-small-zh-v1.5，确保能够下载模型与tokenizer并留出缓存空间；无需另买embedding API | 文档向量化与查询使用相同模型版本，样例检索成功 |
| [ ] | 第一批 FAQ / 产品资料 | 优先整理少量清楚、可更新的文本或 Markdown；标注标题、来源、更新时间 | 能说明资料允许怎样使用；去除不需要的个人信息与秘密 |
| [ ] | 固定测试问题 | 准备约 15–30 个问题及预期依据，包括可回答、资料缺失、矛盾或过期信息 | 可以比较修改前后的答案质量与引用，而不是只凭感觉 |
| [ ] | 一个明确示范场景 | 例如“从公司 FAQ 回答售前问题并给出处” | 能用一句话说明输入、期望输出和不应回答的范围 |

模型密钥仅供服务端读取，不放进浏览器代码、公开构建变量或聊天。endpoint 和模型名称通常不是秘密，可以提供；API key 由你在本地或服务端环境中配置。真实调用准备好前继续使用 Mock，实现工程和界面不必等待模型账号。

### 秘密配置放在哪里

| 位置 | 用途 | 规则 |
| --- | --- | --- |
| 本机 `.env` / 服务端环境变量 | 本地开发或服务器运行时读取 API key、数据库密码等 | 不提交 Git；每个 worktree 和部署环境分别配置 |
| `.env.example` | 告诉开发者需要哪些配置项 | 只含变量名、说明和无效占位值，可提交 |
| GitHub Actions Secrets | CI / 部署工作流需要的秘密 | 在 GitHub 的 Secrets 设置中配置；不会自动成为本机或服务器的 `.env` |
| GitHub Actions Variables | 工作流中的非敏感配置 | 适合环境名称等普通配置，不存密码或 API key |

先使用 Mock 运行 CI，避免普通 PR 测试依赖付费模型凭据。只有真正需要的部署工作流才接收对应秘密，日志不打印值。若秘密误入提交，先撤销或轮换凭据，再处理提交历史；仅添加 `.gitignore` 不会删除已有历史。[GitHub Actions Secrets 官方说明](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

## 4. 上线前再准备：服务器与运行条件

**购买资源和生产发布在部署阶段决定。当前规划不是对任意云消费或生产发布的授权。**

| 完成 | 准备项 | 如何准备 | 完成标准 |
| --- | --- | --- | --- |
| [ ] | 部署方式 | 选择“云服务器调用模型 API”或“自有模型服务”；先按需求估算 | 明确应用运行在哪里，模型在哪里运行 |
| [ ] | 月预算与地域 | 决定费用上限、主要用户地域、模型服务是否可用 | 服务器、模型调用、存储和流量均纳入预算 |
| [ ] | 云服务器与公网地址 | 到部署任务再选择规格和创建；确认系统版本、磁盘、出站网络 | 能 SSH 登录，应用容器能访问数据库和模型服务 |
| [ ] | SSH 身份 | 私钥保留在本机 SSH 配置或凭据管理中；工作流部署时使用独立受限凭据 | 能通过已有本地配置登录；不把私钥、密码发到聊天或提交仓库 |
| [ ] | 域名与 HTTPS | 域名可后配；正式对外使用前完成 DNS 与 HTTPS | 从外部浏览器访问正确域名，证书有效 |
| [ ] | 网络入口 | 只公开所需 Web 入口，数据库及管理端口保持受限 | 外部只能访问计划中的服务 |
| [ ] | 备份与恢复 | 定义数据库、上传资料备份位置、频率及保留周期 | 完成一次恢复演练，确认能还原有效数据 |
| [ ] | 服务端秘密和费用保护 | 配置运行时秘密、请求限额与预算告警 | 不从前端暴露密钥；避免意外无上限调用 |

## 5. 本地模型阶段再准备：推理与微调

RTX 5070 Ti 16 GB 是本地实验的基础，**不代表任意模型、上下文长度或微调配置都能运行**。先测小规模推理，再选 LoRA / QLoRA 实验，记录实际显存、速度和效果；云端 RAG 工程无需等待这一阶段。

| 完成 | 准备项 | 做法与验收 |
| --- | --- | --- |
| [ ] | Ollama 本地推理 | 通过官方 Windows 安装器安装；确认模型存储位置，再下载选定模型；用实际请求和 GPU 使用情况验收 |
| [ ] | 独立的 WSL 2 Linux 训练环境 | 验证发行版版本、磁盘空间和 GPU 可见性；训练依赖与后端环境隔离 |
| [ ] | GPU 软件版本组合 | 按当前 PyTorch、CUDA、量化库及 LLaMAFactory 支持情况选择兼容版本，实际执行一次 GPU 运算 |
| [ ] | 模型和数据下载权限 | 确认模型许可、下载来源、必要账号及访问条件；不要把访问令牌放进数据集 |
| [ ] | LLaMAFactory 数据 | 整理去重、脱敏的高质量问答；训练集与评测集分开；选择 Alpaca / ShareGPT 格式并配置 `dataset_info.json` |
| [ ] | 磁盘空间 | 为原模型、下载缓存、训练检查点、导出模型和数据分别估算，下载前确认容量 |
| [ ] | 小规模训练验证 | 先完成少量步数，确认无显存溢出、能保存与重新加载，再扩大规模 |

Ollama 可在 Windows 原生运行，默认本地 API 地址为 `http://localhost:11434`。模型存储位置可通过 `OLLAMA_MODELS` 配置；模型文件可能很大，先选择位置再下载。[Ollama Windows 官方说明](https://docs.ollama.com/windows)

WSL 的 CUDA 使用 Windows 主机 NVIDIA 驱动提供的能力，**不要在 WSL 中另装 Linux NVIDIA 显示驱动**。需要的 CUDA 工具和 Python 包由训练任务按版本兼容性配置，不照抄旧教程中的固定 CUDA 版本。[NVIDIA CUDA on WSL 官方指南](https://docs.nvidia.com/cuda/wsl-user-guide/)

可在对应环境中使用下列检查；最后一条在已安装 PyTorch 的训练环境内运行：

```powershell
nvidia-smi
wsl --list --verbose
ollama --version
ollama list
```

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CUDA unavailable')"
```

成功预期：识别到目标 NVIDIA GPU，WSL 训练发行版为版本 2，PyTorch 报告 CUDA 可用。之后仍需运行一次真实 GPU 运算及少量训练，不能仅凭版本号判定兼容。LLaMAFactory 安装版本与训练参数在该阶段固定，参考[官方项目](https://github.com/hiyouga/LlamaFactory)和[数据格式说明](https://llamafactory.readthedocs.io/en/latest/getting_started/data_preparation.html)。

## 6. 多任务 / worktree 开发准备

每个同时运行的 worktree 都需要独立环境，避免两个开发任务互相改写数据：

| 完成 | 每个 worktree 单独分配 | 验收方式 |
| --- | --- | --- |
| [ ] | 功能分支与任务编号 | 任务启动时记录分支和负责范围 |
| [ ] | 前端、后端及数据库端口 | 启动两个任务时没有端口冲突 |
| [ ] | Compose project name | 使用不同项目名称，使容器、网络与默认数据卷隔离 |
| [ ] | 开发数据库和数据卷 | 不连接另一个 worktree 的库，不连接生产数据库 |
| [ ] | `.env` 和 Python 虚拟环境 | 本机配置分别创建，使用模板填写，不提交秘密 |

Compose 的项目名称可以通过 `-p` 或 `COMPOSE_PROJECT_NAME` 指定；具体名称和端口由任务启动时登记。[Docker Compose 项目隔离说明](https://docs.docker.com/compose/how-tos/project-name/)

代码仓库只保留代码、规划、配置模板和少量可公开的测试样例。真实上传资料、数据库文件、模型权重、训练检查点、缓存及秘密配置不进 Git；这些内容在实施任务中建立忽略规则和独立存储位置。

## 7. 后续可补充的非敏感信息

- 当前仓库 URL、cdzdd 登录和仓库权限已完成，无需重复提供；将来迁移到新环境时再核对目标仓库与登录权限。
- 可选的项目显示名称，以及进入知识库任务时的第一个示范场景。
- 上线优先选择云模型 API，还是自有模型服务；尚未决定可以先用 Mock。
- 月预算上限与目标地域，允许到部署前再定。

**无需回传密码、API key、GitHub token、SSH 私钥或完整 `.env`。** 002/003/004 无需等待上述可选信息；接手对话检查依赖任务和实际环境，建立自己的隔离配置后即可开始。
