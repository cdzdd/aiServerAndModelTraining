# 智能客服与知识问答系统

面向企业客服、校园服务、政务咨询的基础可部署系统，采用 Vue 3、FastAPI、PostgreSQL/pgvector 和 RAG。支持用户端、客服端、管理后台，后续接入本地小模型与 QLoRA 实验。

## 当前状态

本仓库提供 FastAPI、Vue 3 和 PostgreSQL/pgvector 基础工程，包括健康检查、审计基础、数据库迁移、测试与 CI。已实现注册/登录、会话、用户管理、角色/资源授权，以及多知识库、成员授权和 FAQ 管理；文档上传、受控下载、后台解析与可恢复入库任务已加入；向量索引、知识检索、问答与公开网站部署尚未实现，任务进展以任务文件为准。

GitHub 仓库：[cdzdd/aiServerAndModelTraining](https://github.com/cdzdd/aiServerAndModelTraining)。首次规划基线已经同步；后续功能通过 PR 验证与合并。

**当前采用本地验收 + GitHub PR。** 本地测试、构建和独立评审通过后按规则合并，云端 CI 暂为手动触发。具体证据与恢复条件见 [WORKFLOW 第 10.1 节](docs/WORKFLOW.md)。

## 本地运行

准备 Node.js 24、Python 3.12、uv 和 Docker，在独立 worktree 配置 `.env`，按 [开发与检查说明](scripts/README.md) 安装依赖并启动。常用入口：

```text
node scripts/dev.mjs db-up
node scripts/dev.mjs api
node scripts/dev.mjs web
node scripts/dev.mjs check
```

前后端分别在两个终端运行；完整检查会自行启动测试服务，运行前先停止开发服务。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [todo.md](todo.md) | 任务索引、优先级、开始开发的入口 |
| [开发前准备清单](docs/PREPARATION.md) | GitHub、开发环境、模型与上线资源的准备方式 |
| [详细分步实现计划](docs/IMPLEMENTATION_PLAN.md) | 阶段、依赖、并行批次、交付与验证 |
| [架构与范围](docs/ARCHITECTURE.md) | 产品范围、技术选择、数据与部署边界 |
| [接口与数据契约](docs/CONTRACTS.md) | 并行开发共用的接口、状态和命名约定 |
| [多对话与 Git 工作流](docs/WORKFLOW.md) | 领取、worktree、验证、合并、GitHub、恢复 |
| [AGENTS.md](AGENTS.md) | 新对话应遵循的项目规则 |

## 如何交给新对话

在这个已保存的项目中打开新对话，并发送：

> 请接手该项目，完成 todo-001 的开发。请读取 AGENTS.md 和对应任务计划，按项目规定领取任务、使用独立 worktree、验证、合入 main 并更新任务状态；如已接入 GitHub，也完成对应 PR 和同步。

新增功能时：

> 请接手该项目，开发功能：在问答页导出我自己的会话记录。先把它登记为新的 todo，明确验收条件和依赖，再按项目规定在独立 worktree 开发、验证、合并并更新状态。

第二段只是后续指令示例，不代表已把“导出”加入本项目范围。新对话不会自动知道旧对话的全部内容，因此以仓库中版本化文档和实时领取记录为交接依据。

## 首轮开发安排

先完成 todo-001。它合入 main 后，todo-002（身份权限）、todo-003（前端框架）、todo-004（模型接口）可以分别交给三个对话。依赖未完成的任务可以阅读规划，不能把尚不存在的接口当作已可用成果。

这三项的用户准备内容见 [下一批任务准备](docs/PREPARATION.md#下一批任务准备)。每个新对话负责自己的端口、数据库与 worktree，不直接复用 001 的 `.env`。

## 规划文件和运行文件

`backend/`、`frontend/`、`infra/` 和 `scripts/` 是 todo-001 的工程基础；`docs/tasks/` 中其余任务描述未来功能，不能把规划中的接口当作已实现功能。具体测试结果、阻塞与合并记录见 [todo-001](docs/tasks/todo-001.md)。
