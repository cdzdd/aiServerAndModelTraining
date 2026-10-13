# todo-020：0.6B 全量微调实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在第二个独立 worktree，从原始0.6B基座完成一次累计最多24小时的全参数训练、恢复和完整模型评测。

**Architecture:** 消费019已合入的冻结数据、累计预算CLI和v2评测身份。用Factory full方法与小模型学习完整参数/优化器/checkpoint；保留既有CPU业务环境。沿用本机loopback私钥API展示完整模型。

**Tech Stack:** 019核验的WSL2/Python/PyTorch/LLaMAFactory环境、Qwen3-0.6B、BF16计算/常规AdamW、现有pytest与统一检查。

**Spec:** [todo-020](todo-020.md)；共用预算/数据接口见 [todo-019-plan](todo-019-plan.md)。

## Global Constraints

- 当前仅计划，019的新增接口还未实现；必须待019功能和状态PR实际合入main再正式开发020。
- Qwen/Qwen3-0.6B，full、无quantization/adapter/冻结参数；起步1024tokens、micro1/累积16、seed42、LR1e-5/cosine/warmup3%、SDPA/gradient checkpointing。pure_bf16关闭，记录实际dtype。
- 本任务独立ledger累计86,400秒，所有预跑/失败/加载/期间验证/保存/退出计入；只数据准备/下载/正常停止后最终评测另算。恢复不重置budget，复用019截止与完整性规则。
- 正式从0.6B原始基座开始；不加载019adapter，不默认升级至1.7B或引入卸载框架。
- 共享测试此前已被019运行，应注明复用；不根据其标签调整全量超参。不同模型/数据长度造成的差别不用于断言方法优劣。
- 不改业务默认provider、既有15/19制品或公网状态；只结束已核验由本任务拥有的GPU进程。

## Review Focus

- 配置full但参数仍被冻结/optimizer遗漏：Task 1全量唯一参数集合审计拒绝启动。
- 只有adapter或缺失完整分片：Task 2/3确认完整模型保存、哈希与真实重载。
- 两模型token长度不同导致静默截断标签/证据：Task 1重新投影并记录排除数。
- 019后已消耗的预算被错误算入020或020恢复清零：Task 2验证task_id独立与自身累计。
- loss下降但通用能力明显退化：Task 3逐题报告领域/通用回归和最佳/末轮差异，不只报loss。

## 实施入口：019合入后先领取与隔离

- [ ] 核实权威main中019已done，读取已合入工具、冻结数据/模型清单及预算接口；只读研究可提前，写测试/实现不得提前。
- [ ] 按WORKFLOW原子领取020，优先创建/复用本任务独立原生worktree，核实分支/用户修改、独立环境、对应基线检查。
- [ ] 将唯一canonical账本绑定为真实Git common directory下codex-coordination/training-budgets/todo-020.json，claim记入Windows/WSL实际对应路径；上限固定86400，拒绝换账本路径或增加额度。
- [ ] 完成隔离后进入Task1；GPU训练前再核实019已释放，不能一边共享开发一边补领取。

## Task 1：full配置与全参数审计

**Files:** 新增 `experiments/finetuning/configs/full-0.6b.yaml`、`experiments/finetuning/audit_full_model.py`、`experiments/finetuning/tests/test_full_model.py`；必要修改019的run_training/model identity校验，保持019回归。

**Interfaces:**
- `audit_full_model(model, optimizer) -> dict`：按对象身份去重参数；返回total/trainable/optimizer参数数量、实际dtype、分层统计；集合不等、LoRA/量化模块或冻结参数时抛ValueError。
- 模型manifest schema_version=2/kind=full消费019的load_runtime_manifest；固定base_repository/revision，files_sha256必须指向实际完整模型加载文件。
- prepare_data用019已实现的显式manifest_path/recipe_path投影，在020自身忽略目录输出；正文数据与split沿用019冻结版本，记录源manifest和本机投影双哈希。

- [ ] 写 test_full_requires_all_unique_params_trainable、test_optimizer_covers_exact_model_params、test_tied_params_count_once、test_reject_lora_and_quantized_modules；用真实小torch模型/optimizer验证，先确认缺失接口失败。
- [ ] 实现audit_full_model，在模型加载及optimizer建立后、首个正式step前运行；不依赖文字日志声称full。
- [ ] 写 test_full_recipe_has_no_adapter_or_quantization、test_target_or_evidence_truncation_is_rejected；建立固定recipe并执行CPU测试。
- [ ] 在已经领取且隔离的本任务目录下载固定revision的0.6B及逐文件SHA；核验兼容环境、实际内存与GPU余量。
- [ ] 用0.6B真实tokenizer/template重新投影。超长度训练样本按正式训练前固定规则排除、记录ID/原因/数量；不静默删目标，不用最终test挑样本。
- [ ] 提交实现、配置、静态数据清单和专项测试；旧训练输出不覆盖。

## Task 2：真实预跑、恢复与一次正式full训练

**Files:** 修改 `experiments/finetuning/README.md`；必要扩展 `experiments/finetuning/tests/test_training_budget.py` / `experiments/finetuning/tests/test_full_model.py`；输出位于本worktree忽略目录。

**Interfaces:**
- 沿用019 CLI（PHASE 为 preflight 或 formal）：`python experiments/finetuning/run_training.py --task-id todo-020 --config PATH --budget-file PATH --budget-seconds 86400 --phase PHASE [--stop-after-step N] [--resume CHECKPOINT]`。
- budget文件属于020，数据/基座/recipe/完整checkpoint匹配才能resume；修改task_id或换目录不能恢复旧训练并伪装新额度；--budget-file必须匹配入口绑定的canonical路径，--budget-seconds必须为86400。
- full checkpoint必须含完整模型/config/tokenizer及optimizer/scheduler/RNG/trainer_state；完整标记/last_valid_checkpoint与截止机制完全复用019。

