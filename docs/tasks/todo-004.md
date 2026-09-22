# todo-004：云模型接口与流式 provider

| 字段 | 值 |
|---|---|
| id | todo-004 |
| 状态 | pending |
| depends_on | todo-001 |
| 并行可行性 | 可与 002、003 并行；仅在 provider 目录实现，不提前修改 RAG 或聊天状态机 |
| 负责目录 | `backend/app/modules/providers/`、provider 测试、配置示例 |

## 范围、文件与接口

依据 [CONTRACTS](../CONTRACTS.md)建立唯一模型适配协议、MockProvider、CloudProvider、流式事件转换、超时与取消。云端实现支持契约选定的协议；不建设可视化模型市场或任意插件系统。

- 创建 `backend/app/modules/providers/{schemas,base,mock,cloud,factory,errors}.py`。
- 创建 `backend/tests/providers/test_cloud_stream.py`、`test_provider_errors.py`、`fixtures/cloud_events.py`。
- 消费 001 配置与日志基础；产出 CONTRACTS 规定的请求/响应/usage/取消接口给 008，供 014 实现同一协议。
- 云模型密钥只在后端环境变量/部署 secret 中保存；浏览器不能拿到 provider 密钥。
- SSE 业务事件由后续 009 对外暴露，本任务不直接发布未授权的模型代理 API。

## 分步执行

- [ ] 核对 001 与模型协议；登记模型 ID、API 地址、超时/输出上限与配置来源，缺失真实输入时使用明确标注的假服务。
- [ ] 先写流分片合并、usage、结束、异常和取消测试；用可控制的假 HTTP 服务逐段响应，执行确认目标适配尚未实现而失败。
- [ ] 定义最小 provider 类型与错误映射，实现消息到选定云 API 请求的转换；避免把提供商专有字段泄露到业务接口。
- [ ] 实现异步流读取、分片边界处理、正常结束/中途错误区分；UTF-8 中文被拆分时仍能正确组合。
- [ ] 实现连接/读取超时和上游取消；已向用户输出内容后不做透明全量重试，防止文本和计费重复。
- [ ] 实现模型配置白名单与凭据脱敏；错误信息允许定位故障，但不得记录 Authorization 或原始密钥。
- [ ] 执行假服务全场景验证；若已取得用户 API 配置则提前做短真实调用并记录模型、日期、耗时、usage 和结果，否则明确记录“真实云连接未验证，由 017 发布前完成”，不保存密钥。
- [ ] 独立评审资源释放、异常映射和真实/假服务证据；更新记录并提交 `in_review`，按 WORKFLOW 合并收尾。

## 验收与测试场景

| 场景 | 可判定结果 |
|---|---|
| 中文文本跨多个网络分片 | 合并后文本完全一致，无乱码、丢字或重复 |
| 上游正常结束 | 只产生一次完成信号，usage 按协议保留，缺失 usage 不伪造数值 |
| 429、鉴权失败、超时、半途断流 | 映射为契约错误；中途失败不能当作正常完成 |
| 消费端取消 | 上游连接被释放，后续分片不再继续写给消费者 |
| 日志/异常输出 | 看不到密钥与 Authorization 内容；测试无需真实凭据即可通过 |

```powershell
# backend
uv run pytest tests/providers/test_cloud_stream.py tests/providers/test_provider_errors.py -q
uv run pytest
uv run ruff check .
```

真实调用使用实际开发时提供的受控 smoke 入口，输入固定短问题、输出限制明确；不得在文档中填入虚构成功值。

## 已知问题与外部阻塞

真实调用需要用户选定云提供商、模型 ID、API base URL、API key 和测试预算。无密钥时完整 MockProvider、CloudProvider 协议适配与 fake HTTP 契约测试可以满足本任务完成条件，并明确记录真实云连接未验证。首次真实云 API smoke 可在 004/008 提前完成，最晚由 017 作为正式发布必需验收执行，不让密钥成为 008/009 开发的隐藏阻塞。

## 工作记录与完成标准

- 未领取；负责人、worktree、分支、commit、PR 未产生。
- 未实现、未调用模型、未产生成本或测试结果。
- 按 [WORKFLOW](../WORKFLOW.md) 记录实现、假服务证据及真实调用是否已执行；功能分支最多 `in_review`，合入权威 main 且检查通过后统一收尾为 `done`。此状态不表示真实云 API 已验证。
