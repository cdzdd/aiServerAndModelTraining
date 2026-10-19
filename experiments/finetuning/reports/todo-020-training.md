# todo-020：0.6B 全量微调训练报告

BASE、best250和true last375均完成七组评测，各自1,760题位；全部结果与记录中的自有服务停止/资源释放已独立核准。此核准针对结果完整性与运行边界，未将负结果改为质量通过；当前集成状态见[任务记录](../../../docs/tasks/todo-020.md)。

从原始 Qwen/Qwen3-0.6B 完成 full SFT 的冻结375次更新、3 epochs，最佳250步、真实末轮375步。实际加载的310个唯一 BF16 参数中，两角色222个不同、88个相同，因此分别完整评估；与 BASE 合计21组、5,280个评估题位，并非5,280道独立问题。BASE/BEST/LAST均完成7组/1,760题位并获独立结果核准；benchmark阶段调用分别2,410/2,863/2,863，另各一次中性调用。低 teacher-forced loss 不证明生成提升或没有遗忘；实际指标与解释见[对照报告](todo-020-comparison.md)，集成状态见[任务记录](../../../docs/tasks/todo-020.md)。

## 来源、参数与冻结数据

基座固定revision `c1899de289a04d12100db370d81485cdf75e47ca`，Apache-2.0；9个原始文件合计1,519,207,673bytes。原始权重SHA256为`f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b`。实际训练源码为`5813a7ae1ea89e0b9de46b8e6fd3a430c8b55286`，BASE实际推理源码为`b28f08e8b4d151986a60d1e0f9d42653501f5b34`，FULL best/last实际运行源码为`178af21a74701fb797fef6e8dd3808a3fa577716`。最终文档提交不重标历史执行。各实际报告原有code_commit/working_tree_dirty按原值保留。

原始物理存储311个BF16 tensor、751,632,384元素，embedding与lm_head分别存储。按Parameter对象身份去重后实际训练310个参数tensor、596,049,920元素，全部trainable，optimizer覆盖完全一致；参数及Adam状态FP32、计算BF16。无adapter、量化或冻结训练层。第一步warmup实际LR0，四个完整代表张量当时未数值更新；实际保存pilot100/200及formal250/375的embedding/attention/MLP/norm整张量hash均已变化。第一步310个梯度/930个Adam状态tensor有限；未声称逐步扫描所有后续梯度。best reload的原生missing tied lm_head警告保留；训练审计不伪造Python alias对象证明。

沿用019六个冻结输入文件与同一test，synthetic=true/human_reviewed=false，不是新盲测。完整投影2,000train/600dev/1,000test，上限534/534/536≤1024，没有截断/排除/过滤。安装版Factory converter/processor/collator对全部2,600个train/dev行验证完整template IDs和target labels一致、prompt/padding labels=-100；test只查长度。投影实际执行于历史3090d8a；5813复用时是组件/文件不变核对，不冒充新分词。源文件与投影原始字节哈希不同，投影归一化LF后语义保持，无截断或排除；各自哈希见[制品清单](todo-020-artifacts.json)。

正式recipe：原始基座full起跑，qwen3_nothink/cutoff1024/micro1/累积16/seed42/LR1e-5/cosine/warmup3%/AdamW/SDPA/gradient checkpointing/pure_bf16=false/no packing；max375，每125步dev和完整保存。YAML SHA256 `4688378128fc0243ef687d1fd6ebdf6dca20ed9c90f83b3dbee5ef42c3fd0a3d`；规范化recipe hash `8cb538acbb0a2e0eeb9df9855ef019f10a3cace1d9d90fb7cdd57ff734a173d1`。没有从pilot恢复正式训练，没有根据最终test调参。

## 执行、恢复与累计额度

直接文件CLI导入失败在预算作业前，故障记录保留；首个计时PEFT判定失败同样计费。真实pilot同一总200步配置在100步计划暂停，完整checkpoint恢复至200；恢复optimizer/scheduler/RNG/Trainer原生状态。这不是掉电恢复或不中断GPU训练逐位等价证明。

| 作业 | 阶段 | 实际末步 | 原生原因 | 占用秒数 |
| --- | --- | --- | --- | --- |
| 1 | preflight | 0 | `worker_failed` | 13.720774910595992 |
| 2 | preflight | 100 | `planned_pause` | 329.0476865804121 |
| 3 | preflight | 200 | `completed` | 384.06853044694253 |
| 4 | formal | 375 | `completed` | 1135.561871442239 |

020独立上限86,400秒，四次闭合作业合计**1862.3988633801896秒**，剩余84537.6011366198秒。019闭合占用**4878.797805346716秒**，两者按凭据十进制数相加为**6741.1966687269056秒**。计入加载、失败、期间dev、保存、恢复及退出；没有重置任一账本。020闭合账本SHA256 `9f30fb87407db05b967ea8badfacf9bec0000ecaaf979239502634b9d35d6428`；019保持`d6d10b60fd518caa34aac9b175a32545b48d5f3fb235c4dfb0192696129fd122`。准备/下载/正常结束后最终评估另计，BASE七组活动窗口合计10147.0683426秒；BEST七组活动窗口1826.5819298秒，LAST为1817.9940488秒，详见[对照报告](todo-020-comparison.md)。整段离线评估还含加载、故障排查和评审空闲；这些窗口不能当作纯GPU推理或整个离线阶段耗时，也不追加已闭合训练账本。

正式结束原因是到达冻结max375/3epoch，非早停、非预算耗尽。不要求填满24小时；不得重开、延长或重置本次正式计划。

## 最佳与真实末轮

