# todo-013：固定评测、混合检索与可选重排

| 字段 | 值 |
|---|---|
| id | todo-013 |
| 状态 | done |
| depends_on | todo-008 |
| 并行可行性 | 可与 009、014 并行；本任务独占检索算法改动，其他任务保持既有 search 接口 |
| 负责目录 | `experiments/evaluation/`、`backend/app/modules/retrieval/` 的混合检索/重排、评测测试 |

## 范围、文件与接口

以 [ARCHITECTURE](../ARCHITECTURE.md)和 [CONTRACTS](../CONTRACTS.md)为依据，用固定中文评测集建立纯向量基线，增加词法与向量混合检索，并用独立开关评估可选重排。只有证据显示满足门槛才切换默认配置；“可选重排”允许报告证明不适合后保持关闭。

- 创建 `experiments/evaluation/{README.md,dataset.schema.json,run_eval.py,metrics.py,configs/}`；受版权/隐私限制的数据放忽略目录，仓库保留合成样例与清单/哈希。
- 创建 `backend/app/modules/retrieval/{lexical,hybrid,reranker}.py`，仅在方案确需时新增依赖/索引迁移。
- 创建 `backend/tests/retrieval/test_hybrid_search.py`、`test_rerank_access.py`、`experiments/evaluation/tests/test_metrics.py`；输出真实运行报告到 `experiments/evaluation/reports/`。
- 消费 `search(actor,kb_ids,query,top_k)` 和 `stream_answer(actor,kb_ids,question,history)`；检索输出保持 SearchHit 形状，若 score 含义改变同步更新契约、阈值与评测。
- 不把质量分数写成“正确率”却混用不同分母；不得用测试集答案挑选提示词后仍称其完全未见测试。

## 分步执行

- [x] 核对 008 已合入，建立评测样本字段：问题、允许知识库、参考来源/答案、是否应拒答、多轮历史、标签；至少覆盖正常、无答案、多轮、权限、恶意资料五类。
- [x] 先写 Recall@K/MRR/引用正确性/拒答指标的手算样例测试及跨库泄露检测，运行确认目标评测实现失败。
- [x] 收集并人工审核最少 50 条代表性问题（建议 35 条可回答、10 条无答案、5 条权限/攻击），固定开发/测试划分、样本 ID 和版本哈希；不足时明确样本不足，不能夸大泛化能力。
- [x] 实现评测运行器，记录数据/代码/模型/提示词版本、检索配置、随机性、延迟、token 与错误；先运行纯向量基线并保存原始逐条结果。
- [x] 实现适合中文的最小词法检索与候选融合；记录分词/索引选择依据，不默认 PostgreSQL 英文分词器能满足中文。所有候选生成先限定权限。
- [x] 在相同评测集和生成模型下运行向量与混合检索对照，比较 Recall@5、MRR、引用正确、拒答和 p50/p95 延迟；用开发集调权重，固定后再看测试集。
- [x] 增加可关闭重排器并运行对照，记录模型许可、资源消耗和超时回退；未改善质量或资源预算超限时保持关闭并解释。
- [x] 写真实结果报告与默认方案决定；建议发布门槛为权限泄露 0、有效引用映射 100%、测试集 Recall@5 不低于基线、拒答错误不回退，业务质量门槛由用户结合样本确认。
- [x] 执行指标/检索测试与独立评审，确认没有数据泄漏或混淆 score；提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 手工构造的排名列表 | Recall@K、MRR 与手算值相同，空参考/空结果按明确定义处理 |
| 同一固定数据和配置重跑 | 样本顺序/ID与检索结果可复核；生成随机差异独立记录 |
| 中文专有名词/编号查询 | 词法路线能产生预期候选，融合后不丢掉权限过滤 |
| 未授权库有高度相关答案 | 向量、词法、融合、重排和报告均不泄露该内容 |
| 重排模型不可用或超时 | 按配置回退到已授权混合候选，记录降级，不挂死请求 |

```powershell
# backend；以下脚本由本任务创建
uv run pytest tests/retrieval/test_hybrid_search.py tests/retrieval/test_rerank_access.py -q
uv run pytest ../experiments/evaluation/tests/test_metrics.py -q
uv run python ../experiments/evaluation/run_eval.py --config ../experiments/evaluation/configs/baseline.yaml
uv run python ../experiments/evaluation/run_eval.py --config ../experiments/evaluation/configs/hybrid.yaml
uv run python ../experiments/evaluation/run_eval.py --config ../experiments/evaluation/configs/rerank.yaml
uv run ruff check . ../experiments/evaluation
```

