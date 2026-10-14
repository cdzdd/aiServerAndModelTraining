# todo-019：固定基座与所选 8B LoRA 对照

完整14项已实际完成，共 **3,520次题目评估、5,199个真实API阶段**，不是3,520个独立原始问题。所选LoRA在这批虚构教学资料的给定证据回答格式/参考匹配上为799/800，基座为0/800；实际新RAG的管线状态匹配为760/800，但仍有11次错误作答、29次无效引用/选择回退，以及109条被接受却不属于参考来源的引用。普通任务严格评分47/100，指令类仍0/30。结论限定于此冻结数据与评分，不宣称业务可靠、广泛泛化、无遗忘或零幻觉。

真实运行、完整恢复、累计4,878.797805秒训练预算和best250/last375身份见 [训练报告](todo-019-training.md)；所有逐项summary、元信息和文件SHA见 [制品清单](todo-019-artifacts.json)。原始问答、来源、参考答案与模型输出继续保留忽略目录。

## 同栈与身份

| 条件 | 基座 / LoRA共同实际条件 |
|---|---|
| 原始模型 | Qwen/Qwen3-8B，revision `b968826d9c46dd6066d109eabc6255188de91218`，Apache-2.0 |
| 推理栈 | 既有Factory0.9.5 / Transformers4.57.6 / PEFT0.18.1；HF/BNB NF4 doublequant、BF16、SDPA |
| 模板与解码 | 实际qwen3_nothink普通assistant前缀；内存do_sample严格false、native GREEDY_SEARCH、beams1/returns1 |
| 唯一模型差异 | LoRA增加测试前冻结的best250根目录adapter；504个实际FP32张量逐项等于保存值 |
| given-evidence | 生产ANSWER_SYSTEM与REWRITE_SYSTEM，answer512/rewrite128；答案与改写分别评分 |
| 真实RAG | 原问题/history/真实模型改写驱动检索；有改写时answer384，否则512，整体60秒 |
| 普通任务 | 独立固定ordinary system、max512，不套用RAG禁自由回答提示词 |
| 检索 | vector、threshold0.65、top-k5、不重排，baseline SHA `b386a617d19ad1166455c46149dbf18bfcecb0fe92f66cb12fa939c4f6685a2b` |
| 实际历史元信息 | 全14报告 `code_commit=d69d5b065844995faf28fa33642b066bd5145a53`、`working_tree_dirty=false`；运行源码与9a1e1d3相同 |

基座runtime-v2 SHA为`daf3a02430173f948b26af6d35937924af43b10c6f182f677b76c6c62666e4ab`，LoRA为`2f58b0f9148f1194412d1e3b75358a81eabf9863f210842f733a1dd0a4b72ac4`；inference YAML分别`7bc830ffa37d898f646244135656162597ae41d17e6e357949add6f0dc2e0d36` / `38e8380d25dcdb23f80a443e7a4d2de7dc802af99eb9189c9953fa9eb972c33d`，仅adapter字段不同。实际原生准备检查16/128/384/512四档，并另有真实鉴权中性调用。它们是实际载入/协议旁证，不是服务自动认证、每个benchmark token的hook或质量结果。

没有改提示词、模板、输出上限、检索、参考答案或所选权重来修补测试，也没有strip思考标签或补跑替换结果。基座全部2,371个实际输出含literal `<think>`标记，LoRA2,828个未检出该literal；这描述输出观察，不代表普遍无内部推理。训练identity、推理identity和评测dataset SHA分别保留，不把最终文档head覆盖历史报告元信息。

## 给定正确证据：严格格式/参考匹配

| 指标 | 基座dev300 | LoRA dev300 | 基座test500 | LoRA test500 |
|---|---:|---:|---:|---:|
| Answer格式/参考匹配 | 0/300 | 300/300 | 0/500 | 499/500 |
| Rewrite参考匹配 | 0/240 | 175/240 | 0/400 | 303/400 |
| 无history改写不适用 | 60 | 60 | 100 | 100 |
| 实际API阶段 | 540 | 540 | 900 | 900 |
| 被接受引用 / mapping | 0 / null | 240 / 1.0 | 0 / null | 399 / 1.0 |

