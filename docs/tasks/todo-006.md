# todo-006：文档上传、解析、切分与后台入库任务

| 字段 | 值 |
|---|---|
| id | todo-006 |
| 状态 | pending |
| depends_on | todo-005 |
| 并行可行性 | 可与独立部署工作并行；入库表、文档版本和 chunk 契约由本任务独占到合入 |
| 负责目录 | `backend/app/modules/ingestion/`、文档存储适配、`frontend/src/features/knowledge/documents/`、入库迁移 |

## 范围、文件与接口

按 [ARCHITECTURE](../ARCHITECTURE.md) 与 [CONTRACTS](../CONTRACTS.md)完成文本 PDF、DOCX、TXT、MD 上传、持久化任务、解析、切分、可重试状态和受控下载。采用 PostgreSQL 持久化任务与单独 worker，不仅使用进程内临时 BackgroundTasks。006 处理 `kind=parse`，候选版本解析为 `parsed` 并创建 `kind=index` 任务；007 处理 embedding/index 并激活有效版本。

- 创建 `backend/app/modules/ingestion/{models,schemas,router,service,worker,parsers,chunking,storage}.py` 与独立迁移。
- 创建 `backend/tests/ingestion/{test_uploads,test_parsers,test_worker,test_document_access}.py` 及固定小样本文档。
- 创建 `frontend/src/features/knowledge/documents/{DocumentList.vue,UploadDocument.vue,api.ts}`、相应组件测试及 `frontend/e2e/documents.spec.ts`。
- 消费 005 知识库权限/版本；产出知识库下 `/documents`、文档详情、任务状态、重试和下载契约，以及包含定位信息的 chunk 数据供 007 使用。
- 保存文件名用于展示，存储键由服务端生成；不能以用户路径直接读写磁盘。对原文件下载、解析文本与引用查看同样授权。

## 分步执行

- [ ] 核对依赖已合入，确认上传大小、允许类型、chunk 长度/重叠、任务重试和有效版本规则均有契约值。
- [ ] 先写四种格式解析、空/扫描 PDF、恶意文件名、重复上传与跨库下载测试；运行确认缺少目标行为而失败。
- [ ] 创建文档、版本、chunk、任务模型和迁移；任务 `kind=parse|index`，目标 document_id/faq_id 恰好一个存在、revision_id 可空。006 不切换 active_revision，旧有效版本继续服务。
- [ ] 实现上传校验和受控存储；拒绝不支持类型/超限/路径穿越，下载通过权限路由或有授权且有限时的机制，不暴露静态公共目录。
- [ ] 以 pypdf、python-docx 和标准文本读取实现解析；保留页码/段落或行号等来源定位。扫描件/空内容返回可理解错误，不误标为可检索。
- [ ] 实现确定性切分和仅领取 parse 的 worker；解析成功保存候选 revision 的无 embedding chunks，设 parsed 并创建 index queued 任务；重试不产生重复候选 chunk/任务，失败不破坏旧有效版本。
- [ ] 实现上传进度/任务状态/失败原因/重试页面；parsed 显示“解析完成，待建立索引”，不提前宣称 ready；上传/替换/停用/删除/重试同期写审计。
- [ ] 用强制中断、重复领取、重新启动 worker 验证恢复行为；核对删除或撤权后的文件、chunk 和下载访问策略。
- [ ] 执行集成与 E2E、评审权限和文件处理边界；记录真实结果并提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 上传固定 PDF/DOCX/TXT/MD 样本 | 提取期望中文文本；chunk 顺序、归属与来源定位可追溯 |
| 上传扫描 PDF、空文件或损坏 DOCX | 状态失败且原因明确，不产生可用内容/成功状态 |
| 重复提交或 parse worker 在写 chunk 后崩溃 | 重试后只有一组候选 chunk 和一个待索引任务，无永久处理中状态；006 不抢领 index 任务 |
| 上传名含 `../` 或绝对路径 | 文件只能落在配置存储根内，展示名不改变存储路径 |
| 无权限用户猜测下载 ID，或权限被撤销 | 文件内容、解析文本、任务详情均不可读取 |
| 替换文档只完成解析，尚未有 007 索引 | 新版本为 parsed、active_revision 不变；旧版继续有效，变更有脱敏审计 |

状态断言示例：令解析器在保存中途抛出异常，重启 worker 后重试同一任务；候选 revision 的 chunk 数等于首次正常解析基准数量，index queued 任务只创建一次，active_revision 保持旧值。

```powershell
# backend
uv run pytest tests/ingestion/test_uploads.py tests/ingestion/test_parsers.py tests/ingestion/test_worker.py tests/ingestion/test_document_access.py -q
uv run pytest
uv run ruff check .
uv run alembic upgrade head
# frontend
npm run test -- --run src/features/knowledge/documents
npm run lint
npm run typecheck
npm run build
npm run test:e2e -- e2e/documents.spec.ts
```

## 已知问题与外部阻塞

需用户提供有权使用的代表性资料及上传规模预期；基础范围不做 OCR。真实大文档耗时/内存要用实际文件测量。权限和崩溃恢复可在合成小文件上先验证。

## 工作记录与完成标准

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未实施；没有上传、解析、恢复或下载验证结果。
- 依 [WORKFLOW](../WORKFLOW.md) 完成评审与证据记录后到 `in_review`；合入权威 main 且检查通过后统一标记 `done`。
