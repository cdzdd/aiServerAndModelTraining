# 本机 4B QLoRA 微调实战

本任务完成一个小数据、可恢复的本地训练案例：Qwen3-4B-Instruct-2507 基座、BNB 4-bit NF4、LoRA rank 8，在 RTX 5070 Ti 16GB 上进行 2 step smoke、指定 checkpoint-2 恢复至 step 4，以及独立 20 step 正式训练。训练材料是原创虚构校园资料，仅用于练习 RAG 原文选择 JSON 的输出格式。效果判断以 [同栈对照报告](reports/comparison-2026-10-01.md) 为准；低训练 loss 不能代表真实业务能力。

- [实际训练、恢复与资源记录](reports/training-2026-10-01.md)
- [完整制品与配置哈希](reports/training-artifacts-2026-10-01.json)
- [当前本地服务与整卡资源快照](reports/local-deployment-2026-10-01.json)
- [资料来源与隔离规则](data/README.md)
- [统一评测器](../evaluation/README.md)
- [本地网页使用说明](../../docs/operations/local-run.md)

## 当前机器的位置

独立训练环境：WSL Ubuntu 的 `/home/cdzdongdongcheng/.local/share/qa-training/venv`。实际验证版本为 Python 3.12.3、PyTorch 2.9.1+cu128、CUDA runtime 12.8、bitsandbytes 0.50.2、LLaMAFactory 0.9.5、Transformers 4.57.6、PEFT 0.18.1、Accelerate 1.11.0。FastAPI 0.142.2/uvicorn 0.54.0 仅服务实验 API；业务后端保持自己的 CPU 环境和锁文件。

模型位于 `C:\Users\Administrator\.codex\worktrees\todo-014-ollama\aiSoftwareAttempt\.local\models\qwen3-4b-instruct-2507`，训练数据、生成配置和制品位于 `C:\Users\Administrator\.codex\worktrees\todo-015-qlora\aiSoftwareAttempt\.local\finetuning`。WSL 对应路径从 `/mnt/c/Users/...` 开始。模型缓存只读共享，训练输出、测试数据库和服务端口由 015 独立管理。

基座为 `Qwen/Qwen3-4B-Instruct-2507`，固定修订 `cdbee75f17c01a7cc42f958dc650907174af0554`，Apache-2.0 许可；三个原始 safetensors 分片共 8,044,982,000 字节。完整本机文件身份和许可见制品清单。Adapter 依赖这个原始基座和兼容的 PEFT/BNB 环境；当前交付格式为 safetensors adapter。

2026-10-01 05:34（上海时区）的真实现场：本地网页 `http://127.0.0.1:5246` ready，使用 Ollama 的 `qwen3:4b-instruct-2507-q4_K_M` 基座；微调实验 API `http://127.0.0.1:11435/health` ready，模型 ID 为 `qwen3-4b-qlora-demo`。Ollama 已实际完成一次生成并保持加载，微调 adapter 也已加载，两组服务保留运行。此时整张 GPU 为 16,303 MiB 总量、9,661 MiB 已用、6,335 MiB 空闲，包含桌面和其他进程，仅证明这个空闲现场可承载两组已加载模型；不保证同时生成或训练的余量。原始记录见资源快照。正式训练、重测或交互 CLI 加载时串行协调 GPU，先停止自己启动的实验 API 并卸载本轮 Ollama 模型，再开始下一项。

## 准备数据与配置

以下操作在 WSL、该任务 worktree 根目录运行。当前机器已经安装好环境和模型。另机复现需要单独建立 Python 3.12 训练环境，按上面的精确版本安装 PyTorch CUDA 12.8 与训练库，下载固定修订的原始模型并核验制品清单；业务环境不安装训练依赖。

```bash
source /home/cdzdongdongcheng/.local/share/qa-training/venv/bin/activate
cd /mnt/c/Users/Administrator/.codex/worktrees/todo-015-qlora/aiSoftwareAttempt
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 WANDB_DISABLED=true
MODEL_DIR=/mnt/c/Users/Administrator/.codex/worktrees/todo-014-ollama/aiSoftwareAttempt/.local/models/qwen3-4b-instruct-2507
python experiments/finetuning/prepare_data.py --model-path "$MODEL_DIR" --runtime-root "$PWD/.local/finetuning"
python experiments/finetuning/validate_data.py --manifest .local/finetuning/manifest.json
```

生成 8 条 train、2 条独立 validation，以及 `.local/finetuning/configs/` 下的 5 份训练/推理配置。本次生成的训练/验证 JSON、API 密钥、权重和 checkpoint 均不提交 Git。校验会阻止空回答、角色顺序错误、非法 Unicode、重复问题/来源、评测集泄漏或不受原文支持的引文。代理逐题复核记录在本机 `.local/independent-review-015-data.md`，不冒称人工业务审核。

