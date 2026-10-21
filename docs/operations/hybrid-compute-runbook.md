# 混合计算操作手册

适用于todo-021的queued实现及购买前试验。网站、账号、PostgreSQL、原始资料、BGE和RAG留在服务端；桌面只主动领取固定Ollama生成任务。服务器/域名购买、公网HTTPS发布及整机2GiB验收尚须按[todo-021](../tasks/todo-021.md)记录实际结果；本手册不是完成声明。协议与上限见[CONTRACTS](../CONTRACTS.md#021-云端业务与桌面生成契约)。

## 配置服务端

在本任务独立环境安装冻结依赖、配置数据库及固定BGE快照，步骤沿用[scripts/README](../../scripts/README.md)。保持一个API进程；解析/索引worker仍在服务端运行。仅在独立queued运行环境设置以下非秘密项，不覆盖现有开发Mock或原演示运行版的 `.env`：

```dotenv
MODEL_PROVIDER=queued
MODEL_ID=qwen3:4b-instruct-2507-q4_K_M
MODEL_ALLOWED_IDS=["qwen3:4b-instruct-2507-q4_K_M"]
MODEL_MAX_OUTPUT_TOKENS=512
```

该model_id必须与桌面已安装模型及注册值完全一致。queued不使用MODEL_API_KEY/MODEL_BASE_URL，也不会回退到它们；不要把节点机器凭据填入这些变量。升级前先保留数据库备份，使用该运行环境的DATABASE_URL执行 `uv run --directory backend --frozen alembic upgrade head`；本机容器入口start会在启动API前执行迁移。不得把开发数据库的注册记录误认为容器运行库的记录。

## 注册并交付节点配置

管理员在**能连接目标API实际数据库的后端环境**执行。以下PowerShell例子在worktree根目录运行，用分配的API端口替换8101；只用于同机loopback试验。HTTPS环境改为实际同源HTTPS根地址，不带 `/api` 路径。输出父目录须已存在且由管理员控制。

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
$nodeConfig = Join-Path (Get-Location) '.local/desktop-node.json'
uv run --directory backend --frozen python -m app.modules.compute.manage register --name demo-desktop --model-id qwen3:4b-instruct-2507-q4_K_M --cloud-url http://127.0.0.1:8101 --model-base-url http://127.0.0.1:11434 --output "$nodeConfig"
```

命令只输出worker UUID和操作结果，请保存UUID用于撤销。配置包含cloud_url、token、model_id、model_base_url、ollama_num_ctx（默认4096）；程序以新建方式写入，已有文件会拒绝覆盖。Unix权限为0600；Windows先移除继承ACL、只授予当前用户，再写秘密。权限设置失败则拒绝交付。不要显示文件正文、使用token命令参数或把文件提交到Git。将配置经受控安全通道交到桌面当前用户的私有目录；转移后的访问权限也必须收紧。

本机容器运行版的数据库不发布宿主端口。使用容器版时，在目标Compose项目的api服务内运行同一模块（`python -m app.modules.compute.manage ...`，省略uv前缀），输出到容器可写的 `/tmp/desktop-node.json`；cloud_url用**桌面访问该项目的** `http://127.0.0.1:<WEB_PORT>`。从容器安全复制到预先限制当前用户访问的桌面目录，确认完整后移除容器临时配置。不要通过 `cat`、日志或终端回显转移token，不将该凭据放进镜像；目标数据库、Compose项目和端口须与当前queued运行版一致。

## 启动桌面

桌面安装同一冻结backend运行依赖（`uv sync --directory backend --frozen`），无需数据库密码、上传目录或服务器会话密钥。先确认本机Ollama版本与模型已安装，并在仅监听loopback的服务上预热；已有本机模型的启动方法见[本机运行说明](local-run.md#配置与模型)。Ollama基线为0.35.0，默认context4096；12000 UTF-8字节输入不保证总能放进该context，超限会失败。

从桌面worktree根目录执行，路径指向已安全交付的配置：

```powershell
$nodeConfig = Join-Path (Get-Location) '.local/desktop-node.json'
uv run --directory backend --frozen python -m app.modules.compute.desktop --config "$nodeConfig"
```

`--once` 表示仅领取一次，有任务则执行后退出，无任务则立即退出。用于单次验收时先发起提问，再在其60秒期限内运行：

```powershell
uv run --directory backend --frozen python -m app.modules.compute.desktop --config "$nodeConfig" --once
```

无任务或正常完成退出码0，受控错误1，Ctrl+C为130。节点串行生成，完成后等1秒再领取；每5秒续租，租约15秒，排队与生成共用原请求剩余期限。机器客户端拒绝重定向，不使用环境代理，不重放未获确认的请求。配置只允许HTTPS云端根地址（同机测试例外为127.0.0.1/localhost/::1的HTTP），Ollama必须是loopback HTTP根地址；不接受任意远程模型端点。

## 本机试验与HTTPS部署边界

本机可先按开发入口启动API、解析和索引worker，注册cloud_url为其loopback API根地址，再启桌面；或在**独立queued配置**中运行 `node scripts/deploy/local-run.mjs build`、`start`，注册cloud_url为该套WEB_PORT。容器入口仅支持mock/ollama/queued，不会隐式调用付费cloud。修改代码先build，再start；status/logs/smoke只针对该环境，stop保留卷。不要启动或修改原演示运行版。

用虚构资料依次验证注册登录、上传解析/BGE索引、提问、真实桌面生成、云端引用复核、持久历史；再测停止、断网、离线、撤销和重启。`local-run.mjs smoke`仅证明健康、网页与基础路由，不证明桌面生成成功。保存脱敏结果、代码/模型身份及实际耗时；资源验收还须覆盖PDF/DOCX、并发、重启、磁盘/日志和OS/Docker预算。容器限额合计或小TXT成功不能替代独立2GiB系统结论。

公网阶段需要实际域名、有效证书、生产APP_ENV/HTTPS PUBLIC_ORIGIN、会话与数据库秘密及受控备份恢复。当前 `infra/Caddyfile.local` 关闭自动HTTPS、只监听本机发布端口，不能原样当作生产配置。生产反向代理须保留 `/api`、`/health` 和精确 `/internal/compute`、`/internal/compute/*` 到API的路由；未知机器路径应返回API JSON错误，不能返回SPA页面。验证机器认证失败/未知路由/超限/错误JSON的no-store响应，同时确认普通浏览器写请求仍要求CSRF。

公网仅开放网站HTTP/HTTPS；数据库、Ollama和桌面不公开监听，不使用frp或通用流量转发。HTTPS配置与公网真实链路沿todo-016/017验收，购买与发布不能从本机脚本成功推断。

## 停止、撤销与故障恢复

正常停止桌面用Ctrl+C；停止业务容器用该项目的 `node scripts/deploy/local-run.mjs stop`。API重启会把遗留生成恢复为失败并撤销旧计算；桌面重启不会重做旧任务。聊天页面重连只读历史，不自动重新生成。需再次提问时由用户明确发起，已受理的失败/取消请求仍计入限额。

撤销在目标数据库的管理员环境执行，worker UUID替换为注册命令的实际输出：

```text
uv run --directory backend --frozen python -m app.modules.compute.manage revoke --worker-id <worker-UUID>
```

撤销不删除历史，旧凭据的后续请求被拒绝。要恢复使用，应核对模型空闲后重新register，使用新的私有文件和凭据；旧文件不能原地覆盖。

| 现象 | 恢复操作 |
| --- | --- |
| 桌面离线、休眠或无人领取 | 网站账号/资料等业务仍可用，生成在原期限内失败；恢复节点和模型后人工重新提问，不自动补跑积压任务 |
| 浏览器停止/断网、转人工、会话删除或用户/会话失效 | 云端拒绝旧任务结果；桌面在续租拒绝后关闭本地流并退出。先确认Ollama空闲，再人工重启节点 |
| `NODE_CLOUD_REFUSED` | 核对HTTPS地址、路由、worker是否撤销及任务是否已失效；不循环重启或重放结果 |
| `NODE_CLOUD_ERROR` / `NODE_BODY_LIMIT` / `NODE_INVALID_JOB` | 检查受控网络、协议与大小上限；不要把原始凭据/模型正文附到错误报告 |
| `NODE_DEADLINE_OR_LEASE_EXPIRED` | 排队、网络或模型超时；先确认Ollama计算已结束，演示前预热，不能延长旧任务或提交迟到结果 |
| `NODE_GENERATION_FAILED` | 模型调用失败或协议不完整；检查模型已安装、context与资源，不自动改模型或退回云API |
| `NODE_CONFIG_ERROR` | 核对私有配置路径、结构及允许地址；必要时撤销旧worker并重新注册，不打印配置内容 |

关闭Python流或节点退出不等于GPU已释放。每次取消/异常后都要用本机Ollama状态与GPU监测确认当前计算结束；未确认前不再起新节点、模型评测或训练。心跳失败、提交确认丢失及受控模型错误均结束节点，禁止配置进程管理器无限自动重启。

任务正文在消费、失败或取消后清空；失效的未消费成功结果由清理撤销。应用启动与每分钟执行清理，元数据约保留24小时加一个周期；这不是业务历史、上传资料或审计数据的删除策略。查看故障时仅保留安全错误码、worker/job UUID及脱敏时间，不导出任务payload/result或机器凭据。
