# todo-006：文档上传、解析、切分与后台入库任务

| 字段 | 值 |
|---|---|
| id | todo-006 |
| 状态 | done |
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

- [x] 核对依赖已合入，确认上传大小、允许类型、chunk 长度/重叠、任务重试和有效版本规则均有契约值。
- [x] 先写四种格式解析、空/扫描 PDF、恶意文件名、重复上传与跨库下载测试；运行确认缺少目标行为而失败。
- [x] 创建文档、版本、chunk、任务模型和迁移；任务 `kind=parse|index`，目标 document_id/faq_id 恰好一个存在、revision_id 可空。006 不切换 active_revision，旧有效版本继续服务。
- [x] 实现上传校验和受控存储；拒绝不支持类型/超限/路径穿越，下载通过权限路由或有授权且有限时的机制，不暴露静态公共目录。
- [x] 以 pypdf、python-docx 和标准文本读取实现解析；保留页码/段落或行号等来源定位。扫描件/空内容返回可理解错误，不误标为可检索。
- [x] 实现确定性切分和仅领取 parse 的 worker；解析成功保存候选 revision 的无 embedding chunks，设 parsed 并创建 index queued 任务；重试不产生重复候选 chunk/任务，失败不破坏旧有效版本。
- [x] 实现上传进度/任务状态/失败原因/重试页面；parsed 显示“解析完成，待建立索引”，不提前宣称 ready；上传/替换/停用/删除/重试同期写审计。
- [x] 用强制中断、重复领取、重新启动 worker 验证恢复行为；核对删除或撤权后的文件、chunk 和下载访问策略。
- [x] 执行集成与 E2E、评审权限和文件处理边界；记录真实结果并提交 `in_review`，按 WORKFLOW 合并收尾。

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

- 2026-09-26 已按批次授权原子领取；负责人为当前 Codex 对话，独立 worktree `C:/Users/Administrator/.codex/worktrees/todo-006-ingestion/aiSoftwareAttempt`，分支 `feat/todo-006-ingestion`，基点 `69184f19e76ed1675c494669e28ce81c4254eca5`。
- 已完成上传、受控下载、四格式解析、原文切分、持久 parse worker 与管理页面；使用明确标注的虚构校园样例。本任务只产出 parsed 候选及 queued index 任务，索引与激活由 007 交付。
- 依 [WORKFLOW](../WORKFLOW.md) 完成评审与证据记录后到 `in_review`；合入权威 main 且检查通过后统一标记 `done`。

### 2026-09-26 本地验收与独立评审

- 环境：Windows，Node 24.11.0、Python 3.12.14、uv 0.12.17；独立 Compose project `qa-todo-006-02eeb8`，API/Web/DB 端口 8116/5216/15446。冻结依赖、独立数据库及本地上传目录；秘密和模型不入库。
- `node scripts/dev.mjs check`：退出 0；Ruff、迁移、前端 lint/typecheck/build 均通过，**223 pytest、48 Vitest、18 Playwright** 通过。浏览器用真实上传、真实 parse worker 和 BGE tokenizer 验证 parsed/待索引、受控下载、替换、停用与删除。原始日志 `.local/check-final.log`。
- 专项验证：四格式中文与定位、20 MiB 限制和重复 Content-Type、跨库访问、两数据库会话并发停用/删除、worker 强制终止后的租约恢复、重复领取、写 chunk 事务回滚、旧 active 保留、Windows 512 MiB 子进程内存限额；`alembic check` 无模型漂移。桌面和 390px 移动截图人工核验无溢出。
- BGE 使用 `BAAI/bge-small-zh-v1.5` 固定 revision `7999e1d3359715c523056ef9478215996d62a620`。官方模型为 **512 维**，已纠正架构/契约及 007 计划中的 384 维错误。真实 tokenizer 验证每段重新分词不超过 400 tokens；目标重叠 50 tokens，必要时回退至完整 WordPiece 词边界，实际重叠可略大于 50，保留原文。
- 独立评审发现并已通过先失败后成功的回归关闭：缓存 ORM 对象导致并发停用状态遗漏、重复请求头绕过上传预检、旧下载 401 清除新会话、零 token 文本误标解析成功。独立复核亲自运行 9 项后端回归与 4 项客户端测试，全部通过，无剩余阻塞；报告 `.local/ingestion-full-review.md`。
- 静态核验：`node --check scripts/dev.mjs`、`git diff --check` 与修改文档的本地链接检查通过。仅存在依赖弃用提示，无失败或跳过的验收项。
- 限制：未运行云端 CI（按 WORKFLOW 10.1）；未验证 OCR、客户真实大文档、生产负载或 POSIX 内存限制运行效果；本任务无需调用 DeepSeek。功能已合入权威 main，本状态记录通过独立文档 PR 收尾。

### 功能合并与状态收尾

- 功能 PR：[#13](https://github.com/cdzdd/aiServerAndModelTraining/pull/13)，2026-09-26T06:45:32Z 普通 squash 合并，真实功能合并 SHA `f9a5c8f8c892e6726f234fab8d643d979994b539`。
- 已验证功能提交 `6ef98cf473c44cba128ce591e7c942b991d7c9c5`；合并后完整树与该提交一致。上述统一检查和独立评审适用，云端 CI 未运行。
- 收尾分支 `docs/todo-006-close` 仅更新本任务状态与合并证据；`git diff --check`、Markdown 本地链接与合并事实核验通过，不重复运行应用测试。本状态 PR 合入后权威 main 上任务为 done。
