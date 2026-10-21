# 云端业务与本机生成：购买前资源报告

日期：2026-10-21至22（Asia/Shanghai）
任务：[todo-021](../tasks/todo-021.md)
设计：[云端业务与桌面模型计算](../superpowers/specs/2026-10-21-hybrid-compute-design.md)

## 最终结论

**购买前技术门槛通过：2核2GiB可作为本项目受控小规模演示的候选。** 云端保留业务、数据库、文件和BGE，本机只通过认证任务处理Ollama生成。最终独立2GiB系统在真实索引/查询、同一客服账号3个并行登录及真实模型回答重叠时，100ms采样最低MemAvailable372.06MiB，无新增OOM或重启；较早448MiB API失败与所有探针误差均保留在后文。

此结论限定于本次虚构资料、单API/单桌面节点、1568MiB资源配置和已测负载。API和索引容器曾触碰硬限额，不能承诺更高并发、任意20MiB文件或云端共享CPU延迟；申请实例后仍需实际云机、HTTPS、备案及公网验收。服务器、域名、备案和公网发布尚未提交。前半部分是2026-10-21基础试验历史，后半部分是最终实现与验收。

完整自主取舍及判断错误的代价见[实施决策记录](hybrid-implementation-decisions.md)。

## 2026-10-21基础试验结论

小型教学演示的基础资源试验通过，彼时2GiB服务器购买门槛尚未整体通过。

真实网页路由、注册/登录/会话、角色和知识库成员权限、虚构TXT上传、真实解析/BGE索引、真实BGE查询、历史、统计、审计与退出均通过。第二轮在五个业务容器内存上限合计1376MiB、CPU配额合计2核下重复成功，未见OOM。

生成使用Mock并安全返回no_answer，不能作为回答质量、真实本机计算往返或目标架构交付证据。该轮尚无生产计算任务队列，也未在独立2GiB系统完成OS/Docker余量、PDF/DOCX、并发和故障验证；服务器、域名、备案和公网部署均未提交。

基于该结果，优先选择云端保留现有BGE、桌面只处理LLM生成任务，避免无证据地增加远程向量队列。

## 环境与版本

- 原生worktree：C:/Users/Administrator/.codex/worktrees/todo-021-hybrid-preflight/aiSoftwareAttempt。
- 业务源代码：origin/main bd1d55d98d18f0a921b993ecad41501f38428a39；后端app以只读挂载使用该版本，本轮不改业务源代码。
- Windows Docker Desktop Linux Engine 29.8.0；底层Docker可用内存约19.53GiB，不是独立2GiB虚拟机。第二轮限额仅针对指定业务容器。
- 后端复用qa-backend:039a7e3a7e28，imageID sha256:83aaa130e727cc1416b707b3289f0005d817d4f02fb854a4e4add378e5e29e1b；Python 3.12镜像和冻结依赖。
- 前端复用qa-web:039a7e3a7e28，imageID sha256:8dbe9df4c5b89220769ac63637d9c1fa27a0c6c0b73f0d347f58911d2f79a01b。未重建当前前端，不能称为本轮完整发布构建。
- 数据库pgvector/pgvector:0.8.6-pg16-bookworm，imageID sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b。
- BGE模型BAAI/bge-small-zh-v1.5，revision 7999e1d3359715c523056ef9478215996d62a620，真实512维，既有只读缓存；无新模型下载。
- 试验项目qa-todo-021-preflight、qa-todo-021-bounded；独立数据库、上传卷、配置，web只绑定127.0.0.1:5241/5242，API和数据库不发布宿主端口。

## 测试负载与实际结果

只使用原创且明确标为虚构的教学资料和随机合成账号，不访问原演示数据库。一个37,910字节TXT，32段，每段395个固定tokenizer token。持久化后核对32个长片段、固定模型/修订、512维向量，覆盖两批batch_size=16编码。

| 检查 | 第一轮 | 受限第二轮 |
| --- | --- | --- |
| 注册/登录、CSRF、会话撤销 | 通过 | 通过 |
| 普通用户访问管理接口、未授权知识库 | 分别403/404 | 分别403/404 |
| 成员授权后读取资料、上传TXT | 通过 | 通过 |
| 真实解析→BGE索引ready | 6.052秒 | 8.075秒 |
| 真实API BGE查询→Mock安全终态 | 3.560秒 | 4.567秒 |
| 两条持久历史、统计、审计、退出 | 通过 | 通过 |
| 桌面真实模型计算往返 | 未执行 | 未执行 |

