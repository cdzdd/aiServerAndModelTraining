# todo-022：Ferrari 运维业务交付

| 字段 | 值 |
| --- | --- |
| id | todo-022 |
| 状态 | in_review |
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
- 当前in_review，等待业务PR/合并、正式运维接入PR和状态收尾。ECS/公网均未发布。
