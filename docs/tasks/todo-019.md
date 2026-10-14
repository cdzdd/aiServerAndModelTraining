# todo-019：8B QLoRA 长时训练实践

| 字段 | 值 |
|---|---|
| id | todo-019 |
| 状态 | done |
| depends_on | todo-013、todo-014、todo-015 |
| 优先级 | P2：本机训练实践，不阻塞网站发布 |
| 负责目录 | `experiments/finetuning/`、必要的 `experiments/evaluation/` 扩展 |
| 并行可行性 | 数据、CPU 测试和文档可并行；本机 GPU 训练与模型生成串行 |
| 训练预算 | 本任务所有训练尝试累计最多 86,400 秒；与 020 合计最多 172,800 秒 |

## 用户目标与本轮边界

2026-10-13 用户选择一次 LoRA 路线、一次全量微调实践，各最多 24 小时，合计最多 48 小时；数据准备、下载和训练结束后的最终离线评测另外计时。本任务承担第一轮 8B QLoRA，并建立供 020 复用的新数据与最小训练预算工具。

2026-10-13 已通过 PR35 保存计划；2026-10-14 用户明确接手并授权自主准备数据，现按计划实施。既有015保持done，020未领取；当前真实训练/模型状态以工作记录为准。

## 已确定的设计

- 模型：`Qwen/Qwen3-8B`，执行时从官方仓库解析并冻结不可变 revision、许可和全部加载文件 SHA256；不能把模型名或 latest 当作固定身份。
- 方法：4-bit NF4 / double quantization、BF16 计算、LoRA rank 16 / alpha 32 / all linear、SDPA、gradient checkpointing、micro-batch 1、梯度累积 16、seed 42、初始 LR 5e-5 / cosine / warmup 3%。模板 qwen3_nothink，train_on_prompt=false。
- 初始 cutoff 2048；仅在预跑阶段因显存或目标截断审计结果调整到 1024，记录前后配置。正式训练配置与数据冻结后，不根据最终测试调整。
- 预跑真实吞吐后，冻结一次正式训练的 max_steps，最多覆盖 3 epochs；预算、验证停止条件或训练目标任一达到就停止，不承诺运行满 24 小时。最多 24 小时包含本任务预跑、OOM 尝试、模型加载、训练、期间验证、保存和退出；暂停且已释放 GPU 的间隔不计。
- 常规验证/可恢复保存目标间隔 30 分钟，以预跑的每优化步耗时折算 save/eval_steps。末尾至少预留 10 分钟保存，预算外部截止机制处理卡死；保存超时只能中止本轮实际拥有的训练进程，保留上一完整 checkpoint。完整边界见 [实施计划](todo-019-plan.md)。
- 普通不量化 LoRA、14B、DPO/RL、全量 8B、CPU/NVMe 大规模卸载不属于本轮默认方案。8B 预跑不可承载时报告实际阻塞，不悄悄换成旧 4B 完成验收。

## 数据与评测契约

- 新数据为原创、明确虚构的校园/客服教学材料，synthetic=true、human_reviewed=false。先准备约 10,000–30,000 条训练样本的候选池，按质量和实际 token 数冻结有效规模；行数与耗时不是效果承诺。
- 来源文档、语义近重复及模板 family 先分组，再分 train / dev / test；dev 至少 300 题、新 test 至少 500 题。候选池未达质量要求时缩小正式规模并如实记录，不用改编号重复样本补数量。
- 答案任务严格投影现有 ANSWER_SYSTEM：answered / clarify / no_answer、最多 3 条连续原文、总引文不超过 800 字符。追问任务投影 REWRITE_SYSTEM：question/history → query/needs_clarification。权限始终由后端决定。
- 独立代理逐条核验 dev/test、各 family 的生成规则，并抽查每类至少 20 条 train；未通过 family 排除后重新冻结。代理审核不冒称人工业务审核。原始大数据和参考答案保存在忽略目录。
- 旧 013 的 60 题只作历史回归；不得把其来源或参考答案用于新训练。新测试在配置冻结后运行，禁止依测试答案改训练。020 复用同一冻结测试时注明此前 019 已运行，不声称全新盲测。
- 分开测给定正确证据的生成/改写与真实 RAG；100题通用回归另用固定普通指令提示词与格式/算术/JSON评分，不套用禁止自由答案的RAG提示词；区分无检索候选、模型拒答、JSON/引用验证失败。各自基座与 adapter 的推理栈、检索、提示词、输出上限及实际贪心模式一致。
- 模型、数据、提示词、配置、代码、真实加载制品与预算账本均带版本/哈希；调用者提供的清单是旁证，不冒称服务自动认证。