第一轮另执行既有smoke.py --auth，健康、前端深链接、API404路由、HttpOnly/SameSite、非法CSRF和真实退出检查通过；没有公网HTTPS或Secure Cookie验收。

## 内存与CPU

Docker stats约每2秒采样五个业务容器；第一轮120组、第二轮45组。Docker stats工作集扣除部分可回收缓存，不等同完整宿主物理内存。另读取每个容器cgroup memory.peak和memory.events，避免漏掉短时峰值。

| 服务 | 第二轮硬内存上限MiB | 第二轮CPU配额 | 第二轮cgroup峰值MiB（约） |
| --- | --- | --- | --- |
| API | 448 | 0.75 | 385 |
| parse-worker及解析子进程 | 128 | 0.25 | 100 |
| index-worker | 640 | 0.75 | 567 |
| PostgreSQL | 128 | 0.20 | 95 |
| Caddy/web | 32 | 0.05 | 19 |
| 配额合计 | 1376 | 2.00 | 各进程峰值时刻不同，不能当作同时总峰值 |

- 第一轮同时工作集采样最大889.81MiB。
- 第二轮同时工作集采样最大863.85MiB。
- 两轮所有五个服务的memory.events均为oom=0、oom_kill=0；第二轮读取时max=0。
- 2GiB减去1376MiB留下672MiB仅为系统预算，尚无目标系统实测。Ubuntu、Docker、内核和页面缓存不得默认为零。
- HTTP负载生成器/管理员引导位于另一个临时控制容器，不计入被测五个业务服务，未额外启动BGE或ASGI。常规注册/登录仍由被测API执行。
- 128MiB解析配额仅证明该小TXT负载。PDF/DOCX和原20MiB文件上限没有在此配额通过，不能直接复制为生产默认。
- 索引与查询本轮串行，未证明并发峰值；CPU配额不复现阿里云通用型资源争抢或公网网络。

## 实际命令与证据

命令在上述独立worktree运行；配置与可丢弃探针保存在ignored .local，不含生产凭据，未纳入产品源码。

~~~text
docker compose -p qa-todo-021-preflight --env-file .env -f infra/compose.local.yaml -f .local/preflight.override.yaml run --rm --no-deps api alembic upgrade head
docker compose -p qa-todo-021-preflight --env-file .env -f infra/compose.local.yaml -f .local/preflight.override.yaml up -d --no-build --pull never api parse-worker index-worker web
docker exec qa-todo-021-preflight-api-1 python /app/scripts/deploy/smoke.py http://web:8080 --origin http://127.0.0.1:5241 --auth
docker compose -p qa-todo-021-preflight --env-file .env -f infra/compose.local.yaml -f .local/preflight.override.yaml run --rm --no-deps -e PYTHONPATH=/app/backend api python /probe/resource_probe.py --expected-database qa_preflight
docker compose -p qa-todo-021-bounded --env-file .local/bounded.env -f infra/compose.local.yaml -f .local/bounded.override.yaml up -d --no-build --pull never --wait --wait-timeout 60 db
docker compose -p qa-todo-021-bounded --env-file .local/bounded.env -f infra/compose.local.yaml -f .local/bounded.override.yaml run --rm --no-deps api alembic upgrade head
docker compose -p qa-todo-021-bounded --env-file .local/bounded.env -f infra/compose.local.yaml -f .local/bounded.override.yaml up -d --no-build --pull never --wait --wait-timeout 60 api parse-worker index-worker web
docker compose -p qa-todo-021-bounded --env-file .local/bounded.env -f infra/compose.local.yaml -f .local/bounded.override.yaml run --rm --no-deps -e PYTHONPATH=/app/backend api python /probe/resource_probe.py --expected-database qa_preflight_bounded
~~~

上述两次正式探针均exit0。第一次探针启动未设置PYTHONPATH，无法导入app，在写数据前失败；设置正确模块搜索路径后通过。第二轮首次数据库未就绪即迁移，连接拒绝；改为等待数据库healthy再迁移后通过。没有以更改业务代码、重置卷或删除数据解决。

本机原始证据：.local/resource-probe.log、resource-stats.jsonl、resource-peaks.json、resource-summary.json，以及bounded-*对应文件。探针SHA-256为635c5376d99fd6b75131ed4c8840b623c690073a3580596d824c7e2a3dc5859b。原始日志保留在worktree，不向GitHub上传凭据、Cookie、问题正文或提供商输出。

