# todo-020：0.6B 基座与完整模型对照

BASE、best250、true last375均完整完成七组评测，各1,760题位，并获独立结果完整性核准；记录中的自有API停止/端口/GPU释放也已核准。所有原生失败与狭窄评分边界保留；当前集成状态见[任务记录](../../../docs/tasks/todo-020.md)。

正式best250与true last375实际加载后222/310个唯一BF16参数不同（88个相同、结构差异0），是两个模型；加BASE共3个模型，实际完成21组/5,280个评估题位。每模型七组1,760题位并非独立问题数；同一冻结019测试复用，`synthetic=true`、`human_reviewed=false`，不是新盲测。

| 实际模型 | 推理code_commit / dirty | 完成组/题位 | benchmark阶段调用+中性 | 原生exit（固定组序） |
| --- | --- | --- | --- | --- |
| BASE | `b28f08e8b4d151986a60d1e0f9d42653501f5b34` / false | 7 / 1760 | 2410 + 1 | [1,1,1,1,0,1,1] |
| FULL best250 | `178af21a74701fb797fef6e8dd3808a3fa577716` / false | 7 / 1760 | 2863 + 1 | [0,0,0,0,0,1,1] |
| FULL last375 | `178af21a74701fb797fef6e8dd3808a3fa577716` / false | 7 / 1760 | 2863 + 1 | [0,0,0,0,0,1,1] |

| 完整阶段调用（answer/rewrite/general） | BASE | BEST | LAST |
| --- | --- | --- | --- |
| given-evidence-dev | 300/240/0 | 300/240/0 | 300/240/0 |
| given-evidence-test | 500/400/0 | 500/400/0 | 500/400/0 |
| real-rag-dev | 60/240/0 | 235/240/0 | 235/240/0 |
| real-rag-test | 100/400/0 | 378/400/0 | 378/400/0 |
| general-test | 0/0/100 | 0/0/100 | 0/0/100 |
| legacy-grounded-dev | 18/3/0 | 18/3/0 | 18/3/0 |
| legacy-grounded-test | 42/7/0 | 42/7/0 | 42/7/0 |

训练源码为`5813a7ae1ea89e0b9de46b8e6fd3a430c8b55286`，最终文档head不替换实际code_commit/dirty。组序为given-evidence dev/test、real-RAG dev/test、general test、legacy-grounded dev/test。原生exit0表示按各命令自身退出规则正常结束；RAG安全回退仍保留且不一定使退出码非零，不等于质量通过。legacy两组的exit1完整保留。

## 冻结条件与测量范围

三组使用同一0.6B非量化BF16栈、Factory0.9.5、同一冻结输入/提示词/模板和实际GREEDY_SEARCH。answer/general上限512，rewrite128；RAG成功rewrite后answer384，否则512；请求temperature0，输入内容合计上限12,000 UTF-8字节。未按test更改模板/cap、剥离thinking标签、修复模型输出、过滤错误、重跑调优或再训练。

BASE全部2,410阶段输出含opening thinking tag。安装版`qwen3_nothink`是普通Qwen framing，没有强制空thinking后缀，名称不能证明禁用思考。因此格式/引用选择收益同时混有reasoning/format行为变化，无法单独归因为学到领域任务。given-evidence answer只评冻结status/index/quote参考选择；不是独立自由文本语义正确率。改写是精确参考匹配，不评价其他改写的语义等价性。

| 给定证据/改写 | BASE dev / test | BEST dev / test | LAST |
| --- | --- | --- | --- |
| status/index/quote精确参考匹配 | 0/300；0/500 | 300/300；500/500 | 300/300；500/500 |
| rewrite精确参考匹配 | 0/240；0/400 | 166/240；273/400 | 164/240；272/400 |
| rewrite不适用 | 60；100 | 60；100 | 60；100 |
| answer显式错误 | 300；500 | 0；0 | 0；0 |
| rewrite显式错误 | 240；400 | 0；0 | 0；0 |
| 有效返回引用/quote mapping | 0/null；0/null | 240/1；400/1 | 240/1；400/1 |