## 实施与验收

- [x] 按 WORKFLOW 正式领取实施任务，在独立 worktree 核实依赖与 GPU 占用。
- [x] 以 TDD 扩展新数据/多证据/拒答/改写验证，同时保持 015 的默认 8+2 教程行为。
- [x] 实现最小累计预算 CLI、恢复身份检查与资源记录；不创建调度平台。
- [x] 扩展显式数据集与版本化 base/lora/full 身份评测；保留旧 4B v1 与 loopback 守卫。
- [x] 完成独立代理数据 QA、实际 Factory 模板长度与 train/dev 全行 CPU 标签/padding 审计。
- [x] 冻结新数据/许可/模型文件，完成真实 100–200 steps 预跑和实际恢复。
- [x] 在代码9a1e1d3运行统一检查并通过分项独立代码评审；两项 Windows 跳过行为在 WSL 补验。
- [x] 独立从基座完成一轮有界正式训练，保存完整恢复 checkpoint 与分别标识的最佳/末轮 adapter。
- [x] 完成同模型基座对照、遗忘回归、资源/预算/失败报告与本地使用教程，保留真实负结果与范围限制。
- [x] 完成最终运行/交付独立评审、功能 PR 与状态收尾；本勾选和 done 状态在本状态 PR 实际合入权威 main 时生效。

验收允许负结果与提前停止，但必须有真实参数更新、完整可恢复制品、有限 loss/张量、可加载模型及两条评测路径。若没有这些证据，不能仅以“运行了 24 小时”验收。

## 计划与外部条件

详细步骤、文件、接口和验证命令见 [todo-019-plan](todo-019-plan.md)。实施前核实 RTX 5070 Ti / WSL2 / 现有 CUDA 12.8 环境仍可用及存储容量；不把 015 的短序列显存或耗时外推为 8B 保证。不默认购买资源、调用付费模型、切换网页 provider、删除旧训练制品、发布公网或启用 018。

