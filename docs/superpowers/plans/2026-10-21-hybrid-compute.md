# 云端业务与桌面生成实施计划

> For agentic workers: use superpowers:subagent-driven-development. User approved this design and explicitly authorized autonomous plan review, development and validation on 2026-10-21; do not ask again between stages.

**Goal:** 云端保留完整业务/BGE，本机以认证HTTPS领取Ollama生成任务，真实验证后才进入服务器申请。
**Architecture:** 单体FastAPI和PostgreSQL类型化生成队列；现有Provider接口增加queued实现，桌面串行调用既有OllamaProvider。机器入口与浏览器CSRF隔离。
**Tech Stack:** 现有冻结Python3.12/FastAPI/SQLAlchemy/pgvector/httpx2，无新增依赖。
**Spec:** ../specs/2026-10-21-hybrid-compute-design.md

## Global Constraints

- 独立todo-021 worktree；只使用本任务.env、数据库、端口、上传卷；不修改原运行版。
- generate only；payload/result原始JSON各64KiB；既有RAG输入12000UTF-8字节、输出512tokens/8192字符。
- 一个节点串行；排队最多16；元数据最多10000行，终态清空正文，24小时+每分钟清理。
- 节点poll1秒/heartbeat5秒/lease15秒；deadline为现有RAG剩余60秒；生成只领取一次，无云模型回退。
- 普通/api/v1写请求CSRF不变；/internal/compute精确前缀Bearer认证、no-store、实际body限制。
- TDD先失败再最小实现，真实PostgreSQL测试；统一check与独立评审；无购买/发布直到完整门槛满足。

## Review Focus

1. 取消或凭据撤销与结果提交竞争不能复活旧回复；Task1/3并发和generation_token测试。
2. 结果接受后消费前崩溃不能永久留存正文；Task1 recover/cleanup/consume测试。
3. Cookie不能代替机器Bearer，chunked超限不可绕过body限制；Task1路由/流体测试。
4. 冷模型/网络断开不允许后台重试叠加GPU调用；Task2真实TCP假Ollama和取消后退出测试。
5. 两个会话的ContextVar不能串线，局部生成结果不能绕过原RAG引用复核；Task3并发与真实RAG测试。

## Interface contract

Task1 owns app/modules/compute/{models,schemas,context,service,router,limits,manage}.py and migration021_compute.py, tests/compute/test_queue.py + test_router.py.
Task2 owns app/modules/compute/desktop.py and tests/compute/test_desktop.py ONLY.
Task3 owns providers/queued.py, providerconfig/factory, main.py, chat/streaming.py, migrations/env.py, .env.example and integration tests ONLY.
Root owns docs, task/ledger, developer setup, final runtime, infra and whole-check coordination. Agents do not commit concurrently; root commits each reviewed unit.

compute.context:
- frozen GenerationScope(conversation_id:UUID, assistant_message_id:UUID, generation_token:UUID, actor_id:UUID, actor_role:str, session_hash:str, deadline:datetime).
- generation_scope: ContextVar[GenerationScope|None], defaultNone. bind_scope(scope) synchronous contextmanager sets and finally resets.
- Scope comes from server reservation and SHA256 of qa_session, never worker input.

compute.service functions use caller-owned sqlalchemy Session, no implicit commit; now is aware UTC supplied keyword:
- register_worker(db, *, name:str, model_id:str, now:datetime) -> (ComputeWorker, raw_token:str).
- authenticate_worker(db, token:str, *, now) -> ComputeWorker; failure AuthError401.
- enqueue(db, scope:GenerationScope, payload:dict, *, now) -> UUID; checks current Message/Conversation generation, actor active/same role and AuthSession hash/expiry; serialized queue capacity via pg advisory lock.
- claim(db, worker, *, now) -> dict|None. Dict: job_id(strUUID), lease_token(str), deadline(ISO), payload(dict). No arbitrary model; worker.model_id matches payload.model_id.
- heartbeat(db, worker, job_id:UUID, lease_token:str, *, now) -> None; invalid/expired AuthError409.
- submit_result(db, worker, job_id, lease_token, result:dict, *, now) -> None; validate strictly; duplicate identical digest+same node/lease can acknowledge, never overwrite conflict.
- take_result(db, job_id, scope, *, now) -> dict|None; None pending; terminal failure/cancel AuthError409; succeeded result returned once then clear payload/result atomically.
- cancel(db, job_id, *, now) -> None; idempotent, clear body.
- cleanup(db, *, now, recover=False) -> None; expire leases/deadlines/revoked actors/sessions, orphan successes; recover=True invalidates all old work because chat restart recovers messages failed. bounded rows24h cleanup.

