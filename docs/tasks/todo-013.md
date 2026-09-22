# todo-013：固定评测、混合检索与可选重排

| 字段 | 值 |
|---|---|
| id | todo-013 |
| 状态 | pending |
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

- [ ] 核对 008 已合入，建立评测样本字段：问题、允许知识库、参考来源/答案、是否应拒答、多轮历史、标签；至少覆盖正常、无答案、多轮、权限、恶意资料五类。
- [ ] 先写 Recall@K/MRR/引用正确性/拒答指标的手算样例测试及跨库泄露检测，运行确认目标评测实现失败。
- [ ] 收集并人工审核最少 50 条代表性问题（建议 35 条可回答、10 条无答案、5 条权限/攻击），固定开发/测试划分、样本 ID 和版本哈希；不足时明确样本不足，不能夸大泛化能力。
- [ ] 实现评测运行器，记录数据/代码/模型/提示词版本、检索配置、随机性、延迟、token 与错误；先运行纯向量基线并保存原始逐条结果。
- [ ] 实现适合中文的最小词法检索与候选融合；记录分词/索引选择依据，不默认 PostgreSQL 英文分词器能满足中文。所有候选生成先限定权限。
- [ ] 在相同评测集和生成模型下运行向量与混合检索对照，比较 Recall@5、MRR、引用正确、拒答和 p50/p95 延迟；用开发集调权重，固定后再看测试集。
- [ ] 增加可关闭重排器并运行对照，记录模型许可、资源消耗和超时回退；未改善质量或资源预算超限时保持关闭并解释。
- [ ] 写真实结果报告与默认方案决定；建议发布门槛为权限泄露 0、有效引用映射 100%、测试集 Recall@5 不低于基线、拒答错误不回退，业务质量门槛由用户结合样本确认。
- [ ] 执行指标/检索测试与独立评审，确认没有数据泄漏或混淆 score；提交 `in_review`，按 WORKFLOW 合并收尾。

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

以上配置和入口均在本任务实现，当前没有报告。真实模型评测需预算许可；报告必须区分固定检索测试与真实生成质量。

## 已知问题与外部阻塞

需要有权使用的真实问题/参考答案、人工复核和模型调用预算。门槛中的质量水平不能在没有代表性数据时武断承诺；017 发布前必须基于真实报告接受或处理残余问题。重排模型下载和资源上限需实际验证。

## 工作记录与完成标准

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未采集数据、未运行评测、无质量提升声明。
- 按 [WORKFLOW](../WORKFLOW.md) 交付版本化数据说明、逐条结果、对照结论与评审；分支 `in_review`，合入权威 main 且检查通过后统一 `done`。
