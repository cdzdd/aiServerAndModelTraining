# 并行开发的接口与数据契约

本文件规定第一版模块边界。它是待实现契约，不是现有 API 文档；todo-001 起由 FastAPI OpenAPI 与自动化测试核对。若具体接口需要改变，应先协调受影响任务，在同一 PR 更新本文件、调用方和验收。

## 1. 全局约定

- API 前缀 `/api/v1`；健康检查 `/health/live` 返回200 `{"status":"ok"}`；`/health/ready` 验证数据库可达后返回200 `{"status":"ready"}`，不可达则503且不暴露连接信息。前端与 API 同源，开发由 Vite 转发。
- 主键 UUID；时间使用有时区的 UTC，JSON 为 ISO 8601；页面按用户本地时区显示。
- 请求/响应字段 snake_case；分页 `page` 从 1 开始，`page_size` 默认 20、最大 100；列表 `{items: [], total: 0, page: 1, page_size: 20}`。
- 标准错误 `{error: {code: "FORBIDDEN", message: "没有访问权限", request_id: "..."}}`；输入校验补充 `details`，不返回内部异常堆栈。401 未登录；403 操作不允许；404 资源不存在或不可见；409 状态冲突；413 超限；422 输入错误；429 限流；503 外部依赖暂不可用。
- `X-Request-ID` 由后端生成/校验并贯穿日志。角色由服务器会话读取，不信任请求中的 role/user_id。
- `.env.example` 仅变量名和无效示例。数据库密码、模型 Key、会话秘密不得进入响应、日志、Git 或前端构建变量。

## 2. 身份认证（todo-002）

用户字段：`id, username, display_name, role, is_active, created_at`。角色枚举 `user|agent|admin`；注册只创建 user。密码 Argon2id 哈希，username 3–50 字符、password 12–128 字符；具体中文提示写入前后端测试。

使用服务端存储的随机登录会话，Cookie `qa_session` 为 HttpOnly、SameSite=Lax，正式 HTTPS 环境为 Secure。数据库仅存会话令牌哈希。登录/退出轮换或撤销会话，停用用户使旧会话不可再用。

初始登录会话有效期24小时，不做自动续期。登录限流按“来源IP+标准化用户名”5次失败/5分钟、来源IP总尝试30次/5分钟，超限429；测试使用可控时钟验证窗口恢复，错误消息不暴露账号是否存在。可信代理地址仅由部署配置指定，不能任意相信客户端X-Forwarded-For。第一版限流可在单API进程内使用有界、定期清理的内存计数器；重启会重置登录计数，这个基础版本边界需记录，不能宣称分布式限流。

| 方法/路径 | 输入或结果 |
| --- | --- |
| GET `/auth/csrf` | 返回 `{csrf_token}`，绑定当前或短期预登录会话；所有写请求带 `X-CSRF-Token` |
| POST `/auth/register` | `{username, password, display_name}` → 201，用户摘要；不接受角色指定 |
| POST `/auth/login` | `{username,password}` → 200 `{user,csrf_token}`，设置新登录 Cookie |
| POST `/auth/logout` | 撤销当前会话，清理 Cookie → 204 |
| GET `/auth/me` | 当前用户摘要；未登录 401 |
| GET `/admin/users` | 管理员分页列表 |
| PATCH `/admin/users/{id}` | 管理员修改 display_name、role、is_active；防止停用最后一个有效管理员 |

前端 `features/auth/` 提供唯一会话状态与请求封装，权限恢复通过 `/auth/me`。不把凭据放到 localStorage。前端 todo-003 可以用这份契约的 Mock 开发，正式验收连真实接口。

首次管理员由todo-002提供 `uv run python -m app.modules.auth.bootstrap_admin`，在backend目录交互输入用户名和两次隐藏密码；无默认管理员/默认密码，不从命令行参数接收明文密码。只有当前没有有效管理员时允许引导，重复执行报告已初始化。账号列表、角色与启停API由002实现，用户管理页面由003按契约实现；真实联调归016。测试环境使用专属fixture，不调用生产引导。


### 002 已实现接入细则

认证实现与调用示例见 [auth/README](../backend/app/modules/auth/README.md)。
username 经 NFKC、trim、casefold 后校验 3–50 字符；display_name 去首尾空格后 1–100 字符。PATCH 只接受非空的 display_name/role/is_active 子集，不接受 null、字符串布尔值和其他字段。
错误 details 沿用 `[{location: [...], code: "..."}]`，不回显输入。错误码包括 INVALID_CREDENTIALS、UNAUTHENTICATED、CSRF_FAILED、FORBIDDEN、NOT_FOUND、CONFLICT、RATE_LIMITED；前端同时按 HTTP 状态处理。