LoRA合计answer799/800=99.875%，其中479个answered、160个no_answer、160个clarify，另1个INVALID_CITATION；并非799个实质答案。合计rewrite478/640=74.6875%，160个无history不加入分母。全部162个改写不匹配（dev65/test97）只在query字符串，clarification flags全部与参考相同；输出schema有效、无改写stage错误，语义等价未独立评估，既不擅自改成成功也不称162个语义错误。

test的单个无效引用是有效JSON且index3在三条证据范围内，但quote不在任何给定证据中，原验证器拒绝。639条accepted引用的mapping1.0是条件指标，不抹掉这一个失败。所有LoRA1,440个阶段finishstop并有真实usage；stop不是正确性保证。基座有785个stop/INVALID_JSON答案、15个length答案，640个改写length128；格式失败不等于已评估其潜在语义能力。

这是生产给定证据提示词的独立回答与改写评分，不能代替真实检索链路；exact frozen-reference match不是语义等价评分。

## 真实新RAG：状态、检索与引用分开

| 指标 | 基座dev300 | LoRA dev300 | 基座test500 | LoRA test500 |
|---|---:|---:|---:|---:|
| 诊断macroRecall@5 / MRR | .866667 / .732963 | 相同 | .866667 / .677556 | 相同 |
| 管线状态匹配 | 0/300 | 279/300 | 0/500 | 481/500 |
| false answers / false refusals | 0 / 60 | 8 / 13 | 0 / 100 | 3 / 16 |
| public pipeline errors | 240 | 0 | 400 | 0 |
| handled invalid选择/引用 | 60（INVALID_JSON） | 13 | 100（INVALID_JSON） | 16 |
| accepted引用的reference-correct | null（0分母） | 178/218 | null（0分母） | 302/371 |
| accepted引用的span mapping | null | 218/218 | null | 371/371 |
| 实际API阶段 | 300 | 475 | 500 | 778 |
| 整题p50 / p95秒 | 4.308 / 9.090 | 2.816 / 5.760 | 4.383 / 9.225 | 2.607 / 5.739 |

诊断检索在生产改写/生成检索之前使用冻结retrieval_query。dev的逐题reference recall之和156/180=.866667，不是156个命中题；178/180至少命中一条（134full/44partial/2none）。test为260/300同macro值，292/300至少命中一条（228full/64partial/8none）。两组初始诊断hits相同；不证明实际改写查询/生成候选相同，也不是端到端回答成功率。基座640个length改写终止后续生产检索/答案，另160个stop答案因INVALID_JSON安全回退，public rowerror为null仍是失败，不能称有效拒答。

LoRA真实800题有1,253阶段（640rewrite+613answer）；760/800=.95是包括守卫/回退的状态匹配，不是760个语义正确模型答案。dev279匹配由167个expected-answer/answered、47个model_no_answer、60个rewrite clarify守卫、5个no-candidates构成。实际保留11次expected-refusal却answered，以及29次answerable却因无效选择/引用回退的false refusal。`pipeline error_count=0`不包含29个已处理invalid_citation，不能写成无生成错误。

589条accepted引用中480条属于参考来源（约81.494%），109条不属于参考来源仍被接受；589/589的mapping只证明quote映射到本轮可访问候选。29个拒绝选择不进入accepted分母。合法原文、引用映射和状态匹配均不证明相关性或回答语义正确。观察到permission_leaks0仅限这批来源授权核验，不作普遍安全保证。

延迟是原报告整题路径分位数，输入/输出长度与完成的阶段数不同，warmup/索引另外记录；不将它外推为独立吞吐或生产性能承诺。

## 旧013回归与普通任务