BASE dev answer为290 INVALID_JSON+10 length，test为480 INVALID_JSON+20 length；全部640 rewrite为length。length保留`PROVIDER_UNSUPPORTED_RESPONSE`分类，不能当通信故障或成功。BEST和LAST各800 answer及640 rewrite均stop，无显式错误；两者rewrite参考命中分别439/640与436/640，未过滤错误或改变评分。

## 真实RAG：检索、引用与二元拒答分开

| 指标 | BASE dev | BEST dev | BASE test | BEST test | LAST dev/test |
| --- | ---: | ---: | ---: | ---: | --- |
| 独立固定查询检索分母 | 180 | 180 | 300 | 300 | 180 / 300 |
| recall@5 | 0.8666666666666667 | 0.8666666666666667 | 0.8666666666666667 | 0.8666666666666667 | 0.8666666666666667 / 0.8666666666666667 |
| MRR | 0.7329629629629629 | 0.7329629629629629 | 0.6775555555555556 | 0.6775555555555556 | 0.7329629629629629 / 0.6775555555555556 |
| 返回引用中的参考source-ID命中 | 0/0（null） | 92/170 | 0/0（null） | 170/311 | 91/169；170/309 |
| accepted quote mapping | null | 1 | null | 1 | 1 / 1 |
| 二元expected_refusal匹配 | 0/300 | 263/300 | 0/500 | 453/500 | 262/300；452/500 |
| false refusal | 57 | 37 | 97 | 47 | 38 / 48 |
| 原生row error_count | 243 | 0 | 403 | 0 | 0 / 0 |
| 另记invalid JSON安全回退 | 57 | 0 | 97 | 0 | 0 / 0 |
| invalid citation安全回退 | 0 | 34 | 0 | 37 | 35 / 38 |
| false answer / permission leak | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0；0 / 0 |
| 全案例p50 / p95 ms | 2785.2963 / 7171.0111 | 919.4922 / 2021.4575 | 2678.5263 / 7169.7863 | 881.4669 / 1942.1758 | 873.0278 / 1990.8636；841.4006 / 1907.2378 |

retrieval来自模型管线之前对冻结`case.retrieval_query`的独立检索，固定BGE/vector/threshold0.65/top5/无rerank；不是模型改写后检索指标。相同数值表明独立检索基线一致，不能说微调提高检索。引用correctness逐个返回citation评参考source-ID命中；mapping1仅证明已接受quote可映射到其来源，不等于引用选择符合参考，更不是自由回答语义正确率。BEST仍有dev78/170、test141/311个返回引用未命中参考；LAST为dev78/169、test139/309。分母是返回citation，不是题数。

`refusal_accuracy`只比较二元`expected_refusal`，不是RAG整体准确率。BASE有历史240/400例在rewrite length即停止，未到模型检索/answer；无历史60/100例中各3例answer length，其余57/97为非法JSON安全no_answer，另计误拒答，不增加原生row error_count。BEST/LAST达到更多阶段，benchmark阶段总数不同；相同管线不代表相同实际query、候选和调用数。零显式错误/false answer/leak不证明所有回答正确，安全回退和误拒答均保留。延迟含独立检索及实际到达阶段，不能当纯GPU生成速度或可比工作量的加速倍数。

## 通用回归与legacy负结果

| 指标 | BASE | BEST | LAST |
| --- | --- | --- | --- |
| 冻结普通指令100题精确proxy | 0/100；errors0 | 35/100；errors0 | 35/100；errors0 |
| legacy dev二元拒答 | 0/18；answer errors18 | 11/18；INVALID_CITATION3；false refusal4 | 11/18；INVALID_CITATION3；false refusal4 |
| legacy test二元拒答 | 0/42；answer errors42 | 15/42；INVALID_CITATION4；false refusal23 | 15/42；INVALID_CITATION4；false refusal23 |
| legacy dev/test术语命中 | 0/14；0/31 | 7/14；3/31 | 7/14；3/31 |
| legacy dev/test参考来源支持 | 0/14；0/31 | 7/14；4/31 | 7/14；4/31 |
| legacy strict status/rewrite scored | 0/null；0/null | 0/null；0/null | 0/null；0/null |
| legacy dev/test原生exit | 1 / 1 | 1 / 1 | 1 / 1 |

