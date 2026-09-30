# 模型 provider（todo-004 / todo-014）

本模块只供后端调用，不暴露 HTTP 模型代理端点。`create_provider()` 从本 worktree `.env` / 进程环境读取配置，默认返回不会联网的 `MockProvider`。真实云模型仅支持项目选定的 OpenAI-compatible Chat Completions 文本流公共子集。

## 接口与生命周期

```python
from contextlib import aclosing

from app.modules.providers.factory import create_provider
from app.modules.providers.schemas import LLMMessage

provider = create_provider()
async with aclosing(
    provider.stream(
        [LLMMessage(role="user", content="你好")],
        max_tokens=128,
        temperature=0.2,
    )
) as stream:
    async for delta in stream:
        # text 是新增文本；finish_reason 非空的事件是唯一终止事件。
        # 调用者自行持久化文本、处理截断/过滤、转换为业务 SSE。
        print(delta.text)
```

- `LLMMessage` 接收 system/user/assistant 和文本；不支持工具或图像。
- `LLMDelta(text, finish_reason, usage)`：文本事件没有 finish_reason；收到 `[DONE]` 并关闭上游后才产生唯一终止事件。正常完成为 `stop`，`length` 和 `content_filter` 必须由业务层作为截断/过滤处理，不能当作完整回答。
- `LLMUsage` 只保留 prompt_tokens、completion_tokens、total_tokens，允许各字段为 null；没有上游 usage 时整个 usage 为 null，不在本地猜测计费用量。默认请求不发送厂商扩展字段或 `stream_options`，部分服务因此不返回 usage。
- 空白 stop 响应报告 `PROVIDER_EMPTY_RESPONSE`。有 finish_reason 但无 `[DONE]` 仍报告断流；不能持久化为成功。
- 提前退出循环必须使用 `aclosing` 或显式 `await stream.aclose()`；消费任务的取消会向上传播 `CancelledError` 并释放连接。仅 `break` 不保证 Python 异步生成器立即关闭。
- 每次生成独立持有 HTTP 客户端和连接，没有自动重试或重定向；部分文本失败后由业务层标记失败，不透明重放整段回答。
- 连接和每次等待响应数据分别受超时控制；read timeout 不是整段回答总时长。SSE 单事件最大 64 KiB。客户端直接连接配置地址（不读取环境代理或 netrc），保留 HTTPS 证书验证。
- Mock 返回明确标注的固定文本，按字符模拟输出上限；这是测试行为，usage 始终为 null，不作为真实模型质量或 token 计算依据。

## 后端配置

参考根目录 [.env.example](../../../../.env.example)。配置不进入前端、不从用户消息中选择模型。

| 变量 | 规则 |
| --- | --- |
| MODEL_PROVIDER | `mock`（默认）、`cloud` 或 `ollama` |
| MODEL_BASE_URL | cloud含版本路径并追加`/chat/completions`；ollama为根地址并追加`/api/chat`。HTTPS；HTTP仅loopback，Ollama额外允许host.docker.internal。禁止URL凭据、query、fragment |
| MODEL_DISABLE_THINKING | 默认 false；true时cloud发送`thinking: {type: "disabled"}`，Ollama发送`think:false`，仅用于支持该选项的模型 |
| MODEL_ID | 服务端选择的模型，必须在 MODEL_ALLOWED_IDS 中 |
| MODEL_ALLOWED_IDS | JSON 字符串数组，例如 `["example-model"]` |
| MODEL_API_KEY | cloud必须的后端Bearer key；Ollama不要求且不发送该key；SecretStr隐藏配置repr |
| MODEL_CONNECT_TIMEOUT_SECONDS | 默认 10，范围 (0, 120] 秒 |
| MODEL_READ_TIMEOUT_SECONDS | 默认 30，范围 (0, 300] 秒 |
| MODEL_MAX_OUTPUT_TOKENS | 默认 512，范围 1–32768；调用请求超出此上限时在联网前拒绝 |

默认请求仅包含 model、messages、stream=true、max_tokens、temperature。显式设置 MODEL_DISABLE_THINKING=true 时额外发送 thinking.type=disabled；该厂商选项仅在后端配置，不改变业务 stream 接口。要求提供商支持此子集；只支持 `max_completion_tokens` 或其他协议的模型不能直接宣称兼容。temperature 接受 0–2 的有限数值。

`ProviderError` 的 code/message 为固定脱敏内容；不把上游错误体、Authorization、异常连接信息带入异常输出。业务层可依据 code 记录失败类型与 request_id：

| code | 情况 |
| --- | --- |
| PROVIDER_CONFIG_ERROR | 工厂读取配置失败 |
| PROVIDER_BAD_REQUEST | 本地参数无效，或上游其他非 200 状态（含拒绝重定向） |
| PROVIDER_AUTH_FAILED | 上游 401/403 |
| PROVIDER_RATE_LIMITED | 上游 429 |
| PROVIDER_UNAVAILABLE | 上游 5xx、流内 error，或输出前连接失败 |
| PROVIDER_TIMEOUT | 连接/读取/写入/连接池等待超时 |
| PROVIDER_STREAM_INTERRUPTED | 无 DONE 或已有文本后传输失败 |
| PROVIDER_PROTOCOL_ERROR | SSE/JSON/字段格式错误，或 DONE 缺少结束原因 |
| PROVIDER_EMPTY_RESPONSE | stop 结束但没有有效文本 |
| PROVIDER_UNSUPPORTED_RESPONSE | 工具调用或不支持的结束原因 |