本轮版本化修改仅为任务、设计和报告文档，做diff、链接与事实核对；未运行统一node scripts/dev.mjs check，不将运行探针称作完整代码回归或云端CI。

## 后续购买门槛

需实现并验证机器认证计算任务、真实Ollama往返、取消/离线/迟到结果/重启；补足文件类型和并发峰值、系统预算、磁盘/日志。完成本地检查和独立评审后，再重新核对0元商品及券，进入服务器申请、域名实名和备案流程。

官方支持针对云端实际承载业务、本机只通过认证HTTPS领取有界模型任务，于2026-10-21 23:05回复“服务器侧本身不限制”。不将此等同ICP备案通过，也不放行原frp-only方案。官方通用型适用于小型Web应用，CPU/带宽有争抢波动，见[实例规格](https://help.aliyun.com/zh/simple-application-server/product-overview/instance-families/)与[使用须知](https://help.aliyun.com/zh/simple-application-server/product-overview/usage-notes)。

## 2026-10-22 实现与真实模型检查

用户已审定PR40设计，并授权自主计划、开发和验证。实现代码76bdcd5d3ef2996223183d575a19c4dc0885c637包含PostgreSQL持久生成队列、认证机器API、桌面Ollama节点、queued Provider及云端RAG接入；上述历史基线的Mock结果不再代表本阶段全部验证。

完整本地入口 `node scripts/dev.mjs check` exit0：部署脚本9项、后端879项、评测44项、微调287项、前端114项、浏览器18+4+1项。微调另2项因Windows/Python环境条件跳过（Linux PDEATHSIG与独立Trainer环境）；既有Starlette、Node和前端包体警告保留。统一检查不是云端CI。兼容安全补丁Vite8.3.5与source-map-js1.2.2后npm audit为0；Caddy实际校验通过。

独立数据库qa_hybrid_preflight、API127.0.0.1:8142，只使用虚构资料和随机账号。TXT32×395token、DOCX64段、PDF12页实际解析后分别得到32/64/24个固定BGE向量片段。首次自然短问题与高密度合成段落余弦最高0.466120，低于原0.65，正确保存no_answer且ComputeJob为0；该记录保留，不能当作模型调用成功。

补充简短虚构知识条目（2片）后，同一自然问题余弦0.811162，未调整阈值。真实Qwen3:4b-instruct-2507-q4_K_M经认证队列、桌面Ollama0.35.0完成回答4.585秒；SSE meta/delta/citations/done，云端引用复核通过，历史2条complete、1个引用。任务6fbb23de-16dd-46c5-9f7b-f623fa811ab5为consumed，payload/result已清空并保留digest。模型digest为0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0；未重新下载模型。

三个实现单元和时钟/重复取消修复均有独立评审；最终全分支评审发现跨用户清理与登录的锁循环，其修复、复核以及离线/停止/重启实测见后续记录。服务器/域名均未购买。

### 故障与恢复实测

- 桌面离线时，健康、已登录资料访问及新登录仍可用；浏览器停止（SSE断开）把未领取任务清空为cancelled，历史为cancelled/CANCELLED，不生成引用。
- 独立离线请求在60031ms以现有外层RAG_TIMEOUT结束；唯一任务清空为cancelled/COMPUTE_REVOKED。没有调大60秒期限或自动补跑。探针最初仅预期PROVIDER_TIMEOUT，已依据现有RAG外层超时修正为允许合法的两种超时竞争结果；原始失败日志保留。
- 实际Ollama任务进入running后停止：156ms内历史cancelled/CANCELLED；任务正文清空且无结果digest；桌面实际迟到/result为409，报告NODE_CLOUD_REFUSED并exit1，没有下一次claim。Ollama日志先出现新任务、随后all slots are idle，未将HTTP流关闭本身当作GPU停止证明。
- 在最终修复候选上，只中断本试验API8142，保留解析/索引/Ollama。实际遗留running任务在启动后被撤销、正文清空；历史failed/PROCESS_RESTARTED，唯一generation.recover审计存在；原租约heartbeat和result均实际409。新API健康，未重跑旧任务。
- 探针曾误查/health而得到404，改为实际/health/live；没有更改产品路由来迎合探针。所有harness误差均在原日志中分类保留。

### 最终代码修正

最终评审发现的跨用户清理/登录锁循环已以真实PostgreSQL复现DeadlockDetected，随后修正为清理只做刷新后的非锁定授权读取、实际交付和消费继续持授权锁。提交04f6c418b3aa34310e6920ec2f187f1fcd91e4a9：针对性11项通过，完整后端878项通过（原879减去2项不再适用的清理Message锁等待场景，加1项双用户登录回归），Ruff及diff检查通过。

最初沙箱完整后端为876通过/2失败，均是Windows私有文件ACL测试中的沙箱身份与Administrator差异；相同2项及完整后端在实际Administrator权限分别2通过、878通过，未排除测试或削弱私有权限。最终修复经独立范围复核，原P2判为ADDRESSED且无新增问题；资源、购买和公网验收不在该代码复核结论内。

### 独立2GiB系统第一轮：尚不能放行

在独立Ubuntu24.04软件模拟机内实际限定2048MiB/2vCPU，Linux可用总内存1966MiB、无swap，五个服务硬上限合计1504MiB。固定镜像和BGE快照实际传入，数据库初始化、迁移、全部服务健康及网页/机器路由检查通过；四份资料均实际解析成功。

实际BGE索引路径出现两次本地库退出139，内核指向NumPy的_multiarray_umath；自动重启后的当前OOMKilled=false不能用来抹去历史，因此另查Docker历史事件、持续事件流及完整内核日志。现有108组采样最低MemAvailable990.30MiB，没有观测到OOM事件；两次139与随后人为停止143分开记录。小型隔离NumPy测试通过，不能据此断言完整BGE崩溃的具体归因。QEMU8.2.2/TCG CPU=max的模拟结果不足以判定目标服务器稳定性，本轮2GiB整机门槛不通过。

本机QA数据库桥曾因300秒空闲超时关闭，导致首次seed连接失败；添加SSH20秒保活后SQLping0.405秒、重试seed成功。该传输仅连接本机试验虚拟机、数据均虚构，不是公网部署方案。QEMU及固定本地试验中继的资源在被测guest外，未冒充云端业务占用。

保留原系统、卷、日志、崩溃及未完成索引记录；正在使用电脑已安装的VMware尝试另一独立2GiB环境，并以原生Linux容器分辨完整应用链路与模拟CPU问题。没有通过停用阈值、替换Mock、删除失败记录或下单真机来冒充本轮验证。

## 原生Linux容器对照

代码04f6c418b3aa34310e6920ec2f187f1fcd91e4a9对应两次独立后端构建：原生容器使用12位标签04f6c418b3aa、镜像sha256:26a3d145ee53e5582a4f97ad7fcbe26f84433031614202d5ba7119e306c6e114；VMware使用11位标签04f6c418b3a、镜像sha256:f149459bf0f17ca734288409f5acce2970f51ab6add9ba59817989185d626524。标签长度差异导致原生Compose另建镜像，不能称为同一构建的不同平台摘要。逐一核对两套镜像115个受版本控制的应用、迁移、alembic.ini及smoke文件，规范化CRLF后SHA256均与04f6c41一致，零差异；前端与76bdcd5相比无源文件或infra差异，实际镜像sha256:6e218716ffada1ae7d967e62ab770853dd345c9f32bf053dba9da8a63c5d9b26。数据库仍为上文固定PG镜像。

qa-todo-021-native-final在Docker Desktop原生Linux内核上，以1504MiB容器总上限完成真实TXT/DOCX/PDF索引与队列模型回答8.626秒，1个复核引用、2条完整历史、任务消费后正文清空；真实索引与同一客服账号3个并行登录请求通过，登录1.593–1.609秒。13组采样及历史事件未见OOM、异常退出或重启。各容器cgroup峰值MiB分别为API424.65、解析105.31、索引580.93、数据库97.15、web18.69；这些峰值不同时发生，不能求和冒充整机峰值。对照使用原生Linux验证完整应用链路，不能替代独立2GiB系统验收。

此对照的临时摘要最初保留了容器首次Created状态而非最终状态；已按最后原始采样修正，并保留first_observed/last_observed说明，未修改原始采样/事件。模型缓存无需重新下载；缺失构建依赖轮子后按正常网络构建，不能称完全离线构建。

## 硬件加速2GiB系统：定位API配额不足

使用本机已有VMware Workstation，在独立Ubuntu24.04中配置2048MiB/2vCPU、20GiB系统盘。实际MemTotal2014872kB（约1967MiB）、SwapTotal0，Docker29.1.3/Compose2.40.3；不改变Windows功能、不安装新虚拟化软件、不重启宿主。外部负载发起器与GPU模型不占该guest内存，符合云端业务/外置桌面生成的边界。

同一最终代码镜像在qa-todo-021-vmware独立库完成32/64/24/2片真实索引和首个模型回答12.282秒，任务4cf187d6-ee0d-4440-9041-4d77608b8cf4为consumed，1个复核引用、2条完整历史且任务正文清空。机器入口实际得到认证401、未知路由404JSON、65537字节413和no-store；浏览器非法CSRF403。

2026-10-21T17:13:20Z真实索引、提问和3个并行登录请求重叠时，原448MiB API配额触发Docker oom事件，17:13:21.382Z退出137并重启。内核CONSTRAINT_MEMCG指向API容器，证明容器配额不足；并未证明整机OOM。失败会话保留PROCESS_RESTARTED，没有领取/调用额外模型；首个成功记录保留，未删库重试。

原采集器在此时被多次sudo cgroup读取拖慢，缺少该瞬间有效的20秒整机采样，不能编造最小MemAvailable；历史Docker事件和完整内核证据仍有效。已去除不必要的sudo，并将磁盘特权采集独立，后续样本实际约21–23秒间隔。

最终候选将API增至576MiB、解析从256减至192MiB，索引640、数据库128、web32MiB保持，总上限1568MiB/2CPU。实际guest、版本化budget叠加配置及OMP_NUM_THREADS=1保持一致；不修改密码哈希强度、检索阈值或60秒期限。该调整尚须完整复测通过，不能仅靠上限相加放行。

### 576/192首次复测及采样缺口

17:27:49.399146Z至17:28:09.549374Z，新增串行回答12.625秒；17:28:06.308066Z确认真实索引已running后，同时发起新提问与同一客服账号3个并行登录请求。3个登录均0.594秒成功，提问0.953秒完成真实队列模型调用；两次回答均1个复核引用/2条历史，任务消费且正文清空。前一个成功与PROCESS_RESTARTED失败历史前后保持一致，结束无活动任务，节点在Ollama空闲后停止。

17:30:47.790768Z至17:31:08.305778Z，在192MiB解析上限新上传三种唯一文件名的虚构资料：TXT32片、DOCX64片、12页PDF24片，所有实际parse/index任务均第1次成功，固定BGE修订/向量核对通过，未调用模型。不是复用256MiB下的解析结果。

上述稳定新配额阶段未见新Docker OOM/异常退出/重启，五服务RestartCount0，cgroup oom/oom_kill均0。但API与index memory.events.max分别423和176，说明触碰硬限额并发生回收压力，不能写为从未触限或有充足容器余量。19个低频整机样本的最小MemAvailable656.55MiB出现在17:28:10Z，晚于核心负载结束约0.451秒；两个约20秒负载窗口内均无整机样本，因此不能把该值冒充并发瞬间余量。追加一次同配置负载，以独立100ms轻量/proc/meminfo采样补证；不改变资源或业务设置。

## 最终高频采样验收

第一次高频复测17:38:34.873345Z至17:39:41.095435Z只完成串行真实模型，随后因探针重用固定文件名/内容，产品正确去重返回旧ready文档2dc5fd53，无法观察新索引running而失败。已核对该文档原索引在17:28:09.318145Z成功；不是产品索引故障。保留失败记录，仅将探针改为唯一文件名、原16个长片段并断言返回新ID，没有增加128片负载或修改产品。

最终有效HF2负载为2026-10-21T17:44:58.177246Z至17:45:31.697812Z（本地2026-10-22），同一数据库/配置/模型，10条既有消息包括先前失败记录的摘要前后完全一致：

- 串行真实Qwen回答2.469秒；确认全新文档36623261索引running后，再发提问与同一客服账号3个并行登录请求，回答1.656秒，登录0.531/0.578/0.578秒。密码验证实际发生在账号行锁之前；不把同一账号说成3个独立用户。
- 两次新回答均1个云端复核引用、2条完整历史；真实任务34840198与26da168a消费后payload/result清空。结束活动任务0，桌面节点在实际Ollama空闲后停止。
- 在192MiB解析上限再次新上传TXT32片、DOCX64片和12页PDF24片，实际parse/index均第1次成功；固定BGE修订和512维向量一致，解析阶段不调用模型。

轻量采集器仅每100ms读取/proc/meminfo，同时保存guest UTC与单调时钟；其自身、Ubuntu、Docker及内核开销包含在被测2GiB内，不把桌面GPU或外部负载发起器计入云端。完整日志6215行，本次有效窗口336个样本，无大于200ms的采样间隙。

| 窗口 | 实际样本数 | 最小MemAvailable MiB | 最大样本间隔ms |
| --- | --- | --- | --- |
| 全部有效负载33.52秒 | 336 | 372.06 | 101.123 |
| 串行及并发问答 | 99 | 372.06 | 101.102 |
| 索引/提问/登录重叠段 | 16 | 372.06 | 100.054 |
| 三格式解析/索引 | 218 | 400.23 | 101.123 |

最低样本发生在17:45:07.383485Z，确实位于并发段；所有样本MemTotal2014872KiB且swap为0。这是100ms采样下的观测最小值，不是连续时间的数学下界。两侧边界间隙和单调时钟间隙保存在原始摘要，不隐藏较早低频窗口无样本的问题。

五个容器ID保持一致、RestartCount及本轮增量均0；新增Docker OOM/异常生命周期事件0，全部cgroup oom/oom_kill与增量0，稳定配额阶段内核未见OOM或本地库崩溃。API memory.events.max维持423（本轮增量0），索引176增至205（增量29）；触限/回收压力与OOM分别记录。

| 服务 | 硬上限MiB | cgroup累计memory.peak MiB |
| --- | --- | --- |
| API | 576 | 576.008 |
| 解析 | 192 | 111.559 |
| 索引 | 640 | 640.000 |
| 数据库 | 128 | 97.328 |
| web | 32 | 16.215 |

峰值不在同一时刻，且索引/数据库/web cgroup早于本轮存在，不能相加作为整机峰值。触顶说明需按已测演示负载运行；未通过修改内存计数或忽略回收事件制造余量。

最终guest文件系统使用4,992,040,960字节、剩余14,673,739,776字节；五个容器实际JSON日志合计221,835字节，轮转配置5m×2已与HostConfig核对。这不限制数据库/上传卷增长，也不是长期磁盘压测或备份恢复验收。

### 对应配置、命令与证据

最终应用代码04f6c418b3aa34310e6920ec2f187f1fcd91e4a9。guest实际API/解析/索引image为f149459b…，web6e218716…，数据库ccc6e83d…；完整摘要见前文。版本化[资源叠加配置](../../infra/compose.hybrid-budget.yaml)的SHA256为aad0bdfc7922f51f3fee57207dc4638cc84e889aae0dd855489e406f32cefbe1，实际五服务memory/swap/CPU/logging及三个OMP=1逐项一致。它仅叠加资源/线程/日志，不改变基础本机启动默认、路由、权限、数据库或镜像选择。

实际最终探针入口为任务worktree中的ignored .local/vmware_hf_final.py，使用本任务冻结后端Python与独立vmware-runtime.env，PYTHONPATH指向backend；仅允许loopback18546/16574及qa_hybrid_vmware_preflight，实际运行并输出functional_success=true。虚拟机内通过固定SSH host key的私有NAT连接运行，网页/数据库宿主桥均只绑定127.0.0.1。它是本地QA测量连接，不是公网转发方案。

实际静态入口为 `docker compose --env-file .local/native-final/compose.env -f infra/compose.local.yaml -f infra/compose.hybrid-budget.yaml config --format json`（输出只在私有文件检查，不公开凭据）以及 `git diff --check`、Markdown本地链接核对。统一代码检查与04后端回归对应关系见前文；最终新增资源设置运行了上述受影响的完整真实链路，没有将旧Mock/879结果冒充最终878或云端CI。

本机证据包括.local/vmware-hf-final2-result.json、vmware-retry-hf-final2-result.json、vmware-parse192-hf-final2-result.json、各自.log、.local/vmware2g/app/highfreq-final-resource-summary.json，以及evidence/os100ms-20261021T173641Z.jsonl、历史Docker事件、前后cgroup/镜像/内核快照。所有秘密、Cookie、正文和原始提供商输出不随PR上传。操作方式见[手册](hybrid-compute-runbook.md#2gib演示资源配置)。
