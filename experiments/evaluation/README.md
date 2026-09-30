# 固定中文教学评测（todo-013）

本目录的星河校园、编号、费用、位置、规则和问答均为本项目原创的**明确虚构教学资料**，不对应真实学校。用户授权本轮先交付教学样本与独立代理复核；尚未进行真实业务资料收集或人工验收。发布前仍需真实资料、授权和业务人员审核，不能凭本报告宣称生产质量。

`dataset.json` 的v2固定60个评测问题：40正常/多轮、10无答案、5权限、5资料内恶意指令。18条开发、42条最终测试；来源主题组不跨划分。`training.json`是另外4个主题/8条训练格式示范，供015在自己的独立主题中扩展。不得把评测的题目、参考答案、规则或来源改写进训练数据。所有来源带原创说明、固定ID、文本SHA256；整个数据文件哈希随每次报告记录。近义问法在同一组，不能随机拆分后声称独立测试。

`retrieval_query`是人工编写的独立问题表述，用于隔离检索排名指标；完整RAG另外使用原问题和history，由真实provider改写并记录实际generation_query和generation_hits。引用只按完整RAG实际候选映射。纯检索报告不会把缺少的回答/引用/拒答质量写成零或通过。

## 运行

先按项目开发说明建立该worktree的冻结依赖、独立数据库和.env。配置固定本地BGE目录；所有编码在CPU且离线。运行器使用自己的 `qa_test` 临时随机schema，经现有真实FAQ索引handler写BGE向量，再调用真实pgvector检索；结束仅清理自身schema。不会写开发或生产public表，也不会自动下载模型或调用付费云模型。

在worktree根目录显式运行（普通check不启动真实模型）：

```powershell
uv run --frozen --directory backend python ../experiments/evaluation/run_eval.py --config ../experiments/evaluation/configs/baseline.yaml --split dev --output ../experiments/evaluation/reports/dev-baseline-retrieval.json
uv run --frozen --directory backend python ../experiments/evaluation/run_eval.py --config ../experiments/evaluation/configs/hybrid.yaml --split dev --output ../experiments/evaluation/reports/dev-hybrid-retrieval.json
```

配置在查看最终测试之前冻结。开发对照现阶段保留0.65现有阈值、20个候选、RRF常数60与两路相同权重；没有用最终测试调参。将split改为test并更换输出文件名运行最终检索。默认仍为 `RETRIEVAL_MODE=vector`，`RETRIEVAL_RERANK_ENABLED=false`；两个实验开关独立。

真实生成另需014已集成、worktree明确配置 `MODEL_PROVIDER=ollama` 及本机模型；同一命令添加 `--generate`。运行器拒绝Mock/云provider生成质量报告。RAG发出temperature=0请求，但本地推理服务仍可能有数值差异，重复生成应单独保存，不能把单次结果视为确定事实。缺失usage保留null，不估算tokens。

重排配置为 `configs/rerank.yaml`：固定 `BAAI/bge-reranker-base` revision `2cfc18c9415c912f9d8155881c133215df768a70`，本地CrossEncoder、CPU、512-token上限；模型路径由 `.env` 的 `RERANKER_MODEL_PATH` 指定。真实重排权重由用户已授权的root准备。本地目录只读加载，不从请求下载或执行远程代码。评测先使用开发问题预热并单独记录预热耗时；报告逐题延时不包含模型加载/索引。内存列是整个进程峰值工作集，不能当成模型独占显存。

服务重排默认每次最多2秒、单个后台worker；不可用、超时或已有工作未完成时回退到授权候选，诊断分别为unavailable/timeout/busy。线程中的计算不能硬取消，超时后继续到结束；不无限排队，后续调用回退。耗时和降级使方案不适合时保持关闭。

## 检索选择与分数

中文词法使用NFKC归一化后的中文字符bigram和完整ASCII标识（例如GH-204），不使用PostgreSQL英文分词器、不新增词库依赖。初期小规模语料在SQL完整权限/当前有效版本/模型元数据/余弦阈值过滤后扫描候选并词法排序，因此词法不能绕过阈值救回低余弦条目。较大语料的全文索引与性能优化不在本轮范围。

