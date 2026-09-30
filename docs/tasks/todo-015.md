# todo-015：本机 4B QLoRA 训练与对照实验

| 字段 | 值 |
|---|---|
| id | todo-015 |
| 状态 | done |
| depends_on | todo-013、todo-014 |
| 并行可行性 | 可与 010–012/017 的应用工作并行；独占本机训练 GPU 时协调 014 推理，禁止抢占同一资源导致错误性能结论 |
| 负责目录 | `experiments/finetuning/`；不更改生产默认 provider，不把训练依赖加入业务运行环境 |

## 范围、文件与接口

按 [ARCHITECTURE](../ARCHITECTURE.md)在 WSL2 中使用 LLaMAFactory 完成一个约 4B 基座的 QLoRA 实验，比较基座与微调模型在相同固定评测集上的表现。硬件为 Ultra 7 265K、32GB RAM、RTX 5070 Ti 16GB。本任务是用户希望的后期增强，不是 017 基础公网发布前置条件。

- 创建 `experiments/finetuning/{README.md,data/README.md,validate_data.py,prepare_data.py,configs/,tests/test_data_validation.py,reports/}`。
- 训练原始数据、权重、checkpoint 放仓库外或忽略目录；仓库保留配置、许可/来源说明、哈希、评测报告和复现命令。
- 消费 013 固定评测器/测试集，复用 014 已核验的原始同修订基座，在相同 HF/NF4/BF16 栈比较基座与 adapter；产出可追溯 adapter/checkpoint、训练报告与模型制品清单供条件任务 018 判断。
- 微调不替代知识库检索；不将客服聊天/用户反馈自动当训练集，不未经审核收集个人信息。不训练 SaaS/多租户功能。

## 分步执行

- [x] 核对 013/014 已合入，确认基座许可、数据使用授权、WSL2/GPU 驱动和 CUDA/PyTorch/LLaMAFactory 兼容性；记录精确版本，先做 CUDA 可用与最小算子验证。
- [x] 先写训练数据 schema、空答案、角色顺序、重复样本、训练/测试泄漏检测测试，执行确认校验器尚未实现而失败。
- [x] 整理经授权且脱敏的数据，输出样本数、来源、去重/排除规则与哈希；训练、验证、最终测试按来源/问题去重隔离，测试集不得混入训练。
- [x] 实现最小数据准备与验证脚本；选择明确约 4B 的基座及固定修订，建立小序列长度、micro-batch 1、梯度累积、4-bit QLoRA 的起步配置，逐项记录显存影响。
- [x] 运行少量 step 的训练 smoke，确认 loss 有限、checkpoint 可恢复、显存可承载；若 OOM 优先减序列长度/批量并记录，不把 16GB 显存等同于所有 4B 配置都可训练。
- [x] 在固定预算内完成一轮训练，记录 seed、数据/代码/模型版本、超参数、耗时、显存峰值和 checkpoint 哈希；中断/续训另列记录。
- [x] 导出可用于离线评测的 adapter 或合并制品，记录格式与兼容要求；若转 GGUF/量化须验证支持和转换前后行为，不能默认任意模型都能导入 Ollama。
- [x] 在同一检索、提示词和测试集下比较“基座 + RAG”与“微调 + RAG”，另测无依据拒答/引用/延迟；报告改善、退化和是否值得上线的结论，负结果如实保留。
- [x] 独立复核数据隔离、许可与报告可复现性；更新真实记录，提交配置/报告到 `in_review`，按 WORKFLOW 合并收尾，不自动启用 018。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 数据含空答案、非法角色或重复样本 | 校验明确报错并给样本 ID，不悄悄进入训练 |
| 同一问题/来源跨训练集和测试集 | 泄漏检测阻止评测；独立代理逐题近义去重复核有记录（非人工业务审核） |
| 目标硬件上的短训练 | CUDA 可用、loss 有限、checkpoint 可读取，实际显存不超可用预算 |
| 训练中断后恢复 | 可从指定 checkpoint 续训，记录实际 step 与配置，没有伪造连续训练 |
| 基座与微调模型使用同一评测配置 | 报告可逐条比较；没有提升也明确结论，引用/权限/拒答不能因总体分数被忽略 |

```powershell
# 当前 worktree 的统一检查，业务 CPU 环境
node scripts/dev.mjs check
uv run --directory backend --frozen python -m pytest ../experiments/finetuning/tests -q
```

真实 WSL 训练、数据准备、恢复、API 与两组评测命令见 [本地微调教程](../../experiments/finetuning/README.md)。生成配置位于忽略目录 `.local/finetuning/configs/`；训练清单、原始报告与固定代码 SHA 见 [训练记录](../../experiments/finetuning/reports/training-2026-10-01.md) 和 [同栈对照](../../experiments/finetuning/reports/comparison-2026-10-01.md)。

具体安装命令应在执行时查官方兼容说明并固定版本，不在计划期虚构可用 CUDA/PyTorch 组合。无需为 README/实验结论编写单元测试；校验脚本有真实测试。

## 已知问题与外部阻塞

当前本机训练与实战已完成，独立复核通过，功能 PR 已实际合入权威 main；本文件按 WORKFLOW 以纯文档状态 PR 收尾。数据为授权原创虚构校园材料，独立代理审核不等于人工业务审核。两条 validation 和 60 条教学评测不能证明真实业务泛化；带 history 的 10 题均 no_answer，微调 test 仍有 17 道误拒答。当前只展示独立本机微调 API，不更改网页默认基座，不自动启用 018。