以上配置和入口均已在本任务实现；用户授权的本地真实模型检索与生成报告见experiments/evaluation/reports。报告区分固定检索与完整RAG质量，未调用付费云模型。

## 已知问题与外部阻塞

需要有权使用的真实问题/参考答案、人工复核和模型调用预算。门槛中的质量水平不能在没有代表性数据时武断承诺；017 发布前必须基于真实报告接受或处理残余问题。重排模型下载和资源上限需实际验证。

## 工作记录与完成标准

- 负责人implement_013（root协调）；工作与评审已完成，功能及状态收尾按本地验收 + GitHub PR流程合入main。
- 本轮已交付用户授权的60题虚构教学数据、真实检索与完整RAG逐题报告；没有质量提升或人工业务验收声明。
- 按 [WORKFLOW](../WORKFLOW.md) 交付版本化数据说明、逐条结果、对照结论与评审；分支 `in_review`，合入权威 main 且检查通过后统一 `done`。

## 2026-10-01 本轮教学范围与实施记录

- 用户明确授权先使用原创、明确虚构的校园教学资料和至少50个评测问题，由独立代理复核；真实业务资料收集、人工审核与生产质量验收仍留到正式发布前。此范围调整不把自动审核冒充人工验收。
- 分支 `feat/todo-013-evaluation`，独立worktree `todo-013-evaluation`，基线 `0f5832279978983c959deff434990ca1b7ec7c9f`；API8143/Web5243/DB15473，独立qa_test随机schema，冻结uv/npm依赖。
- 实施：60题固定教学评测（18开发/42最终测试），20来源带sha256；dev/test按来源组隔离，另4主题/8条训练格式样例供015独立扩展。禁止从最终评测规则改写训练样本。
- 先观察手算指标、混合/权限、重排降级、运行器DB/引用/索引集成行为RED，再最小实现；已有真实PostgreSQL/pgvector检索套件101通过，评测测试7通过（包括上游错误不算正确拒答）。依赖第三方Starlette存在已记录DeprecationWarning。
- 中文bigram/完整ASCII编号词法在SQL完整权限/有效版本/元数据/余弦阈值之后排序；RRF仅改顺序、SearchHit.score保留真实余弦。默认vector/重排关闭。CrossEncoder本地CPU开关、单worker超时/busy/不可用回退、重排前后复验；不自动下载模型。
- 真实BGE开发基线/混合18题报告已跑：14可答题Recall@5/MRR=0.50，两模式无提升，各0泄露/错误；现有0.65阈值与RRF配置冻结，不用最终测试调参。纯检索的生成质量列为null。
- 最终检索、真实Ollama生成、重排模型对照、完整统一检查与独立代码/逐题评审待记录。共享.env.example/CONTRACTS/dev检查入口由root串行整合，未直接修改。仍in_review，尚无PR/合并SHA，不宣称main完成。

独立评审纠错：v2资料和standalone query修订详见evaluation README；保留reports/v1，明确v1最终测试已见、v2为纠错重测且不调参数。三项评测/完整模型元信息P2及RAG排序问题已逐项RED→GREEN；评测9、重排4、RAG128专项通过。首次完整check在da0573e通过（backend680/frontend114/E2E18+4+1），评审修订后还要重跑完整check。RAG prompts.py及对应预算测试为root明确扩展的最小授权范围。

- v2独立代理复审通过，初审6项问题关闭。20评测来源和4训练来源hash/划分核对无数字替换近重复跨split；仍非人工业务验收。review_status在报告前冻结；接下来重跑v2全部模式。

- v2真实CPU检索6份均已运行：dev14参考题Recall@5/MRR=10/14；test31参考题=21/31，vector/hybrid/CrossEncoder三模式一致，各0泄露/0错误。真重排dev10/test21题applied，无降级；test p95分别26.12/38.70/82.29ms，进程峰值约522/532/1139MiB。默认保持vector、重排关闭，不能宣称质量提升或生产SLA。
- 真实生成仍待014先走PR合入main后同步provider；本worktree生成配置模板在忽略目录，不含密钥，需root填写真实已验证tag再运行。纯检索报告的引用/拒答质量为null。
- root授权串行整合共享.env.example/CONTRACTS/scriptsdev到本分支，提交8d23104；统一check现包含评测9项与外目录Ruff，当前完整重跑中。