训练前必须使用真实 Factory 模板检查完整输入与目标长度；本次实测 366–403 tokens，均小于 cutoff 1024。以下片段可在同一 WSL 终端复现：

```bash
python - <<'PY'
import json
from pathlib import Path
from transformers import AutoTokenizer
from llamafactory.data.template import get_template_and_fix_tokenizer
from llamafactory.hparams import DataArguments
root = Path('.local/finetuning')
config = __import__('yaml').safe_load((root/'configs/qlora-smoke.yaml').read_text())
tokenizer = AutoTokenizer.from_pretrained(config['model_name_or_path'], local_files_only=True, trust_remote_code=False)
template = get_template_and_fix_tokenizer(tokenizer, DataArguments(template='qwen3_nothink'))
for split in ['train', 'validation']:
    for index, sample in enumerate(json.loads((root/(split+'.json')).read_text())):
        messages = sample['messages']
        pairs = template.encode_multiturn(tokenizer, messages[1:], system=messages[0]['content'])
        tokens = sum(len(src)+len(tgt) for src, tgt in pairs)
        assert tokens <= config['cutoff_len'] and sum(len(tgt) for _, tgt in pairs) > 0
        print(split, index, tokens)
PY
```

## 短训练、恢复和正式训练

训练独占 GPU 时先卸载本轮 Ollama 已加载模型并停止其他训练。保留本轮自己创建的服务与制品；不终止不明进程。配置 recipe 使用 micro-batch 1、梯度累积 4、cutoff 1024、NF4 double quantization、BF16、SDPA、LoRA rank 8/alpha 16/all、constant LR 5e-5、seed 42。

```bash
llamafactory-cli train .local/finetuning/configs/qlora-smoke.yaml
llamafactory-cli train .local/finetuning/configs/qlora-resume.yaml
llamafactory-cli train .local/finetuning/configs/qlora-train.yaml
```

smoke 到 step 2 后正常退出；resume 显式恢复 optimizer/scheduler/RNG 与 adapter，从 checkpoint-2 继续到 step 4。正式训练在独立 `train/` 目录从基座开始 20 steps，不沿用 smoke adapter。本次验证的是计划停止后的恢复机制，没有制造强制崩溃。`save_steps=2` 表示每两步保存，正式训练保留 checkpoint-2 到 checkpoint-20 共 10 份；`train/` 根目录保留最终 adapter，方便本地使用。

重新实验时给 `--output` 和 `--runtime-root` 指定新的忽略目录并准备独立配置，避免自动从旧 output_dir 恢复。相同 seed 和软件版本不保证跨设备逐 bit 相同。实际 loss、GPU 峰值和包含模型加载/验证/保存的耗时见训练报告。

## 本地使用微调模型

实验 API 固定绑定 `127.0.0.1:11435`，使用本机私有 key 文件；启动时先加载基座/adapter，再出现 `/health` ready。所有生成单并发，错误不输出凭据或原始模型异常。当前机器已生成 `.local/finetuning/api.key`；另机首次使用需把 `secrets.token_hex(32)` 写入自己的私有 key 文件，避免把凭据放命令行或日志。已有服务占用 11435 时直接使用该服务；切换模型或重启前在自己启动它的终端按 Ctrl+C，等待退出再启动下一组。

```bash
python experiments/finetuning/local_api.py --config .local/finetuning/configs/inference-finetuned.yaml --key-file .local/finetuning/api.key --model-id qwen3-4b-qlora-demo --port 11435
```

另一个同环境终端可用虚构训练样本演示请求：

```bash
python - <<'PY'
import json
from pathlib import Path
import requests
messages = json.loads(Path('.local/finetuning/train.json').read_text())[0]['messages'][:-1]
key = Path('.local/finetuning/api.key').read_text().strip()
with requests.Session() as client:
    client.trust_env = False
    response = client.post('http://127.0.0.1:11435/v1/chat/completions',
        headers={'Authorization': 'Bearer '+key},
        json={'model': 'qwen3-4b-qlora-demo', 'messages': messages, 'stream': True,
              'max_tokens': 512, 'temperature': 0}, timeout=120)
    response.raise_for_status()
    print(response.text)
PY
```

本节示例已在当前微调 API 原样执行：返回 answered 原文选择 JSON、finish_reason=stop、prompt/completion/total=345/22/367，并以 DONE 结束，输出不含私钥。这是教学训练样本的调用验证，不作为独立评测结果。

输出是原文选择 JSON 与实际 finish reason/usage 的 SSE。服务缓冲完整响应后发送，首段时间包含整次生成；`length` 保留为截断，业务 RAG 会拒绝其成功收尾。prompt/completion 数来自 Factory 的真实返回值，total 为二者之和。

