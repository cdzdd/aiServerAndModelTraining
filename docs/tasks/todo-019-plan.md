# todo-019：8B QLoRA 长时训练实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本机完成一次累计最多 24 小时、可恢复、可评测的 8B QLoRA 实践，并给 020 留下冻结数据与最小预算工具。

**Architecture:** 沿用 015 的 WSL 独立训练环境和实验 API，扩展现有数据准备与评测器。新增一个训练 CLI 包装 Factory run_exp 和 TrainerCallback，不建立服务调度平台。CPU 数据/工具开发可并行，真实 GPU 工作按任务串行。

**Tech Stack:** Python 3.12、WSL2、LLaMAFactory/PyTorch/Transformers/PEFT/bitsandbytes；优先核验并复用 015 已验证的版本，不升级业务后端依赖。

**Spec:** [todo-019](todo-019.md)，共用项目规则见 [WORKFLOW](../WORKFLOW.md)、[ARCHITECTURE](../ARCHITECTURE.md)、[CONTRACTS](../CONTRACTS.md)。

## Global Constraints

- 本文件是尚未执行的计划；下列新增文件/参数和预期结果当前不是已实现能力。
- Qwen/Qwen3-8B、4-bit NF4、BF16、rank 16/alpha 32/all linear、seed 42，起步参数见任务范围；模型 revision 在正式下载前解析为不可变提交并存入清单，不编造 SHA。
- 单任务累计上限 86,400 秒；预跑和失败尝试也计入。下载/数据准备/结束后最终离线评测另算。通过新 output_dir、重启或恢复不能获得新额度。
- 正式 max_steps 和 LR schedule 在预跑后冻结，最多 3 epochs；正式从原始基座开始，不能把短预跑 checkpoint 的不同 schedule 偷偷当成连续正式训练。
- 现有 015 的默认数据、recipe、manifest v1、私钥/loopback/单并发/取消门控及 12,000-byte 输入、512-token 输出边界保持可复现。
- 新原始数据、参考答案、权重、checkpoint、私钥置本 worktree 忽略目录；Git 保留规则、小型虚构测试 fixture、配置模板、哈希清单与脱敏报告。
- 仅实施任务明确接手后领取开发；当前登记不占用未来 GPU。不能停止未知属主进程或删除旧制品。

## Review Focus

- 只换编号的同源/同模板问题跨 split：Task 1 必须拒绝，不能用字符串不同冒充独立数据。
- 历史助手回答被当作证据、拒答样本误投影：Task 1/3 核对生产 answer/rewrite 两种契约。
- 崩溃、恢复或更换目录重置计时：Task 2 以可注入时钟和持久 ledger 验证累计额度。
- 参数清单写 8B 但真实加载旧模型/错误 adapter：Task 3/4 核验实际配置与文件身份，v1 回归必须保留。
- 截止时正在保存或旧 checkpoint 不完整：Task 2/4 只恢复完整标记的 checkpoint，保留失败与上次有效状态。

## 文件边界与既有事实

- 现有 prepare_data.prepare 固定读取旧 training.json 并生成 8+2 / 4B 配置；不能只改 model_id 就宣称支持新实验。
- validate_manifest 目前只接受 answered、单 evidence/index=1 和三个消息；需要版本化扩展。
- run_eval.py 当前固定 dataset.json 与旧 4B revision，finetuned 清单只支持 adapter 双哈希；Task 3 必须解决。
- local_api.create_app / enforce_greedy 可复用，无须新 API；保持其真实 stop/length/usage 与取消门控。
- 新测试置 experiments/finetuning/tests/，已有统一检查会发现；必要时扩展 evaluation/tests/，不另建测试系统。

## 实施入口：先领取与隔离，再写测试或代码

- [ ] 核实权威main中013/014/015已done，按WORKFLOW原子领取019；当前计划登记不能替代正式实施领取。
- [ ] 优先创建/复用本任务原生独立worktree，核对分支、用户修改、独立数据库/端口、忽略目录和训练环境；先做对应基线检查，失败先诊断。
- [ ] 在本机真实Git common directory的codex-coordination/training-budgets/todo-019.json建立唯一预算账本绑定，并把解析后的Windows/WSL对应绝对路径记入本任务claim。WSL不得把Windows worktree pointer交给Linux git后伪造路径。
- [ ] 完成这些步骤后才进入Task1。GPU只在Task4实际训练前领取占用；数据/CPU工具阶段不停止运行服务。

