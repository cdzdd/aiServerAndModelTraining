# todo-022：Ferrari 运维业务交付

| 字段 | 值 |
| --- | --- |
| id | todo-022 |
| 状态 | in_progress |
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
- 具体构建、测试、代码评审、PR、运行包及未测范围随真实执行补充；当前未宣称构建、测试或云端部署成功。
