# 模型 provider（todo-004）

本模块只供后端调用，不暴露 HTTP 模型代理端点。`create_provider()` 从本 worktree `.env` / 进程环境读取配置，默认返回不会联网的 `MockProvider`。真实云模型仅支持项目选定的 OpenAI-compatible Chat Completions 文本流公共子集。

## 接口与生命周期

```python
from contextlib import aclosing

from app.modules.providers.factory import create_provider
from app.modules.providers.schemas import LLMMessage

provider = create_provider()
async with aclosing(provider.stream(
    [LLMMessage(role="user", content="你好")],
    max_tokens=128,
    temperature=0.2,
)) as stream:
    async for delta in stream:
        # text 是新增文本；finish_reason 非空的事件是唯一终止事件。
        # 调用者自行持久化文本、处理截断/过滤、转换为业务 SSE。
        print(delta.text)
```

- `LLMMessage` 接收 system/user/assistant 和文本；不支持工具或图像。
- `LLMDelta(text, finish_reason, usage)`：文本事件没有 finish_reason；收到 `[DONE]` 并关闭上游后才产生唯一终止事件。正常完成为 `stop`，`length` 和 `content_filter` 必须由业务层作为截断/过滤处理，不能当作完整回答。
- `LLMUsage` 只保留 prompt_tokens、completion_tokens、total_tokens，允许各字段为 null；没有上游 usage 时整个 usage 为 null，不在本地猜测计费用量。首版请求不发送厂商扩展字段或 `stream_options`，部分服务因此不返回 usage。
- 空白 stop 响应报告 `PROVIDER_EMPTY_RESPONSE`。有 finish_reason 但无 `[DONE]` 仍报告断流；不能持久化为成功。
- 提前退出循环必须使用 `aclosing` 或显式 `await stream.aclose()`；消费任务的取消会向上传播 `CancelledError` 并释放连接。仅 `break` 不保证 Python 异步生成器立即关闭。
- 每次生成独立持有 HTTP 客户端和连接，没有自动重试或重定向；部分文本失败后由业务层标记失败，不透明重放整段回答。
- 连接和每次等待响应数据分别受超时控制；read timeout 不是整段回答总时长。SSE 单事件最大 64 KiB。客户端直接连接配置地址（不读取环境代理或 netrc），保留 HTTPS 证书验证。
- Mock 返回明确标注的固定文本，按字符模拟输出上限；这是测试行为，usage 始终为 null，不作为真实模型质量或 token 计算依据。

## 后端配置

参考根目录 [.env.example](../../../../.env.example)。配置不进入前端、不从用户消息中选择模型。

| 变量 | 规则 |
| --- | --- |
| MODEL_PROVIDER | `mock`（默认）或 `cloud` |
| MODEL_BASE_URL | 含版本路径的 HTTPS 地址；会追加 `/chat/completions`。仅本机 loopback 允许 HTTP 假服务；禁止 URL 凭据、query、fragment |
| MODEL_ID | 服务端选择的模型，必须在 MODEL_ALLOWED_IDS 中 |
| MODEL_ALLOWED_IDS | JSON 字符串数组，例如 `["example-model"]` |
| MODEL_API_KEY | 后端 Bearer key；SecretStr 隐藏普通配置 repr |
| MODEL_CONNECT_TIMEOUT_SECONDS | 默认 10，范围 (0, 120] 秒 |
| MODEL_READ_TIMEOUT_SECONDS | 默认 30，范围 (0, 300] 秒 |
| MODEL_MAX_OUTPUT_TOKENS | 默认 512，范围 1–32768；调用请求超出此上限时在联网前拒绝 |

请求仅包含 model、messages、stream=true、max_tokens、temperature。要求提供商支持此子集；只支持 `max_completion_tokens` 或其他协议的模型不能直接宣称兼容。temperature 接受 0–2 的有限数值。

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

2026-09-23 用户明确要求真实云联调等其另行通知。当前真实云连接未验证；下列命令是以后获得启动指令后的入口，不是已经运行的证据。

在本 worktree 被忽略的 `.local/model-smoke.env` 填好连接信息，确认厂商、调用次数、预算和账户限额，再显式运行：

```text
uv run --directory backend --frozen python -m app.modules.providers.smoke --env-file ../.local/model-smoke.env --run
```

每次执行只发送一个固定短问题，最多 64 个输出 tokens，无重试；只打印模型、UTC 时间、耗时、字符数、结束原因及实际返回的 usage，不打印 key、endpoint 或完整回答。非 stop 结束返回非零退出码。省略 `--run` 不发送请求。配置文件中的 SMOKE_PROVIDER_NAME / SMOKE_MAX_CALLS / SMOKE_BUDGET 是人工审批记录，程序不自动解析价格或累计预算；后续操作者须核对累计调用次数和厂商账单，不得将输出 token 上限等同于金额上限。

协议参考：[Chat Completions 官方结构](https://developers.openai.com/api/reference/resources/chat)。