所有状态改变的 API 请求（含注册、登录、退出、multipart、后续 SSE POST）要求 Cookie、X-CSRF-Token 和同源 Origin/Referer。预登录 Cookie qa_prelogin 有效 10 分钟；登录成功改用 qa_session 并返回新 csrf_token。生产必须配置 HTTPS PUBLIC_ORIGIN，SESSION_SECRET 至少 32 字符；开发默认使用请求 origin。敏感响应设置 Cache-Control: no-store。
LOGIN_ACCOUNT_LIMIT=5、LOGIN_IP_LIMIT=30、LOGIN_WINDOW_SECONDS=300、LOGIN_MAX_ENTRIES=10000 可配置；并发请求预占账户失败额度，容量耗尽拒绝新请求且不驱逐有效限制。第一版仅单进程；应用不读取 X-Forwarded-For，部署 ASGI 代理信任必须显式限定地址。

内部接口：`service.current_user` 提供 User，`service.current_actor` 提供 schemas.Actor（FastAPI Depends）；`permissions.require_roles(actor, *roles)` 不通过返回 403；`require_conversation_access(actor, *, owner_id, assigned_agent_id)` 和 `require_knowledge_access(actor, *, visibility, is_member, is_active)` 不通过返回 404。资源字段/成员资格须由数据库获得，调用方负责不存在对象的相同 404 和列表过滤。停用知识库对所有角色不可读；具体业务写操作仍由对应模块校验角色与状态。

## 3. 知识与文件（todo-005/006）

KnowledgeBase：`id,name,description,visibility,is_active,version`；visibility=`public|restricted`。成员由独立关联表维护，version用于管理员修改冲突检测。FAQ：`id,kb_id,question,answer,is_active,version,indexed_version,updated_at`；编辑递增version，仅indexed_version=version的片段可用于检索，停用立即排除。

Document：`id,kb_id,filename,status,active_revision_id,created_at`。status=`uploaded|processing|parsed|ready|failed|disabled|deleted`；parsed明确表示候选版本解析完成、待索引，该候选不能用于问答。DocumentRevision：`id,document_id,content_sha256,parser_version,created_at`。原始文件路径仅服务端可见。

| 方法/路径 | 行为 |
| --- | --- |
| GET `/knowledge-bases` | 只列当前用户可读且有效的知识库 |
| POST/PATCH `/knowledge-bases[/{id}]` | 管理员创建/修改知识库（实际为两个不同路由） |
| PUT `/knowledge-bases/{id}/members` | 管理员设置成员 `{user_ids:[UUID],expected_version:int}`；版本不符返回409，成功递增version |
| GET/POST `/knowledge-bases/{id}/faqs` | 可读列表/管理员新增 |
| PATCH/DELETE `/faqs/{id}` | 管理员更新/停用，触发对应索引失效/更新 |
| GET/POST `/knowledge-bases/{id}/documents` | 可读文档列表/管理员 multipart 上传一个 file |
| POST `/documents/{id}/revisions` | 上传替换版本，旧有效版本保留至新索引成功 |
| GET `/documents/{id}` | 文档摘要及最近入库任务状态 |
| PATCH `/documents/{id}` | 管理员启用/停用；不直接写 ready |
| DELETE `/documents/{id}` | 软删除并立即从检索和下载排除 |
| GET `/documents/{id}/download` | 每次鉴权后返回允许的原文件 |
| POST `/documents/{id}/reindex` | 管理员重试/重建，返回 202 `{job_id}`，避免并发重复任务 |

上传响应 202 `{document_id,job_id,status:"uploaded"}`。FAQ 未建好索引仍可在后台维护，但不能误报可检索。

### 005 已实现接入细则

详见 [knowledge/README](../backend/app/modules/knowledge/README.md)。新增 GET `/knowledge-bases/{id}` 返回可读且启用的知识库摘要；GET `/knowledge-bases/{id}/members` 仅管理员可用，返回 `{user_ids,version}`。GET `/admin/knowledge-bases` 为管理员分页列出所有知识库元信息（含停用），用于恢复；普通列表和详情仍对所有角色排除停用库。

