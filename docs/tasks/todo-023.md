# todo-023 基金平台只读业务助手集成

状态：done。创建：2026-11-04。依赖：todo-021、todo-022。已完成本仓库的功能、验证和正式运行包交付，功能PR45已合入权威main。ECS发布及远程台式机真实模型验收仍由Ferrari运维OPS-11继续，本状态不表示这两项已完成。

## 目标及边界

基金用户沿基金登录，通过基金后端专属Bearer key和服务器生成的用户ID访问固定私有知识库；不接收浏览器指定的QA用户、KB、模型或任意prompt。每个基金用户使用不可交互登录的影子身份及独立会话，短期仅存哈希的内部会话绑定现有compute授权。复用已有远程台式机worker、模型、队列和全局聊天槽，不注册第二节点、不增加模型服务，不执行交易。

新增受控`/internal/fund-assistant`异步POST/GET接口；默认key/KB未配置时404，原QA用户路由和队列权限不变。每个小Markdown作为FAQ，由受控CLI导入专属库并触发现有索引worker；没有索引或桌面离线时明确不可用。新增worker最近活动时间以复用旧节点的claim/heartbeat协议。

## 步骤及验收

1. 原子领取todo-023并建立独立worktree，明确内部接口及两张映射表迁移。
2. 实现固定KB、服务鉴权、跨用户所有权、请求ID幂等及冲突、受控后台任务和取消/恢复。
3. 实现小目录知识导入、索引就绪与离线/排队状态；文档说明鉴权与网络边界。
4. 新增真实PG行为测试：跨subject/跨KB、缺token伪造header、请求ID冲突、离线/队列、撤权/取消、影子账号无法登录及原接口回归；继承现有统一check。
5. 本地提交交root集成；功能PR及main实际合并前不标done。用户现行工作流覆盖旧Superpowers和强制独立AI评审引用；不加载已退休流程，不发起未请求的独立AI代码审查。

## 实施及中间验收记录

- 2026-11-04：基线f529337，工作树`.local/worktrees/fund-assistant`、分支`codex/todo-023-fund-assistant`，本机原子claim已登记；只在该工作树修改。
- 后续测试、提交、PR及发布证据由真实运行结果补充。当前尚未部署新功能，不能把旧问答网站上线当成本集成验收。
- 已实现固定服务鉴权、专属KB名称/标记校验、不可交互影子身份、异步受控生成、现有compute队列绑定、取消/短期会话清理、状态和受限来源摘要、Markdown导入与迁移。未改变原队列的授权校验，也未重新注册桌面节点。
- 锁定Ruff0.16.8全backend、Python编译与diff检查通过。专项首轮14通过/2因测试PUBLIC_ORIGIN误配导致CSRF失败；移除本任务测试环境的固定origin后16通过（77.86秒）。其后追加专属KB误配和若干边界测试，最终完整检查结果见下文；不将中间专项冒认为全套通过。
- 环境：Windows、Python3.12.13、uv0.12.4、Node24.22.2，隔离Linux PG16.15/pgvector经本机15459私有隧道；没有连接生产数据库。Playwright1.63.0所需Chromium1243按冻结版本从官方源下载。npm ci沿现锁文件安装，报告16个moderate通知，未升级或声称全部供应链问题已清零。
- 运维指定Docker26 classic构建环境，原`docker image save --platform`仅API1.48+支持。已在正式构建入口增加逐镜像实际ID/OS/arch检查及daemon API/store核验；只有已确认classic的旧API省略save平台参数，新API保留过滤，其他旧store拒绝；构建recipe和buildx参数不变。build-report记录实际inspect结果、兼容分支与命令，不把Docker29的inspect ID冒认成config ID。
- 构建兼容专项Windows真实Git+Docker命令stub：`python -m pytest backend/tests/deploy/test_ferrari_build.py -q`，30通过、1个宿主无法创建symlink跳过（39.49秒）。此中间结果仅证明stub检查；后续Linux完整检查及真实Docker26导出证据分别见下文，不将stub检查冒认为实机导出成功。

## 最终本地验收（2026-11-04）

已验证干净源码提交`213f423333dd1342279a557ad3f81e6a6a085fe3`，独立Linux builder执行`node scripts/dev.mjs check`退出0。工具链实际为Node24.22.2/npm11.19.1、uv0.12.17、Python3.12.3、PG16.15/pgvector0.8.6、Playwright1.63.0；数据库只在该测试机loopback，由此任务独占测试配置，未连接生产。Windows冻结venv另用uv0.12.17复核69包一致，无重装。

| 检查 | 真实结果 |
| --- | --- |
| 部署工具 | 9通过 |
| Ruff、后端 | 静态检查通过；927通过，无跳过，188.02秒 |
| 评测工具 | 44通过 |
| 训练工具 | 288通过；1项明确要求独立Trainer训练venv的集成跳过 |
| 迁移 | 统一入口连续两次upgrade head成功；后端包含随机schema全升级/回退/模型一致性检查 |
| 前端 | lint、vue-tsc、构建通过；19文件114个Vitest通过 |
| 浏览器 | 默认18、聊天/人工接管/反馈4、统计1，全部通过 |

