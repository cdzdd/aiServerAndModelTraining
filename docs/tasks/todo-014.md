# todo-014：Ollama 本地推理与 provider 切换

| 字段 | 值 |
|---|---|
| id | todo-014 |
| 状态 | in_review |
| depends_on | todo-004、todo-008 |
| 并行可行性 | 可与 009、013 并行；只扩展 provider 与配置，不复制 RAG 流程或修改检索算法 |
| 负责目录 | `backend/app/modules/providers/ollama.py`、provider 选择配置、`experiments/inference/` |

## 范围、文件与接口

依据 [CONTRACTS](../CONTRACTS.md)实现 OllamaProvider，与 CloudProvider 共用 `stream(messages, *, max_tokens, temperature)` 协议。RAG 调用入口不变，以配置明确选择云端/本地；本地故障不默认悄悄把资料发往云端。

- 创建 `backend/app/modules/providers/ollama.py`、`backend/tests/providers/test_ollama.py`、`test_provider_selection.py`。
- 修改现有 `factory.py`/配置示例；创建 `experiments/inference/{README.md,smoke.py,reports/}`。
- 消费 004 的 LLMMessage/LLMDelta/错误与取消契约，008 的 RAG 编排；提供供 015 对照使用的基础模型推理路径。
- 本机硬件为 Ultra 7 265K、32GB RAM、RTX 5070 Ti 16GB。具体量化/上下文/批量以实测为准，不承诺硬件未测吞吐。
- Ollama 仅在受控本地/内部网络开放，公网入口仍为有认证的业务服务。

## 分步执行

- [ ] 核对依赖合入，确定 Ollama 可用版本、模型名称/精确标签及许可；先记录环境探测结果，不把“能下载”当“能运行”。
- [x] 先写 NDJSON 分片、结束统计、错误、取消和 provider 配置选择测试，运行确认目标实现失败。
- [x] 实现 Ollama 请求/响应到统一 provider 类型转换，保证中文分片、停止原因与 usage 按契约表达，缺失字段不伪造。
- [x] 实现超时、连接失败、模型未加载/不存在与取消；保持统一错误，不暴露 Ollama 内部地址/完整异常给普通用户。
- [x] 加入显式 provider 配置切换，确认无意外云端回退；使用相同 RAG 输入比较云端与本地事件协议。
- [ ] 在本机运行固定短问题和知识问答 smoke，记录模型版本、量化、上下文、首 token/总耗时、显存峰值与冷/热启动区别。
- [ ] 调整到本机可稳定承载的最小参数，记录上下文过长/资源不足的可理解失败；不以一次成功掩盖持续请求失败。
- [ ] 执行适配测试、RAG 回归和独立评审；交付运行说明与真实报告，提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| Ollama 中文流被网络拆分 | 输出文本与原始响应一致，正常结束只出现一次 |
| MODEL_PROVIDER 切换 cloud/ollama | 同一 RAG 调用使用指定适配器，事件字段和业务响应不改变 |
| Ollama 离线、缺模型、资源不足 | 返回明确可恢复错误，不偷偷向云模型发送资料 |
| 用户取消或请求超时 | 本地生成连接释放，后续分片不写成成功回答 |
| 真机连续运行固定小样本 | 有实际成功率、首 token/总耗时和显存记录；引用/拒答链路可用 |

```powershell
# backend
uv run pytest tests/providers/test_ollama.py tests/providers/test_provider_selection.py -q
uv run pytest tests/providers tests/rag -q
uv run ruff check .
uv run python ../experiments/inference/smoke.py --provider ollama
```

smoke 入口在本任务创建，读取环境配置；不得把模型密钥或未经授权的真实资料写进命令历史。

## 已知问题与外部阻塞

需用户允许的模型下载、可用 Ollama/GPU 驱动环境及磁盘容量。模型精确标签、大小和许可证开发时核对；GPU 不可用时可推进假服务测试，真实本地推理验收仍待环境就绪。

