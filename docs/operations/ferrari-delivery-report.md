# Ferrari 业务交付验证报告

日期：2026-10-29。todo-022交付业务适配、冻结运行包及运维接入PR；ECS、基金、DNS、安全组和公网未操作，运维负责人合并和部署。

## 冻结身份与产物

| 项目 | 实际值 |
| --- | --- |
| 业务源码基线 | `8e70a795740003c01280c689eec2729f5cb4de41` |
| 运行包冻结源码 | `8e7c602395ed41e3cc43556a8cfc68be0e05cdee` |
| 构建入口提交 | `ce5feec3c2ee82ba0dec9d17bc2ac53a008a65e6` |
| 运维契约基线 | `a4142436b46e0e972f3926bb0c6168ab7c4290e0` |
| 类型/平台 | `python-pgvector-v1` / `linux/amd64` |
| 外层包 | `knowledge-qa-8e7c602395ed.tar.gz`，644881396字节，仅manifest.json和images.tar |
| 外层SHA256 | `36a2af01268c62dd9d4675bc6ff5a399f4c14af1e12300a4a988ce4ccdc69c77` |
| 经典Docker-save | 2082709504字节；SHA256 `7bd62b6fc61b7bf70df3ea5083c3e6097947f2c5968661819b5393aad832873c` |
| 私有草稿Release | [实际草稿链接](https://github.com/cdzdd/Ferrari_Server/releases/tag/untagged-376448dde4b01aee0245) |
| 交付tag | `artifact/knowledge-qa/8e7c602395ed41e3cc43556a8cfc68be0e05cdee`，target运维main，保持草稿 |

从草稿附件实际重新下载644881396字节并核对相同SHA。链接需有私有运维权限，普通Git克隆不下载附件。后续文档提交不改变该冻结源码；功能合并和收尾另记任务文件，不将包改称另一源码版本。

| 角色/tag | Docker配置ID（非Docker29 OCI index） |
| --- | --- |
| `ferrari-knowledge-qa-api:8e7c602395ed` | `sha256:93cde5c1636c3fcd767d1e995f4dd184977acb3e7d83b8394f14df5f9641b8b2` |
| `ferrari-knowledge-qa-web:8e7c602395ed` | `sha256:de1a3d650730155d9443d8fb7d5daacc9875826b85c6dd43d732c31a21d9b92d` |
| `pgvector/pgvector:0.8.6-pg16-bookworm` | `sha256:9b05db12a35460fff0587e009f9326e414a53e9484555547f96d214a2ba98ef7` |

Python/Caddy/PG基底digest及BGE修订/十文件SHA严格沿契约。BGE在`/opt/models/bge`为普通文件；三个Python角色共用后端，无宿主模型bind、训练环境、桌面权重或真实配置入包。

## 构建与离线验证

Windows、Node24.11.0、Python3.12.14、uv0.12.17、Docker29.8.0；独立worktree、数据库和端口。冻结依赖安装后，将Vitest5.0.1开发工具链兼容升级至5.0.5，npm audit由两项moderate变为0，没有更新业务框架版本。

构建入口先观察缺失入口RED，最终18项部署测试通过（15新增）；真实临时Git/文件覆盖脏版本、私有文件排除、HF链接物化、模型损坏、Docker失败和同名产物拒绝。单测只替代Docker边界，实际构建另行运行。

默认local目标也在没有BGE构建目录的根上下文中实际构建成功；临时本地验证镜像不纳入交付包。

从干净提交执行`python scripts/deploy/ferrari_build.py --model-dir <固定BGE目录> --output-dir .local/ferrari-build-8e7c602`，buildx真实构建两应用并导出三tag。原Docker29导出661488640字节，SHA256 `c964cfad8b2e615016fc485c00b37aba0268fb075c37a2a3b561f318f15d42cb`，因上游PG的SLSA attestation被运维拒绝`Unknown OCI content`；它不是额外可运行架构。原导出/诊断保留，未放宽白名单。

在隔离classic Docker26.1.3导入已知来源的同三镜像，确认配置ID不变后标准save重新导出。运维`package_qa.py`完成装包和真实ID/SHA回填；`validate`、`plan knowledge-qa`、`check-artifact`及随机测试配置的Compose渲染/check_compose通过。离线结果仍为`runtimeVerified=false`。项目Compose将`MODEL_ALLOWED_IDS`修正为JSON数组字符串，公共校验器不变。

新增登记暴露onboarding测试只复制fund目录但继承全部registry的问题：先观察62项中2失败，仅隔离其临时registry为实际复制的fund后，Windows62项60通过/2项Linux专用跳过，独立Linux62项全通过。该三行fixture变更不影响生产CLI、基金或网关。

## 统一业务检查

`node scripts/dev.mjs check`在冻结提交对应树执行exit0：9部署、893后端、44评测、287微调工具（另2平台跳过）、114前端、23浏览器（18+4+1），两次迁移成功；Ruff、lint/typecheck/build通过。浏览器测试使用既有受控RAG，真实模型HTTP验证单列如下。

既有依赖弃用、Node shell/颜色提示及chunk大小告警保留在原始日志，没有伪写零告警。构建任务独立评审Approved；最终分支评审与合并结果见任务记录。

## 真实运行验证

本机既有自有Ubuntu24.04 VMware：2vCPU、2048MiB配置，实际MemTotal2014872KiB、无swap。使用独立socket/data-root的classic Docker26.1.3与Compose2.27.0，不迁移或删除原Docker29数据。静态二进制仅用于本隔离测试；它不是阿里云ECS。运维CLI实际首装本包，验证BGE、卷权限和迁移`021_compute`，启动五服务；通过私有转发的回环5323验收，不是提案18082/18089通道。

| 场景 | 实际结果 |
| --- | --- |
| 三格式入库 | 虚构TXT/DOCX/PDF共3份，parse/index各3成功，文档ready；入库等待6.828秒 |
| 检索和生成 | 原阈值、真实BGE及桌面Ollama，1次answered/1引用，HTTP流10.175秒 |
| 模型身份 | Ollama0.35.0；`qwen3:4b-instruct-2507-q4_K_M`，2497293803字节，digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0` |
| 三角色业务 | 下载摘要、历史隔离、CSRF；转人工/接单/双向消息/关闭，评价/处理/统计通过 |
| 路由 | 健康、SPA深链、API404、未认证计算、未知机器JSON/no-store通过 |
| 取消 | meta后断连为cancelled，重复提交拒绝且无重复助手；不冒充运行中GPU取消压测 |
| 桌面离线 | 停止自有节点并卸载模型，60.22秒按原期限失败，期间健康/身份/知识读取可用 |
| 重启保留 | readiness后3份原文/下载摘要、4条关闭会话历史、原答案/引用和已解决反馈保持，新增生成0 |
| 撤销 | 旧节点`--once`为1/NODE_CLOUD_REFUSED；未回显凭据 |
| 清理与观察 | 1 consumed/2 cancelled，活动任务0，终态非空正文0（JSONB null正确口径）；OOM事件0、末次自动重启计数0 |

五服务限额1568MiB/2CPU，memswap与memory相等。末次资源采样为重启后空闲，不冒充负载峰值；没有验证基金共存、任意20MiB资料或更多并发。

Docker26的cp未取得tmpfs中的节点配置，改为exec捕获到预设0600私有文件，再经SSH与Windows当前用户ACL交付，无终端/日志回显。首次重启后探针过早访问有HTTP_TRANSPORT_ERROR，保留记录，等待readiness再完整通过。初始正文计数误将JSONB null当成非空，修正观察口径后为0；未修改业务数据来消除报告差异。

## 一致备份与隔离恢复

实际执行`backup knowledge-qa --maintenance-window`和`restore-check`，该组47.282秒。停写窗口备份PG及uploads，保留原卷、恢复原运行服务；隔离恢复核对18张表（含迁移表）行数、3上传文件/关联摘要、5向量片段的512维、pgvector0.8.6及迁移`021_compute`。临时对象按归属清理，原库未覆盖。

恢复报告明确`businessDownloadAndRetrievalVerified=false`：这是导入/行数/文件/向量结构检查，未对恢复副本启动全应用执行下载检索。重启保留测试针对原库，不代替恢复副本业务验收；017正式恢复演练仍保留。备份内容只留私有测试目录，不入Git、Release或PR。

## 容量与运维待办

三镜像Size之和2041580961字节，含重复共享层的保守求和。两版不共享、两版包再留一份传输临时包及一次解包估算：`3×644881396 + 2×2041580961 + 2082709504 = 8100515614字节`（约7.544GiB）。不含OS、基金、数据库/uploads/备份增长和额外拷贝，不代表40GiB实机余量已通过。

ID/Compose、2048MiB/2CPU与18082/18089均为提案；ECS现场、磁盘、端口、秘密、管理员、私有通道和新节点交付仍由运维核定。本项目AI不合并运维PR或部署；公网、HTTPS和目标机共存未验证。

## 自主实施取舍

1. Ferrari不在当前workspace，原生工具拒绝其源路径后用Git独立worktree；代价是没有该工作树的原生附件管理。
2. 按已批准契约自审计划直接执行；代价是常规实现选择由本轮评审与版本记录供复核。
3. 纳入Vitest兼容补丁；代价是已执行的完整前端回归。
4. 自有VM使用独立classic26引擎，保留旧Docker；代价是临时VM/磁盘资源。
5. 保留PG attestation失败，经典引擎重导相同ID；代价是额外离线步骤/空间，未放宽校验。
6. 修正临时onboarding登记输入；代价是运维需审阅三行测试fixture，生产校验不变。
7. tmpfs凭据经受控exec、0600文件及加密通道转移；代价是运维必须保留权限和不回显步骤。

原始失败、日志、配置与程序状态保留在任务worktree忽略目录。最终PR、收尾及停止自有服务结果见任务文件。
