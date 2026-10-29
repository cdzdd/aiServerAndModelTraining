# Ferrari 运维交付 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task; root handles isolated validation and external handoff. Steps use checkbox syntax for tracking.

**Goal:** 完成业务侧Linux镜像交付与真实验证，将可读取运行包和部署配置提交运维PR。

**Architecture:** 复用五服务与queued计算，不改变业务协议。固定BGE随后端镜像，既有本地构建保持默认行为；运维公共工具继续由Ferrari仓库管理。

**Tech Stack:** Python3.12标准库构建入口、Docker29/buildx、Vue/Caddy、FastAPI、PG16/pgvector、现有BGE/Ollama。

**Spec:** [设计](../specs/2026-10-29-ferrari-delivery-design.md)。契约为Ferrari_Server a414243的docs/python-pgvector-runtime.md。

## Global Constraints

- `python-pgvector-v1`，仅`linux/amd64`；BGE固定修订7999e1d3359715c523056ef9478215996d62a620与现有十文件SHA。
- `/opt/models/bge`；API UID/GID10001，三个角色共镜像，web8080；单API进程；MODEL_ALLOWED_IDS用JSON数组字符串。
- 应用镜像`ferrari-knowledge-qa-api/web:<源码前12位>`；数据库固定契约tag/digest。Docker-save仅三个tag，开发机save使用`--platform linux/amd64`，禁attestation、多架构混入。
- 不把真实配置、凭据、数据库、uploads、训练权重写入Git/镜像/运行包；复用缓存不降低BGE摘要验证。
- 运维PR由负责人合并和部署；业务PR依WORKFLOW正常本地验收与合并。所有服务/端口/卷与原演示隔离。

## Review Focus

1. 脏Git版本或源文件夹含.env/训练文件时不能产生冒充干净提交的运行镜像（Task1）。
2. HF缓存为符号链接、文件损坏或复制时变化时，实际复制普通文件并再次校验，损坏提前拒绝（Task1）。
3. 默认本地Docker构建不能因缺BGE上下文而失败，只有显式ferrari目标需要模型（Task1与Task2）。
4. Docker失败或输出同名时不覆盖原产物、不宣称打包成功（Task1）。
5. 原模板模型白名单类型、只读/tmp64MiB、节点取消和桌面离线不能用toy或healthy代替真实结果（Task2）。

## Task 1: 提交绑定的镜像构建入口

**Files:** 新建scripts/deploy/ferrari_build.py、backend/tests/deploy/test_ferrari_build.py；修改backend/Dockerfile、scripts/dev.mjs（新脚本Ruff入口）、scripts/README.md（构建用法）。

**Interfaces:** CLI `python scripts/deploy/ferrari_build.py --model-dir <固定模型目录> --output-dir <忽略输出目录>`。从工作区HEAD构建，固定项目knowledge-qa；输出images.tar及非秘密build-report.json，不装包、不推送、不读.env。Dockerfile新增ferrari target，从runtime-bge复制到/opt/models/bge，默认最后local target保持既有行为。根负责工作区配置，implementer不启动其他服务。

- [ ] RED：干净临时Git仓库、缺模型/损坏文件、HF链接物化、排除.env/未提交代码、已存在导出、Docker失败及生成平台/源码tag命令的行为测试；先确认缺失入口导致失败。
- [ ] 实现最小构建脚本：Git提交及干净检查；Git归档受控构建输入；固定BGE清单普通文件复制与验证；Docker buildx build --platform linux/amd64 --provenance=false --load，api target ferrari；pg固定digest取得与tag核对；三tag save与报告。
- [ ] 保留现有本地默认target；新增脚本接入统一Ruff，运行专项测试及Ruff，记录RED/GREEN，提交代码。
- [ ] 任务评审（业务代码范围）通过；必要修复回归。

## Task 2: 冻结版本、统一检查与真实隔离验证

**Files:** ignored .local/运行配置、原始日志和私有节点文件；必要任务事实写入docs/tasks/todo-022.md。

- [ ] 新worktree按锁文件安装依赖，独立数据库/端口；执行node scripts/dev.mjs check并保留实际结果，不使用旧环境冒充。
- [ ] 从完成适配的干净提交运行构建入口；临时运维Compose修正JSON白名单，使用本项目独立秘密和端口，数据库健康→迁移→五服务启动。
- [ ] 用虚构TXT/DOCX/PDF实际parse/index；节点安全注册并使用现有Ollama真实回答、引用、下载、历史、CSRF、停止/离线/重启；观察worker、日志、OOM、资源，记录运行限制。
- [ ] 在可用隔离Linux环境执行新包导入、PG+uploads一致备份与restore-check；保留本机与ECS差异，不操作真实云机。
- [ ] 对最终业务分支进行独立整体评审，修复关键问题后重新执行受影响验证。

## Task 3: 运维包与接入配置

**Files:** Ferrari独立worktree的projects/knowledge-qa/compose.yaml、release.json、.env.example、README交接区；registry.json仅增加本项目提案。

- [ ] 按契约填写真实源码身份、镜像tag及固定元数据；package_qa.py生成包、回填配置ID和外包摘要，验证附件小于2GiB。
- [ ] validate/plan/check-artifact、临时配置Compose渲染、运维单测；记录实际包、双版本与解包临时空间估算、维护窗口和恢复边界。
- [ ] 用私有草稿Release附件交付，不发布Release、不覆盖同名版本；重新下载校验可读性和摘要。
- [ ] 提交正式运维接入PR并附到当前对话。若运维核定或ECS验证待办则按事实保留草稿；不自行合并或部署。

## Task 4: 业务PR与交付状态收尾

- [ ] 更新简短docs/operations-handoff.md、任务记录、实际验证与已知限制；按本地验收模式创建业务PR，普通squash合并，核对必要保护。
- [ ] 功能实际合并后另做任务状态收尾PR；任务完成定义为业务适配+产物+运维PR交接，明确云端尚未发布。
- [ ] 同步干净业务main、释放本任务claim/锁，停止自有QA服务保留卷/证据，保留待运维接收的运行包和工作树。