普通任务按严格整数/格式/类型敏感JSON子集评分，35/100是狭窄proxy提升。BASE0分是地板，不能据此证明无遗忘或广泛通用能力。legacy是旧60例给定证据18+42，非019 legacy RAG；strict status/subtype/rewrite gold缺失，scored0、correct/accuracy=null，不能补gold或混算领域准确率。BASE legacy dev18 INVALID_JSON、test41 INVALID_JSON+1 answer length，rewrite3/7均length；BEST/LAST rewrite3/7均stop但无gold仍不评分，所有失败保留。

BEST与LAST给定证据参考选择均800/800、通用proxy均35/100；LAST的精确rewrite少3/640，RAG二元拒答dev/test各少1例，返回引用分母也不同。这些是本冻结量表的实际差异，不作广泛语义能力优劣或统计显著性结论。

## 耗时、审计与集成

| 活动评测组窗口秒数 | BASE | BEST | LAST |
| --- | ---: | ---: | --- |
| given-evidence-dev | 2441.5570417 | 295.5724042 | 292.0690294 |
| given-evidence-test | 4183.8066684 | 490.0116785 | 514.8216353 |
| real-rag-dev | 1128.9817118 | 389.9040905 | 382.3605209 |
| real-rag-test | 1779.9775704 | 589.7328470 | 565.7734653 |
| general-test | 306.3008143 | 29.5960081 | 30.7181743 |
| legacy-grounded-dev | 89.2139688 | 13.0650173 | 12.1879376 |
| legacy-grounded-test | 217.2305672 | 18.6998842 | 20.0632860 |
| 合计 | 10147.0683426 | 1826.5819298 | 1817.9940488 |

LAST上表按原始100ns时间重算合计1817.9940488秒；原生微秒浮点汇总字段为1817.994049秒，精度不同。首组开始到末组结束的原始窗口为1859.7378863秒（含组间间隙），终端微秒记录字段1859.737887秒。每组按同OS终端明确started_at/ended_at求差，包含启动/setup、CPU检索/索引、provider等待、生成、评分/报告；不是纯GPU推理。整段离线阶段还包含加载、已保留故障、调试、评审/空闲，完整起止未建立，整段总耗时不作数值声明，也不计入闭合训练占用1862.3988633801896秒。

BASE、BEST、LAST均各完整覆盖7组/1760题位并获独立结果核准；BEST完整188+6+70项静态审计exit0，并核准记录中的自有API停止/端口/GPU释放。BEST首个dev启动receipt缺失、第四后代birth未知，后续仅有三个已知身份的工具输出转录；短legacy-dev在首次10秒工具返回前结束，birth未观测、start为空/absence为null。这些是观察限制，不能补造进程身份或视为缺失题位。跨OS端口时间约0.5秒偏差，只能按wrapper明确await顺序说明，不推断隐藏属主/预留寿命。LAST实际runtime/auth与不同模型身份已独立33项核准；全部7组188项与最终75项closure审计exit0，完整结果及记录中的自有服务释放均核准。六组各四个初始birth完整且后续记录均absent；短legacy-dev在首次出生身份捕获前结束，birth未观测，absence保持null，没有重建历史身份。记录中自有API经SIGINT正常exit0，native只读核实旧birth/11440监听不存在、无GPU compute；随后wrapper明确await成功才做Windows exclusive最后绑定并关闭socket，均exit0，之后没有WSL bind。两OS时钟约0.18秒偏差，不据时间戳排序推断属主或进程寿命。725MiB/1%是释放后的整卡快照，不是模型占用或峰值。BEST/LAST完整mode/cap日志哈希相同仅因生成设置顺序相同，不代表输出/模型相同或允许去重。

制品与训练细节见[训练报告](todo-020-training.md)、[安全制品清单](todo-020-artifacts.json)。最终集成状态、功能PR及独立全分支评审见[任务记录](../../../docs/tasks/todo-020.md)。不同规模8B QLoRA与0.6B full不能比较方法优劣；公开内容仅聚合，不发布原始QA/标签/prompt/output、私钥/其哈希、权重或本机私有绝对路径。