## Task 1：冻结新数据和兼容的数据投影

**Files:** 新增 `experiments/finetuning/prepare_corpus.py`、`experiments/finetuning/tests/test_corpus.py`；修改 `prepare_data.py`、`validate_data.py`、`experiments/finetuning/tests/test_prepare.py`、`experiments/finetuning/tests/test_data_validation.py`、`data/README.md`。

**Interfaces:**
- 在 `validate_data.py` 新增 `validate_corpus(corpus: dict) -> dict`：检查 sources/cases 的 train/dev/test 分组、family、来源许可/哈希、完整语境近重复、ground truth 和 synthetic/human_reviewed。
- 将 `prepare(output, *, model_path, runtime_root, root=ROOT, manifest_path=None, recipe_path=None) -> dict` 显式扩展；两项可选参数均不传时保留旧 8+2 行为。新数据单独输出目录，拒绝覆盖已有冻结版本。
- corpus v2 记录 source_id、group、family、split、question/history、answer 或 rewrite 标签及参考来源；其训练投影分别使用现有 ANSWER_SYSTEM 与 REWRITE_SYSTEM。相同 case 的两种任务投影留在同一 split。
- 输出忽略目录 `manifest-v2.json`、`train.json`、`validation.json`、`dataset_info.json`、`evaluation-v2.json`、`general-regression.json` 与文件/样本/token 清单；test 不进入训练 dataset_info。

- [ ] 写 test_family_must_not_cross_split、test_reject_cross_split_context_duplicates、test_reject_unsupported_quote、test_rewrite_history_is_not_evidence、test_nonanswered_has_empty_selections。
- [ ] 在 CPU 执行新增测试确认缺失的新接口/行为失败，保留实际失败证据。
- [ ] 实现版本化校验与投影；多 evidence 编号唯一，answered ≤3 引文/总长≤800，拒答 selections=[]，rewrite 的 needs_clarification 严格布尔。answer 的检索 query 与 rewrite 目标逐题可核验。
- [ ] 执行新测试及旧 test_prepare/test_data_validation，确认旧 8+2 内容哈希和 v1 行为不变；UTF-8 明确写入。
- [ ] 准备候选池，完成 dev≥300/test≥500 逐题代理审核及 train 每类≥20 抽样/规则审核；再冻结数据。准备 100 条与新训练隔离的原创中文指令、算术和结构输出通用回归。
- [ ] 记录实际 token 数、重复排除、授权/许可、审核分母与未决项；质量不够则缩小规模，不复制小样本补时长。提交代码/规则和脱敏清单，原始数据仍忽略。

## Task 2：累计预算、恢复和真实资源记录

**Files:** 新增 `experiments/finetuning/run_training.py`、`experiments/finetuning/tests/test_training_budget.py`；修改 `README.md`。

**Interfaces:**
- `remaining_seconds(used_seconds: float, elapsed_seconds: float, budget_seconds: int = 86400) -> float` 返回不小于零的余额。
- `validate_resume(record: dict, current: dict) -> None` 核验 task_id、基座/数据/recipe 哈希、checkpoint 完整状态；不匹配抛 ValueError。
- CLI（PHASE 为 preflight 或 formal）：`python experiments/finetuning/run_training.py --task-id todo-019 --config PATH --budget-file PATH --budget-seconds 86400 --phase PHASE [--stop-after-step N] [--resume CHECKPOINT]`。
- ledger 唯一canonical路径为真实Git common directory下codex-coordination/training-budgets/todo-019.json（020同目录对应todo-020.json），--budget-file必须与正式claim绑定及真实common directory解析一致，--budget-seconds必须等于86400，拒绝更换路径/提高上限。ledger含 budget_seconds、累计 occupied_seconds、attempts、退出原因和 last_valid_checkpoint；用原子写和单 writer 防并发。每个 attempt 有配置/模型/数据哈希、属主进程、阶段和 UTC/monotonic 时钟。
- Factory `run_exp(args, callbacks=[...])` 在训练环境懒加载；CLI 的父进程独立计时，GPU worker 为其实际拥有的子进程。普通 tests 不加载 GPU 或 Factory。

