# todo-020：0.6B 全量微调长时训练实践

| 字段 | 值 |
|---|---|
| id | todo-020 |
| 状态 | in_review |
| depends_on | todo-019 |
| 优先级 | P2：本机训练实践，不阻塞网站发布 |
| 负责目录 | `experiments/finetuning/`，必要的完整模型评测身份适配 |
| 并行可行性 | 可提前只读研究；019 合入后复用其工具与冻结数据，GPU 串行 |
| 训练预算 | 本任务所有训练尝试累计最多 86,400 秒；与 019 合计最多 172,800 秒 |

## 用户目标与本轮边界

2026-10-13 用户确定两次训练各最多 24 小时。本任务是第二次独立正式训练，使用小模型完整实践全参数更新、优化器状态、恢复、完整模型保存和能力遗忘评测。本轮已完成真实预跑/恢复与375步正式full训练；BASE/BEST/LAST完整结果及记录中的自有服务释放均已独立核准；当前等待全分支独立评审、功能PR合并与单任务状态收尾。

019 负责共用数据与预算工具，因此 020 必须消费已经合入权威 main 的版本；不能在另一 worktree 静默复制未合入源码。020 从自己的原始基座开始，不沿用 019 adapter。

## 已确定的设计

- 模型：`Qwen/Qwen3-0.6B`；执行时冻结官方不可变 revision、许可与全部加载文件 SHA256。
- finetuning_type=full、BF16 计算、常规 AdamW，纯 BF16 权重/优化器模式关闭；按已核验 Factory 实现记录真实参数/梯度/优化器 dtype。不量化基座、不加 LoRA、不冻结层。
- 初始 cutoff 1024、SDPA、gradient checkpointing、micro-batch 1、梯度累积 16、seed 42、LR 1e-5 / cosine / warmup 3%、train_on_prompt=false、qwen3_nothink。正式配置由预跑验证并冻结。
- 确认全部唯一模型参数 requires_grad=true，optimizer 参数集合与模型唯一参数集合相同；tied 权重只计算一次。至少核验 embedding、attention、MLP、norm 的真实张量更新以及有限梯度/loss。
- 与 019 使用同一预算语义：本任务预跑/OOM/加载/训练/期间验证/保存/退出合计最多 24 小时，恢复不重置额度；最终离线评测和数据准备不计。停止、checkpoint 完整性、保存超时与属主边界复用 019。
- 不默认挑战 1.7B 或更大模型，不引入 DeepSpeed/CPU/NVMe 卸载。0.6B 在本机仍需实际预跑确认，显存不足时先修正本方案，不冒称训练成功或偷偷替换方法。

## 数据、制品与比较

- 复用 019 已冻结的数据来源和拆分；用 0.6B tokenizer/template 重新计数并记录投影哈希。不能静默截断目标或参考证据；不适配长度的训练样本按预先规定规则排除并记录。dev/test 的有效评测输入对基座和全量模型保持相同。
- 全量制品包含完整模型 safetensors 分片/索引、config、tokenizer/template、许可/来源；checkpoint 另保留 optimizer、scheduler、RNG、trainer_state。不能把合并 adapter 称作全量训练。
- 同一 0.6B 基座与全量模型做给定证据生成/改写、真实 RAG、100 条冻结通用回归（独立普通指令提示词与评分）的对照；检索参数不因训练更改。基座与全量采用同一非量化 BF16 推理栈与实际贪心模式。
- 记录领域能力、拒答/引用、字面指标、通用能力退化、延迟及不同阶段资源范围。不用两次不同规模模型的结果断言 LoRA 与 full 方法优劣。
- 019 已运行过共用测试，020 报告明确“同一冻结测试复用”，不是全新盲测；仍禁止用 test 调超参。

## 实施与验收

- [x] 正式接手后核实 019 done、工具/数据 SHA 与 GPU 已释放，创建本任务独立 worktree。
- [x] 先写参数覆盖、错误方法拒绝、恢复身份和完整制品加载行为测试。
- [x] 建立 full recipe 与全参数/optimizer 审计，生成实际数据投影与基座身份。
- [x] 完成真实 100–200 steps 预跑、有限梯度和计划停止后 checkpoint 恢复。
- [x] 从原始 0.6B 独立进行一次正式全量训练，遵守自身 24 小时累计预算。
- [x] 加载最佳与末轮完整模型，与基座完成两条评测和通用能力回归。
- [x] 输出完整模型制品清单、资源/恢复/负结果、使用说明；源码统一检查与运行/结果分项独立评审已通过，全分支强评审另见下表。
- [ ] 实际合入功能和状态收尾 PR 后更新为 done；否则保留真实待验收状态。

具体步骤见 [todo-020-plan](todo-020-plan.md)。全量微调的验收重点是所有参数可训练且有真实更新、可恢复和完整模型可加载，不要求大幅提升，也不要求凑满 24 小时。

## 外部条件与未执行范围