- 最终统一验收 `node scripts/dev.mjs check` 已实际exit0（8d23104对应实现）：backend681、评测9、frontend114、E2E18+4+1；Ruff/ESLint/typecheck/build、两次Alembic upgrade完成。完整输出保留该worktree忽略目录的unified-check-final.log。检查后仅报告/文档追加，真实生成仍待014，状态保持in_review，不宣称已合并或生成质量已过。


## 2026-10-01 014集成后的完整RAG验收

- 014功能PR27与状态PR28已合入origin/main b6b5f9c2dd18536f77cacf6d70961586e6205d16；root同步本分支至c0d19f0cc9baaaae79abc8cacbf115c313839e1e。此为013六份真实生成报告的执行源码提交，不是013已合入main。
- 在本worktree真实Ollama qwen3:4b-instruct-2507-q4_K_M（8192上下文、512输出、不发送think、temperature=0）串行运行dev/test × baseline/hybrid/rerank --generate，六份均exit0；BGE与真实CrossEncoder仍CPU。报告与事后运行身份旁证已版本化，资料和参数未改。
- 三模式均dev回答6/14、误拒答8；test回答12/31、误拒答19。各0权限泄露/0上游错误/0应拒答误答/0恶意短语匹配；dev6/test12个实际引用来源精确率及原文映射1.0，不代表全部问题正确或无幻觉。纯检索test缺10/31参考题；完整RAG实际搜索16/31无候选，另1clarify、2生成/引用校验拒答。完整结果见evaluation/reports/decision.md，默认vector与关闭重排保留。
- 首次合入014后统一check因provider测试fixture继承外部8192上下文失败：737通过/1失败，原日志保留.local/unified-check-after-014.log。4096进程覆盖下完整check exit0仅用于诊断，不作为解决方案。随后目标测试在8192环境复现RED；root授权仅fixture默认ollama_num_ctx=4096及model_disable_thinking=false两行，生产provider/真实报告不改。外部8192/thinking=true下providers105通过，backend目录Ruff通过；修复提交0a341005c1bd9019004d88326bdddd0936304d7d。
- 修复后在0a341005c1bd9019004d88326bdddd0936304d7d对应实现使用实际.env8192、仅该check进程MODEL_PROVIDER=mock重跑完整node scripts/dev.mjs check，实际exit0：backend738、评测9、frontend114、E2E18+4+1；Ruff/ESLint/typecheck/build与重复迁移检查完成。完整原始输出保留.local/unified-check-after-014-fixture-fixed.log。六份真实生成在独立进程使用ollama，未用mock冒充效果。
- 独立代理已复算12份v2报告360行/54引用无不一致，最终文案、数值和两行fixture定点复核均已通过。正式发布前真实业务资料与人工审核仍未完成；本轮教学交付依用户范围调整接受代理复核，不声称替代人工验收。013仍in_review，由root继续普通PR/合并/状态收尾。

## 功能合并与收尾

- 2026-10-01，功能 [PR29](https://github.com/cdzdd/aiServerAndModelTraining/pull/29) 已实际MERGED，功能合并SHA `92ca52b63fd7522ccaec578e4f949dcd5e7433ff`，功能分支 `feat/todo-013-evaluation`，PR头 `88ef31d878f040c4f9bee8409a6dee2144898139`。
- 代码验收对应 `0a341005c1bd9019004d88326bdddd0936304d7d`，后续只有报告/文档；最终完整check及真实模型证据见上节。独立复核通过，云端CI未运行，合并前实际核对main无强制保护/ruleset，未绕过规则。
- 本次checked材料审核步骤按用户授权调整为60题原创虚构教学资料与独立代理复核；真实业务材料、人工审核和生产质量接受仍为上线前待办，不是本任务已执行的人工验收。
- 本纯文档收尾只更新本任务状态/勾选及真实合并信息；状态PR合入后权威main为done，不再创建记录自身的PR。历史in_review/待真实生成记录保留为执行轨迹，以最后验收与本节为当前事实。