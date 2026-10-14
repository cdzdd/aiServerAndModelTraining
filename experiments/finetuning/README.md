# 本机 QLoRA 微调实战

本任务完成一个小数据、可恢复的本地训练案例：Qwen3-4B-Instruct-2507 基座、BNB 4-bit NF4、LoRA rank 8，在 RTX 5070 Ti 16GB 上进行 2 step smoke、指定 checkpoint-2 恢复至 step 4，以及独立 20 step 正式训练。训练材料是原创虚构校园资料，仅用于练习 RAG 原文选择 JSON 的输出格式。效果判断以 [同栈对照报告](reports/comparison-2026-10-01.md) 为准；低训练 loss 不能代表真实业务能力。

上述 4B 案例属于已完成的 015。019 已完成真实 100→200 step 恢复和独立 375-step 正式训练，保存有限完整状态与选出的最佳 adapter；实际 API 使用与对照效果尚待验收。见 [019 训练报告](reports/todo-019-training.md)、[任务记录](../../docs/tasks/todo-019.md) 和下方教程。020 未开始。

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

## 019：8B 数据与实际预跑

019 基座是 `Qwen/Qwen3-8B`，固定 revision `b968826d9c46dd6066d109eabc6255188de91218`、Apache-2.0；14 个原始加载文件共 16,397,459,696 字节，逐文件 SHA256 已核验。原始基座有 8,190,735,360 个参数，实际 4-bit Factory 加载后另有 43,646,976 个 LoRA 可训练参数，共 8,234,382,336 个。训练环境沿用上方已验证版本；未升级业务或 GPU 依赖。

新数据是明确虚构的校园/客服教学材料，`synthetic=true`、`human_reviewed=false`。7,200 候选题产生 14,400 个回答/改写候选投影，经质量与同上下文变体筛选保留 1,800 题：train 1,000 / dev 300 / test 500，对应 train 2,000 / dev 600 / test 1,000 条任务投影。14,400 不是正式训练行数。5,400 条原始来源按去标识归一后为 2,016 种文本；重复措辞与有限模板限制了结果的外推范围。独立代理核验了全部题目关系与 36 个 family，抽查 train 五类各 20 题，核验另有 100 题普通任务回归；这不是人工业务审核。

实际 Factory 模板编码审计覆盖 3,700 行，最长完整序列 536 tokens。实际 Factory 数据处理/CPU collator 另检查 train/dev 全部 2,600 行：train 742,392 个非 padding tokens、54,836 个监督目标 tokens，源输入和 padding 的标签均被屏蔽，目标与证据无截断。采用 cutoff 2048、qwen3_nothink、train_on_prompt=false；CPU 检查与真实 GPU 训练分别留证。

真实预跑始终保持同一个 `max_steps=200` cosine schedule：先暂停于 100，再从完整 checkpoint-100 恢复至 200，两个进程均正常退出并释放 GPU。完整文件哈希、504 项 Adam 状态在 100/200 的步数、scheduler 在 200 的 LR=0、Python/NumPy/CPU/CUDA RNG 及 504 个有限 LoRA 张量均核验；100→200 全部 504 个张量继续变化，支持完整状态恢复与真实参数更新。此证据不等于与不中断运行逐 bit 一致。

两个预跑尝试累计占用 1,905.2937805 秒，包括加载、三次 dev 验证、保存和退出；释放 GPU 后的暂停间隔未计时。实际每次执行 100 个更新，首段 train_runtime 718.8813 秒，不能把 Factory 以名义 200 步计算的 0.278 steps/s 当成实际吞吐。预跑采样整卡峰值 9,168 MiB，Torch 分配/保留峰值分别 7,935,535,104 / 8,550,088,704 字节；整卡包含桌面进程，10 秒采样不保证捕获瞬时峰值。

正式配置根据实测 7.242648 秒/更新冻结为 `max_steps=375`（2,000 行、有效 batch 16、每 epoch 125 步，3 epochs），save/eval_steps=250（预计约 30.18 分钟）、warmup 12 步；保持 NF4/double quant/BF16、LoRA rank16/alpha32/all、SDPA、gradient checkpointing、micro1/accum16、seed42、LR5e-5。实际从原始基座、独立空目录开始，无预跑 adapter 或 resume，已完成375步并正常退出。正式训练 forward 输入2,227,176/监督目标164,508tokens精确等于三遍CPU全行数据，累计三次尝试4,878.797805346716秒；GPU已在API启动前释放。