- [ ] 写 test_budget_counts_preflight_and_failures、test_resume_preserves_consumed_time、test_output_change_cannot_reset_task_budget、test_budget_file_change_is_rejected、test_budget_above_86400_is_rejected、test_expired_budget_rejects_launch。
- [ ] 用假时钟断言 remaining_seconds(3600,7200,86400)==75600、remaining_seconds(86400,1,86400)==0，先运行确认失败。
- [ ] 实现单调运行计时、原子持久 heartbeat（最多每10秒一次）和重启恢复。正常暂停保存后才停止计时；未正常关闭的 attempt 保守累计失联区间，UTC 倒退或属主无法核实则拒绝自动恢复，不减已用额度。
- [ ] 写 test_save_hang_hits_deadline、test_only_owned_worker_can_be_stopped、test_partial_checkpoint_is_not_resumable、test_corrupt_ledger_blocks_resume，并用无 GPU 的短寿命子进程验证真实超时/退出。
- [ ] 在余额≤max(600秒, 2×预跑最慢完整保存耗时)时停止提交新优化步并保存；父进程到硬截止只结束自身 worker。保存未完成标失败，不能延长 24h 等待，也不能假报最终制品成功。
- [ ] 增加 test_planned_stop_keeps_schedule_and_checkpoint：预跑 recipe 预设200总steps，--stop-after-step 100在第100优化步保存并停止；不改recipe恢复至200，核对原schedule/optimizer/RNG。stop-after-step仅操作控制，不改变训练身份。
- [ ] checkpoint 仅在权重、optimizer/scheduler/RNG/trainer_state齐备、哈希/状态核对后写完整标记并更新 last_valid_checkpoint；恢复拒绝半写目录。
- [ ] 记录有效输入 token/s、监督目标 tokens、steps、loss、CUDA allocated/reserved 峰值，以及整卡显存/温度/功耗和进程内存（每10秒采样，注明测量范围）。
- [ ] 跑专项测试、CPU Ruff 并提交；不做“后台自动加预算”或通用调度服务。

## Task 3：新模型身份与两条评测路径

**Files:** 修改 `experiments/evaluation/run_eval.py`、`experiments/finetuning/tests/test_local_evaluation.py`；新增 `experiments/finetuning/evaluate_model.py`、`experiments/finetuning/tests/test_model_evaluation.py`；修改两目录 README。

**Interfaces:**
- run_eval 新增 `--dataset PATH`，省略时保留旧 dataset.json。
- load_runtime_manifest 保留 v1；新增显式 schema_version=2，记录 base_repository、40位 revision、kind=base/lora/full、inference/data/prompt SHA、实际加载 files_sha256、runtime_versions。v2 仅接受本计划的 Qwen3-8B/Qwen3-0.6B；路径与密钥不进入公开输出。
- base 没有 adapter；lora 要求实际 adapter_config 与 safetensors 双哈希；full 要求完整 config/tokenizer/权重及分片索引（分片时）的清单。不得用 lora 清单伪装 full。清单仍是调用者核验旁证。
- evaluate_model CLI（MODE 为 grounded 或 general，SPLIT 为 dev 或 test）：`--mode MODE --dataset PATH --split SPLIT --runtime-manifest PATH --output PATH`，端点/私钥由工作区现有 ModelSettings 读取，固定 literal HTTP loopback。
- grounded模式用生产build_answer_prompt/build_rewrite_prompt；给定金标准证据与真实RAG分开报告。general模式单独固定system为“按用户要求完成任务，严格遵守要求的输出格式。”，输入只含该条用户任务，不带RAG证据规则或参考答案。
- general-regression schema_version=1、mode=general；100个cases带id/group/family/split=test/task=instruction|arithmetic|json/user_prompt、expected={match:exact|json_subset,value:...}。只输出整数的算术按去首尾空白后的精确字符串评分；JSON按严格解析与固定字段子集评分；指令按预定精确格式评分。规则和标签在训练前冻结，只代表这组受控任务。
- general与grounded均保持同一模型内基座/微调推理栈、greedy和输出上限；原始请求/模型JSON只留忽略目录安全副本，expected绝不送入模型。

