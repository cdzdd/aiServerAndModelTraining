# Ollama 本地推理验收（todo-014）

本目录只放显式执行的本地模型验收，不由普通pytest或业务启动自动调用。业务通过相同`create_provider()`和`stream(messages, *, max_tokens, temperature)`切换；没有本地失败后的云端fallback。

## 模型与环境

本批次建议精确标签`qwen3:4b-instruct-2507-q4_K_M`，对应[Qwen/Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)的非思考指令版本；模型下载、Ollama版本、真实量化与digest以主代理真机报告为准。不能把标签建议当作已安装或已验证。Ollama标签页：[精确模型标签](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M)。不从本脚本安装工具、拉模型或修改GPU环境。

只在本机/受控内部网络运行Ollama，不公开未鉴权模型端口。后端运行Windows时根地址用`http://127.0.0.1:11434`；Docker Desktop容器中的后端显式用`http://host.docker.internal:11434`，并由部署者验证宿主绑定/防火墙。这个别名仅Ollama允许HTTP，任意外网HTTP域名仍被拒绝；云provider仍要求HTTPS（loopback假服务例外）。

在本worktree忽略目录`.local/ollama-smoke.env`配置以下非秘密模型项；BGE、数据库、上传目录沿用本worktree自己的`.env`，不要复用其他worktree的服务数据：

```dotenv
MODEL_PROVIDER=ollama
MODEL_BASE_URL=http://127.0.0.1:11434
MODEL_ID=qwen3:4b-instruct-2507-q4_K_M
MODEL_ALLOWED_IDS=["qwen3:4b-instruct-2507-q4_K_M"]
OLLAMA_NUM_CTX=4096
MODEL_MAX_OUTPUT_TOKENS=512
MODEL_CONNECT_TIMEOUT_SECONDS=10
MODEL_READ_TIMEOUT_SECONDS=120
MODEL_DISABLE_THINKING=false
```

Ollama不要求或发送MODEL_API_KEY。MODEL_BASE_URL是服务根地址，不带`/api`；适配器追加`/api/chat`。不设置MODEL_DISABLE_THINKING时使用模型默认值；true时发送Ollama原生`think:false`，仅适用于支持该选项的模型。本次非思考指令模型不需要该选项。

## 上下文完整性与版本边界

本批次以 **Ollama 0.35.0** 为接口兼容基线，适配器固定发送顶层 `truncate:false`、`shift:false`，要求输入过长时拒绝而不静默删除上下文，并禁止生成期间的上下文滑动。超限可能通过 HTTP 错误、流内 error 或非正常结束原因返回，沿用现有脱敏错误和 RAG 失败处理，不自动重试或改用云端。12000 UTF-8 字节的 RAG 预算不是模型 token 上限；不能据此宣称输入一定适配 4096 context。

依据已核对的 [0.35.0 请求字段](https://github.com/ollama/ollama/blob/v0.35.0/api/types.go)、[消息裁剪](https://github.com/ollama/ollama/blob/v0.35.0/server/prompt.go)、[shift 调度](https://github.com/ollama/ollama/blob/v0.35.0/server/sched.go)和[底层裁剪处理](https://github.com/ollama/ollama/blob/v0.35.0/llm/llama_server.go)，两个开关必须同时关闭。请求契约由真实 TCP 假服务核验；旧版本兼容性未验证，不能假定服务会识别开关。真机验收须记录实际版本、模型和 context，先确认短输入正常完成，再确认明显超过上下文的输入被拒绝且没有成功终态。此项真实超长检查由主代理完成，当前文档不声称已通过。

## 固定短问与连续请求

从worktree根目录执行。省略`--run`仅说明，不发出模型请求；显式运行固定三个独立问题，无自动重试。每个问题至多64输出token、temperature=0。

```powershell
uv run --directory backend --frozen python ../experiments/inference/smoke.py --provider ollama --env-file ../.local/ollama-smoke.env --label cold --run --output ../.local/ollama-smoke-cold.json
uv run --directory backend --frozen python ../experiments/inference/smoke.py --provider ollama --env-file ../.local/ollama-smoke.env --label warm --run --output ../.local/ollama-smoke-warm.json
```

`--label`只是操作者对首个请求状态的声明。真正冷启动必须先显式卸载该模型，热启动必须保留加载状态；脚本不自动装载/卸载其他模型。短问为1+1、3+4、1+1，报告保存固定问题与输出，人工核对答案2/7/2；`successes`只统计stop完成，不能当作质量正确率。报告包括实际Ollama版本、模型digest/量化详情、num_ctx、各请求首段文本延时和总耗时、真实usage及脱敏错误码。首段文本延时近似首token，不代表底层精确token时间。

显存峰值字段默认null。主代理另用`nvidia-smi`在执行期间采样，记录采样间隔、GPU型号和峰值后附入真机报告；不能用模型文件大小推测显存。若元数据预检失败，脚本返回非零且不继续生成。若请求失败，仍记录三个计划请求的实际结果，不额外重试。

## 真实知识问答、引用与拒答

确保本worktree专属DB已启动、指定固定BGE模型/tokenizer路径可用。专项使用已有真实认证/临时schema fixture，建立一份明确标注虚构的校园文档，通过上传、解析、真实CPU BGE索引/检索和生产RAG引用校验。不会读取未经授权业务资料。

```powershell
$env:OLLAMA_SMOKE_CONFIG = Join-Path (Get-Location) '.local/ollama-smoke.env'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
uv run --directory backend --frozen pytest -c pyproject.toml ../experiments/inference/smoke_rag.py -q -s
```

这里必须显式`-c pyproject.toml`，外部专项路径不会自动使用backend测试配置。覆盖三次相同知识问题正常回答与引用、多轮追问、无相关依据拒答、成员撤权后拒答；预计5次实际模型生成（追问为改写+回答），无证据与撤权不调用模型。失败即非零，`.local/ollama-rag-smoke.json`逐例保留已完成证据，不把部分运行当完整通过。

普通统一验收包含假HTTP协议测试；专项真实模型不在自动收集范围。发布`reports/`前移除连接地址、账号/密钥、文件系统敏感路径，标明冷/热前置条件、硬件、样本规模和限制。小样本成功不等于代表性质量或生产吞吐保证。

## 协议依据

[Ollama Chat](https://docs.ollama.com/api/chat)、[Streaming](https://docs.ollama.com/api/streaming)、[Errors](https://docs.ollama.com/api/errors)。POST`/api/chat`的NDJSON按`done:true`完成；`done_reason`映射统一终止原因。`prompt_eval_count`/`eval_count`分别映射prompt/completion，未提供字段保留null，total不相加估算。done原因缺失、EOF中断、无效协议、空白stop均不冒充正常答案。业务RAG只接受正常stop。