RRF合并向量和词法各前20候选；完全同分优先词法参与候选，再按稳定chunk UUID。RRF分数仅作内部排序，**SearchHit.score一直是当前query与该chunk的真实余弦**，现有RAG证据阈值不接收RRF/交叉编码器分数。重排只排列当前已授权候选，不能增加、修改或重复来源；重排前后再次验证当前权限与原文版本。

## 指标与审核

- Recall@5：仅有参考来源的题目，命中的唯一参考source数/参考source数，再宏平均。空参考不进入分母，空结果按0。
- MRR@5：同一有参考题目集合，前5个唯一source中首个参考来源排名的倒数，未命中为0。
- citation_correctness：所有生成引用中，source属于该题参考来源的比例；只代表来源精确率，不能证明所摘句子回答完整或人工语义正确。
- citation_mapping：每个引用是否映射至本轮RAG实际检索候选且摘录属于原文；引用分母为实际引用数，无引用时null。
- refusal_accuracy：成功answered用于可答题，成功no_answer/clarify用于应拒答题；上游error不计正确。分别记录误答、误拒答与错误数，不能混称回答准确率。
- answer_term_coverage：参考短语在回答中的字面覆盖率，仅作逐题复核辅助；forbidden_answer_term_matches记录恶意指令用语。两者均不是人工质量审核。
- permission_leaks：逐个检索/引用候选调用真实当前权限验证发现的失效来源数；零泄露是必要条件，不代表覆盖了所有攻击。
- p50/p95：包含该模式整条评测请求墙钟时间，线性插值；另外记录纯检索耗时、模型加载/索引/预热耗时、代码提交及dirty状态、数据与配置hash、模型修订、提示词、包版本、真实usage与安全错误代码。

独立评审者逐题核查：来源和规则原创/虚构说明；group与dev/test/train隔离；原文支持reference_answer及answer_terms；无答/权限题的当前允许范围；多轮历史与standalone query；攻击资料中的可答事实与禁止执行的指令；实际报告的引用位置和误拒答原因。应记录逐题结论和未决项，明确为**代理复核**。本轮还没有人工业务审核。

行为验证在backend运行：

```powershell
uv run --frozen pytest tests/retrieval/test_hybrid_search.py tests/retrieval/test_rerank_access.py -q
uv run --frozen pytest -c pyproject.toml ../experiments/evaluation/tests -q
uv run --frozen ruff check --config pyproject.toml . ../experiments/evaluation
```

普通自动化测试中的固定向量/provider只证明指标、权限、降级和运行器记录行为；真实教学模型效果以reports里的逐条报告为准。默认方案决定与发布前限制见 `reports/decision.md`。
`bge-reranker-base`的MIT许可与固定修订来源见[官方模型卡](https://huggingface.co/BAAI/bge-reranker-base/blob/2cfc18c9415c912f9d8155881c133215df768a70/README.md)。

2026-10-01代理逐题复核修订说明：v1的dev/test权限与攻击资料曾仅换编号跨split，另有自习室题目缺主语、部分独立检索表述缺实体。v2把dev权限资料改为财务核对/档案保管，把dev攻击资料改为饮水设施/花圃浇水及不同攻击payload；同一family统一group，test自习室补明确主体，q4独立query补来源实体。旧负结果完整保留于reports/v1。由于v1最终测试已运行，v2报告属于评审纠错后的重测，不声称完全未见测试；检索参数未改变。真实跨业务泛化仍需另外独立数据。

重排运行前校验六个固定快照文件SHA256（含1,112,206,140-byte safetensors）；报告模型ID/修订来自通过校验的已知快照常量，不接受配置文字冒充实际加载版本。RAG提示版本rag-extractive-v2保留retriever排序并从末尾丢弃超预算证据，避免按cosine重排撤销实验排名。

v2独立代理定点复审已通过，6项初审问题关闭；共20评测来源与另4训练来源逐条核对。review_status在报告前最后冻结，文字状态不代表人工审核。所有参数保留v1的0.65/Top5/20候选/RRF60，v1已见最终数据的限制继续保留。