完整checkpoint-375保存504个有限Adam状态step375、scheduler375/LR0、Python/NumPy/CPU/CUDA RNG和有限LoRA张量。唯一周期dev在250（loss0.01013548020273447），测试前冻结选择的根目录adapter与checkpoint-250的weights/config均字节相同；所选weights SHA256 `46b2b53189c21b7ae5df206ad4aaae45136ae07cb3df1c282a0c17f8e324498b`，last375 weights为`0be0eca7e70e96b9152bcecb8df14d709886ddbcea7425591f90d2cac1e79617`。保存的末步状态与供推理所选adapter分开；训练/dev loss不证明最终生成效果。

## 019：累计预算、停止与恢复

所有真实训练须通过 [run_training.py](run_training.py)，同一任务全部尝试累计最多 86,400 秒。预跑、OOM/失败、加载、训练中验证、保存和退出都计入；数据准备、下载/哈希和训练结束后的最终离线评测另外计时。达到固定目标或停止条件便结束，不复制数据或重复训练来耗满 24 小时。

权威账本位于 Git common directory 的 `codex-coordination/training-budgets/todo-019.json`，CLI 会对照领取记录核验该路径。019 已初始化一次；恢复继续使用原账本，不再执行 `--initialize-budget`，不删除、重建账本或 `.initialized` 标记，不选择新路径或提高上限。原始模型、冻结数据、输出和 checkpoint 保留在 019 独立 worktree 的忽略 `.local/` 中；主工作区的 `.local/` 不含这些制品。

以下在保留制品的 019 WSL worktree 根目录运行。先将 `TRAIN_PY` 指向已有训练环境的 Python，`BUDGET` 指向上述共享账本；只在本轮获得 GPU 串行时段时运行。现有预跑与正式训练已完成，这些是复现/恢复用法，不要在实验API占用GPU时重复启动。新的首次预跑须使用独立空输出目录；CLI 会拒绝非空目录。

```bash
: "${TRAIN_PY:?先指定现有 WSL 训练环境 Python}"
: "${BUDGET:?先指定原有 todo-019 共享账本绝对路径}"
PREFLIGHT_CONFIG="$PWD/.local/finetuning-019/preflight.yaml"
test -f "$PREFLIGHT_CONFIG" && test -f "$BUDGET" || exit 1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1

# 配置始终 max_steps=200；100 仅是操作暂停点，不缩短 LR schedule。
"$TRAIN_PY" experiments/finetuning/run_training.py \
  --task-id todo-019 --config "$PREFLIGHT_CONFIG" --budget-file "$BUDGET" \
  --budget-seconds 86400 --phase preflight --stop-after-step 100

# 完整状态恢复，不仅加载 adapter；模型/数据/语义配置必须相同。
"$TRAIN_PY" experiments/finetuning/run_training.py \
  --task-id todo-019 --config "$PREFLIGHT_CONFIG" --budget-file "$BUDGET" \
  --budget-seconds 86400 --phase preflight \
  --resume "$PWD/.local/finetuning-019/preflight-output/checkpoint-100"
```

正式运行使用已冻结的 `.local/finetuning-019/formal-candidate.yaml`，phase 为 `formal`；首次不传 `--resume`，后续恢复只能使用正式目录中自己的完整 checkpoint 和原配置。配置 SHA256 为 `82cc53eb038d75292c37ad2197f26d0a06a96abab753412c80b183494937a516`。改变固定 max_steps、模型或数据会被身份核验拒绝；`tokenized_path` 被拒绝，不能用缓存绕过原始数据哈希。

完整恢复点保留 safetensors adapter/config、optimizer.pt、scheduler.pt、rng_state.pth、trainer_state.json 与 complete.json；恢复时核验文件集合、SHA256、step/schedule 和任务/模型/数据/语义配置身份。只带 adapter 的目录不能恢复训练。保留最新两份完整 checkpoint，并保留最佳模型所需的第三份；最佳 adapter、末步恢复 checkpoint 与 API 实际加载 adapter 要分别记录。

预算回调在优化步边界预留 `max(600 秒, 2 × 最慢完整保存计时)` 后停止保存；外部截止机制只结束本次拥有的训练子进程，未完成保存不能覆盖上一完整指针。checkpoint-200 的 92.074 秒计时包含之前的同步 dev 验证与保存，不是纯磁盘写入时间；checkpoint-100 暂停保存计时 3.954 秒。实际占用不裁剪成虚假的 24 小时以内结果。闭合且已释放 GPU 的暂停不计时；异常退出的未观测间隔，在确认原进程均已退出后保守计时。账本损坏、身份无法确认、换主机或 UTC 倒退时停止自动恢复并调查，不重置预算。

