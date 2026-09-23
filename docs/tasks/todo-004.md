# todo-004：云模型接口与流式 provider

| 字段 | 值 |
|---|---|
| id | todo-004 |
| 状态 | done |
| depends_on | todo-001 |
| 并行可行性 | 可与 002、003 并行；仅在 provider 目录实现，不提前修改 RAG 或聊天状态机 |
| 负责目录 | `backend/app/modules/providers/`、provider 测试、配置示例 |

## 范围、文件与接口

依据 [CONTRACTS](../CONTRACTS.md)建立唯一模型适配协议、MockProvider、CloudProvider、流式事件转换、超时与取消。云端实现支持契约选定的协议；不建设可视化模型市场或任意插件系统。

- 创建 `backend/app/modules/providers/{schemas,base,mock,cloud,factory,errors}.py`。
- 创建 `backend/tests/providers/test_cloud_stream.py`、`test_provider_errors.py`、`fixtures/cloud_events.py`。
- 消费 001 配置与日志基础；产出 CONTRACTS 规定的请求/响应/usage/取消接口给 008，供 014 实现同一协议。
- 云模型密钥只在后端环境变量/部署 secret 中保存；浏览器不能拿到 provider 密钥。
- SSE 业务事件由后续 009 对外暴露，本任务不直接发布未授权的模型代理 API。

## 分步执行

- [x] 核对 001 与模型协议；登记模型 ID、API 地址、超时/输出上限与配置来源，缺失真实输入时使用明确标注的假服务。
- [x] 先写流分片合并、usage、结束、异常和取消测试；用可控制的假 HTTP 服务逐段响应，执行确认目标适配尚未实现而失败。
- [x] 定义最小 provider 类型与错误映射，实现消息到选定云 API 请求的转换；避免把提供商专有字段泄露到业务接口。
- [x] 实现异步流读取、分片边界处理、正常结束/中途错误区分；UTF-8 中文被拆分时仍能正确组合。
- [x] 实现连接/读取超时和上游取消；已向用户输出内容后不做透明全量重试，防止文本和计费重复。
- [x] 实现模型配置白名单与凭据脱敏；错误信息允许定位故障，但不得记录 Authorization 或原始密钥。
- [x] 执行假服务全场景验证；若已取得用户 API 配置则提前做短真实调用并记录模型、日期、耗时、usage 和结果，否则明确记录“真实云连接未验证，由 017 发布前完成”，不保存密钥。
- [x] 独立评审资源释放、异常映射和真实/假服务证据；更新记录并提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 中文文本跨多个网络分片 | 合并后文本完全一致，无乱码、丢字或重复 |
| 上游正常结束 | 只产生一次完成信号，usage 按协议保留，缺失 usage 不伪造数值 |
| 429、鉴权失败、超时、半途断流 | 映射为契约错误；中途失败不能当作正常完成 |
| 消费端取消 | 上游连接被释放，后续分片不再继续写给消费者 |
| 日志/异常输出 | 看不到密钥与 Authorization 内容；测试无需真实凭据即可通过 |

```powershell
# backend
uv run pytest tests/providers/test_cloud_stream.py tests/providers/test_provider_errors.py -q
uv run pytest
uv run ruff check .
```

真实调用使用实际开发时提供的受控 smoke 入口，输入固定短问题、输出限制明确；不得在文档中填入虚构成功值。

## 已知问题与外部阻塞

当前本地 DeepSeek 配置已于 2026-09-23 完成单次真实流式 smoke，结果与调用限制见文末续作记录；本轮无未解决外部阻塞。早先未验证条目保留为基础交付时的历史。

真实调用需要用户选定云提供商、模型 ID、API base URL、API key 和测试预算。无密钥时完整 MockProvider、CloudProvider 协议适配与 fake HTTP 契约测试可以满足本任务完成条件，并明确记录真实云连接未验证。首次真实云 API smoke 可在 004/008 提前完成，最晚由 017 作为正式发布必需验收执行，不让密钥成为 008/009 开发的隐藏阻塞。

## 工作记录与完成标准

- 2026-09-23 已原子领取；负责人为当前 Codex 对话，独立 worktree `C:/Users/Administrator/.codex/worktrees/todo-004-providers/aiSoftwareAttempt`，分支 `feat/todo-004-providers`，基点 `0dcff3b2fd164d872e02066799d440493aecb9ec`。
- 用户先选择真实联调，随后明确要求先完成其余工作，真实联调等其另行叫开始。已创建忽略的 `.local/model-smoke.env` 供用户填写；本任务不读取或调用真实凭据，真实云连接未验证。
- 按 [WORKFLOW](../WORKFLOW.md) 记录实现、假服务证据及真实调用是否已执行；功能分支最多 `in_review`，合入权威 main 且检查通过后统一收尾为 `done`。此状态不表示真实云 API 已验证。

