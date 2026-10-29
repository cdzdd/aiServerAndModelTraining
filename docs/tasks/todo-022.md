# todo-022：Ferrari 运维业务交付

| 字段 | 值 |
| --- | --- |
| id | todo-022 |
| 状态 | done |
| depends_on | todo-021；复用016本地阶段；Ferrari_Server PR13契约 |
| 范围 | 业务镜像适配、真实隔离验证、离线包和运维接入PR；不合并运维PR、不部署ECS |
| 分支 | codex/todo-022-ferrari-delivery |

2026-10-29 用户授权按最新发布契约自主完成业务交付，运维负责人合并和部署。设计与实施步骤见[计划](../superpowers/plans/2026-10-29-ferrari-delivery.md)。

## 验收与接口

- 保持本地运行入口，固定BGE入Linux后端镜像，满足五服务、只读运行、CPU依赖及模型身份契约。
- 独立worktree完成统一检查与真实TXT/DOCX/PDF、BGE、queued/Ollama、引用/历史和故障验证；恢复在独立库/卷，结果如实记录。
- 从真实提交构建，包、镜像ID和摘要可核对，可通过私有草稿Release接收；运维PR提供完整配置与维护/恢复/容量说明。
- 业务变更经本地验收、独立评审、PR与main状态收尾。本任务done只表示交付完成，不改变016/017公网状态；运维PR实际合并/发布另记。

## 工作记录

- 原子领取todo-022，业务基线origin/main 8e70a79；Ferrari基线a414243。创建原生业务worktree及运维独立Git worktree；原生工具不接受非当前workspace的Ferrari源目录，故运维使用Git worktree回退。
- 端口API8122、web5322、DB15482、独立容器入口5323；数据库、上传、环境及节点凭据均独立。Docker Desktop按需启动，既有容器按原重启策略恢复，未修改或清理它们。
- 初始登记时尚无本轮构建或测试成功声明；后续实际结果见下节，云端部署始终排除在本任务范围。

## 业务与产物验收

- 构建入口ce5feec，专项18通过、独立任务评审Approved；冻结源码8e7c602395ed41e3cc43556a8cfc68be0e05cdee含Vitest5.0.5补丁，npm audit0。
- 统一检查exit0：9部署、893后端、44评测、287微调工具（另2平台跳过）、114前端、23浏览器；真实环境、命令及告警见[交付报告](../operations/ferrari-delivery-report.md)。
- 镜像真实构建，PG attestation导出失败保留，classic26重导相同ID后通过运维校验。外包644881396字节、SHA256 `36a2af01268c62dd9d4675bc6ff5a399f4c14af1e12300a4a988ce4ccdc69c77`，私有草稿上传/重新下载核对通过。
- 运维validate/plan/check-artifact、Compose渲染/契约通过；Windows62项60通过/2跳过，独立Linux62全通过。onboarding夹具新增登记的2失败经三行输入隔离修正，生产CLI不变。
- 自有2GiB/2vCPU VM、Docker26.1.3/Compose2.27.0实际首装该包到021_compute。真实三格式/BGE/桌面生成/引用、三角色闭环、取消/重复、60.22秒离线、重启保留及撤销通过；活动任务和终态非空正文0。
- PG+uploads同窗口备份及隔离restore-check通过18表/3文件/512维关联；恢复副本应用下载检索未测，不能替代017正式恢复验收。OOM事件0/末次自动重启0，不作容量压测结论。
- 整体业务分支评审Ready to merge，无P0/P1/P2；P3依赖起始版本文字已于653d591修正并经范围复核Addressed。冻结源码后只有文档变化，默认local目标也已实际构建通过。
- 功能评审提交阶段为in_review；实际GitHub交付及本次状态收尾见下节，ECS/公网均未发布。

## GitHub交付与状态收尾

- 业务[PR42](https://github.com/cdzdd/aiServerAndModelTraining/pull/42)已于2026-10-29T07:13:47Z普通squash合并，功能SHA `6c3ba54e716a54ce820ff4e36e8429c6622cb607`，已验功能头 `87989385e53f86f611c1acefc02e825e9eec1e24`；合并树与已验头一致。冻结包源码8e7c602保持原身份，源分支保留可取。
- 草稿Release编辑说明后untagged页面位置发生变化，tag和附件身份/大小不变；纯文档[PR43](https://github.com/cdzdd/aiServerAndModelTraining/pull/43)于2026-10-29T07:27:47Z合并，SHA `9a21c8b9888618669810ebb04882b442a5030dd7`，改用固定交付tag和实际运维PR作为长期入口。该取舍增加一个文档PR，避免过期草稿页影响接收，不发布Release来固定网址。
- 正式运维接入[PR14](https://github.com/cdzdd/Ferrari_Server/pull/14)已提交并附到对话，当前头 `46ced439918b884bc805fd195fb3f9b6d380b769`、OPEN/DRAFT；包含真实Compose/release/env示例、登记提案、交接和三行onboarding测试fixture修正。资源、端口和ECS发布前核查待运维负责人确认；其后由负责人合并、部署、初始化及验收，本项目没有代为合并或部署。
- 私有草稿tag `artifact/knowledge-qa/8e7c602395ed41e3cc43556a8cfc68be0e05cdee` 的实际包已认证上传、重新下载并经运维CLI校验；大小644881396字节、SHA256 `36a2af01268c62dd9d4675bc6ff5a399f4c14af1e12300a4a988ce4ccdc69c77`。取包入口及最新实际草稿页见PR14；包、账号、节点凭据、备份均未进入Git。
- 验收采用本地验收+GitHub PR。业务云端CI未运行；运维最新头的push/PR运行均startup_failure，已在PR14记录真实链接与本地/独立Linux证据，未冒充CI通过或绕过强制门禁。
- 已停止本轮五服务、开发数据库、桌面节点、私有转发和自有Ollama（确认模型卸载后）；自有独立26引擎停止、测试VM已关机。保留原卷、VM磁盘、冻结包、原始失败和评审证据，以及业务/运维工作树；未对其他项目执行清理。
- 本收尾只更新本任务文件，经静态事实/链接核对和独立文档复核后普通PR集成。只有该收尾实际进入origin/main，本任务权威状态才为done；不记录自身收尾SHA以免自引用。done表示业务与产物/PR交接完成，运维PR及ECS/公网状态继续独立记录，不改变016/017状态。
