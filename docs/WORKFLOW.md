# 多对话、worktree 与 Git/GitHub 工作流

## 1. 适用范围和预先授权

用户希望以后只说“请接手 todo-NNN”或“开发新功能并加入 todo”，对话就完成从任务登记到分支合并的正常流程。本文件把这个要求保存到仓库，供新对话读取。

指定任务已经授权：领取、隔离开发、测试、代码评审、commit、推送功能分支、创建 PR、符合仓库规则后合并、更新任务状态和同步。`main` 是默认集成分支。使用 Superpowers 的 worktree、执行计划、验证、评审和分支收尾能力；用户已选定合并方式，不重复展示技能中的选择菜单。

尚未授权的动作仍单独处理：付费资源购买、未指定的生产发布、改变仓库公开性、数据删除、强推、绕过检查或删除未合入成果。服务端要求他人审批时等候该审批，不自批、不绕过。

这些文件是执行规则，不是已安装的自动化守护程序。每个接手对话必须按规则操作；未来 GitHub 分支保护与 CI 提供服务端约束。依赖未装、权限不足、远端未提供时应明确实际阻塞。

**当前验收模式：本地验收 + GitHub PR。** 用户于 2026-09-22 明确授权临时采用此模式，原因是 GitHub Actions 因账号账单限制不能启动。执行细则见第 10.1 节；保留远端 `origin/main` 作为权威分支。该授权替代“必须等待云端 CI”的项目要求，不授权跳过本地失败、代码评审或服务端强制保护。

## 2. 三种事实来源

1. **已集成的代码与任务状态：** 有 origin 时是 `origin/main`；确实未配置 origin 时是本地 `main`。已配置但网络失败不等于“无远端”。
2. **进行中的开发进度：** 任务分支里的 `docs/tasks/todo-NNN.md`、提交和 PR。
3. **本机实时领取/协调：** Git common directory 下 `codex-coordination/`，所有 worktree 共享。记录不进 Git，不上传 GitHub，不能存秘密。

不同 worktree 各有一份 Markdown，修改自己的任务文件不会立即通知其他对话。因此领取不能仅靠 Markdown 状态，也不能把分支上的 done 当作已集成事实。

## 3. 接手检查

先读 AGENTS、README、todo索引、目标任务、架构/接口契约，检查：

```powershell
git status --short --branch
git remote -v
git worktree list --porcelain
git rev-parse --show-toplevel
git rev-parse --git-dir
git rev-parse --git-common-dir
git rev-parse --show-superproject-working-tree
```

有远端则 fetch 并检查最新 origin/main、PR、依赖任务；没有远端记录本地模式。不要切换有未提交修改的主目录；不要自行 stash 用户文件。读取协调记录，确认同一任务没有其他活跃负责人。

目标任务的依赖必须已经合入权威 main。未就绪时可以准备本任务设计，但不宣称依赖功能可用；如用户只指定该任务，则报告精确依赖，不擅自把前置任务全部纳入范围。

本轮从空目录建立规划基线允许在主目录一次性初始化 Git。以后业务开发均使用独立 worktree。

## 4. 原子领取与本机协调

### 4.1 目录和记录

通过 `git rev-parse --git-common-dir` 解析真实绝对路径，不能硬编码当前 worktree 的 `.git`（linked worktree 中它是文件）。所有对话使用同一个 common directory。

```text
<git-common-dir>/codex-coordination/
  claims/todo-002.json        长期任务领取，持有至收尾或显式交接
  locks/registry.json        任务编号和共享登记短时互斥
  locks/integration.json     集成main和状态收尾的短时互斥
  locks/shared-files.json    修改锁文件/共享契约等的短时互斥
```

领取记录包含：`task_id, owner_token, owner_description, thread_id(可用时), claimed_at, heartbeat_at, branch, worktree_path, stage, ports, note`。owner_token 是随机UUID；thread_id未知时留null，不编造。时间是UTC。领取成功后才创建worktree；创建失败更新stage并保留可恢复信息。

