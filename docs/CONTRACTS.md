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

IngestionJob：`id,kind,document_id?,faq_id?,revision_id?,state,attempts,lease_until,error_code,created_at,finished_at`。kind=`parse|index`，document_id/faq_id恰好一个存在，parse只用于文档。state=`queued|running|succeeded|failed`。领任务必须原子；失败码区分超限、格式错误、无文本、解析超时、向量模型失败。测试覆盖 worker 退出后恢复。

006的parse worker只领取kind=parse：成功保存候选revision和chunks，置文档parsed，完成parse job，并在同一事务创建kind=index的queued任务。007增加index handler消费它。新候选版本即使尚不是active，也必须能够建索引；只有索引全部成功才原子更新active_revision_id并置ready。替换期间旧active版本仍可查询，候选版本不参与查询。新版本失败不改变旧active；界面分别显示当前有效版本和新版本处理状态。006独立交付时停在明确的待索引状态，不把入库全链路误标完成。

检索可用条件是“有已完成索引的active_revision，且文档/知识库未停用删除、当前用户有权限”，不能简单要求Document.status=ready，否则新版本processing/parsed/failed会错误屏蔽旧版。worker提交时再次检查停用/删除和当前候选版本，不能让后台任务重新启用管理员已停用/删除的内容，也不能让较旧的并发任务覆盖更新的版本。

FAQ在005编辑后标记version已变更；007补齐有效FAQ索引并消费后续变更，索引只写对应捕获版本，提交前核对version仍相同，否则重新排队。旧版本不匹配时不参与检索。

Chunk：`id,kb_id,document_id?,faq_id?,revision_id?,faq_version?,chunk_index,text,title,page_number?,embedding?,embedding_model?,embedding_version?`。document_id 与 faq_id 恰好一个存在。未索引向量为空；检索使用当前有效文档版本与版本一致的有效FAQ，旧向量不参加搜索。初始分段为最多400个模型token、重叠50个token，以模型tokenizer计数，并为检索前缀保留空间不超过模型512上限；tokenizer版本随模型固定。

## 4. 内部模块接口（todo-004/007/008/014）

以下类型在所属模块 `schemas.py` 中定义，跨模块复用定义，不复制不同版本。

| 类型 | 字段 |
| --- | --- |
| Actor（auth） | user_id: UUID, role: user/agent/admin；由会话产生 |
| LLMMessage（providers） | role: system/user/assistant, content: str |
| LLMDelta（providers） | text: str, finish_reason: str或null；供应商 usage 可在结束时附带 |
| SearchHit（retrieval） | chunk_id, kb_id, text, source_type: document/faq, source_id, title, page_number?, score, revision_id? |
| Citation（rag） | index: int, chunk_id, source_type, source_id, title, page_number?, quote |
| AnswerEvent（rag） | type: delta/citations/done/error, payload: dict |

Provider 接口：`stream(messages: list[LLMMessage], *, max_tokens: int, temperature: float) -> AsyncIterator[LLMDelta]`。异步生成器，不接收数据库会话或用户权限。实现 `MockProvider`、`CloudProvider`、`OllamaProvider`，由配置选择。统一超时/取消、429/5xx、无有效输出处理；不把不同协议的错误内容直接展示给用户。