正式训练配置原生 Transformers patience=3、`eval_loss` 越低越好，改善必须严格大于 0.001，恰好等于算未充分改善；callback state 随完整 checkpoint 恢复。375/250 的配置仅有一次周期 dev 选择机会，不能在上限前观察三次连续失败；CPU 测试验证了计数恢复，正式运行实际结束原因为completed，未触发三次失败早停。

账本旁的 `todo-019-attempt-N.log`、`.worker.json`、`.status.json`、`.resources.jsonl` 保留真实身份、退出原因与资源记录。input/target tokens 来自训练 forward 的非 padding 输入与 `labels != -100`，token/s 的计时包含回调阶段验证/保存开销；Torch 进程分配峰值与整卡 MiB 分开记录，缺失数据为 null。制品和原始请求/答案/输出/密钥保留忽略目录，不提交 Git。

## 019版本化身份与独立评估

019/020 使用显式 `schema_version=2` runtime JSON，旧 015 的缺省/v1 4B 清单保持原有格式。v2 清单必需记录：

- `base_repository`：仅 `Qwen/Qwen3-8B` / `Qwen/Qwen3-0.6B`；`base_revision` 为原始基座的固定40位小写修订；`kind=base|lora|full`。
- `files_sha256`：实际加载文件的裸文件名/SHA256映射，必含 config.json、tokenizer.json、tokenizer_config.json，以及 model.safetensors；分片权重改为完整 model-NNNNN-of-NNNNN.safetensors 集合及 model.safetensors.index.json，不能混用。base/lora记录实际基座文件；full记录实际完整微调制品。
- `adapter_files_sha256`：base/full 为 null；lora 必须恰好包含实际 adapter_config.json 与 adapter_model.safetensors 的两个哈希，不能用 adapter 冒充完整模型。
- `inference_config_sha256`、`training_manifest_sha256`、`training_data_sha256`：分别对实际推理 YAML、准备 manifest-v2.json、训练 train.json 的原始字节计算 SHA256。评估器自己计算本次评估文件的 `evaluation_dataset_sha256`，与训练身份分开。
- `prompt_sha256={answer,rewrite,general}`：分别为生产 ANSWER_SYSTEM、REWRITE_SYSTEM 和固定普通指令 system 的 UTF-8 字节哈希，不加换行。general 固定为“按用户要求完成任务，严格遵守要求的输出格式。”，SHA 为 `6ec8888abc33d084792f4a86c655ed0f51ca39dc8c78086348d401e1a444c6fe`；入口拒绝不同提示词哈希。
- `runtime_versions`：实际 torch/transformers/llamafactory/bitsandbytes/peft/accelerate/cuda 版本。未知字段、路径与密钥不会进入公开 runtime 元信息。
- `generation_evidence`：未核验实际模式时为 null；核验后为 `{ "mode": "GREEDY_SEARCH", "do_sample": false, "evidence_sha256": "实际有效模式核验记录的64位SHA256" }`。必须先核验实际加载模型的有效模式；仅设置请求 temperature=0 不能填成已核验。清单是调用者制品旁证，HTTP 服务没有自动认证这些哈希。

训练制品身份已核验；11439基座API实际加载/贪心准备/鉴权中性调用已获分项批准，LoRA同样的运行证明与两组完整评测仍待验收，以下不是已执行的完整评测。准备完成后，在 019 Windows worktree 根目录的新终端设置操作方给出的实际 `TODO019_KEY_FILE`、`TODO019_MODEL_ID`、`TODO019_RUNTIME_MANIFEST`（文件用绝对路径），再设置本终端的 ModelSettings；不要修改业务 `.env`，不要把私钥直接放入命令或输出。

