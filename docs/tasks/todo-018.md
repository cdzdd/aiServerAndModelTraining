# todo-018：自有微调模型的公网推理接入（条件任务）

| 字段 | 值 |
|---|---|
| id | todo-018 |
| 状态 | planned_optional |
| depends_on | todo-015、todo-017 |
| 并行可行性 | 依赖完成且用户明确启用后执行；独占推理服务发布和模型切换窗口，可先独立整理制品验证材料 |
| 负责目录 | `experiments/finetuning/` 制品清单、必要 provider 适配、`infra/` 推理配置、部署说明与验证 |

## 启用条件与范围

用户在 015 真实对照结果基础上明确决定把自有微调模型用于公网业务时，将本任务由 `planned_optional` 改为 `pending` 并记录决定。未决定时不部署、不购买 GPU、不把条件任务标成已完成。017 基础发布不依赖本任务。

依据 [ARCHITECTURE](../ARCHITECTURE.md)选择与训练制品兼容的最小推理路径：若已验证可转兼容格式则复用 Ollama；否则选择经过实测、满足统一 provider 协议的独立推理服务。不能假设 LoRA adapter 可直接被任意服务加载。

- 创建 `experiments/finetuning/artifacts/manifest.example.json`、`docs/operations/custom-model-serving.md`、实际选用的 `infra/` 推理配置及 `frontend/e2e/custom-model.spec.ts`。
- 必要时新增 `backend/app/modules/providers/custom.py` 和 `backend/tests/providers/test_custom_model.py`；若已有 OllamaProvider 满足要求，不增加重复适配层。
- 消费 015 基座/adapter/合并/量化制品及哈希、许可、评测结果，017 运行中的正式部署和回滚机制；业务 RAG/检索/权限接口保持一致。
- 推理服务置于私网，公网调用仍经过认证的业务 API；模型切换不是向公众开放无认证生成端口。

## 分步执行

- [ ] 记录用户启用决定、模型制品、推理资源/预算与部署授权；核对 015/017 已合入及模型质量是否接受。
- [ ] 先写制品加载后版本/哈希可核对、统一流事件、错误和回退行为测试；如复用已有适配器只补真实集成验证，不编写重复镜像测试。
- [ ] 校验基座/adapter/合并关系、许可证、模型架构、tokenizer 与量化格式；复制到隔离推理环境并核验哈希，不能把权重提交 Git。
- [ ] 在目标 GPU/服务资源上启动内部推理，记录精确运行镜像、模型版本、上下文、并发和显存；不兼容时停止发布并报告证据。
- [ ] 通过已有 provider 配置或最小新增适配接入 RAG；同一权限过滤、引用校验、拒答与 CSRF 链路不得旁路。
- [ ] 在预发布使用同一固定评测集核对“离线微调结果”与“线上制品结果”，比较量化后质量、延迟和错误，确认转换没有不可接受退化。
- [ ] 演练推理不可用、资源耗尽和回退；云模型回退只有在用户明确同意资料发送规则后启用，否则给出明确不可用状态。
- [ ] 在授权发布窗口切换正式 provider，从外网完成问答/引用/取消/人工接管，并记录实际加载的自有模型版本及容量结论。
- [ ] 独立评审模型可追溯性、质量、权限与回退，更新运行手册和真实记录；提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 启动推理服务 | 加载制品的哈希/模型版本与 015 发布清单一致，不能误用原始基座冒充微调模型 |
| 通过公网应用进行知识问答 | 业务日志能核对实际模型版本；引用和权限仍由原有 RAG 服务约束 |
| 量化/转换后的同一固定测试集 | 有逐条对照报告，接受的退化范围明确，不只展示主观成功案例 |
| 推理 OOM、离线或超时 | 页面得到可理解错误或经授权的回退；无未经授权的云端资料发送 |
| 回切旧 provider 后复测 | 健康、问答、引用、历史和转人工恢复，原始会话数据不丢失 |

```powershell
# backend；仅新增适配器时执行对应新测试，否则执行复用适配器的现有测试
uv run pytest tests/providers tests/rag -q
uv run ruff check .
uv run python ../experiments/evaluation/run_eval.py --config ../experiments/finetuning/configs/eval-deployed.yaml
# frontend；BASE_URL 指向本次验证环境
npm run test:e2e -- e2e/custom-model.spec.ts
```

`eval-deployed.yaml` 与浏览器测试由本任务创建。实际 GPU 服务的启动命令随已选推理方案记录于运行手册，不在计划中虚构所有服务通用的启动参数。

## 已知问题与外部阻塞

本任务当前条件未满足：用户尚未选择上线自有模型，015 尚无模型制品，017 尚无正式站点。还需公网推理 GPU/服务资源、网络路径、模型许可与费用预算。没有公网 GPU 时不能默默把用户家用电脑暴露成无保护服务。

## 工作记录与完成标准

- 未启用、未领取；负责人、worktree、分支、commit、PR 未产生。
- 未导出/部署模型、未更改正式 provider、未执行公网测试。
- 保持 `planned_optional` 直到用户明确启用；启用后依 [WORKFLOW](../WORKFLOW.md) 进入常规状态流。任务分支到 `in_review`，合入权威 main 且检查通过后统一更新 `done`；未启用不能伪写 `done`。