| step | epoch | in-loop dev loss | native best | patience counter |
| --- | --- | --- | --- | --- |
|125|1|0.008646487258374691|125|0|
|250|2|0.008023361675441265|250|1|
|375|3|0.008143704384565353|250|2|

patience3、严格改善阈值0.001；250更新native best，但改善小于0.001所以patience累加。375尚未触发早停。根输出和train_end已经回载best250，不能据此识别true last375。

| 角色 | 权重SHA256 | complete.json SHA256 | 含出处文档bytes |
| --- | --- | --- | --- |
|best250|`a69a403eb09f60270da1ec992dc0119e0952919805c0fb7cb16b23ba1eec5f0a`|`b27fcce82a75a181f340e4183f578aa36a497c5a0ecb9801931de5523ed5d356`|7168862107|
|true last375|`baaf6c07c28ee915ce9c8a8f3e6cbdcd1b4675882c53a1aa36bbed2edd907313`|`0a3b213dcc9a56cf838454275cb76d11fec2ae3bd8c463c0a5fea7574e8d00c8`|7168882457|

保留125/250/375，满足最近两份和best；pilot与故障证据保留。三份完整标记均校验15项绑定文件，含full weights/config/tokenizer/template及optimizer/scheduler/RNG/Trainer。独立评审对250/375所有310个FP32权重和全部Adam tensor逐值检查均有限；每份596,049,920个exp_avg及exp_avg_sq元素与310个step标量，形状覆盖全部参数。optimizer step为250/375，scheduler last_epoch为250/375，LR分别2.651368701730889e-6/0。125做完整格式/哈希/scheduler/RNG核对，未声称逐值扫描其全部权重与Adam。添加的LICENSE/README出处文档未改15项绑定输入或complete标记。

## Token、吞吐与资源

正式375更新×16=6,000microbatch，实际训练forward计2,227,176 input tokens和164,508 target tokens；按attention_mask/labels!=-100计数，排除dev/padding。每epoch742,392输入/54,836目标，与冻结数据一致。平均train_loss0.041575130896999324，日志四舍五入0不等于精确零或生成通过。

正式book占用1135.561871442239秒：0.3302329969248836更新/秒、1961.2986804244656训练input token/秒。原生train_runtime1093.0365秒与callback elapsed1040.9022082430001秒口径不同。pilot暂停100时原生train_steps/sec用计划200作分子，不作为实际100步吞吐。

正式106次采样：owned worker RSS峰4,700,319,744bytes；CUDA allocator allocated峰11,947,356,160/reserved峰13,774,094,336bytes；整卡采样14,202MiB、54°C、169.54W。pilot100整卡采样最高14,212MiB=13.87890625GiB，不能写14.2GiB。整卡含桌面/其他进程，与allocator/RSS不同；温度/功率采样非连续峰或能耗。125/250/375完整保存窗口65.9863487520006/66.35471654399953/67.00302727100006秒，callback可能含前序同步dev和哈希，非纯文件写延迟。

## 实际加载、验证与限制

实际推理配置为 `infer_dtype=bfloat16`，但 Factory 0.9.5 的加载入口硬编码 `torch_dtype="auto"`，使存储为FP32的full参数仍按FP32加载；这两个参数不能混为同一配置。修正后的共享 full/BF16 路径仅转换 Parameter，保留 buffer 与 tied 身份。BASE 已是 BF16，转换为已核验的无变化路径；不改写任何模型/config/权重。BEST/LAST 实际运行各核验310个唯一 BF16 参数、存储FP32到加载BF16 cast、tied embedding、一个原生FP32 buffer在转换前后不变、GREEDY_SEARCH的16/128/384/512上限，以及一次中性401/401/200鉴权与no-store/DONE。原始BASE buffer未捕获，其原生策略仅由同一builder和既有tiny CPU证据推断，不能补造BASE实际buffer快照。中性调用只验证协议/身份，不能当质量分数。

BEST250 与 LAST375 的实际加载参数规范清单 SHA256 分别为 `61ec12469d39aa6907472c296f51dbaed76827eb651ce78135ade0852ed60f9a`、`f69dcd14a2e1b5f989b7706813b630b4115aebbcca5b06b70be6d93b611b74e6`。原始config.json字节哈希 `348b829d7048cc22943bfc66aee434e34fe03520d7d559a204e22b44848a6a71` 与规范化已解析config哈希 `53cebae1fdeb945fab35b96144edb265f62a22c6d7d70ad4a00c88a35421a68e` 是不同表示的哈希，不相互替代。

源码178有实际统一检查exit0：Node8/backend741/evaluation44/finetuning287+2 Windows skips/Vitest114/Playwright18+4+1=23；专项finetuning287+2skip exit0，前后工作区clean。Linux PDEATHSIG和tiny CPU Trainer恢复/早停实际执行于5813；178仅复用四份消耗源码完整字节未变的证明，不是新原生执行。保留Starlette/AnyIO、Vite chunk、颜色环境、Node DEP0190及原生tied lm_head警告。文档尾段只做事实/哈希/链接/格式静态核对，没有重复训练、模型调用或测试套件。云端CI未运行，采用本地验收+普通GitHub PR。

早前Alembic导入、full FP32推理dtype、端口顺序及TimeWait守卫失败记录均保留；没有将失败改写为成功或修改闭合训练账本。所有完整结果保留原生非零退出、错误和null分母。全分支独立评审、功能PR及单任务状态收尾以[任务记录](../../../docs/tasks/todo-020.md)为准；合入权威main前不写done。公开内容只保留安全来源/哈希/聚合信息；实际模型与私有使用指南保留忽略目录。