完整日志保存在本机忽略目录`.local/qa-check-linux-213f423.log`，SHA256为`8e2589334cfea3a0b1f77cd8cd2f3b4a200e2019ce093f1f91fccffe92377bb9`，与Linux原始文件校验一致。日志不进入Git；GitHub Actions仍为原手动触发模式，没有伪造云端绿色check。浏览器和生成测试采用明确的合成RAG/计算节点，本轮未在远程台式机运行真实Ollama或宣称真实回答验收。

### 中间失效证据及旧测试harness修正

Windows经私有PG隧道的中间全检为899通过/9跳过/3失败，失败集中于两个2秒子进程启动窗口及queued provider短超时；原生Linux相同运行代码927项全部通过。该Windows运行未继续完成全流程，也不作为最终通过证据。

Linux全检继续暴露三个既有harness问题，分别实证定位并最小修正，未把它们描述成生产业务缺陷修复：

1. `1eeb3fc`：Linux父子进程保护探针从backend启动时，子进程不能继承pytest修改的sys.path，`import experiments`失败。只为该Popen设置项目根目录cwd；PDEATHSIG及进程死亡断言保留，并在最终训练工具检查实际通过。
2. `3bd8c24`：聊天流结束后原UI会刷新服务端历史并关闭旧引用面板；旧E2E在引用事件刚出现时点击，可能被正常刷新关闭。仅等待最终服务端标题后再点击；无sleep/自动重试，引用、下载、取消、所有权及撤权断言保留。专项4项通过（53.5秒），随后最终完整检查再次通过。
3. `213f423`：原知识迁移测试在随机schema降级后使用不限定schema的Inspector；此前浏览器已创建的public同名表会通过search_path可见性再次出现。独立探针证实当前schema仍为probe、probe知识表已删除且users保留、public知识表仍存在，而无schema反射仍返回该表。仅将两处Inspector限定为测试自有schema；没有清空public、修改迁移或放宽用户保留断言。保留public表的专项1项通过（1.12秒），最终完整检查再次通过。

业务接口和迁移的运行代码最后实质变更为`9e0fb7c`，构建导出兼容代码为`d43b42a`；之后三次提交只修上述测试harness。最终各组证据均对应213f423完整源树。后续仅更新此类记录的文档提交复用该运行代码证据，不将文档改动说成重新运行过应用。

接口、状态、鉴权、知识导入及网络边界见[模块说明](../../backend/app/modules/fund_assistant/README.md)。此前个人工作流覆盖旧Superpowers/强制独立AI评审引用，未启动未请求的独立代码审查。

## 功能合并及正式运行包交付

[功能PR45](https://github.com/cdzdd/aiServerAndModelTraining/pull/45)已由root在原子integration锁下使用普通squash流程合并，实际main合并提交为`c08b25490922ad2cec4b09146bab03d4c830544a`，mergedAt为`2026-11-03T19:16:07Z`。已核对该main提交的完整Git树与已验证、打包的`05c895b45787d676a79094f5194e7ed53fb532c0`完全相同。本关闭文档从该权威main创建，仅更新本任务记录，不变更运行代码。

正式运行包继续冻结在05c895b，不因状态收尾文档更换镜像或runtime标签。包大小为644,893,844字节，SHA256为`de5cbb9ad79d5816d78666f55f113c707082969fb235172968285d7214ee7235`。root在独立Linux builder上完成官方Docker26 classic实际build/save、完整严格解包，以及UID10001、无网络、只读条件下的BGE十个固定文件探针；这些为真实构建/产物验证，不再仅是命令stub。

## 双平台隔离联调及未验收范围

独立builder的双平台阶段报告确认28项断言全部通过，`stageOnly=true`、`complete=true`、`protocolStub=true`、`realOllamaVerified=false`。阶段使用基金源码`0e9d493df08d6913e1d1ac5e35e1d741bcd9df39`、QA冻结源码05c895b，完成真实prepare/deploy、24条专属FAQ导入及512维固定BGE索引、基金后端桥接，以及两用户隔离、CSRF、请求幂等、排队/取消、节点离线和QA故障时基金查询/持仓/健康仍可用、订单不变等检查。计算协议fixture实际领取并返回任务，来源引用核对为该专属库索引原文。

原始阶段报告保存在运维仓库忽略目录`.runtime/business-assistant-20261104/stage-smoke/stage-smoke-report.json`；此关闭记录只采用其脱敏结论，没有读取或提交stage-access凭据文件。全部阶段均未操作ECS，不把协议fixture、真实BGE索引或固定FAQ命中冒认为远程Ollama成功。ECS保留数据发布、现有生产台式机的认证/网络接入及真实推理证据，由运维OPS-11继续核对和记录。

状态关闭PR仍由root统一提交、普通合并；权威main以其实际合入为准。在root确认关闭PR已MERGED之前，原claim保持in_review，不提前释放、不删除工作树、包或日志。