POST 知识库接受 `{name,description?,visibility?}`（默认 restricted），POST FAQ 接受 `{question,answer,is_active?}`（默认 true），返回 201 摘要。PATCH 知识库/FAQ 必须带 `expected_version` 和非空修改字段子集，版本不符 409；成功递增 version。知识库 name 1–100、description 0–2000，FAQ question 1–500、answer 1–10000 字符，文本去首尾空白并拒绝无效 Unicode/NUL。额外字段、null 修改值和非严格布尔值返回 422。成员最多 1000 个不同且存在的用户 UUID。

FAQ 列表按全局格式分页；user/agent 仅见启用项，管理员可见同库停用项。DELETE FAQ 返回 204 并软停用，重复停用无额外版本变更；PATCH 可重新启用。知识库通过 PATCH is_active 停用/恢复，无物理删除接口。停用知识库后所有角色的普通详情/FAQ 请求返回 404。所有知识接口返回 no-store。

内部查询 `readable_knowledge_bases(actor)` 和 `effective_faqs(actor,kb_ids)` 位于 knowledge.service，返回 SQLAlchemy SELECT。后者严格执行当前知识库权限、启用状态及 FAQ 版本一致条件，空范围为空结果；007 仍须联接真实且匹配版本的 Chunk。FAQ 初始 indexed_version=null，005 不伪造索引完成。

IngestionJob：`id,kind,document_id?,faq_id?,revision_id?,state,attempts,lease_until,error_code,created_at,finished_at`。kind=`parse|index`，document_id/faq_id恰好一个存在，parse只用于文档。state=`queued|running|succeeded|failed`。领任务必须原子；失败码区分超限、格式错误、无文本、解析超时、向量模型失败。测试覆盖 worker 退出后恢复。

006的parse worker只领取kind=parse：成功保存候选revision和chunks，置文档parsed，完成parse job，并在同一事务创建kind=index的queued任务。007增加index handler消费它。新候选版本即使尚不是active，也必须能够建索引；只有索引全部成功才原子更新active_revision_id并置ready。替换期间旧active版本仍可查询，候选版本不参与查询。新版本失败不改变旧active；界面分别显示当前有效版本和新版本处理状态。006独立交付时停在明确的待索引状态，不把入库全链路误标完成。

检索可用条件是“有已完成索引的active_revision，且文档/知识库未停用删除、当前用户有权限”，不能简单要求Document.status=ready，否则新版本processing/parsed/failed会错误屏蔽旧版。worker提交时再次检查停用/删除和当前候选版本，不能让后台任务重新启用管理员已停用/删除的内容，也不能让较旧的并发任务覆盖更新的版本。

FAQ在005编辑后标记version已变更；007补齐有效FAQ索引并消费后续变更，索引只写对应捕获版本，提交前核对version仍相同，否则重新排队。旧版本不匹配时不参与检索。