使用 **FileMode.CreateNew** 原子创建锁文件。检查不存在后再普通写入存在竞争，禁止使用。下面是 PowerShell 原理示例，接手时填入真实任务/拥有者；不是已经存在的项目脚本：

```powershell
$commonPathText = (git rev-parse --git-common-dir).Trim()
$commonPath = (Resolve-Path -LiteralPath $commonPathText).Path
$coordinationPath = Join-Path $commonPath 'codex-coordination'
$claimsPath = Join-Path $coordinationPath 'claims'
[IO.Directory]::CreateDirectory($claimsPath) | Out-Null
$taskId = 'todo-002'
$ownerToken = [guid]::NewGuid().ToString()
$claimPath = Join-Path $claimsPath ($taskId + '.json')
$claim = @{ task_id=$taskId; owner_token=$ownerToken;
  owner_description='当前接手对话'; thread_id=$null;
  claimed_at=[DateTime]::UtcNow.ToString('o');
  heartbeat_at=[DateTime]::UtcNow.ToString('o');
  branch=$null; worktree_path=$null; stage='claimed'; ports=@{}; note='' }
$claimStream = [IO.File]::Open($claimPath, [IO.FileMode]::CreateNew,
  [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
  $bytes = [Text.Encoding]::UTF8.GetBytes(($claim | ConvertTo-Json -Depth 4))
  $claimStream.Write($bytes, 0, $bytes.Length)
} finally { $claimStream.Dispose() }
```

CreateNew 失败先读取现有领取记录，不覆盖。碰到正在写入的短暂独占或不完整JSON，稍后重读；不能当作空记录重新领取。只允许owner_token匹配的对话更新/释放记录。

短时锁也使用上述CreateNew方式并写入拥有者；持锁期间串行完成对应操作，finally释放自己的锁。锁文件跨工具调用保持占用，不依赖某个已经退出的shell进程持有文件句柄。不能只锁第一条命令，之后无锁合并。

### 4.2 恢复与新任务编号

- 领取文件没有自动超时抢占。时间较久不证明任务已停止；先查看对应对话、分支、worktree、PR和未提交文件。
- 原对话恢复时核验owner记录并续接。其他对话接手须确认原负责人停止或用户明确转交，保存旧记录后在registry锁下转移拥有者。
- 新功能：持有registry锁，扫描权威main、现有任务分支和claims中的最大编号，分配下一个三位编号（当前预留到018，下一项从019开始），原子创建claim再释放锁。
- 在新功能分支创建 `docs/tasks/todo-NNN.md` 并把范围/验收/依赖写清，同时更新todo索引。实时登记包含该文件位置，其他本机对话据此发现尚未合入的新任务。
- 不要把同一台机器的协调文件当作跨机器锁。新增第二台开发电脑时，先增加GitHub Issue领取/集成协调机制；本计划的并行范围是同一工作区及其worktree。

短时registry/integration/shared-files锁也可能因对话中断遗留。恢复它们时，先核验记录中的原负责人已停止、相关Git操作没有进行，并由用户明确指定一个恢复对话、暂停受影响的并行任务。该恢复者把旧锁原子改名到带时间和原owner_token的归档文件，随后重新CreateNew领取；不能删除其他对话后来新建的同名锁。恢复registry锁自身不要求先取得它；依靠上述单一恢复者和暂停约定完成。不得只看文件时间或进程号就自动抢锁。

## 5. 创建和复用 worktree

遵循 `superpowers:using-git-worktrees`：

