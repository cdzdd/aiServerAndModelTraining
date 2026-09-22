# todo-015：本机 4B QLoRA 训练与对照实验

| 字段 | 值 |
|---|---|
| id | todo-015 |
| 状态 | pending |
| depends_on | todo-013、todo-014 |
| 并行可行性 | 可与 010–012/017 的应用工作并行；独占本机训练 GPU 时协调 014 推理，禁止抢占同一资源导致错误性能结论 |
| 负责目录 | `experiments/finetuning/`；不更改生产默认 provider，不把训练依赖加入业务运行环境 |

## 范围、文件与接口

按 [ARCHITECTURE](../ARCHITECTURE.md)在 WSL2 中使用 LLaMAFactory 完成一个约 4B 基座的 QLoRA 实验，比较基座与微调模型在相同固定评测集上的表现。硬件为 Ultra 7 265K、32GB RAM、RTX 5070 Ti 16GB。本任务是用户希望的后期增强，不是 017 基础公网发布前置条件。

- 创建 `experiments/finetuning/{README.md,data/README.md,validate_data.py,prepare_data.py,configs/,tests/test_data_validation.py,reports/}`。
- 训练原始数据、权重、checkpoint 放仓库外或忽略目录；仓库保留配置、许可/来源说明、哈希、评测报告和复现命令。
- 消费 013 固定评测器/测试集和 014 基座本地推理入口；产出可追溯 adapter/checkpoint、训练报告与模型制品清单供条件任务 018 判断。
- 微调不替代知识库检索；不将客服聊天/用户反馈自动当训练集，不未经审核收集个人信息。不训练 SaaS/多租户功能。

## 分步执行

- [ ] 核对 013/014 已合入，确认基座许可、数据使用授权、WSL2/GPU 驱动和 CUDA/PyTorch/LLaMAFactory 兼容性；记录精确版本，先做 CUDA 可用与最小算子验证。
- [ ] 先写训练数据 schema、空答案、角色顺序、重复样本、训练/测试泄漏检测测试，执行确认校验器尚未实现而失败。
- [ ] 整理经授权且脱敏的数据，输出样本数、来源、去重/排除规则与哈希；训练、验证、最终测试按来源/问题去重隔离，测试集不得混入训练。
- [ ] 实现最小数据准备与验证脚本；选择明确约 4B 的基座及固定修订，建立小序列长度、micro-batch 1、梯度累积、4-bit QLoRA 的起步配置，逐项记录显存影响。
- [ ] 运行少量 step 的训练 smoke，确认 loss 有限、checkpoint 可恢复、显存可承载；若 OOM 优先减序列长度/批量并记录，不把 16GB 显存等同于所有 4B 配置都可训练。
- [ ] 在固定预算内完成一轮训练，记录 seed、数据/代码/模型版本、超参数、耗时、显存峰值和 checkpoint 哈希；中断/续训另列记录。
- [ ] 导出可用于离线评测的 adapter 或合并制品，记录格式与兼容要求；若转 GGUF/量化须验证支持和转换前后行为，不能默认任意模型都能导入 Ollama。
- [ ] 在同一检索、提示词和测试集下比较“基座 + RAG”与“微调 + RAG”，另测无依据拒答/引用/延迟；报告改善、退化和是否值得上线的结论，负结果如实保留。
- [ ] 独立复核数据隔离、许可与报告可复现性；更新真实记录，提交配置/报告到 `in_review`，按 WORKFLOW 合并收尾，不自动启用 018。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 数据含空答案、非法角色或重复样本 | 校验明确报错并给样本 ID，不悄悄进入训练 |
| 同一问题/来源跨训练集和测试集 | 泄漏检测阻止评测；人工近义去重复核有记录 |
| 目标硬件上的短训练 | CUDA 可用、loss 有限、checkpoint 可读取，实际显存不超可用预算 |
| 训练中断后恢复 | 可从指定 checkpoint 续训，记录实际 step 与配置，没有伪造连续训练 |
| 基座与微调模型使用同一评测配置 | 报告可逐条比较；没有提升也明确结论，引用/权限/拒答不能因总体分数被忽略 |

```bash
# 在 WSL2 的实验隔离环境；目录为 experiments/finetuning
python -m pytest tests/test_data_validation.py -q
python validate_data.py --manifest data/manifest.json
llamafactory-cli train configs/qlora-smoke.yaml
llamafactory-cli train configs/qlora-train.yaml
# 使用 todo-013 的评测入口，具体配置由本任务创建
python ../evaluation/run_eval.py --config configs/eval-base.yaml
python ../evaluation/run_eval.py --config configs/eval-finetuned.yaml
```

具体安装命令应在执行时查官方兼容说明并固定版本，不在计划期虚构可用 CUDA/PyTorch 组合。无需为 README/实验结论编写单元测试；校验脚本有真实测试。

## 已知问题与外部阻塞

需要授权训练数据、选定基座及许可、WSL2/GPU 环境、模型下载空间和可接受训练时间。缺任何前置条件可完成数据/配置独立工作，但不能将未训练标为“实验完成”。若硬件确实不可承载，应提供实测失败和降低规模的方案，由用户决定调整目标；不能无声改成更小模型后声称完成 4B 目标。

## 工作记录与完成标准

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未创建训练数据、未安装训练环境、未训练、未产出模型或质量结论。
- 按 [WORKFLOW](../WORKFLOW.md) 保存真实实验与对照证据；分支 `in_review`，合入权威 main 且检查通过后统一 `done`。基础发布可先完成，全部增强目标仍需要本任务。