Chunk：`id,kb_id,document_id?,faq_id?,revision_id?,faq_version?,chunk_index,text,title,page_number?,embedding?,embedding_model?,embedding_version?`。document_id 与 faq_id 恰好一个存在。未索引向量为空；检索使用当前有效文档版本与版本一致的有效FAQ，旧向量不参加搜索。初始分段为每片独立重分词后最多400个模型token、目标重叠50个token；重叠起点落在WordPiece词内时向前扩到完整词边界，实际重叠可略多于50但每片仍不得超过400，以固定模型tokenizer计数，并为检索前缀保留空间不超过模型512上限；tokenizer版本随模型固定。指定中文模型 `BAAI/bge-small-zh-v1.5` 固定修订 `7999e1d3359715c523056ef9478215996d62a620`，真实输出为512维（原计划384维为误记）；该值与512 token输入上限是两个独立约束。模型来源见 [官方配置](https://huggingface.co/BAAI/bge-small-zh-v1.5/blob/7999e1d3359715c523056ef9478215996d62a620/config.json)。

### 006 已实现接入细则

文档列表遵循标准分页。摘要/详情增加 `candidate_revision_id`、`active_revision`、`candidate_revision` 与 `latest_job`；版本摘要仅含 ID、文件名、内容 SHA-256、parser_version、创建时间，不返回存储路径。任务摘要含 kind/state/attempts/error_code/安全中文error_message及创建/完成时间。PATCH 仅接受严格布尔 `is_active`，不能直接设置 ready。管理员可读取停用文档摘要以恢复；停用或删除文档对所有人的下载均返回404，普通用户不能读取停用摘要。

上传初始版本和替换版本均接受单个 multipart `file`，返回202 `{document_id,job_id,status:"uploaded"}`。同库同文件名同内容的重复上传复用候选版本/任务；已存在的历史内容不重复创建版本。授权下载优先返回当前有效版本，尚无有效版本时返回候选原文件；下载同样检查当前知识库及成员权限。DELETE 软删除，保留受控存储供持久化与历史审计，不公开静态文件路径。

`node scripts/dev.mjs worker` 使用本worktree数据库和上传目录。parse任务有持久租约与每次领取的新令牌，过期可重领；旧worker即使恢复也不能提交覆盖新领取者。解析与chunk写入/index排队在提交阶段再次验证知识库、文档启用状态及候选版本。独立解析进程默认60秒超时、512MiB内存上限，文档最多2000页、提取文本最多200万字符；DOCX按原始段落/表格顺序保留位置。空/扫描PDF、损坏格式、资源超限有明确失败状态。模型配置、下载与运行步骤见 [开发说明](../scripts/README.md#5-文档解析-workertodo-006)。

## 4. 内部模块接口（todo-004/007/008/014）

以下类型在所属模块 `schemas.py` 中定义，跨模块复用定义，不复制不同版本。

| 类型 | 字段 |
| --- | --- |
| Actor（auth） | user_id: UUID, role: user/agent/admin；由会话产生 |
| LLMMessage（providers） | role: system/user/assistant, content: str |
| LLMDelta（providers） | text: str, finish_reason: str或null；供应商 usage 可在结束时附带 |
| SearchHit（retrieval） | chunk_id, kb_id, text, source_type: document/faq, source_id, title, page_number?, paragraph_number?, line_number?, score, revision_id?, faq_version? |
| Citation（rag） | index: int, chunk_id, kb_id, source_type, source_id, title, page_number?, paragraph_number?, line_number?, revision_id?, faq_version?, quote |
| AnswerEvent（rag） | type: delta/citations/done/error, payload: dict |

Provider 接口：`stream(messages: list[LLMMessage], *, max_tokens: int, temperature: float) -> AsyncIterator[LLMDelta]`。异步生成器，不接收数据库会话或用户权限。实现 `MockProvider`、`CloudProvider`、`OllamaProvider`，由配置选择。统一超时/取消、429/5xx、无有效输出处理；不把不同协议的错误内容直接展示给用户。

首版CloudProvider固定实现 **OpenAI-compatible Chat Completions文字流协议**，不要求用户购买特定厂商服务。`MODEL_BASE_URL`包括版本路径（例如`https://example.invalid/v1`），后端POST到其`/chat/completions`，Bearer认证；请求字段为`model,messages,stream:true,max_tokens,temperature`。首个真实提供商须支持此公共子集；若选定模型只支持其他上限字段/协议，在004接入时明确适配并补契约测试，不猜测兼容。返回按SSE `data:`行解码JSON，读取`choices[0].delta.content`、`finish_reason`，以`data: [DONE]`识别完整流结束；空role片段不产生文本，存在usage的末尾空choices块也应能处理。usage未提供则记录null，不伪造计费用量。不发送工具调用/图像请求，不展示提供商的推理过程字段。为已选定的 DeepSeek 模型增加显式后端配置 `MODEL_DISABLE_THINKING=true`，仅启用时额外发送 `thinking: {type: "disabled"}`；默认 false 保持公共子集。协议参考[Chat Completions官方结构](https://developers.openai.com/api/reference/resources/chat)。

004的假HTTP服务固定覆盖此协议：中文UTF-8跨网络块、SSE事件跨块、空delta、usage块、DONE、错误状态和未完整结束即断连。收到length/content_filter等终止原因时明确向调用方暴露，不能把截断/过滤内容当作正常完整答案。Ollama在014实现自身HTTP协议到同一内部类型的转换。

### 004 已实现接入细则

接口、配置与取消示例见 [providers/README](../backend/app/modules/providers/README.md)。`create_provider()` 默认选择 Mock；云模型 ID 必须在服务端 `MODEL_ALLOWED_IDS` 中，key 为后端 `MODEL_API_KEY`。`LLMDelta.usage` 为可空 `LLMUsage(prompt_tokens?, completion_tokens?, total_tokens?)`，只保留上游数值，不估算。

文本片段只有 text；只在 `[DONE]` 后发出一个 text 为空、finish_reason 非空的终止片段，usage 附在该片段上。`stop` 表示完整，`length/content_filter` 需业务层明确处理；缺少 DONE、协议无效或空白 stop 抛出 `ProviderError`。错误 code 及含义见模块说明，不透传厂商错误体。上游资源在终止片段前关闭；消费方提前退出须使用 `contextlib.aclosing`，任务取消保留 CancelledError。连接/读取超时分别配置，无透明重试。

本任务无对外代理 API；真实云连接按用户明确授权执行受控 smoke，当前提供商与结果见 [todo-004](tasks/todo-004.md) 最新工作记录。单次成功不替代 017 发布前对实际部署配置的真实验收。
Retrieval 接口：`search(actor: Actor, kb_ids: list[UUID], query: str, top_k: int = 5) -> list[SearchHit]`，异步调用。内部重新验证权限；空授权集合返回空候选，不能退化为全库。初期 score 是余弦相似度；混合检索后类型/含义变化必须更新评测与阈值，不能视为同一概率。

### 007 已实现接入细则

本地 embedding 使用 `BAAI/bge-small-zh-v1.5` 固定 revision `7999e1d3359715c523056ef9478215996d62a620`，512 维、CPU、L2 归一化。仅查询加官方前缀 `为这个句子生成表示以用于检索相关文章：`，文档/FAQ 不加；编码前检查实际 token 数（含特殊 token）不超过 512，超限拒绝，不能静默截断。模型只从 `EMBEDDING_MODEL_PATH` 的本地固定快照加载，首次下载在启动前显式执行；不从问答请求自动下载或运行远程模型代码。

`RETRIEVAL_THRESHOLD` 默认 0.65（余弦分数），Top-K 默认 5、范围 1–20。此阈值只是初始设置，真实代表性语料和 013 评测前不宣称已校准。首版采用 PostgreSQL pgvector 精确查询，不引入近似索引。知识库权限、请求范围、启用状态和当前有效来源版本都在 SQL 候选集合中限定，再排序/限制数量。编码后重新查询权限，空授权范围返回空列表。当前可见有效向量的模型元数据不匹配时明确要求重建，不混用向量空间；无权库的元数据不能影响可见结果或错误。

`node scripts/dev.mjs index-worker` 单独处理持久 index 任务；原 `worker` 仅处理 parse。索引批次在事务外编码并续租，最终重新检查租约令牌、知识库/来源状态及捕获版本，完整写入向量后才在同一事务激活文档或设置 FAQ indexed_version。文档重建保留已有 chunk ID，失败不破坏旧 active；FAQ 编辑使旧版本立即失效，并排入新版本索引。迁移为已有启用 FAQ 创建初始任务。首次加载和运行说明见 [scripts/README](../scripts/README.md)。

RAG 接口：`stream_answer(actor: Actor, kb_ids: list[UUID], question: str, history: list[LLMMessage]) -> AsyncIterator[AnswerEvent]`。不依赖 Conversation ORM；由 chat 提供已过滤的历史，由 retrieval 验证知识范围。todo-008 可以在 todo-009 尚未开发时独立测试。

`done` payload：`{answer_status: "answered|clarify|no_answer", evidence_level: "sufficient|limited|none", intent: "knowledge|complaint|handoff|other"}`。明确转人工意图交由 chat/handoff 执行状态变更，RAG 不自行写会话状态。done 可附带 `usage: {prompt_tokens?,completion_tokens?,total_tokens?}|null`；仅使用真实上游 usage，多阶段某字段缺失则该合计保持 null，不按字数估算，不把缺失当零。

### 008 已实现接入细则

首版为抽取式证据回答：模型只选择本轮证据的来源编号与连续原文，服务端严格校验后生成回答和引用，不直接展示模型自由摘要。模型原始响应先缓冲，验证完成才发 delta/citations/done，因此首段会晚于上游首 token；不以逐字延时伪造实时流。未知编号、伪造引文和额外自由答案字段会被拒绝，不生成假引用。

引用元数据由当前 SearchHit 提供，包含 kb_id、文档 revision_id 或 FAQ faq_version 与定位。发送任何证据前，通过 retrieval.validate_hits 复用当前 SQL 权限/有效版本谓词再次核验；同一 SQL 同时要求用户仍有效且当前角色未变；撤权、用户停用/改角色、来源停用、删除或版本改变返回安全 SOURCE_CHANGED 错误，不输出旧原文。该接口为新短会话只读查询，不跨模型调用持数据库锁。

提示词版本 `rag-extractive-v1`，问题 1–2000 字符；历史只接收调用方已授权的完整 user/assistant 轮次，最近最多 3 轮。system 历史不受信任。回答提示词同时保留原问题与改写后的独立查询；后者仅恢复指代，不作为事实证据，两者都计入体积预算。问题不截断；证据超出输入预算时丢弃最低排名的完整片段并同步来源映射。输入按序列化消息内容的 UTF-8 字节限制为 12000，属于保守体积上限而非 DeepSeek 精确 token 计数。当前 DeepSeek 配置容量依据见 [官方模型文档](https://api-docs.deepseek.com/quick_start/pricing/)；BGE 自身仍用真实 tokenizer 检查 512 上限，超过时请求用户缩短问题。

改写、检索、答复及发送前核验共用 60 秒期限；无历史时答复最多 512 输出 tokens，有改写时最多 128+384。所有模型流有明确关闭/取消，失败无透明重试；不完整、截断、过滤或超时不能以成功 done 结束。文档/历史仅作为不可信数据，不进入 system 权限或工具调用；本模块不写会话或人工接管状态。

明确转人工/投诉/简单问候使用固定安全说明；否定转人工和询问投诉渠道仍按知识问题处理。空证据不调用答复模型，返回无依据说明。默认 MockProvider 的固定联调文字不能冒充合规知识回答；自动化 RAG 测试注入受控 provider，真实 DeepSeek 检查另行显式运行并记录。

## 5. 会话与流式输出（todo-009）

Conversation：`id,user_id,title,kb_ids,mode,assigned_agent_id?,created_at,updated_at`。mode=`bot|queued|human|closed`。Message：`id,conversation_id,role,author_id?,content,status,citations,client_message_id?,answer_status?,evidence_level?,intent?,latency_ms?,created_at`。role=`user|assistant|agent|system`；status=`generating|complete|failed|cancelled`；回答元数据供历史展示与统计使用。

| 方法/路径 | 行为 |
| --- | --- |
| POST `/conversations` | `{kb_ids:[UUID]}` → 201，校验知识可见性 |
| GET `/conversations` | 当前用户自己的列表；客服/管理员通过授权入口获取允许的集合 |
| GET/DELETE `/conversations/{id}` | 获取/软删除，服务器校验访问资格 |
| GET `/conversations/{id}/messages` | 分页历史，包含助手输出状态 |
| POST `/conversations/{id}/messages/stream` | bot 模式用户提问 `{content,client_message_id}`，返回 SSE |
| POST `/conversations/{id}/messages` | queued/human 下发文字消息，用户或已接单客服；JSON响应201，机器人不生成 |

SSE 使用 `fetch` 的响应流，不使用仅支持 GET 的原生 EventSource。请求携带 Cookie 与 CSRF。事件依次为：

```text
event: meta
data: {"user_message_id":"UUID","assistant_message_id":"UUID"}

event: delta
data: {"text":"回答片段"}

event: citations
data: {"items":[]}

event: done
data: {"answer_status":"answered","evidence_level":"sufficient","intent":"knowledge"}
```

发生错误发 error（如仍可写流），助手消息状态 failed；断连取消生成并尽力保存当前文本、标记 cancelled；重启后把失去执行者的 generating 消息转为 failed。历史查询是恢复依据，重连不自动发起第二次模型调用。`client_message_id` 在同一会话/作者范围唯一，重复请求返回409和既有消息ID；同一会话另有生成时返回409。

最终提交答案前再次检查会话未转人工/关闭、仍持有生成权；否则保存 cancelled，避免机器人和客服同时回答。

初始模型调用限额由009实现：每用户10次/分钟、60次/业务自然日，全局最多2个正在生成、每会话最多1个；超限429或会话冲突409。以“接受的 RAG 请求”为单位原子预留一次，改写+回答两阶段仍算一次；重复 client_message_id、鉴权/状态/额度拒绝不计入，接受后的失败、取消及固定业务回复均计入且不退款；日计数存数据库，避免重启绕过。基础部署固定1个API进程，全局并发由该进程控制，扩多进程时必须先改成共享并发控制。用户问题最多2000字符；模型输出上限512 token，上游总超时60秒；提示词加历史按所选模型上下文上限裁剪。限额作为明确配置有默认值，在017按预算调整并记录。次数限额不等于准确货币账单，供应商usage与估算usage分开记录，云账号费用上限/告警由部署配置落实。

### 009 已实现接入细则

会话创建的 kb_ids 必须是 1–50 个不同且当前有权访问的知识库，创建后固定范围。content 去首尾空白后 1–2000 有效字符，拒绝 NUL 和无效 Unicode；client_message_id 为 UUID。列表与历史返回 `{items,total,page,page_size}`，默认 50、最多 100；会话按最近更新排序，历史按创建时间/ID 正序，page=1 为最早消息。正文与引用均以文本呈现，不执行 HTML。

任意有效角色可以创建和使用自己的 bot 会话；管理员可审阅/软删他人会话，不能代别人发起 AI 或发送文字。agent 可读自己的会话及分配给自己的人工会话；未接单不读取完整历史。owner 可在 queued/human 发送文字，接单 agent 仅在 human 回复，closed 只读。会话删除保留消息及用量记录。

`Message` 另存 in_reply_to_id、generation_token、error_code、request_id。助手占位与用户消息、GenerationUsage 在同一事务写入后发 meta；只有最终提交成功才发 done。会话/消息生成令牌和数据库唯一约束防止迟到任务覆盖新请求。重复键返回 409/DUPLICATE_MESSAGE，error.details 带既有 user_message_id 和可空 assistant_message_id；历史查询不会重发模型请求。

GenerationUsage 保留每次已接受请求的身份、会话、消息、UTC accepted_at/finished_at、outcome 和实际 prompt/completion/total_tokens；缺失 usage 字段为 null。`CHAT_REQUESTS_PER_MINUTE=10` 按滚动 60 秒，`CHAT_REQUESTS_PER_DAY=60` 按 Asia/Shanghai 自然日，`CHAT_GLOBAL_CONCURRENCY=2`，每会话最多一个生成。用户行锁串行预留，获锁后读取记账时间，已提交用量不会因时间顺序反转而漏计；重启不重置计数；这是请求配额，不是供应商调用数或金额。

每个应用实例绑定自己的数据库、RAG 和运行中任务表。监听真实 HTTP 断连以取消仍在等待首段的上游，结束时保存 cancelled/failed。长流在每个可见事件和最终提交前重新检查登录会话、当前身份、会话模式/归属和令牌。启动恢复先将遗留 generating 标为 failed/PROCESS_RESTARTED；恢复失败时保留 /health/live，/health/ready 返回 503，聊天写入拒绝，修复数据库后重启服务。部署仅支持单 API 进程。

历史引用按当前 Chunk、知识库权限、来源有效版本与原文再次核验，不执行 embedding。任一引用失效时，响应将整条助手正文替换为“该回答所依据的资料当前不可访问”，清空 citations 并标 evidence_hidden=true；数据库原文和终态仍保留，客户端此前已看到的内容不能撤回。送入 RAG 的历史排除隐藏/未完成/失败/取消轮次，仅保留有限完整 user/assistant 对。文档引用下载仍走现有每次鉴权的下载接口。

内部 `chat.service.transition_mode(db, actor, conversation_id, expected_mode=..., next_mode=..., assigned_agent_id=..., request_id=...)` 是 010 复用的状态入口，flush 不 commit，由交接业务事务提交后调用 `app.state.chat_runtime.cancel(conversation_id)`。011 可复用 get_message 验归属，不能通过反馈接口绕过当前历史来源权限。

## 6. 人工客服（todo-010）

- POST `/conversations/{id}/handoff`：本人申请，bot→queued，记录一个开放 Handoff；重复申请返回现有排队状态。
- GET `/handoffs`：客服看待接单最小摘要；普通用户不可枚举队列。
- POST `/handoffs/{id}/claim`：客服原子接单，queued→human，两个客服竞争仅一个成功，另一个409。
- POST `/handoffs/{id}/close`：已接单客服或管理员关闭，human→closed。
- GET `/handoffs/{id}`：本人/已接单客服/管理员查询状态。排队/人工消息短轮询已有消息接口。

关闭的会话只读，继续提问创建新会话。无人接单时 queued 消息就是待处理留言，不伪造在线客服。

## 7. 反馈、审计与统计（todo-011/012）

- POST `/messages/{id}/feedback`：本人对助手消息提交 `{rating:"up|down",comment}`；每作者每消息一条，可用 PATCH `/feedback/{id}` 修改本人评价。
- GET `/admin/feedback`：管理员分页筛选；PATCH `/admin/feedback/{id}` 设置 `status:"open|resolved", resolution`。
- GET `/admin/audit-events`：管理员查询；GET `/admin/stats?from=...&to=...`：访问/问答次数、独立用户数、热门问题、无答案比例、转人工量、评价满意度、平均耗时。

统计口径：回答数量只计已结束的助手生成；无答案率=no_answer/(answered+clarify+no_answer)；满意度=up/(up+down)，没有评价时为 null；错误和取消另列，不能当满意。日界线使用业务展示时区 Asia/Shanghai，数据库时间仍为UTC。

AuditEvent 至少有 actor_id、action、target_type/id、outcome、request_id、created_at、脱敏metadata。身份/知识/转人工/反馈修改任务实现时同时写审计事件；todo-012负责统一查询、统计和后台页面，不能等它才开始记录审计。todo-001提供 `core/models.py` 的AuditEvent和 `core/audit.py` 的 `record_audit(db, *, actor_id, action, target_type, target_id, outcome, request_id, metadata)`，加入调用方事务；actor_id为可空UUID，日志不依赖尚未实现的User表。基础迁移创建审计表，测试直接验证写入，避免另引消息系统。登录失败等无业务事务动作使用自己的短事务记录。

### 011 已实现接入细则

反馈只接受消息所属用户对 complete 的 assistant 回复评价；当前有效 user/agent/admin 均只能评价自己的回复，不能借管理员或客服读取权限代评。关闭会话可评价，软删会话不再向原用户提供反馈读写；既有反馈记录保留供管理员处理和统计。反馈不改知识库、索引或训练数据。

rating 为 up/down；comment 可省略或空串，有内容时去首尾空白且最多 2000 字，纯空白、NUL、无效 Unicode、null 及额外字段拒绝。每用户每消息唯一，POST 初次 201；相同规范化内容重试 200 返回既有记录，不重复写审计；不同内容重试 409，使用 PATCH /feedback/{id} 修改。修改必须含 rating/comment 至少一项；真实内容变化重新置 open 并清除旧处理说明、处理者和处理时间，相同请求不变更时间/审计。

GET /messages/{id}/feedback 返回本人已有反馈或 null，仍先校验消息归属及可评价状态。GET /admin/feedback 支持标准分页及 status/rating 筛选；GET /admin/feedback/{id} 返回详情。只有管理员能 PATCH 管理接口：resolved 必须有非空、有效且最多 2000 字的 resolution；open 清空处理字段且拒绝非空 resolution。相同处理重试幂等；修改已处理说明会记录本次处理者和时间。

来源版本仅从服务端存储引用生成快照，保存 chunk/kb/source/revision/faq_version 身份，不复制引文、标题或答案。管理员查看现存原回答时复用当前聊天来源授权投影；会话已软删时 message_available=false 且不返回原回答。普通反馈响应不返回来源快照。前端使用文本展示评论和说明，反馈入口仅对本人已完成助手回复显示。

统一 Conversation→Feedback 锁序保证并发提交与更新一致。feedback.create/update/resolve/reopen 与业务修改同事务记录，幂等重试不加事件；审计只存 ID、枚举及变更字段名，不存评论、处理说明或聊天原文。
## 8. 环境变量与测试约定

业务变量：`APP_ENV, DATABASE_URL, SESSION_SECRET, UPLOAD_DIR, MODEL_PROVIDER, MODEL_BASE_URL, MODEL_API_KEY, MODEL_NAME, EMBEDDING_MODEL`。`SESSION_SECRET` 用于会话/CSRF相关签名；随机 session token 本身仍只存哈希。训练环境拥有独立配置，不借用生产API凭据。

每worktree变量：`COMPOSE_PROJECT_NAME, API_PORT, WEB_PORT, DB_PORT, DATABASE_URL, UPLOAD_DIR`。`DATABASE_URL` 是后端配置，不暴露在前端；Compose 内连接使用db:5432，主机运行后端才用独立DB_PORT。

CI默认使用Mock模型和可复现的小型 embedding fixture，数据库权限和向量查询测试使用真实 PostgreSQL/pgvector；真实 embedding/云模型/Ollama 验收由明确标记的集成检查执行并记录。Mock结果不证明真实模型接通或算法质量。