官方依据：[模型卡](https://huggingface.co/Qwen/Qwen3-8B)、[LLaMAFactory 显存估算](https://github.com/hiyouga/LlamaFactory#hardware-requirement)。以上保留原验收设计；本轮真实训练、对照、评审与功能合入证据见下方。功能已通过PR36合入权威main；状态收尾按本PR实际合入生效。

## 2026-10-14 实施记录

- 本轮原子领取owner5071ddae-5c88-425b-9e34-1cf51e26d54c，原生独立worktree todo-019-8b-qlora，分支 feat/todo-019-8b-qlora；基点adc0d408。
- API/Web/DB/实验模型端口8149/5249/15479/11439，Compose qa-todo-019-5071dd；私有配置独立生成，未输出凭据。
- 接手准备阶段确认 WSL 原训练环境与 CUDA12.8 实际可用并记录精确版本；当时只做隔离基线与实现准备，未启动训练。后续真实训练另行记录。

- 隔离基线 node scripts/dev.mjs check 实际退出0：8Node、741后端、9评测、46微调、114Vitest、23Playwright，Ruff/构建/迁移通过；日志.local/baseline-check.txt，对应原始代码adc0d408。
- 原始 Qwen/Qwen3-8B 固定修订b968826d9c46dd6066d109eabc6255188de91218，Apache-2.0；14文件共16,397,459,696字节下载完成且逐文件SHA核验，清单.local/verified-base-8b.json。
- 准备阶段曾出现工作区与 Git 共享目录拒写；2026-10-14 恢复完整访问并验证两处实际可写，沿用原 Task1/2 代理继续，没有重跑安装/模型下载；该故障恢复时尚未启动训练、预算未消耗。

### 实现、数据与检查已完成

- 新数据准备、v2 兼容校验、预算 CLI 和显式评测已按 TDD 实现并完成分项独立评审；预算截止/缓存身份与评测公开隐私问题在真实复现后修复并通过复审。现有015默认8+2教程和旧4B v1保持兼容，未改共享依赖。源码/统一检查提交为 `9a1e1d3a310c58a07aa03962af4d07cc1a07d8fb`，runner SHA256 `13605adff21880929bcf05e9a57abb2bc3fd9c06b298e624f6a49504973be4f3`。
- 原创虚构材料 `synthetic=true/human_reviewed=false`。7,200候选题/14,400双任务候选投影筛选为1,800题：train1000/dev300/test500，对应正式train2000/dev600/test1000投影；新评测文件只含dev/test800题，普通回归100题另列。5,400原始来源归一后2,016种文本，有限family和复用措辞限制外推；不把14,400称为训练行数。
- 独立代理完成36family阅读、全部1,800题结构/问题证据关系检查、普通100题复核、train五类各20题语义抽查。五项初始条件/动作问题在r2修正后复核通过；跨split重复/近重复与旧013的60题/20来源筛查无命中，不据此承诺语义绝无泄漏或真实业务质量。原始资料/参考答案保留忽略目录。
- 冻结r2原始输入 SHA256 `c0eda2cfc12bcf8d4475370763fe64d7664f8b0ddf8575ec1cd7ffcb9af56cad`，manifest `d28984112c49aa6d0c0a8199ffedaf9e8711532929d26a582d82c7d06a321ac3`，train `5253f93cb564d169a233b668e25b9915065bca70629912c89651bbeee045c61c`，validation `618f4f6bf0a4de11ba8b0fa59cd0d4bcc5dd726265ff73f31bdb84fab17c42a0`。原始来源示例ID按各自身份评分，不用归一文本把不同来源等同。
- 实际 Factory qwen3_nothink 模板审计3,700行，最大完整序列536tokens；CPU真实Factory数据处理/collator核查全部train/dev2600行，输入/目标无截断，源及padding标签屏蔽正确。train742392非padding/54836监督targettokens；cutoff保持2048。CPU审计不冒充GPU模型更新。
- `node scripts/dev.mjs check` 在9a1e1d3实际退出0：8Node、741后端、9评测、165微调（另2项Windows跳过）、114Vitest、23Playwright，Ruff/迁移/构建通过；日志 `.local/integration-check-9a1e1d3.txt`。两项跳过行为另在既有WSL CPU环境验证：完整Trainer100→200恢复/原生early-stop counter恢复，以及Linux父进程退出守卫；非8B质量结果。保留基线Starlette/AnyIO、Node FORCE_COLOR/DEP0190/构建体积提示及CPU快速checkpoint mtime回退警告；此前锁定source-map-js1.2.1高风险audit发现仍未通过本任务改依赖解决，不能称无告警。

### 真实8B预跑与恢复已通过

- 同一固定200-step配方先暂停100再完整恢复到200，两次CLI实际退出0，暂停后所属进程均已退出并释放GPU；两次尝试累计1,905.293780500666秒，正式启动前剩余84,494.70621949933秒。账本位于Git common directory `codex-coordination/training-budgets/todo-019.json`，只初始化一次，未重置；加载、验证、保存和退出均计时，闭合暂停间隔不计。
- 真正加载的基座8,190,735,360参数+LoRA43,646,976=8,234,382,336，NF4/double quant/BF16/rank16/alpha32/SDPA/GC/micro1accum16与冻结配置一致。checkpoint100/200完整哈希验证通过，504个Adam状态分别step100/200且有限，固定200cosine/warmup6的scheduler到200时LR为0，Python/NumPy/CPU/CUDA RNG均保存；实际恢复日志与已安装Trainer恢复路径共同证明完整状态继续。全部504个LoRA张量有限且100→200继续变化；独立运行制品评审批准预跑连续性，不声称与不间断训练逐bit等同或已证明API可加载。
- 预跑最终训练loss0.0014，周期dev eval_loss0.004522998817265034；仅说明这批教学材料上的训练/验证。训练forward合计1,187,026非padding输入/87,793监督targettokens。首段100实际更新train_runtime718.8813秒；原生打印0.278steps/s以名义200为分子，不用于正式吞吐估算。正式折算采用7.242648秒/更新。CP100保存计时3.954秒，CP200计时92.074秒含同步dev验证+保存，不能称92秒纯写盘。
- 10秒采样整卡最大9,168MiB，Torch allocated/reserved峰值7,935,535,104/8,550,088,704字节；整卡包含其他进程，采样不保证连续峰值。预跑未观察OOM或非有限故障，仍不据此宣称最终效果提高。

### 正式训练、实际推理、完整对照与独立评审已完成

- 经独立制品/冻结评审批准后，正式配置 SHA256 `82cc53eb038d75292c37ad2197f26d0a06a96abab753412c80b183494937a516` 已实际运行至375步/epoch3.0并exit0。固定save/eval250约30.18分钟、warmup12，原始基座/独立空正式输出、首次无resume/预跑adapter；沿用同一86,400秒累计账本，正式2,973.50402484605秒+两次pilot1,905.293780500666秒=4,878.797805346716秒，剩余81,521.20219465328秒，三次attempt均闭合、无OOM/非有限故障。正式退出后实际所属进程均退出、GPU721MiB/util0，再启动基座API。
- 实际GPU125步输入742392/监督target54836精确等于CPU审计的2000行一遍；375步2,227,176/164,508精确等于三遍。末步checkpoint375完整文件/身份/哈希验收通过，Adam504项均step375且有限、scheduler375/LR0、四类RNG、504有限LoRA张量43,646,976元素/all252B非零；正式mean train_loss0.08791322911312939，显示舍入0.0000不当作严格零loss或生成效果。
- 周期dev仅250一次，loss0.01013548020273447，测试前冻结所选rootadapter weights/config与best250字节完全相同（weights `46b2b53189c21b7ae5df206ad4aaae45136ae07cb3df1c282a0c17f8e324498b` / config `43292c5dc94801f6606732bc8513045cf0fb5f9a3bf377b6725cf0ac1828a027`）；末步375完整恢复weights `0be0eca7e70e96b9152bcecb8df14d709886ddbcea7425591f90d2cac1e79617` 另存。实际保留完整250/375（recent2包含best）及根目录所选adapter，不虚构第三个不同checkpoint；后续实际API载入的504张量已逐项核验。
- 原生early-stop patience3/改善严格大于0.001/callback state恢复已实现并CPU验证；375/250仅能有一次周期dev选择，不能在上限前观察三次失败，实际结束completed/counter0，未触发三次失败早停。正式250计时88.346秒是验证+save复合；375末步save3.957秒。训练/source/环境/预算/资源/恢复完整记录见 [训练报告](../../experiments/finetuning/reports/todo-019-training.md)；正式终态独立制品复核、完整运行结果复核和最终整分支评审均已通过。
- 两组实际loopback11439加载/nativeGREEDY_SEARCH/鉴权调用与14项完整评测已完成并获独立fidelity/公平比较分项批准，共3,520题次/5,199native API阶段（非独立原始问题）。LoRA所选250实际504个FP32张量精确等于保存值。基座7项全exit1；LoRA逐项0,1,0,0,0,0,1；两wrapper1，真实错误/负结果保留。测试前冻结baseline SHA `b386a617d19ad1166455c46149dbf18bfcecb0fe92f66cb12fa939c4f6685a2b`，无prompt/template/limits/data/retrieval/weights retune或补跑。
- LoRA given-evidence回答799/800、改写478/640、160N/A；162改写差异仅query文本，flags正确、语义等价未评。保留单个validJSON/in-range index3但quote无任何证据支持的INVALID_CITATION，mapping1.0仅639accepted。新RAG状态760/800含守卫/回退，不是语义正确率；11falseanswers、29handledinvalid引用/false-refusals、480/589reference-correct和109wrong-reference accepted引用全部保留。旧60=25modelanswers+15正确noCandidate guards+20false-refusals；普通47/100=17/40arith、0/30instruction、30/30typedJSONsubset，23arith失败含21格式+2错误bare整数；base floor0不证明无遗忘。见 [完整对照](../../experiments/finetuning/reports/todo-019-comparison.md) 与 [制品清单](../../experiments/finetuning/reports/todo-019-artifacts.json)。
- 实际9a源码统一检查内的完整专项命令为backend cwd `uv run --frozen pytest -c pyproject.toml ../experiments/finetuning/tests -q`（scripts/dev.mjs:53）；日志55–57行165pass/2Windows skip/13.45s，另有既有WSL补验。未重复literal standalone python-m命令或伪称新dochead跑过codecheck。所有14历史metadata d69d5b065844995faf28fa33642b066bd5145a53/working_tree_dirty=false原样保留。
- 两组拥有API均核对身份后SIGTERM、实际session exit15；LoRA最后释放证明所属进程退出、WSL11439无listener、Windows bind成功、GPU16303/719/15277MiB/util1%/38°C。忽略本机指南 `.local/finetuning-019/LOCAL-USAGE.md` 已包含实际nativeenv/helper/私钥FILE路径与真实中性调用、正常停止/完整恢复/预算注意事项。快照 `.local/finetuning-019/delivery-evidence-20261014T181337Z/` 已逐字节核验133份复制文件，另有3份summary/manifest/receipt，共136只读标记；manifest SHA `4a1114f5e5eda84a93ad3330f6d6d1ffdd5045a91184a60b933e6a2c5f7b4c22`、receipt SHA `deaa8cc850e5d18390c4894c271ecef6c79733c50f205847331a64223dc62941`，最终操作制品独立审查Approved。普通只读+SHA不是WORM；权重/私钥未复制，原始私有问答仍在原忽略位置。首次错误源路径造成的partial archive无complete receipt，不当成完成。
- [功能PR36](https://github.com/cdzdd/aiServerAndModelTraining/pull/36) 已于2026-10-14T18:43:07Z普通squash合入权威origin/main，功能合并SHA `0cc400f88167431ad9b1a2517deb435c9170f4ba`，已验收PR头 `325b68903bd9167372e2e717a41c39a7026f4619`；fetch后功能main树与已验收分支完全相同。最强模型独立整分支评审Ready to merge，无Critical/Important；唯一DOC-01快照状态表述已修复并通过一次范围复核，无剩余问题。最终纯文档变化仅做事实、SHA、链接、格式、隐私和命令静态核对；复用未改变的9a源码实际统一检查，不冒称新代码检查或云端CI成功。

- 本次仅更新本任务记录的状态收尾PR以真实功能合入为前提，实际合入后权威main的done生效；不写该收尾提交自身SHA，不再创建下一层状态PR。交付报告中的in_review/待合并明确属于2026-10-14 UTC组装快照，实时状态以本文件为准。主目录按WORKFLOW在状态合入后干净main上ff-only同步。云端CI未运行；020保持pending未领取或执行，016本地停止边界、业务provider及018保持原约定。