## 验证与受控真实联调

`uv run --directory backend --frozen pytest tests/providers -q` 使用本机真实 TCP 假 HTTP 服务验证网络分片、usage、失败和关闭连接。连接超时使用确定性的传输边界替身；不依赖公网超时、真实 key 或计费服务。这些测试已被统一 `node scripts/dev.mjs check` 中的完整 pytest 自动收录。

2026-09-23 用户先延后真实云联调，随后明确授权恢复；本次配置为 DeepSeek `deepseek-flash`、最多 1 次、预算 5 CNY、最多 64 输出 tokens。实际结果以 todo-004 最新工作记录为准。DeepSeek 默认开启思考，短回答测试在本地配置 MODEL_DISABLE_THINKING=true，避免额度被思考过程耗尽；依据 [官方模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)。

在本 worktree 被忽略的 `.local/model-smoke.env` 填好连接信息，确认厂商、调用次数、预算和账户限额，再显式运行：

```text
uv run --directory backend --frozen python -m app.modules.providers.smoke --env-file ../.local/model-smoke.env --run
```

每次执行只发送一个固定短问题，最多 64 个输出 tokens，无重试；只打印模型、UTC 时间、耗时、字符数、结束原因及实际返回的 usage，不打印 key、endpoint 或完整回答。非 stop 结束返回非零退出码。省略 `--run` 不发送请求。配置文件中的 SMOKE_PROVIDER_NAME / SMOKE_MAX_CALLS / SMOKE_BUDGET 是人工审批记录，程序不自动解析价格或累计预算；后续操作者须核对累计调用次数和厂商账单，不得将输出 token 上限等同于金额上限。

协议参考：[Chat Completions 官方结构](https://developers.openai.com/api/reference/resources/chat)。


## Ollama 原生流（todo-014）

显式`MODEL_PROVIDER=ollama`选择`OllamaProvider`，不会因本地故障选择云provider。MODEL_ID同样必须在服务端allowlist，Ollama无需MODEL_API_KEY。新增`OLLAMA_NUM_CTX`默认4096，范围512..131072，控制原生`options.num_ctx`；每次调用的max_tokens/temperature映射`options.num_predict`/`options.temperature`，业务调用签名保持一致。完整运行和真机专项见[本地推理验收](../../../../experiments/inference/README.md)。

本批次以 **Ollama 0.35.0** 为兼容基线：请求固定发送顶层 `truncate:false` 和 `shift:false`，禁止静默裁剪输入及生成期间的上下文滑动，超出可用上下文时应拒绝或以非正常终态结束；业务 RAG 不将其当作完整回答。RAG 的 12000 UTF-8 字节预算不是 token 估计，不能保证适配 `OLLAMA_NUM_CTX=4096`，也不以减掉 system 或证据来重试。开关已通过请求契约测试并核对 [0.35.0 ChatRequest](https://github.com/ollama/ollama/blob/v0.35.0/api/types.go)、[消息裁剪](https://github.com/ollama/ollama/blob/v0.35.0/server/prompt.go)、[调度器](https://github.com/ollama/ollama/blob/v0.35.0/server/sched.go)和[底层上下文处理](https://github.com/ollama/ollama/blob/v0.35.0/llm/llama_server.go)。旧版本兼容性未验证；实际模型的短问成功和超长输入拒绝仍须在真机专项中记录，不能以假 HTTP 测试代替。

以上`[DONE]`/SSE生命周期说明专用于cloud。Ollama读取原生`application/x-ndjson`，按完整JSON行解码，允许中文UTF-8跨网络块，单行上限64KiB。`done:true`与有效`done_reason`共同确定完整流结束；终止片段仍在上游关闭后唯一发出。`stop`正常完成，`length`显式表示截断；缺少原因为协议错误，缺少done的EOF为断流。不把`thinking`文本展示为回答；工具/图像响应拒绝。RAG现有正常stop约束保持不变。

`prompt_eval_count`映射prompt_tokens，`eval_count`映射completion_tokens；只有这些原生计数有值时才提供usage，各缺失字段保留null，total_tokens始终null，不相加估算。模型缺失404、上游5xx或流内error为PROVIDER_UNAVAILABLE；错误体、内部地址和完整异常不对外暴露。所有连接、取消、超时、无自动重试/重定向的保证与cloud相同。

协议主源：[Chat](https://docs.ollama.com/api/chat)、[Streaming](https://docs.ollama.com/api/streaming)、[Errors](https://docs.ollama.com/api/errors)。本机真实TCP假服务测试已接入默认完整pytest，真实模型脚本需显式执行，不由普通测试调用GPU或云服务。
