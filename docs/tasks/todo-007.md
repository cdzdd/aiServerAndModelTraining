# todo-007：本地向量化与有权限的语义检索

| 字段 | 值 |
|---|---|
| id | todo-007 |
| 状态 | done |
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

- [x] 核对 006 有效版本与 chunk 契约；采用 bge-small-zh-v1.5 的 512 维向量，冻结模型修订、归一化/查询前缀规则、默认 Top-K 5 与阈值，并写入可追溯配置。
- [x] 先写索引幂等、向量维度不匹配、检索排名、撤权/停用过滤测试；用固定向量 fixture 先运行并确认目标行为失败。
- [x] 创建向量列、所需索引与模型元数据迁移；数据量很小时先保证正确性，索引优化依据真实检索计划与规模。
- [x] 实现本地 embedding 加载、批处理及失败映射；CI 默认固定向量或小测试替身，真实模型 smoke 另行记录。
- [x] 增加只处理 index 的 handler，为候选 revision 全量生成 embedding，全部成功后在事务中切 active_revision_id 并设 ready；失败保持旧版有效。FAQ 索引捕获 version、提交前复核未变更才设 indexed_version，否则重新排队，停用立即排除。
- [x] 实现服务端授权候选集、向量检索、Top-K/阈值与稳定来源结果；文档排除 disabled/deleted 后按 active_revision 查询，即使新候选 parsed/failed 也不屏蔽旧有效版；FAQ 仅 indexed_version=version 可检索。
- [x] 验证撤权、删除、版本更新和模型版本不匹配；用真实 bge 模型对小型中文知识集完成检索 smoke，记录质量与耗时。
- [x] 执行相关测试、迁移与静态检查；独立评审查询过滤位置和来源可追溯性，记录并提交 `in_review`，按 WORKFLOW 合并收尾。

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

- 2026-09-26 已按用户七任务批次授权原子领取；分支 `feat/todo-007-retrieval`，独立 worktree `C:/Users/Administrator/.codex/worktrees/todo-007-retrieval/aiSoftwareAttempt`；依赖 006 已由 PR #13/#14 合入，基点 `69f888d61b4254161824721aab283055df608195`。
- 模型已下载并校验固定 revision，SentenceTransformers CPU 预检真实输出 512 维；业务索引与权限检索已完成，实际证据见下。初始阈值 0.65 待真实语料校准；查询加官方中文前缀，文档无前缀，全部向量 L2 归一化。
- 按 [WORKFLOW](../WORKFLOW.md) 记录固定向量与真实模型两类证据；任务分支至 `in_review`，合入权威 main 且检查通过后统一置 `done`。

### 2026-09-26 实现、验收与独立评审

- 固定 `BAAI/bge-small-zh-v1.5` revision `7999e1d3359715c523056ef9478215996d62a620`，本地 CPU、512 维、L2 归一化；加载前核验影响模型/分词/池化的文件 SHA-256。查询加官方中文前缀、资料不加；空/零 token 及超过 512 token 输入明确拒绝，禁止静默截断。
- 实现 pgvector 精确检索；权限、启停、请求知识库范围、文档 active revision 与 FAQ indexed_version 在候选 SQL 生效。模型元数据不匹配拒绝检索；新候选解析/失败不遮蔽旧 active。SearchHit 保留稳定 ID、版本与页/段/行定位。
- index worker 独立领取、批次续租与令牌隔离，全部向量与有效版本在同一事务发布。FAQ 新增/编辑事务内排队，迁移回填已有 FAQ，恢复知识库补排；文档重建保留 chunk ID，失败不写部分向量。页面轮询索引完成并区分解析/索引重试。
- 环境：Windows、Node 24.11.0、Python 3.12.14、uv 0.12.17；SentenceTransformers 5.2.0 / Transformers 4.57.6 / torch 2.9.1+cpu / pgvector 0.4.2。隔离项目 `qa-todo-007-02eeb8`，端口 API/Web/DB 为 8117/5217/15447。
- 最终 `node scripts/dev.mjs check` 退出 0：**288 pytest、50 Vitest、18 Playwright** 全部通过，无跳过；Ruff、两次迁移、前端 lint/typecheck/build 均通过。日志 `.local/check-final.log`。`uv pip check --python backend/.venv/Scripts/python.exe` 通过，`alembic check` 无漂移，`alembic heads` 唯一为 007；脚本语法与 diff 静态检查通过。
- 行为测试先失败再成功；覆盖向量排序、SQL 权限优先于 Top-K、编码期间撤权、文档/FAQ 版本与停用、维度/非有限值/模型修订错误、重复索引、第二批失败、写入回滚、旧租约隔离与实际终止子进程后的恢复。
- 显式真实模型检查 `uv run --frozen --directory backend pytest tests/retrieval/smoke_real_model.py -q -s`：1 passed；真实上传两份中文 TXT 加一条 FAQ，经实际 parse 子进程、BGE 编码、pgvector 写入、权限检索及撤权验证，3 项索引完成。来源定位与版本均来自实际记录；结果 `.local/real-retrieval-smoke.json`。
- 虚构校园问题：图书馆/食堂/补卡 Top-1 得分约 0.660/0.777/0.815 且命中预期来源；无关热水器问题最高 0.264，返回空。0.75 初始候选阈值漏掉图书馆问题，调整为 **0.65** 后全部通过。模型加载约 4.58 秒，3 项索引约 0.19 秒，热查询约 21–30 毫秒；仅小样例功能测量，不是代表性质量/吞吐基准。
- 独立评审发现 P2：文档停用期间索引取消，恢复后未呈现重试入口。修复为优先保留失败状态和有效版本指针；无旧版/旧 active/当前版本重建三类回归先 3 failed，修后通过。独立复核亲自运行 4 项恢复测试通过、无剩余阻塞，报告 `.local/retrieval-full-review.md` 含受审文件哈希。
- 限制：阈值尚未用用户代表性语料校准；精确查询未做大规模性能验收；本任务未调用 DeepSeek，无生产部署。云端 CI 未运行，按 WORKFLOW 10.1 保留真实本地证据和普通 PR 合并。

### 功能合并与状态收尾

- 功能 PR [#15](https://github.com/cdzdd/aiServerAndModelTraining/pull/15) 于 `2026-09-26T07:00:08Z` 实际 MERGED，普通 squash 合并 SHA `bc6b4debea33bb47ac39ee3b9fef0b3ddb8def76`。
- 已验证提交 `3c28307a26a7cf9f2ee5899a987aed0236742cc9`，功能合并完整树与该提交一致。上述最终统一检查、真实 BGE smoke 和独立评审适用；云端 CI 未运行。
- 本状态分支 `docs/todo-007-close` 仅修改本任务，核对 diff、Markdown 链接及 GitHub 实际合并事实；无代码变更，不重复应用测试。本状态 PR 实际合入后权威 main 上任务为 done。