首版CloudProvider固定实现 **OpenAI-compatible Chat Completions文字流协议**，不要求用户购买特定厂商服务。`MODEL_BASE_URL`包括版本路径（例如`https://example.invalid/v1`），后端POST到其`/chat/completions`，Bearer认证；请求字段为`model,messages,stream:true,max_tokens,temperature`。首个真实提供商须支持此公共子集；若选定模型只支持其他上限字段/协议，在004接入时明确适配并补契约测试，不猜测兼容。返回按SSE `data:`行解码JSON，读取`choices[0].delta.content`、`finish_reason`，以`data: [DONE]`识别完整流结束；空role片段不产生文本，存在usage的末尾空choices块也应能处理。usage未提供则记录null，不伪造计费用量。不发送工具调用/图像请求，不展示提供商的推理过程字段。协议参考[Chat Completions官方结构](https://developers.openai.com/api/reference/resources/chat)。

004的假HTTP服务固定覆盖此协议：中文UTF-8跨网络块、SSE事件跨块、空delta、usage块、DONE、错误状态和未完整结束即断连。收到length/content_filter等终止原因时明确向调用方暴露，不能把截断/过滤内容当作正常完整答案。Ollama在014实现自身HTTP协议到同一内部类型的转换。

### 004 已实现接入细则

接口、配置与取消示例见 [providers/README](../backend/app/modules/providers/README.md)。`create_provider()` 默认选择 Mock；云模型 ID 必须在服务端 `MODEL_ALLOWED_IDS` 中，key 为后端 `MODEL_API_KEY`。`LLMDelta.usage` 为可空 `LLMUsage(prompt_tokens?, completion_tokens?, total_tokens?)`，只保留上游数值，不估算。

文本片段只有 text；只在 `[DONE]` 后发出一个 text 为空、finish_reason 非空的终止片段，usage 附在该片段上。`stop` 表示完整，`length/content_filter` 需业务层明确处理；缺少 DONE、协议无效或空白 stop 抛出 `ProviderError`。错误 code 及含义见模块说明，不透传厂商错误体。上游资源在终止片段前关闭；消费方提前退出须使用 `contextlib.aclosing`，任务取消保留 CancelledError。连接/读取超时分别配置，无透明重试。

本任务无对外代理 API；真实云连接尚未验证，用户要求另行通知后再执行受控 smoke。该状态不阻塞 Mock/协议验收，真实验证最晚由 017 发布前完成。
Retrieval 接口：`search(actor: Actor, kb_ids: list[UUID], query: str, top_k: int = 5) -> list[SearchHit]`，异步调用。内部重新验证权限；空授权集合返回空候选，不能退化为全库。初期 score 是余弦相似度；混合检索后类型/含义变化必须更新评测与阈值，不能视为同一概率。

RAG 接口：`stream_answer(actor: Actor, kb_ids: list[UUID], question: str, history: list[LLMMessage]) -> AsyncIterator[AnswerEvent]`。不依赖 Conversation ORM；由 chat 提供已过滤的历史，由 retrieval 验证知识范围。todo-008 可以在 todo-009 尚未开发时独立测试。

`done` payload：`{answer_status: "answered|clarify|no_answer", evidence_level: "sufficient|limited|none", intent: "knowledge|complaint|handoff|other"}`。明确转人工意图交由 chat/handoff 执行状态变更，RAG 不自行写会话状态。

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

初始模型调用限额由009实现：每用户10次/分钟、60次/业务自然日，全局最多2个正在生成、每会话最多1个；超限429或会话冲突409。接受请求时原子登记用量，重复client_message_id不重复登记，已向模型发起但失败/取消的请求仍计入次数；日计数存数据库，避免重启绕过。基础部署固定1个API进程，全局并发由该进程控制，扩多进程时必须先改成共享并发控制。用户问题最多2000字符；模型输出上限512 token，上游总超时60秒；提示词加历史按所选模型上下文上限裁剪。限额作为明确配置有默认值，在017按预算调整并记录。次数限额不等于准确货币账单，供应商usage与估算usage分开记录，云账号费用上限/告警由部署配置落实。

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

## 8. 环境变量与测试约定

业务变量：`APP_ENV, DATABASE_URL, SESSION_SECRET, UPLOAD_DIR, MODEL_PROVIDER, MODEL_BASE_URL, MODEL_API_KEY, MODEL_NAME, EMBEDDING_MODEL`。`SESSION_SECRET` 用于会话/CSRF相关签名；随机 session token 本身仍只存哈希。训练环境拥有独立配置，不借用生产API凭据。

每worktree变量：`COMPOSE_PROJECT_NAME, API_PORT, WEB_PORT, DB_PORT, DATABASE_URL, UPLOAD_DIR`。`DATABASE_URL` 是后端配置，不暴露在前端；Compose 内连接使用db:5432，主机运行后端才用独立DB_PORT。

CI默认使用Mock模型和可复现的小型 embedding fixture，数据库权限和向量查询测试使用真实 PostgreSQL/pgvector；真实 embedding/云模型/Ollama 验收由明确标记的集成检查执行并记录。Mock结果不证明真实模型接通或算法质量。