需要交互体验时可运行 `llamafactory-cli chat .local/finetuning/configs/inference-finetuned.yaml`，先停止自己启动的 API 以释放 GPU。Factory 原生 CLI chat 没有本项目对已加载 model.generation_config 的修正，do_sample=False 仍可能被模型默认值覆盖为采样，因此不能将其结果称为本次相同贪心对照。可复现的正式对照和主要使用入口是上述已修正的实验 API。实验 API/聊天的原始输出尚未经过应用的权限、引用和资料版本核验；正式 RAG 对照仍走现有后端规则。网页使用已经验收的 Ollama 基座；微调 adapter 通过本节独立 API 或 Factory 聊天访问，不自动切换生产 provider、导出 GGUF 或启用 todo-018。

## 复现基座与微调 RAG 对照

两组均采用原始同一 4B 基座的 HF/BNB NF4、BF16、qwen3_nothink、贪心输出与最多 512 tokens；只在微调组增加 adapter。桥接服务在模型加载后固定实际 model.generation_config.do_sample=False，防止 Transformers 4.57.6 用模型采样默认值覆盖调用参数；真实依赖回归与独立 PEFT generate 核验有效模式为 GREEDY_SEARCH。先运行 `inference-base.yaml`，完成两份报告，关闭本轮 API 后再运行 `inference-finetuned.yaml`。固定使用 todo-013 的 baseline vector/threshold 0.65/top-k 5、rag-extractive-v2、18 dev/42 test；测试标签不用来调参。

实际 benchmark 的 private runtime manifest 分别记录推理配置 SHA、训练 manifest SHA、固定基座修订、软件版本，以及微调组 config/weights 两个 adapter SHA。该清单是调用者复核的旁证，HTTP 服务没有远程证明机制。JSON 报告保留实际代码 SHA、dirty 状态与每条检索/生成/引用/失败。

在 Windows worktree 根目录的新 PowerShell 终端设置本轮进程变量；命令不显示 key：

```powershell
$env:MODEL_PROVIDER='cloud'
$env:MODEL_BASE_URL='http://127.0.0.1:11435/v1'
$env:MODEL_ID='qwen3-4b-qlora-demo'
$env:MODEL_ALLOWED_IDS='["qwen3-4b-qlora-demo"]'
$env:MODEL_API_KEY=[IO.File]::ReadAllText((Join-Path $PWD '.local/finetuning/api.key')).Trim()
$env:MODEL_READ_TIMEOUT_SECONDS='120'
$env:MODEL_DISABLE_THINKING='false'
uv run --directory backend --frozen python ../experiments/evaluation/run_eval.py --config ../experiments/evaluation/configs/baseline.yaml --split dev --generate --local-openai --runtime-manifest ../.local/finetuning/runtime-base.json --output ../.local/finetuning/replayed-dev-base-rag.json
uv run --directory backend --frozen python ../experiments/evaluation/run_eval.py --config ../experiments/evaluation/configs/baseline.yaml --split test --generate --local-openai --runtime-manifest ../.local/finetuning/runtime-base.json --output ../.local/finetuning/replayed-test-base-rag.json
```

微调组将 runtime manifest 改成 `runtime-finetuned.json`、输出文件名改成 `replayed-dev-finetuned-rag.json` / `replayed-test-finetuned-rag.json`，仍放入忽略的 `.local/finetuning/`，保留本轮已提交的原始报告。`MODEL_PROVIDER=cloud` 在这里仅选择现有 OpenAI 协议适配器；必须显式 `--local-openai` 且 URL 为字面量 HTTP loopback，所有远程、HTTPS 和 DNS 主机均被拒绝。应用 `.env` 与部署默认值保持原配置。完成后关闭这个临时 PowerShell 终端，避免实验变量影响普通检查。

该评测使用专用 qa_test 数据库的随机临时 schema；不会修改开发/本地网页业务资料。统一验收 `node scripts/dev.mjs check` 会运行本任务数据、桥接、实际 loopback HTTP 协议与端点守卫测试，不隐式启动 GPU、云服务或训练。

另机复现评测时，准备实际运行清单后再启动两组 API；以下片段仅采集已准备数据/配置/adapter 的 SHA，不读取密钥、不加载模型：

```bash
python - <<'PY'
import hashlib, importlib.metadata, json
import torch
from pathlib import Path
root = Path('.local/finetuning')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
packages = ['torch', 'transformers', 'llamafactory', 'bitsandbytes', 'peft', 'accelerate']
for kind in ['base', 'finetuned']:
    record = {'kind': kind, 'base_revision': 'cdbee75f17c01a7cc42f958dc650907174af0554',
        'inference_config_sha256': sha(root/f'configs/inference-{kind}.yaml'),
        'training_manifest_sha256': sha(root/'manifest.json'),
        'adapter_files_sha256': None,
        'runtime_versions': {p: importlib.metadata.version(p) for p in packages}}
    record['runtime_versions']['cuda'] = torch.version.cuda
    if kind == 'finetuned':
        record['adapter_files_sha256'] = {name: sha(root/'train'/name)
            for name in ['adapter_model.safetensors', 'adapter_config.json']}
    (root/f'runtime-{kind}.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
PY
```
