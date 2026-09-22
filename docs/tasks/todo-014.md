# todo-014：Ollama 本地推理与 provider 切换

| 字段 | 值 |
|---|---|
| id | todo-014 |
| 状态 | pending |
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
- [ ] 先写 NDJSON 分片、结束统计、错误、取消和 provider 配置选择测试，运行确认目标实现失败。
- [ ] 实现 Ollama 请求/响应到统一 provider 类型转换，保证中文分片、停止原因与 usage 按契约表达，缺失字段不伪造。
- [ ] 实现超时、连接失败、模型未加载/不存在与取消；保持统一错误，不暴露 Ollama 内部地址/完整异常给普通用户。
- [ ] 加入显式 provider 配置切换，确认无意外云端回退；使用相同 RAG 输入比较云端与本地事件协议。
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
