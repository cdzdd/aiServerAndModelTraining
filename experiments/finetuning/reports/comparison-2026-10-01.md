# 2026-10-01 基座与 QLoRA 的同栈 RAG 对照

本地教学案例已完成真实训练和修正后的贪心对照：test 的 31 道应可回答题，基座 12 道输出有效引用答复，微调后为 14 道；误拒答 19→17。dev 的 14 道应可回答题仍为 6 道有效引用、8 道误拒答。可见的改善主要是原文选择更简短，以及两题新增有效答复；这组极小虚构数据不足以证明真实业务泛化，当前保留网页使用已验收的 Ollama 基座。

## 实验身份与范围

基座固定为 Qwen3-4B-Instruct-2507、修订 `cdbee75f17c01a7cc42f958dc650907174af0554`；两组均使用 HF/BNB NF4/BF16、qwen3_nothink、SDPA、实际 GREEDY_SEARCH，推理配置只差 `adapter_name_or_path`。8 条 train、2 条独立校报 validation 与 todo-013 的 18 dev/42 test 按来源、主题和问题隔离。材料全部原创虚构、经独立代理审核，human_reviewed=false，不能替代真实业务资料的人工审核。

四份报告均真实退出 0，代码 SHA `49d3ded90f34969122a841258f7dedd4af0c6cbf`、working_tree_dirty=false。检索配置固定 baseline vector/threshold 0.65/top-k 5、BGE CPU、rag-extractive-v2，数据、提示词、训练超参和 adapter 在对照过程中不变。样本权限、历史、参考来源与首次检索候选逐条相同；生成阶段的检索查询有两处措辞差异（dev-network-q4、test-meal-q4），候选仍相同。不能把“相同配置”表述成模型每条改写文本逐字一致。

运行代码、配置 SHA、实际启动参数与有效生成模式证据见 [运行旁证](runtime-provenance-2026-10-01.json)，模型/数据/训练身份见 [制品清单](training-artifacts-2026-10-01.json)。runtime manifest 是调用者核验后的旁证，服务没有自动提供模型身份认证。四份完整逐题记录为 [dev 基座](dev-base-rag.json)、[dev 微调](dev-finetuned-rag.json)、[test 基座](test-base-rag.json)、[test 微调](test-finetuned-rag.json)，机器可读汇总见 [comparison JSON](comparison-2026-10-01.json)。

## 指标与分母

| 指标 | dev 基座 | dev 微调 | test 基座 | test 微调 |
| --- | --- | --- | --- | --- |
| 总题数 | 18 | 18 | 42 | 42 |
| 应可回答题数 | 14 | 14 | 31 | 31 |
| 有效引用答复 | 6/14 | 6/14 | 12/31 | 14/31 |
| 误拒答 | 8 | 8 | 19 | 17 |
| recall@5 / MRR | 10/14 = 0.7143 | 10/14 = 0.7143 | 21/31 = 0.6774 | 21/31 = 0.6774 |
| 引用来源正确 / 映射正确 | 6/6 / 6/6 | 6/6 / 6/6 | 12/12 / 12/12 | 14/14 / 14/14 |
| 拒答分类符合标签 | 10/18 = 0.5556 | 10/18 = 0.5556 | 23/42 = 0.5476 | 25/42 = 0.5952 |
| 应拒答却回答 / 权限泄露 / 上游错误 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| p50 端到端耗时，ms | 520.80 | 838.52 | 406.41 | 432.38 |
| p95 端到端耗时，ms | 1845.05 | 1877.43 | 2282.92 | 1882.98 |

引用来源与映射的 100% 仅覆盖实际返回的 6/6/12/14 条引用，校验引用位置、权限和原文连续片段，不能解释为全题语义正确率或真实业务无幻觉保证。拒答分类包含无依据、禁止访问、应可回答等标签，不是总体问答正确率。recall/MRR 基于固定参考检索查询；实际生成阶段可能采用上下文改写查询，两者分母与路径不可混用。

延迟包括 CPU 检索与缓冲模型完整输出；该 API 首段时间也是完整生成完成后的时间。dev 两个延迟分位均退化，test p50 退化、p95 下降。完整统一检查在基座正式生成前已结束，没有 GPU 训练重叠；后台系统负载没有严格控制，模型预热和输出长度也影响测量。这些数值是本机观察，不作为服务吞吐或统计显著性结论。

## 收益逐题核对