```powershell
if (-not $env:TODO019_MODEL_ID -or -not $env:TODO019_KEY_FILE -or -not $env:TODO019_RUNTIME_MANIFEST) { throw '先填写操作方核验的实际模型别名、私钥文件与 v2 runtime 清单路径' }
if (-not (Test-Path -LiteralPath $env:TODO019_KEY_FILE) -or -not (Test-Path -LiteralPath $env:TODO019_RUNTIME_MANIFEST)) { throw '实际私钥文件或 runtime 清单不存在' }
$env:MODEL_PROVIDER='cloud'
$env:MODEL_BASE_URL='http://127.0.0.1:11439/v1'
$env:MODEL_ID=$env:TODO019_MODEL_ID
$env:MODEL_ALLOWED_IDS=ConvertTo-Json -InputObject @($env:TODO019_MODEL_ID) -Compress
$env:MODEL_API_KEY=[IO.File]::ReadAllText($env:TODO019_KEY_FILE).Trim()
$env:MODEL_READ_TIMEOUT_SECONDS='120'
$env:MODEL_DISABLE_THINKING='false'
uv run --frozen --directory backend python ../experiments/finetuning/evaluate_model.py --mode grounded --dataset ../.local/corpus-019/projection-preview-v2-r2/evaluation-v2.json --split dev --runtime-manifest $env:TODO019_RUNTIME_MANIFEST --output ../.local/finetuning-019/replay-grounded-dev.json
uv run --frozen --directory backend python ../experiments/finetuning/evaluate_model.py --mode general --dataset ../.local/corpus-019/projection-preview-v2-r2/general-regression.json --split test --runtime-manifest $env:TODO019_RUNTIME_MANIFEST --output ../.local/finetuning-019/replay-general-test.json
```

路径必须对应本轮实际冻结文件；例子不是训练/最终测试已执行的证据。grounded 分开调用生产给定证据回答与历史指代改写提示词，参考答案只用于评分。回答只含当前问题、独立查询和给定资料，历史助手答案不会进入证据；没有历史时改写不适用，不加入模型改写分母。真实检索/权限/RAG评估另走 `experiments/evaluation/run_eval.py --dataset PATH`，不能把给定证据的结果当成真实 RAG。

general 使用 `schema_version=1, mode=general` 的冻结普通任务集，正式回归100题；输入只含固定普通 system 和该题 user_prompt，不发送 expected。算术仅按去首尾空白后的规范整数精确匹配，17.0、+17、解释文字都不计正确；指令按原样精确格式匹配；JSON拒绝重复字段、NaN/Infinity、Markdown包装，并对预定字段做类型严格的递归子集匹配，布尔值不等于整数，2.0不等于2。受控格式/算术评分不代表全部泛化或语义质量。

两模式回答上限512 tokens，改写128，输入最多12,000个 UTF-8 内容字节；真实生产 RAG 有改写时回答上限384，否则512，整体期限60秒，客户端120秒读取超时不会取消该期限。基座与微调组在各路径内复用同一推理栈、模板、提示词、上限和实际核验的贪心模式。报告记录真实 finish_reason、usage、失败与各自评分分母；length/缺失终止/无效JSON等保留为失败，不改写成成功。无引用时 citation_mapping 为 null。公开输出只含评分与脱敏元信息，实际请求和模型输出仅在输出位于本仓库忽略 `.local/` 下时写入邻接 `.private.json`；保留在本机，不提交私钥、原始参考答案或模型输出。

计划完整对照每个模型各运行 7 项：给定证据 dev300/test500、真实 RAG dev300/test500、旧013 dev18/test42、普通任务100，共 14 项/3,520 次题目评估，当前尚未执行。给定证据每个模型有800个回答评分、640个适用历史改写评分；真实 RAG 可在意图/澄清/无候选阶段停止，题数不等于 API 调用数。真实 RAG 固定现有 [baseline.yaml](../evaluation/configs/baseline.yaml) 的 vector/threshold0.65/top-k5/不重排，SHA256 `b386a617d19ad1166455c46149dbf18bfcecb0fe92f66cb12fa939c4f6685a2b`；相同配置不保证两组模型生成相同改写查询或候选。精确参考匹配不等于语义正确性，实际错误、无检索候选、拒答及普通任务退化都必须保留。完成本终端工作后关闭它，避免实验变量影响普通检查。

真实 RAG 的新报告隐私规则由数据集 v2 或 runtime v2 触发，检索模式及未提供/v1清单也不发布新数据标签。新报告中的模型名称仅来自已验证的 `base_repository`，没有 v2 身份时为空；原始 ModelSettings 模型别名可以是本地路径，不放入新公开报告。实际旧数据集配合缺省/v1运行清单的兼容报告保持原有行为。

CPU行为验证不加载模型、不下载、不运行最终基准：

```powershell
uv run --frozen --directory backend pytest -c pyproject.toml ../experiments/finetuning/tests/test_local_evaluation.py ../experiments/finetuning/tests/test_model_evaluation.py ../experiments/evaluation/tests -q
uv run --frozen --directory backend ruff check --config pyproject.toml ../experiments/evaluation/run_eval.py ../experiments/finetuning/evaluate_model.py ../experiments/finetuning/tests/test_local_evaluation.py ../experiments/finetuning/tests/test_model_evaluation.py
```