1. 先区分普通checkout、linked worktree和submodule。已在本任务独立worktree时复用，不套一层worktree。
2. 优先调用Codex原生worktree工具，从最新权威main对应commit创建。工具返回目录不一定在项目根下，后续操作明确使用返回目录。
3. 原生工具可能给出detached HEAD。创建本任务命名分支后再提交，例如 `feat/todo-002-auth`；如果平台限制命名分支，使用平台支持的分支/PR流程并记录真实状态，不直接清理该工作区。
4. 只有平台没有原生工具时，使用忽略目录 `.worktrees/` 下的Git手动worktree，先检查 `git check-ignore .worktrees/probe`，再从权威main创建命名分支。
5. 分支名 `feat/todo-NNN-short-name`，修复用 `fix/`，文档用 `docs/`；短名由任务含义决定。不得复用另一个活跃任务的分支。
6. 创建失败先解决沙箱/目录权限。用户明确要求隔离开发，因此不得静默回退共享主目录。

示例（只适用于无原生工具的回退）：

```powershell
git worktree add .worktrees/todo-002-auth -b feat/todo-002-auth main
```

有远端时基点改为刚fetch的 `origin/main`。若分支/目录已存在，检查是否为本任务可恢复现场，不强行覆盖。

## 6. 开发运行环境隔离

每个worktree有自己的前端node_modules、后端.venv、`.env`、上传数据目录、Compose project和数据库卷。模型只读缓存可共享，但可写训练输出与实验配置隔离。

创建worktree后，在registry锁下分配并记录空闲端口。例如首次可从API 8101、Web 5201、DB 15433依次分配，必须检查占用；不根据编号盲目假定端口可用。Compose project使用 `qa-todo-002-<随机短码>`。

Compose 文件不能硬编码 `container_name` 或复用无前缀的外部数据库卷。容器内数据库端口仍5432；主机映射端口按worktree配置。启动/停止都指定本worktree的Compose project和env文件。不要执行会影响其他任务的全局容器清理。

todo-001实现跨平台启动/检查说明及必要小脚本。数据库迁移和测试只能连接本任务数据库，不能借用生产连接串。生成的模型权重、上传资料、API Key不得提交。

## 7. 任务状态与开发步骤

状态只有：`planned_optional`、`pending`、`in_progress`、`blocked`、`in_review`、`done`。

| 状态 | 含义 |
| --- | --- |
| planned_optional | 条件任务，用户选择对应能力后再执行 |
| pending | 已规划、未领取开发 |
| in_progress | 已领取且在任务分支实施 |
| blocked | 明确依赖或外部输入阻塞，记录恢复条件 |
| in_review | 功能已提交，等待评审/CI/合并或合并后状态收尾 |
| done | 功能已合入权威main、必要检查通过且状态收尾也已合入 |

开始时在自己的任务分支更新为in_progress并填真实工作记录。按任务测试场景先建立失败证据，再完成最小实现、测试、评审；每个独立有意义的改动提交一次。提交信息采用 `feat(auth): implement session login (todo-002)` 这类类型/范围/内容格式，禁止仅写update。

发现任务范围外缺陷：写入本任务“发现的问题”，必要时按registry流程登记新todo，包含复现、影响与验收。阻塞当前验收的问题必须处理或保持blocked；不能以另建todo掩盖当前功能未完成。

普通进度只改自己的todo文件，不重写根索引。新任务或依赖变化才改根索引。日期/SHA/测试结果必须来自实际执行。

## 8. 并行修改共享文件

- 模块目录可并行。`backend/pyproject.toml`/`uv.lock`、`frontend/package.json`/`package-lock.json`、核心路由入口、共享配置与CONTRACTS属于共享文件。
- 尽量在todo-001冻结基础依赖和约定；新增依赖先与活跃任务协调，持shared-files锁完成编辑/锁文件再生/提交，更新领取记录中的影响范围后释放。Git各分支仍有独立文件，锁用于避免未经协调的相互不兼容改动，不意味着可免冲突检查。
- 每项新增Alembic迁移用唯一revision。合并顺序变化时检查 `alembic heads`；尚未发布的迁移可基于最新main调整父节点，已发布迁移只增不改。真正的双head使用明确merge revision，升级空库和已有库都要验证。
- 公共接口破坏性修改必须先列出受影响任务并更新契约；不能依赖其他对话“从聊天里猜到”。

## 9. 本地模式：尚未设置 origin