硬件基线为 Ultra 7 265K / 32GB RAM / RTX 5070 Ti 16GB。按常见混合精度 AdamW 的 18 字节/参数估算，0.6B 参数相关状态约 10.8GB，另需激活/临时缓冲；这不是本机实际峰值或必定适配的承诺。[官方训练显存说明](https://huggingface.co/docs/transformers/v4.57.1/en/model_memory_anatomy)、[模型卡](https://huggingface.co/Qwen/Qwen3-0.6B)。

本任务不购买云 GPU、执行预训练、部署公网、自动切换网页模型、启用 018 或删除 015/019 制品。实际模型revision、训练、恢复与BASE/BEST/LAST结果见下方记录；功能合并SHA尚未产生，任务保持in_review。

## 2026-10-19 接手记录

用户明确授权开始020；019已实际done并合入origin/main。当时从main5620befe建立独立原生worktree和feat/todo-020-full-06b；已原子领取，独立API8150/Web5250/DB15480/实验模型11440，Compose project qa-todo-020-7dd724fb。累计训练账本绑定Git common directory的codex-coordination/training-budgets/todo-020.json，上限86400秒，不重置019或020已有额度。接手时仅完成准备；之后实际训练和评估以本节新增终态记录及报告为准。


## 2026-10-20 训练、评测与文档验收记录

任务in_review。训练、21组完整评测、分项运行/结果独立评审及记录中的自有服务释放已完成；全分支强评审、功能合并与单任务状态收尾仍待执行。

- 真实训练源码5813a7ae1ea89e0b9de46b8e6fd3a430c8b55286，原始Qwen/Qwen3-0.6B revision c1899de289a04d12100db370d81485cdf75e47ca。310唯一参数/596,049,920元素全部FP32可训练，optimizer覆盖一致，BF16计算，无adapter/量化/冻结。
- pilot在同一200步计划100暂停后完整恢复到200；正式独立从基座完成375步/3epochs，未早停。best250 loss0.008023361675441265，true last375 loss0.008143704384565353，根输出回载best。保留125/250/375、恢复与失败证据；不重置账本或延长计划。
- 020四次闭合占用1862.3988633801896/86400秒（包括失败13.720774910595992秒），019为4878.797805346716秒，相加6741.1966687269056秒。最终离线评测另计，不当训练GPU纯生成耗时。
- BASE推理源码b28f08e8b4d151986a60d1e0f9d42653501f5b34、FULL best/last运行源码178af21a74701fb797fef6e8dd3808a3fa577716，历史报告dirty按原值false保留。best/last实际BF16参数222不同、88相同，因此分别执行评估。BASE/BEST/LAST各7组1760题位完整核准，分别2410+1、2863+1、2863+1调用；共21组5280题位、8136 benchmark阶段加3中性。
- BEST给定证据参考选择800/800、rewrite439/640；RAG引用参考命中92/170和170/311、二元拒答263/300和453/500、误拒答37和47；LAST参考选择800/800、rewrite436/640，RAG引用91/169和170/309、二元拒答262/300和452/500、误拒答38和48；两full普通严格proxy均35/100。legacy两组原生exit1、误拒答与引用错误保留。不是整体RAG准确率、自由语义正确率或无遗忘证明；thinking/format混杂、synthetic/human_reviewed=false、019测试复用限制均详见报告。

报告：[训练](../../experiments/finetuning/reports/todo-020-training.md)、[对照](../../experiments/finetuning/reports/todo-020-comparison.md)、[制品聚合清单](../../experiments/finetuning/reports/todo-020-artifacts.json)、[本地使用](../../experiments/finetuning/README.md)。上述5份公开文档已按本次静态核对安装；私有路径、QA/标签/prompt/output、密钥与权重只留忽略目录。

### 实际验证与集成

源码178af21实际运行`node scripts/dev.mjs check` exit0，Node8/backend741/evaluation44/finetuning287+2 Windows skip/Vitest114/Playwright23；专项`uv run --directory backend --frozen python -m pytest ../experiments/finetuning/tests -q` exit0，287passed+2skip，前后工作区clean。Linux PDEATHSIG+tiny CPU Trainer为5813实际证明，178只复用四份源码完整字节不变，不冒称重跑。已知警告保留。本次安装后的未提交变动仅为文档，历史源码检查的dirty=false保持原值。此文档尾段只作事实/哈希/链接/格式静态核对，不重跑源码套件；云端CI未运行。

| 项目 | 实际状态 |
| --- | --- |
| 分支 | feat/todo-020-full-06b |
| 功能PR | [#38](https://github.com/cdzdd/aiServerAndModelTraining/pull/38) |
| LAST完整矩阵、结果独立评审、自有服务释放 | 已完整7组/1760题位，188组检查+75闭合检查exit0；原生legacy1/1保留 |
| 全分支独立强评审 | PENDING |
| 功能PR普通合并 / 实际SHA | PENDING |
| 仅020任务状态收尾PR / 普通合并 | PENDING |
| 权威origin/main与主工作区同步、领取释放 | PENDING，由负责人串行收尾 |

只有功能PR和单任务状态收尾都真实合入权威main后才能done。后续合并状态收尾只在本任务文件记录实际功能合并SHA与PR，不创建自指文件提交SHA，不改todo索引或其他任务。