- 实现：统一 Provider / LLMMessage / LLMDelta / LLMUsage、Mock、OpenAI-compatible 文本流、白名单与配置校验、超时/取消/资源释放、固定脱敏错误；无业务代理路由、无自动重试。保留一个显式 --run 的受控单次 smoke 入口，当前只用假服务测试该入口。
- 隔离：Compose project `qa-todo-004-d6a7e4`；API 8104、Web 5204、数据库 15436；独立 .env、虚拟环境、node_modules 和数据库卷。
- 基线：冻结安装依赖后完整 `node scripts/dev.mjs check` exit 0，100 pytest + 33 Vitest + 15 Playwright，静态检查/构建/重复迁移通过。
- TDD：初始 36 个场景因 provider 模块缺失无法完成；实现后 36 passed。补充配置 URL 错误脱敏和 smoke 场景，实际 2 failed / 42 passed，修复后 44 passed。原始日志保存在忽略的 .local 目录。
- 调试记录：现有 HTTP 客户端 EventSource 使用异步迭代协议；纠正调用名。Windows Proactor 假 TCP 服务在 peer reset 后触发 WinError 10054 并卡在 server.wait_closed；用独立诊断复现后，Windows 测试选择 Selector 事件循环，应用运行逻辑不变。取消/关闭连接断言保留，未改为返回假结果。
- 依赖：仅把已锁定的 httpx2 从 dev 提升为运行依赖，未升级版本；SSE 解析复用该库的公开 EventSource，避免重复实现协议解析器。
- 真实云联调：按用户最新指令延后，调用次数 0、模型费用 0；真实 endpoint/model/usage/耗时均没有验证结果。待用户明确开始后读取本地配置并在其预算内执行，最晚 017 发布前完成。
- 首轮完整验收：2026-09-23 Windows，Node 24.11.0、Python 3.12.14、uv 0.12.17；执行 node scripts/dev.mjs check，exit 0，144 pytest + 33 Vitest + 15 Playwright，全量静态检查、构建、两次迁移通过。现有 Starlette 弃用和 Node DEP0190 提示保留。后续评审及最终验证见下。

- 独立评审：对 0dcff3b..681a313 的只读评审发现损坏 gzip 解码未统一映射、异常 URL 的解析器校验差异。后者同样影响统一错误边界，因此一并按必须修复处理。新增 3 个场景先 3 failed，再修复到 47 provider tests passed；没有剩余未处理评审发现。评审未涉及真实云连接和账户预算，按用户指令保留未验证。
- 最终代码验收提交：2b5ef97a604d18302dad05eb36aa05a7f65befe0；2026-09-23 执行 node scripts/dev.mjs check，exit 0，147 pytest + 33 Vitest + 15 Playwright；Ruff、前端静态检查/构建与两次 Alembic 升级通过。代码树与此已验证提交一致；此后的任务记录更新按纯文档检查。
- 文档和入口：3 份 Markdown 相对链接、git diff --check 通过；不带 --run 执行 smoke 入口确认没有请求，也不读取模型配置。云端 CI 未触发，按本地验收规则完成合并门槛。

## 合并与收尾