1. 功能worktree执行必要检查、评审，任务改为in_review并commit。确认工作区干净。
2. 原子获取integration锁，查阅 `git worktree list --porcelain` 找到持有main的主checkout。它必须干净；若有用户修改，保留现场并报告阻塞，不能自动stash。
3. 将最新main合入功能分支（有变化才做），解决冲突，在合并后的功能树运行相关检查。失败则修复后重试，不污染main。
4. 在主checkout以 `git merge --no-ff <feature-branch>` 集成，记录真实merge SHA。对集成结果执行所需验证。
5. 更新本任务为done，填功能合并SHA、实际测试和已知限制，以独立 `docs(tasks): close todo-NNN` commit提交。不要在该文件写它自己的收尾commit SHA，避免自引用循环。
6. 验证main干净且包含功能和收尾提交，释放integration锁、任务claim；清理遵循第12节。

如果主分支合并后验证失败，不推远端、不标done；在持锁现场调查，保留失败证据。需要退回时使用可审计的revert或修复提交，不用reset销毁历史。

## 10. GitHub 模式：origin 已接入

1. fetch最新origin/main，合入功能分支并解决冲突；运行验收、评审，任务状态in_review，commit、push功能分支。
2. 创建base=main的PR，按模板写真实改动、验证、迁移和任务号；如工具支持，将PR附到当前Codex任务。
3. 按第10.1节的当前模式满足验收与仓库规则。检查证据必须对应待合并提交；代码、依赖、迁移或运行配置改变后重新执行受影响的完整检查。缺少必要审批、本地检查失败或服务端强制规则未满足时保持in_review，不绕过。纯文档提交按第10.1节静态核验，不冒用旧结果证明新的代码行为。
4. 获取integration锁后重新确认main、PR头SHA和检查状态。main有影响性变化时先在功能分支merge origin/main并重新验证/推送。以普通PR squash方式合并，可用 `gh pr merge --squash --match-head-commit <已验证头SHA>`；规则要求排队时按队列执行。
5. 若使用 `--auto`，命令成功只说明已安排自动合并。释放短时integration锁，保持claim和in_review，读取PR的state/mergedAt/mergeCommit确认真正MERGED后重新获取integration锁进行收尾。不要持锁长期等待CI或人工审批。
6. 读取功能PR真实merge commit，并fetch。基于新origin/main在本任务worktree切出 `docs/todo-NNN-close`；仅修改该任务的状态为done、补功能PR链接/合并SHA及验证证据。新增任务索引若已随功能PR合入，此处不重复改索引。
7. 推送收尾分支，创建纯文档状态PR，满足同样仓库规则后合并。等待时释放短时锁，实际收尾后再获取锁同步主checkout。**只有此PR也合入，权威main上的任务才done。** 收尾PR不再创建下一层“记录自身”的PR。
8. 主checkout干净且在main时，`git merge --ff-only origin/main`同步。若主checkout有用户修改，保留，报告本地同步尚未执行；远端集成结果仍可明确汇报。
9. 验证权威main中的任务状态、功能SHA和检查结果，再释放claim及自己的短时锁。日常工作禁止直接push main，不使用 `--admin`。

多个对话仍可并行开发和跑CI，但main同步/本地合并/状态收尾要串行。远端分支保护应要求PR和可用的必要CI；对严格并发合并，启用“分支需与main保持更新”或支持的merge queue。规则与套餐限制详见PREPARATION。

### 10.1 当前模式：本地验收 + GitHub PR（临时）