## 工作记录与完成标准

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未安装 Ollama、未下载模型、未测性能。
- 按 [WORKFLOW](../WORKFLOW.md) 记录假服务/真机证据和评审；分支 `in_review`，合入权威 main 且检查通过后统一置 `done`。


### 2026-10-01 实现与本地验收（待真机/评审/合并）

- 已原子领取，owner_token `c65d9708-1e82-40d9-afb7-40d07be9ded5`；独立worktree `C:/Users/Administrator/.codex/worktrees/todo-014-ollama/aiSoftwareAttempt`，分支`feat/todo-014-ollama`，基线`0f5832279978983c959deff434990ca1b7ec7c9f`。专属API8144/Web5244/DB15474/Compose qa-todo-014-c65d97。主代理统一负责PR/评审/合并和状态收尾；本代理不推送。
- `uv sync --directory backend --frozen --extra dev`、`npm ci --prefix frontend`、`node scripts/dev.mjs db-up`真实成功；复用锁定httpx2==2.13.0，无新增依赖或迁移。provider/RAG基线176项通过。
- TDD：Ollama/配置RED为40失败、12通过（缺少ollama选择）；Docker宿主HTTP行为单独RED 1失败后GREEN；smoke入口RED 2失败后GREEN。最终新增55项测试，provider/RAG共231项通过。真实TCP假服务覆盖中文跨UTF-8块、NDJSON、唯一终态/部分usage、错误脱敏、缺模型404、EOF、无效/过大记录、超时、取消/aclose/socket释放及现有RAG对length拒绝。
- `OllamaProvider`消费原生POST`/api/chat`与NDJSON，输出既有LLMDelta；`done:true`必须有stop/length原因，缺字段不猜成功。原生输入/输出token计数映射prompt/completion，total保持null。缺模型/资源失败报告既有脱敏错误，不透明重试或云fallback。
- 配置显式mock/cloud/ollama，保留allowlist、默认mock；本地Ollama无需key。HTTP只允许loopback；仅Ollama额外允许Docker Desktop的host.docker.internal，cloud限制不变。`OLLAMA_NUM_CTX=4096`为待真机验证参数，不是吞吐保证。
- 真机入口`experiments/inference/smoke.py`已实现，固定三次短问、元数据、首文本/总耗时、真实usage/失败记录；无`--run`不发模型请求。`smoke_rag.py`显式专项复用真实上传/解析/BGE/RAG与临时schema，覆盖连续引用、多轮、无依据和撤权；`--collect-only`已核验1项可收集，未实际GPU运行。命令与报告字段见[说明](../../experiments/inference/README.md)。
- 实际统一验收：`node scripts/dev.mjs check`退出0；Ruff通过、pytest **730 passed, 1 warning**、两次Alembic成功、前端lint/typecheck通过、Vitest **114 passed / 19 files**、build成功、Playwright默认**18 passed**、chat/handoff/feedback **4 passed**、analytics **1 passed**。保留`.local/check-014.txt`；warning为现有Starlette AnyIO别名弃用，前端现有大chunk/NO_COLOR/Node shell弃用提示，不伪报为无warning。专项`uv run --directory backend --frozen ruff check ../experiments/inference`通过。
- 已核对官方主源[Chat](https://docs.ollama.com/api/chat)、[Streaming](https://docs.ollama.com/api/streaming)、[Errors](https://docs.ollama.com/api/errors)。本批次推荐`qwen3:4b-instruct-2507-q4_K_M`；模型下载、精确digest/量化/许可、Ollama0.35.0及GPU由主代理实测。模型/HF主源补核因浏览工具连接失败尚待主代理处理，不把建议标签当已运行。
- 主代理正在处理真实Ollama模型下载连接中断；尚未提交真实短问/RAG、显存峰值、冷/热或稳定性成功记录。真实环境通过、独立评审通过及合入权威main后才可收尾done。当前PR、功能合并SHA为空，云CI未运行。共享`.env.example`/CONTRACTS整合提案位于忽略目录`.local/shared-proposals.md`，由主代理协调编辑。