- [ ] 写 test_v1_identity_still_reproducible、test_v2_requires_real_artifact_kind、test_new_dataset_is_explicit、test_no_remote_or_dns_endpoint；先确认新增行为失败。
- [ ] 实现 v2 身份白名单和显式数据路径，不放宽 select_generation_provider 的 Mock/cloud/loopback 守卫。
- [ ] 写 test_no_candidates_is_separate_from_bad_json、test_quote_must_map_to_supplied_evidence、test_rewrite_uses_history_only_for_referent、test_general_uses_own_prompt_without_expected、test_general_arithmetic_exact_and_json_subset；实现grounded生成/改写及general分开指标/分母。
- [ ] 输出真实 finish_reason/usage、实际贪心核验、输入/输出预算、配置/代码/模型/数据哈希；无引用指标保留 null，语义质量不能仅用字符匹配冒称全部正确。
- [ ] 执行新旧 CPU 测试与 Ruff；确认 private_key 等额外字段被过滤，12,000-byte/512-token API 边界不变；提交。

## Task 4：真实预跑与一轮有界正式训练

**Files:** 新增 `experiments/finetuning/configs/qlora-8b.yaml`；修改 `README.md`；忽略目录保存本轮数据、完整配置、ledger、模型与 checkpoint。

- [ ] 正式接手/原子领取后在独立 worktree 核实依赖、GPU进程属主和模型资源占用；仅协调已确认本轮所属的推理服务，记录网页推理可能暂时不可用。不在当前计划登记阶段停止服务。
- [ ] 核验现有训练 venv；从官方仓库解析固定 revision/Apache-2.0 许可、下载与逐文件 SHA，加载本地路径 trust_remote_code=false。不足条件写实际阻塞。
- [ ] 用真实 tokenizer/Factory模板统计完整源+目标长度；目标/关键证据不得静默截断。记录不同长度的覆盖和排除数，预跑阶段才允许调整 cutoff。
- [ ] 在本任务同一累计 ledger 下预设200总steps，用--stop-after-step 100做计划停止，再不改recipe从完整checkpoint恢复至200；核验 global_step、optimizer/scheduler/RNG，而不是仅重新加载 adapter。
- [ ] 按 token/s、每优化步耗时和保存开销确定一次正式 max_steps，<=3epochs且在剩余时间内；冻结 LR schedule/数据/配置。验证 loss 连续3次未改善至少0.001时提前停止。
- [ ] 预跑与正式目录分开，正式从原始基座重新开始；同 ledger 不重新给24h。保留最近2份完整 checkpoint、最佳和最终制品；清理仅限本轮明确生成的目录，保留15制品/失败日志。
- [ ] GPU 串行运行正式训练，记录真实起止、早停/预算/目标原因、最高显存与非有限值；异常后只恢复经完整性校验的 checkpoint，不能修改数据/recipe继续冒称同一实验。
- [ ] 训练结束释放 GPU，再分别启动 base 与 lora 的同栈私钥API；确认 enforce_greedy 的实际效果，依次完成grounded dev/test两条评测、旧60题回归及general模式100题通用回归。
- [ ] 独立核对数据、制品、预算累计与逐题报告；最终 test 只用于报告，不据其调参重训。未改善/遗忘/误拒答全部保留。

## Task 5：验证、交付与状态收尾

**Files:** 新增 `experiments/finetuning/reports/todo-019-training.md`、`todo-019-comparison.md`、`todo-019-artifacts.json`；更新 `README.md` 与本任务文件。

- [ ] 运行 `node scripts/dev.mjs check`；专项在工作区根运行 `uv run --directory backend --frozen python -m pytest ../experiments/finetuning/tests -q`。本计划没有提前运行或声明这些命令通过。
- [ ] 固化真实源码SHA、revision、数据/配置/权重哈希、预算与恢复、环境/制品位置和逐题分母；记录代码检查与 GPU 验收分别对应哪个提交。
- [ ] 在本地通过私钥 API 实际加载/调用最终 adapter，给出可复制的启动、恢复和使用说明；不自动切换业务provider或公开模型端口。
- [ ] 独立评审通过后按 WORKFLOW 普通 PR 合并及单任务状态收尾，done 必须以权威main为准；019并不启用018或改变016的本地停止边界。

## 顺序与交接

Task 1的数据工作可与Task 2预算工具独立开发，随后集成Task 3；共享数据/评测源码需协调。Task 4真实GPU串行，Task 5完成后020消费合入的工具和冻结清单。实现分支、端口与模型路径到正式领取时实际分配，当前不虚构占用。

官方接口依据：[Factory v0.9.5 run_exp](https://raw.githubusercontent.com/hiyouga/LLaMA-Factory/v0.9.5/src/llamafactory/train/tuner.py)、[8B模型卡](https://huggingface.co/Qwen/Qwen3-8B)。版本变更只能经兼容预跑和记录，不能直接升级整个业务环境。