- **适用范围：** todo-001 及后续任务，直到用户明确同意恢复云端 CI。GitHub 继续负责远端代码、PR、普通 squash 合并与历史；各任务继续使用独立 worktree 和本机协调锁。
- **验收内容：** 代码 PR 在隔离环境完成冻结依赖安装、`node scripts/dev.mjs check` 与对应任务专项检查。完整检查包含真实数据库测试、迁移、前端静态检查/构建和浏览器测试；不能以 Mock 代替任务要求的真实链路。真实云模型/GPU/公网检查仍按各任务的外部条件执行并标明未验证范围。
- **证据：** PR 描述或版本化任务记录写明验收模式、已验证提交 SHA、日期、操作系统/关键版本、命令、退出结果/测试数、评审结果及限制。原始日志可保存在忽略的 `.local/`，对外记录只保留脱敏摘要；本地记录不能伪造成 GitHub Actions 的成功 check。
- **提交对应关系：** 合并前工作区干净，核对本地 HEAD 等于 PR head。新代码提交或合入影响性 main 变化后重跑检查；仅文档改变时核验 diff、Markdown 链接、状态事实并说明复用哪次代码验收。功能合并后仍要另建状态收尾 PR；纯文档收尾无需重跑应用测试。
- **独立评审：** 保留 requesting-code-review 流程，重要问题修复后复核。多个任务开发与验收可并行，integration 锁下的合并、状态收尾和主目录同步仍串行。
- **云端工作流：** `.github/workflows/ci.yml` 保留完整工作流，暂时仅允许 `workflow_dispatch` 手动触发，停止每次 push/PR 自动触发。历史账单锁导致的失败保留为事实；在本模式下它不代表代码失败，也不再作为项目自行要求的合并门槛。不要为了得到绿色标记创建空成功任务。
- **服务端限制：** 每次合并前核实 branch protection/rulesets 和必要审批；如服务端要求云端 check，仍应暂停并报告，不能自行关闭保护、写假状态或使用管理员绕过。本次启用时 main 无强制 check/ruleset；该事实不保证以后不变。
- **恢复条件：** 账号限制解除且用户同意恢复后，先手动运行实际目标提交的完整工作流并确认通过，再通过 PR 恢复 push/PR 自动触发及准确的 required check 名称，同时更新本节和 AGENTS。未恢复之前，新对话无需重复请求本地验收授权。

## 11. GitHub 首次接入

用户准备空仓库和本机认证，提供明确URL。核对owner/repository及公开性后，添加origin并首次push已经检查的main。这是一次性初始化；完成后切换为上述PR模式。不得把有独立历史的远端仓库直接覆盖，不使用强推；遇到已有内容先比较历史与保留策略。

采用云端 CI 模式时，先确认一次真实运行，再启用准确的required check名称，避免配置一个永远不会出现的状态。CI必须覆盖文档PR的适用校验，不能因路径过滤导致required checks永远pending。当前本地验收模式不新增无法运行的云端 required check，也不移除已有保护。GitHub自动合并能力和保护规则受仓库配置/套餐约束，不承诺无需任何账号准备即可使用。

## 12. 清理、交接和恢复

- 原生工具创建的worktree由平台管理；不按猜测路径执行删除。若平台允许安全退出/归档工作区，确认功能和状态收尾已保存再使用。
- 手工创建的worktree只在所有改动已提交、任务已合并、当前路径已切出后由 `git worktree remove <真实路径>` 清理；先核实路径属于本项目且没有其他活跃任务。
- 不用`--force`处理脏目录。显示未提交文件，保存必要成果；删除未提交成果需要用户明确指示。
- squash合并后Git可能不把功能分支判定为祖先，`git branch -d`可拒绝；保留分支或交给已核实的GitHub/平台清理，不擅自用-D。
- 中断前尽可能commit已有可审查进度，并写工作记录：已做/未做/测试/阻塞/下一步/branch/worktree/PR。重启时先核验主分支和claim，避免重复创建同任务worktree。
- 若功能已合并而收尾中断，下个接手者只续做状态PR和同步，不重新实现功能。

## 13. 完成报告

每个对话最终报告：任务号与实现范围、测试和实际结果、功能分支/合并SHA/PR、任务状态、main同步情况、保留的worktree及未解决事项。当前环境不支持某一步时直接说明，不把计划、排队或未验证结果当作完成。

参考：[Codex worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)、[AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[GitHub PR merge CLI](https://cli.github.com/manual/gh_pr_merge)。