| 旧真实RAG | 基座dev18 | LoRA dev18 | 基座test42 | LoRA test42 |
|---|---:|---:|---:|---:|
| 状态匹配 | 4/18 | 12/18 | 11/42 | 28/42 |
| false refusals | 11 | 6 | 25 | 14 |
| accepted引用正确/映射 | null | 8/8 | null | 17/17 |
| 实际API阶段 | 10 | 11 | 21 | 24 |

LoRA旧60题有25个model_answered、15个expected-negative/no-candidates正确守卫、20个answerable/no-candidates false refusals；40/60状态匹配不等于40个正确模型答案，15个不称模型拒答。基座15/60匹配也全来自无候选守卫，其21个stop无效答案、9个length改写错误，以及1个stop128tokens无效改写回退原问题后无候选的路径保留。诊断检索dev10/14、test21/31相同，来源/参考不用于新训练。LoRA25条accepted引用在这一小集均reference/span对应正确，不据此消除新RAG中的错误。

| 普通100严格评分 | 基座 | LoRA |
|---|---:|---:|
| 算术（bare整数trim） | 0/40 | 17/40 |
| 指令（原样精确文字） | 0/30 | 0/30 |
| JSON（严格解析+typed递归subset） | 0/30 | 30/30 |
| 合计 | 0/100 | 47/100 |

两组均99stop/1length，所有100 native usage保留；唯一length512按unsupported失败，不替换成功。LoRA23个算术失败含21个不满足仅输出整数的格式和2个真正错误的裸整数，不能把失败全解释为格式。JSON允许预定typed字段的递归subset，非整对象精确全等；布尔/整数/浮点不混同。指令依旧0/30，显著限制复用范围。基座严格评分已在floor0，47/100提高不能证明无遗忘，也不能判断全部基座原始数学/语义能力；固定100题不代表广泛泛化。

## 完整执行、审查与交付边界

| 操作 | 每组题次 | 基座阶段 / CLI exit | LoRA阶段 / CLI exit |
|---|---:|---:|---:|
| grounded-dev | 300 | 540 / 1 | 540 / 0 |
| grounded-test | 500 | 900 / 1 | 900 / 1 |
| rag-dev | 300 | 300 / 1 | 475 / 0 |
| rag-test | 500 | 500 / 1 | 778 / 0 |
| legacy-dev | 18 | 10 / 1 | 11 / 0 |
| legacy-test | 42 | 21 / 1 | 24 / 0 |
| general-test | 100 | 100 / 1 | 100 / 1 |
| 合计 | 1,760 | 2,371 / wrapper1 | 2,828 / wrapper1 |

CLI的非零exit由记录的错误触发，不伪写为通过；0也不评定全部质量（例如RAG已处理的invalid引用不增加rowerror）。所有14项已获独立fidelity/覆盖/评分/公平比较分项审查，包含真实负结果；分项批准不是模型质量合格或全分支最终评审。

两组API分别由其操作方核对拥有身份后请求SIGTERM，实际session退出码都为15，原样保留。LoRA最后的释放边界记录所属进程已退出、WSL11439监听数0、Windows loopback bind成功，整卡16,303MiB/已用719/空闲15,277/利用率1%/38°C；不当成任意未来的端口/空闲保证。

历史证据快照 `.local/finetuning-019/delivery-evidence-20261014T181337Z/` 已完成133份复制文件的SHA绑定，另有3份summary/manifest/receipt文件，最终操作制品独立审查Approved。manifest SHA `4a1114f5e5eda84a93ad3330f6d6d1ffdd5045a91184a60b933e6a2c5f7b4c22`，receipt SHA `deaa8cc850e5d18390c4894c271ecef6c79733c50f205847331a64223dc62941`；完整索引见制品清单。普通只读+SHA不是硬件WORM，原始私有评测问答保留原忽略位置，权重/私钥未复制。首次失败partial快照无complete receipt，不作为完成快照。任务`in_review`，最终全分支评审、功能PR与状态收尾合入main仍待完成；020保持pending，不启用018或改变016本地停止边界、业务provider与公网发布。
