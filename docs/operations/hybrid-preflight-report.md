# 云端业务与本机生成：购买前资源报告

日期：2026-10-21（Asia/Shanghai）
任务：[todo-021](../tasks/todo-021.md)
设计：[云端业务与桌面模型计算](../superpowers/specs/2026-10-21-hybrid-compute-design.md)

## 结论

**小型教学演示的基础资源试验通过，2GiB服务器购买门槛尚未整体通过。**

真实网页路由、注册/登录/会话、角色和知识库成员权限、虚构TXT上传、真实解析/BGE索引、真实BGE查询、历史、统计、审计与退出均通过。第二轮在五个业务容器内存上限合计1376MiB、CPU配额合计2核下重复成功，未见OOM。

生成使用Mock并安全返回no_answer，不能作为回答质量、真实本机计算往返或目标架构交付证据。目前没有生产计算任务队列，也未在独立2GiB系统完成OS/Docker余量、PDF/DOCX、并发和故障验证；服务器、域名、备案和公网部署均未提交。

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
