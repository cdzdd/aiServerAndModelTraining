# 项目接手与协作规则

## 先读什么

每个新对话先读 `README.md`、`todo.md`、`docs/WORKFLOW.md`，再读目标 `docs/tasks/todo-NNN.md`、`docs/ARCHITECTURE.md` 和 `docs/CONTRACTS.md`。跨 worktree 的实时领取记录位于 Git common directory 下 `codex-coordination/`；任务分支上的状态不能替代权威 main 状态。

## 用户已确定的工作方式

- 用户要求多个对话并行开发，每项功能使用独立 worktree，完成验证后合入 `main`，更新任务记录、Git，并在配置 GitHub 后更新远端与 PR。
- 用户说“接手 todo-NNN”即授权该任务正常的实现、测试、提交、推送功能分支、创建 PR、满足检查后合并和任务状态收尾；不必重复询问是否创建 worktree、提交或合并。
- 此授权不包含购买资源、任意生产发布、删库、强制推送、绕过分支保护、丢弃他人修改或公开秘密。远端、账户、费用或需求不明确时只询问具体缺失项。
- 当前批准的是总体方向及规划文件建设。业务代码从用户随后指定的任务开始；本轮没有实现业务功能。

## Think Before Coding

先说明假设与取舍；不隐藏不确定性。多种解释会显著改变结果时先澄清。存在更简单方案时说明。不要把未知的需求默认为已确定。

## Simplicity First

只实现当前任务的验收要求。不要增加未请求的功能、单次使用的抽象、假设性的配置或错误处理。使用单体模块化后端，避免无必要的基础设施。发现可以明显简化时先简化。

## 必须执行的流程

1. 检查仓库、当前分支、worktree、工作区修改和 `origin`；不覆盖未提交修改。读取实时领取记录，核实依赖任务已合入权威 main。
2. 依照 `docs/WORKFLOW.md` 原子领取任务。不得只修改自己分支里的 Markdown 就认为已占用任务。
3. 使用 `superpowers:using-git-worktrees`：已在对应独立 worktree 则复用，否则优先使用 Codex 原生 worktree 工具；仅无原生工具时使用 Git 手动方式。创建后在返回的目录内工作。
4. 已批准任务按其计划执行；新增功能先登记任务、写明范围/接口/验收和实施步骤。使用适用的 brainstorming、writing-plans、executing-plans 或 subagent-driven-development 技能；不因技能模板重复索取本节已经给出的正常流程授权。
5. 按 test-driven-development 完成有意义的行为测试；故障使用 systematic-debugging。文档、格式等低影响更改采用对应静态核对，不编造业务测试。
6. 完成前使用 verification-before-completion、requesting-code-review、finishing-a-development-branch。依本项目已经选定的合并流程执行，不再次展示合并选项菜单。
7. 只有验证通过并实际合入权威 main，才走状态收尾；GitHub PR 等待 CI、审批或排队时保持 `in_review`，不能写成 `done`。
8. 更新本任务文件与必要接口/使用文档，记录真实命令、结果、功能合并 SHA 和 PR；不伪造测试、部署或远端状态。

## 并行工作的边界

- 不在主工作区实现业务，不同时编辑他人的任务目录。worktree 创建失败时解决权限或报告阻塞，不回退到共享主目录开发。
- 端口、Compose project、数据库、上传目录、测试数据、`.env` 按 worktree 隔离；worktree 不会自动隔离外部服务。
- 模块内部文件独立开发；依赖清单/锁文件、数据库迁移图、路由入口和共享契约按 WORKFLOW 协调。不得覆盖他人的依赖或迁移。
- `todo.md` 是索引；每项进度以 `docs/tasks/todo-NNN.md` 为准。每个对话只更新自己领取的任务文件，普通状态变化不重写总索引。
- 不执行 `git reset --hard`、`git clean -fd`、`push --force` 或强制移除 worktree。保留用户修改、未合入分支和主机管理的 worktree。
- GitHub 已接入时所有日常更改走 PR，禁止直接推送 main 或使用管理员绕过。尚未接入时走本地串行合并；如 origin 存在但暂时不可达，不假装为本地模式。

## 验证与技术约定

技术契约在 `docs/CONTRACTS.md`。测试命令由 todo-001 建立，详见各任务。当前文档基线尚无应用、依赖清单或测试框架，不把规划命令说成现有可用命令。

GitHub 接入后以 `origin/main` 为权威；接入前以本地 `main` 为权威。创建/接手 PR 时如工具可用，使用 Codex artifact 工具把 PR 附到当前任务。技能缺失时先检查路径和可用能力，说明情况并遵循已批准的项目流程；不得静默跳过必要验证。

最终回复说明：完成范围、实际验证、分支/提交/PR、main 合并状态、任务状态及未解决阻塞。不得仅以“代码写好了”宣告整个任务完成。