- [ ] 写test_two_tasks_have_independent_budgets、test_full_resume_rejects_base_or_recipe_change、test_full_checkpoint_requires_all_shards；先验证失败，再完成必要full格式适配。
- [ ] 跑CPU/短寿命子进程预算与恢复格式测试，不为020重建另一套scheduler/watchdog。
- [ ] 在020累计ledger内实际预跑100–200steps，记录finite loss/梯度、唯一trainable/optimizer覆盖、实际显存与吞吐、完整checkpoint大小和保存耗时。
- [ ] 对embedding/attention/MLP/norm代表张量做训练前后完整tensor指纹比较，保留真实更新与有限值证据；不要求每个元素每步都变化。
- [ ] 预跑recipe预设200总steps，以--stop-after-step 100正常保存并停止，不改recipe从完整checkpoint恢复至200，核对optimizer/scheduler/RNG/global_step并保存；这只证明计划停止恢复，不能声称已验证掉电。
- [ ] 依据自身吞吐冻结一次正式max_steps和schedule，最多3epochs，扣除预跑/失败已用时间并预留保存。验证loss连续3次未改善至少0.001时早停。
- [ ] 正式目录从原始0.6B基座独立开始，全程full；无需训练满24小时。若截止强制结束只能使用上次完整checkpoint，报告实际终止原因与未完成状态。
- [ ] 保存最近2份完整checkpoint、最佳和末轮完整模型；有限值/哈希/配置与恢复状态核对。清理只限020明确生成目录。
- [ ] 释放训练GPU后提交真实阶段记录；缺少完整可恢复模型时不进入成功验收。

## Task 3：完整模型重载与领域/遗忘评测

**Files:** 修改 `experiments/finetuning/README.md`；新增 `reports/todo-020-training.md`、`todo-020-comparison.md`、`todo-020-artifacts.json`；必要补充 `experiments/finetuning/tests/test_model_evaluation.py`。

**Interfaces:**
- 沿用019evaluate_model的grounded/general两种模式与run_eval的显式dataset/v2身份。base与full都使用非量化BF16、同模板、输出最多512tokens、实际greedy。
- local_api消费完整模型目录的model_name_or_path，不传adapter_name_or_path；保持loopback/私钥/单并发和12,000-byte输入边界。
- 最佳/末轮可为同一checkpoint；若相同只需一次实际评测并标清，不重复宣称两次独立验证。

- [ ] 先写test_full_identity_cannot_be_adapter、test_full_reload_requires_complete_config_and_weights；校验身份/重载指向完整模型，不只是文件名存在。
- [ ] 对实际完整safetensors/config/tokenizer逐文件hash，离线重载最终模型；记录模型唯一参数数与真实加载位置/源revision。
- [ ] 依次启动0.6B base、最佳full、末轮full的本地私钥API，实际调用与greedy核验；不同时加载三组模型。
- [ ] 各自执行同一新dev/test的给定证据生成/改写、真实RAG、general独立提示词模式的100题通用回归与旧60题grounded回归。保存安全的原始选择JSON，分别报告检索空候选、拒答、JSON/引用校验失败。
- [ ] 比较有效引用答复、误拒答/误答、rewrite指代、结构格式、通用回归变化和延迟；保留所有退化及null指标。不得凭领域低loss宣称全面提升。
- [ ] 独立代理核查full证据、预算账本、恢复、实际加载/文件哈希与逐题结果；同一冻结test复用事实写入报告，不根据test再调参。

## Task 4：统一验证与交付

**Files:** 更新 `docs/tasks/todo-020.md`、`experiments/finetuning/README.md` 和实际报告。

- [ ] 执行 `node scripts/dev.mjs check` 及 `uv run --directory backend --frozen python -m pytest ../experiments/finetuning/tests -q`，记录实际提交/命令/结果；这里是未来步骤，不是已通过检查。
- [ ] 教程给出完整模型本地启动、使用、checkpoint恢复与制品位置；表明0.6B规模和真实性能限制，不自动切换网页。
- [ ] 报告两任务各自已占用时间与相加值，任何失败/恢复也计入本任务；正式训练没有满24h时说明目标达成/早停原因。
- [ ] 独立评审、普通功能PR和单任务状态收尾，权威main实际合并后才done。云端CI仍按项目实际验收模式记录，不伪造check。

## 执行顺序与结果解释

019合入完成 → 020工具/参数审计 → 020真实预跑/恢复 → 单轮有界正式full → 完整模型重载/评测 → PR收尾。GPU串行；CPU数据分析、审核和文档可并行。

用户追求的是两次更充分的训练实践，不要求大幅增益。提前停止、显存失败和能力退化都需要真实报告；它们不能替代可恢复制品与实际评测。预算上限48小时仅指两项累计训练作业，其余准备/最终评测时间单独展示。

官方依据：[0.6B模型卡](https://huggingface.co/Qwen/Qwen3-0.6B)、[Factory full示例](https://raw.githubusercontent.com/hiyouga/LLaMA-Factory/v0.9.5/examples/train_full/qwen3_full_sft.yaml)、[训练显存组成](https://huggingface.co/docs/transformers/v4.57.1/en/model_memory_anatomy)。示例中的多卡/DeepSpeed配置不直接照搬到本机。