- 功能 PR [#7](https://github.com/cdzdd/aiServerAndModelTraining/pull/7) 于 `2026-09-23T05:51:24Z` 实际 MERGED，普通 squash 合并 SHA：`c89788de30cd5b7debab4494d2b61d961cbc4e65`。
- 已合并 PR head 为 `af20ba69c21982c1818c7fc34be0d1256f3bbcdf`；代码验收提交为 `2b5ef97`（完整 SHA 见上方最终代码验收记录），之后仅更新任务文档。功能合并后的整个文件树与 PR head 完全一致，`git diff --exit-code` exit 0。
- 合并前重新确认本地工作区干净、PR head 与本地 HEAD 一致、main 无新变化；GitHub main 未设置保护且 rulesets 为空，无必要审批或强制 check。未创建虚假 check、未使用管理员绕过、未直接推送 main。
- 本收尾分支 `docs/todo-004-close` 从真实 `origin/main` 创建，仅更新此任务的状态与合并证据；静态核对 Markdown 链接、diff 和 PR 事实。此 PR 合入后权威 main 上状态为 done，无需再创建记录自身的 PR。
- 本地独立 worktree、忽略的模型配置模板与验证日志保留供后续真实联调。用户明确要求等待另行开始指令，因此真实云连接未验证；本次调用次数 0，未产生模型费用。真实云联调仍是 todo-017 发布前必要验收，不能据本任务 done 宣称真实模型已可用。
## 真实云联调续作（2026-09-23）

- 用户已填写本地模型配置并明确叫开始；预算从 1 CNY 提升为 5 CNY，最多调用次数仍为 1，输出最多 64 tokens。厂商 DeepSeek，模型 deepseek-flash，base URL 为 https://api.deepseek.com，key 仅在忽略的本地配置中读取。
- 复用原生独立 worktree，从 origin/main `0934132` 创建 `fix/todo-004-deepseek-smoke`，重新原子领取 todo-004。先前 done 为基础协议交付，此次补充适配和真实证据合入前保持 in_review。
- 官方文档确认 DeepSeek 默认思考模式，新增默认 false 的 MODEL_DISABLE_THINKING；本次本地配置 true，仅此时发送 thinking.type=disabled，不更改消息/流接口或输出上限。新增请求契约测试先 1 failed，再 48 provider tests passed。
- 最小适配后执行完整 node scripts/dev.mjs check，exit 0：148 pytest、33 Vitest、15 Playwright，静态检查、构建和两次迁移通过；源码验证提交在 PR 描述记录。
- WSL：按用户要求正常停止 Docker Desktop 后执行一次 wsl --shutdown，再启动 Ubuntu 和 Docker；内核 boot ID 从 fc3e659f-6fc4-4480-90b6-5051023b3512 变为 a2ed9801-b621-487b-830b-eaa4c4522f8e。随后出现 Ubuntu 集成写配置超时；Windows Docker 和两个项目数据库保持健康，Ubuntu 本身可启动且 .docker 目录可写。保持 Ubuntu 临时运行并正常重启 Docker Desktop 后，Ubuntu 内 docker version 返回 Client/Server 均为 29.8.0，日志报告 Ubuntu distro is ready，两个原有数据库均恢复 healthy；没有删除容器/数据或改动 WSL 网络设置。
- 独立只读评审范围 `0934132..11be023`，未发现 P0–P3 问题，可合并。源码验收提交 `11be023ea92a0d7b24afb0489e731def3428aa62`；后续仅追加文档证据。- 真实调用：2026-09-23T09:46:45Z 至 09:46:46Z，通过现有 run_smoke/CloudProvider 发出固定短问题，thinking=disabled，max_tokens=64，无重试。响应成功，elapsed_seconds=0.727，text_characters=1，finish_reason=stop；usage 为 prompt_tokens=16、completion_tokens=1、total_tokens=17。
- 本轮调用额度在联网前以忽略的 .local/cloud-smoke-attempt-20260923.json 原子预占；实际仅执行 1 次，1/1 已用完，不再自动请求。该记录与 .env/key 均不提交。
- 成本：按 [DeepSeek 官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 的高峰输入未命中 2 CNY/百万 tokens、输出 8 CNY/百万 tokens，保守估算上限为 `(16*2 + 1*8)/1000000 = 0.00004 CNY`，低于用户授权 5 CNY。不是账户实际扣款回执；未额外调用账单或余额 API。
- 验证边界：已验证这份本地 DeepSeek 配置的单次真实流式连接、正常结束、usage 解析和资源关闭；不代表 RAG/聊天页面已完成，不代表质量、吞吐或生产部署验收。017 仍须验证最终部署使用的模型配置。
### 真实云续作合并与收尾

- 功能续作 PR [#9](https://github.com/cdzdd/aiServerAndModelTraining/pull/9) 于 `2026-09-23T09:48:55Z` 实际 MERGED，普通 squash 合并 SHA `0fcee90d1fd9dcc200d0628d13fb5238d7f3e0c0`。
- 已验证源码提交 `11be023ea92a0d7b24afb0489e731def3428aa62`，最终 PR head `6b9ff6847b8a4c814455536e64454972dea67c67` 只追加文档证据；功能合并文件树与该 head 完全一致（git diff --exit-code exit 0）。完整本地检查148/33/15、独立只读评审、单次真实云 smoke 已完成；云端 CI 未触发。
- 合并前 main 无变化、工作区干净、本地 HEAD 与 PR head 一致；main 未设置保护且 rulesets 为空，无服务端强制审批或 checks。未使用 --admin、未伪造检查、未直接推送 main。
- 本次状态收尾分支 `docs/todo-004-cloud-close` 只更新此任务为 done 并记录实际合并证据；采用文档链接、diff 与 PR 事实静态验证。此 PR 合入后此次真实云联调续作完成。
- 后续保留独立 worktree、本地密钥配置和脱敏调用记录。最多1次的本轮额度已用完；任何新的真实请求需要新的用户授权，5 CNY 预算未被解释为无限次数授权。现有应用默认仍为 Mock，不自动转为持续计费的云调用。