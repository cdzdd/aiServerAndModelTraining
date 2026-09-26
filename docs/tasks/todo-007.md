# todo-007：本地向量化与有权限的语义检索

| 字段 | 值 |
|---|---|
| id | todo-007 |
| 状态 | pending |
| depends_on | todo-006 |
| 并行可行性 | 本任务拥有 embedding 与检索 schema；008/013 在本任务合入后消费或扩展 |
| 负责目录 | `backend/app/modules/retrieval/`、向量迁移、入库索引衔接与检索测试 |

## 范围、文件与接口

依据 [CONTRACTS](../CONTRACTS.md)建立 SentenceTransformers `BAAI/bge-small-zh-v1.5` embedding、PostgreSQL pgvector 存储、相似度检索、阈值/Top-K 与来源元数据。首版采用向量检索；混合检索和可选重排属于 013。

- 创建 `backend/app/modules/retrieval/{embedding,indexing,repository,service,schemas}.py` 和向量迁移。
- 创建 `backend/tests/retrieval/{test_indexing,test_semantic_search,test_access_filter,test_embedding_contract}.py`。
- 消费 006 候选 revision 的无 embedding chunk、`kind=index` 任务和 005 待索引 FAQ/知识库权限；产出有效索引和 CONTRACTS 约定的检索结果，包含稳定来源 ID、版本、文本、得分、定位与知识库归属。
- 索引记录 embedding 模型标识、版本/修订与维度；更换模型必须重建，不能把不同向量空间混用。
- 权限条件在查询候选集时生效，不先全库取结果再只在前端过滤；文档删除、FAQ 停用、撤权立即影响可见结果。

## 分步执行

- [ ] 核对 006 有效版本与 chunk 契约；采用 bge-small-zh-v1.5 的 512 维向量，冻结模型修订、归一化/查询前缀规则、默认 Top-K 5 与阈值，并写入可追溯配置。
- [ ] 先写索引幂等、向量维度不匹配、检索排名、撤权/停用过滤测试；用固定向量 fixture 先运行并确认目标行为失败。
- [ ] 创建向量列、所需索引与模型元数据迁移；数据量很小时先保证正确性，索引优化依据真实检索计划与规模。
- [ ] 实现本地 embedding 加载、批处理及失败映射；CI 默认固定向量或小测试替身，真实模型 smoke 另行记录。
- [ ] 增加只处理 index 的 handler，为候选 revision 全量生成 embedding，全部成功后在事务中切 active_revision_id 并设 ready；失败保持旧版有效。FAQ 索引捕获 version、提交前复核未变更才设 indexed_version，否则重新排队，停用立即排除。
- [ ] 实现服务端授权候选集、向量检索、Top-K/阈值与稳定来源结果；文档排除 disabled/deleted 后按 active_revision 查询，即使新候选 parsed/failed 也不屏蔽旧有效版；FAQ 仅 indexed_version=version 可检索。
- [ ] 验证撤权、删除、版本更新和模型版本不匹配；用真实 bge 模型对小型中文知识集完成检索 smoke，记录质量与耗时。
- [ ] 执行相关测试、迁移与静态检查；独立评审查询过滤位置和来源可追溯性，记录并提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 固定问题查询固定向量库 | 返回预期排序和不超过 Top-K 的结果，低于阈值为空 |
| A/B 知识库拥有相同高相似文本但用户仅有 A 权限 | 检索、引用候选与调试输出均不出现 B 内容 |
| 对同一候选版本重复运行索引 | 向量数量不翻倍，来源 ID 稳定；完成后才原子切为 active revision/ready |
| 撤权、文档删除、FAQ 停用或新版本切换 | 已撤权/删除/停用内容不可检索；文档新候选 parsed/failed 时旧 active 仍可用，切换后旧版排除；FAQ 版本不一致不可检索 |
| 配置模型维度/修订不同于已有索引 | 明确阻止混用并提示重建，不返回无意义相似度 |

```powershell
# backend
uv run pytest tests/retrieval/test_indexing.py tests/retrieval/test_semantic_search.py tests/retrieval/test_access_filter.py tests/retrieval/test_embedding_contract.py -q
uv run pytest
uv run ruff check .
uv run alembic upgrade head
uv run alembic heads
```

真实模型 smoke 记录模型来源/修订、数据样本、查询、Top-K 与耗时；不得将固定向量测试称为真实模型质量验证。

## 已知问题与外部阻塞

首次模型下载需要网络与磁盘空间；CPU 可用于功能验证，GPU 不是基础检索前提。用户需提供代表性问题评估阈值；没有真实语料时默认值只能标为初始设置，013 会做量化校准。

## 工作记录与完成标准

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未建立向量、未下载模型、未执行测试。
- 按 [WORKFLOW](../WORKFLOW.md) 记录固定向量与真实模型两类证据；任务分支至 `in_review`，合入权威 main 且检查通过后统一置 `done`。