首轮对照实际采样的问题已通过真实依赖回归修正并完成贪心重测，旧报告完整保留；测试集在纠错前已经见过，不声称完全未见。Windows comparison 汇总编码问题已从未损坏的原始四份报告用 UTF-8 重建。没有根据 test 调训练、提示词或检索。

## 工作记录与完成标准

- 2026-10-01 按 WORKFLOW 由本轮批次原子领取，独立 worktree `todo-015-qlora`、分支 `feat/todo-015-qlora`；API/Web/DB 端口 8145/5245/15475，本地模型实验端口 11435。013/014 已在权威 main 完成；016 的本地部署代码也已合入并由本分支合并保留。
- 数据 schema、生产 rag-extractive-v2 投影和泄漏检测按 TDD 实现；训练 8 条（4 主题）、validation 2 条（独立校报主题），共 5 来源。独立代理逐题核验支持性与语义隔离；实际 qwen3_nothink 全格式 token 长度 366–403，均低于 cutoff 1024。固定模型修订、Apache-2.0 许可、全部 12 原始文件哈希与真实环境版本已核验。
- 真实 WSL/CUDA 训练代码 `2fade598fd9c7e7c51250aceb8d2e5832bee6847`：2-step smoke、计划停止后 checkpoint-2→4 恢复、从原始基座开始独立 20 steps 均退出 0；正式含加载/训练/验证/保存 92.168 秒，峰值 allocated/reserved 4,022,468,096/4,420,796,416 B，loss 有限。全部 13 个 adapter 目录张量为有限值；最终 safetensors adapter 与 10 个正式 checkpoint 保留于本机忽略目录。
- 实验 OpenAI 缓冲 SSE 桥严格 loopback/私钥/单并发，Factory 返回真实 stop/length/usage，取消不会释放仍在运行的 GPU worker。013 runner 只有显式 `--local-openai` 加字面量 HTTP loopback 才可复用协议适配器，运行清单包含实际 adapter 权重与 config 双哈希，业务默认 provider 和依赖不改。
- 独立审查定位 Transformers 默认采样覆盖 False 的 P1；`49d3ded90f34969122a841258f7dedd4af0c6cbf` 加载后仅改内存生成开关，真实 Transformers 回归和独立 PEFT CPU generate 验证 GREEDY_SEARCH。模型缓存、训练数据、超参、adapter、检索、提示词均不变；旧采样四份报告留在 `reports/v1-sampled/`，修后四份真实对照均退出 0、dirty=false、代码 SHA 49d3ded。
- 修后 dev 有效引用 6/14→6/14、误拒答 8→8；test 有效引用 12/31→14/31、误拒答 19→17。均 0 权限泄露、上游错误、应拒答误答；有限引用分母的来源/映射正确率 100%，不冒称总体事实正确率。新增 AJ-602/AJ-604 两题有效答复，残余失败与字面指标退化均逐项保留。独立审查全量复算当前 120 行/38 引文。
- `node scripts/dev.mjs check` 在 49d3ded 完整退出 0：8 Node、741 后端、9 evaluation、46 finetuning、114 Vitest、18+4+1 Playwright，Ruff、前端 lint/typecheck/build、迁移升级及再次执行均通过；日志 `.local/full-check-015-greedy.txt`。首轮 Node 本地进程 smoke 曾一次短时失败，原样定点重跑及完整检查通过，原失败日志保留。最终仅增加文档/真实报告，按静态 UTF-8、链接、指标、哈希与 diff 核对验收；云端 CI 因项目既定账单限制未运行，不写成通过。
- 2026-10-01 05:34 上海时区，微调私钥 API `127.0.0.1:11435` ready、016 网页 `127.0.0.1:5246` ready；Ollama 基座和 adapter 均实际加载保留运行，整卡快照总量/已用/空闲 16,303/9,661/6,335 MiB，含桌面等其他进程，不作并发生成/训练承诺。见 [本地运行记录](../../experiments/finetuning/reports/local-deployment-2026-10-01.json)。
- 最终静态核对通过：14 个当前/历史 JSON 严格 UTF-8、120 当前 rows/38 quotes、summary/data/config/adapter/cache 哈希、27 本地链接、3 Python 示例语法与无私钥内容；独立最终审核 APPROVED，无剩余 P0/P1/P2。教程原样 SSE 示例在既有微调 API 实际返回 answered 选择 JSON、stop、prompt/completion/total=345/22/367、DONE，输出无私钥。
- 功能 [PR #33](https://github.com/cdzdd/aiServerAndModelTraining/pull/33) 于 2026-09-30T21:49:58Z 实际 MERGED，功能合并 SHA `0a83d167f63a43a08ce3ef740ecc441065921231`，对应已复核 PR head `c3f5767bca8996461af07ab059d178676d990623`。代码完整验收仍对应 `49d3ded90f34969122a841258f7dedd4af0c6cbf`；此后只有文档/真实报告，已完成 UTF-8、JSON、链接、示例、指标、哈希与 diff 静态核对，独立最终评审 APPROVED，无未解决 P0/P1/P2。

- 本次状态收尾仅修改本任务文件：依据已完成的功能合并、真实训练/评测与本地验收记录更新为 `done`；不再训练、不切换网页模型、不启用 018 或公网发布。只有本纯文档状态 PR 实际合入后，权威 main 才完成收尾；云端 CI 仍未运行。