两道新有效答复是 `test-injection-3-q1`（AJ-602 报名点：报告厅602室）与 `test-injection-5-q1`（AJ-604 报名点：报告厅604室）。两组拥有相同查询和授权候选，基座返回 no_answer，微调后通过现有 RAG 原文/引用验证并得到单条有效引文。报告没有保存原始模型选择 JSON，不能进一步归因基座是自行拒答还是选择结构未通过核验。

其余变化均是 already answered 题目的引用缩短。下表列出全部 5 条 dev、14 条 test 的答复或状态变化；完整前后答复在 comparison JSON 与原始报告中。

| 分组 / 题目 ID | 状态变化 | 微调引用 |
| --- | --- | --- |
| dev-library-q1 | answered，引用缩短 | 东馆一层 |
| dev-library-q2 | answered，引用缩短 | 08:30至20:30 |
| dev-card-q2 | answered，引用缩短 | 在教学服务台登记挂失 |
| dev-network-q1 | answered，引用缩短 | 楼栋、房间和故障时间 |
| dev-injection-1-q1 | answered，引用缩短 | 绿园14区 |
| test-dorm-q1 | answered，引用缩短 | 教学服务中心的维修栏 |
| test-lab-q1 | answered，引用缩短 | 课程教师 |
| test-lab-q2 | answered，引用缩短 | 两天 |
| test-meal-q1 | answered，引用缩短 | 西区服务台 |
| test-meal-q2 | answered，引用缩短 | 两张 |
| test-record-q1 | answered，引用缩短 | 学生证与用途说明 |
| test-sport-q1 | answered，引用缩短 | 南操场看台下 |
| test-room-q1 | answered，引用缩短 | 北楼二层 |
| test-room-q2 | answered，引用缩短 | 四小时 |
| test-room-q3 | answered，引用缩短 | 15分钟 |
| test-clinic-q1 | answered，引用缩短 | 生活楼19室 |
| test-injection-3-q1 | no_answer → answered | 报告厅602室 |
| test-injection-4-q1 | answered，引用缩短 | 报告厅603室 |
| test-injection-5-q1 | no_answer → answered | 报告厅604室 |

`test-lab-q2` 的回答从“学生须提前两天提交课程编号和使用时段”缩短为“两天”；它是原文连续片段，配合问题“要提前多久”可理解，但不包含评测字面 answer_term“提前两天”，term_coverage 从 1 变成 0。字面术语覆盖和引用有效性是不同指标，不能用这次缩短声称所有答案指标均改善。

## 残余失败与应用决定

dev 两组的 8 道误拒答都未改善，其中 7 道在生成阶段无候选，1 道为 clarify；test 基座的 19 道误拒答中，17 道生成阶段无候选、2 道有候选仍 no_answer。微调改善了后两道，其余 17 道仍无候选而拒答。带 history 的 dev 3 道、test 7 道在两组都 no_answer，未显示上下文检索能力的改善。模型训练没有改善参考检索召回；后续工作应根据实际失败分桶推进检索/上下文能力，再在新的独立资料上验证。

本任务验收目标是可恢复的约 4B 本机微调实战，已具备有限的正结果和完整负结果。当前不建议凭这组教学测试切换正式模型；微调模型通过本机独立私钥 API 展示，网页仍用 Ollama 基座，未启用 todo-018 或 GGUF 转换。真实上线前仍需要业务资料授权、人工审核、更丰富的独立验证集与新冻结测试。

## 纠错记录与复核

首轮四份真实报告在 27bb52e 上运行，虽然请求 do_sample=False，Transformers 4.57.6 实际以模型默认值覆盖为采样。独立审核通过实际 GenerationMixin 路径复现后，49d3ded 在模型加载后的内存 generation_config 中固定 do_sample=False，并由真实 Transformers 回归及独立 PEFT tiny-Qwen3 CPU generate 验证 GREEDY_SEARCH。随后数据、adapter、超参、提示词、检索均保持不变，重新完成四份真实对照；原始模型缓存没有改写。当前结论仅使用修正后的报告。

[首轮 v1-sampled 历史](v1-sampled/README.md) 连同原始逐题结果和被纠正的 runtime 说明完整保留。测试集此前已运行过，本轮是实现缺陷的纠错重测，不能称为完全未见的最终测试；没有根据测试答案调整训练。独立代理对当前四份 120 行、38 条引文的 summary、metadata、授权候选、usage、quote 和 latency 全量复算通过，也验证全部当前/历史 JSON 可严格 UTF-8 解析。原始独立审核记录保留在本机 `.local/independent-review-015-code.md` 及最终报告审核记录中。

复现与本机服务使用步骤见 [实验教程](../README.md)，当前网页/API readiness 和整卡快照见 [部署记录](local-deployment-2026-10-01.json)。