Compute result JSON:
{model_id:str, text:str<=8192, finish_reason:'stop'|'length', usage:null|{prompt_tokens:int|null,completion_tokens:int|null,total_tokens:int|null}}
failure: {error_code: allowlisted ProviderError.code}, not exception repr/provider body. Schemas forbid extra/null-invalid fields.
Payload: {model_id, messages:[LLMMessage], max_tokens<=512, temperature:finite}.

Machine routes:
claim POST body{} ->200 {job:null|claim_dict}; heartbeat POST body{lease_token} ->204; result POST body{lease_token,result} ->204. Bearer checked against active worker every request.
ComputeBodyLimitMiddleware limits bytes of /internal/compute prefix to65536 before dispatch; 413 JSON no echoed input; no-store for all machine responses.

Task2 desktop private config:
{cloud_url, token, model_id, model_base_url, ollama_num_ctx:4096}. HTTPS cloud except exactloopback HTTP for local tests; local model must be loopback HTTP, no arbitrary externaldestination; credentials not logged. Reads JSON file, no token CLI arg.
Node uses httpx2, fixed cloud endpoints above and preconfigured OllamaProvider. Task's model must match config.model_id. bounded reads65536; no redirects or ambient proxy. heartbeat concurrently5s; deadline cancels; cancellation/heartbeat-invalid closes local provider and exits process before claiming another job. Successful result submit once, failed acknowledgment stops node; no transparent request replay.
Module CLI python -m app.modules.compute.desktop --config PATH; supports --once for repeatable single-job verification.

## Task 1: 持久计算任务、认证与机器路由

- [ ] Write real PostgreSQL tests for concurrent single claim, max16queue, lease15s expiration, jobdeadline, disabled actor/revoked session, worker revoke, duplicate/conflict/late submission, single consumption and orphan cleanup.
- [ ] Run tests RED (missing feature) and save evidence.
- [ ] Implement caller-owned transaction service and fixed strict schemas; add unique migration021_compute down_revision012; no dependency changes.
- [ ] Implement token creation/revocation CLI (writes secret JSON only to explicit new file with restrictive permissions; no overwrite/token stdout) and bearer routes/body limiter.
- [ ] Run service/router tests GREEN with real database. No hidden import side effects or broad CSRF exemption.
- [ ] Independent task review, fix findings, root commit only this unit.

## Task 2: 桌面Ollama节点

- [ ] Write real local TCP/HTTP service tests for claim/nojob, successful Ollama complete, stop/length/usage, cancellation/heartbeat rejection/deadline, oversize body, wrong model, auth/redirect errors.
- [ ] Run RED then implement desktop.py using existing OllamaProvider. No database Settings required on desktop, no cloud API fallback.
- [ ] Verify credentials never appear in diagnostics; cancellation exits before next claim.
- [ ] Run GREEN, independent review and root commit scoped unit.

## Task 3: Provider、会话绑定与生命周期接入

- [ ] Write tests for queued factory, bound scope required, pending/success/failure/timeout/cancel, ContextVar per-conversation isolation, unchanged Mock/Cloud/Ollama behavior.
- [ ] Run RED then QueuedProvider(factory,model_id,max_output_tokens) using service enqueue/take_result/cancel in short transactions and async polling. Preserve terminal finish_reason/usage.
- [ ] create_provider(settings=None, *, session_factory=None): queued requires explicit session_factory. ModelSettings allows queued with allowed model ID; no model base URL/key needed for queued. main passes own factory.
- [ ] GenerationStream.events binds scope from reservation.accepted_at+60s and server session hash; finally resets context and cancels outstanding compute. No provider signature change.
- [ ] main imports compute router/middleware, startup recover cleanup after chat recovery and safe minute cleanup lifecycle; auth middleware still covers browser writes. migrations/env imports models.
- [ ] Tests GREEN and independent review; root commit this unit.

## Task 4: 真实模型、资源与项目集成

- [ ] Add exact Caddy machine route to deployment candidate and scope queue config to its own runtime; no public deployment. Document HTTPS, credential setup, node start/stop/offline behavior.
- [ ] Use same original virtual資料, realOllama model already on this PC, actual task claim→generation→RAG引用/历史. Test cancellation/offline/restart and inspect late result rejection.
- [ ] Repeat memory budget trial with real queued model and larger PDF/DOCX/concurrent actions, record system/disk/log budgets, limitations. If evidence cannot pass2GiB, hold purchase; do not invent pass.
- [ ] Run node scripts/dev.mjs check and specific model/security/resource checks against finalcode, fresh independent whole-branch review; fix substantive issues and rerun affected checks.
- [ ] Update task/PR and actual evidence, satisfy normal merge rules/localchecks. Only after task actually merged do status closePR; main sync under integration lock.
- [ ] Re-evaluate actual Alibaba quote, provision only after complete resource gate. Any contract acceptance/security access/browser-sensitive step requires action-time handling; no earlier broad approval substitutes it.
