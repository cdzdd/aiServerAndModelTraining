# todo-019：真实 8B QLoRA 训练与恢复记录

2026-10-14 完成真实 100→200 step 预跑恢复，以及另从原始基座开始的 375-step、3-epoch 正式训练。三次训练尝试均正常退出，累计占用 **4,878.797805346716 秒（约 81.31 分钟）**，未观察到 OOM 或非有限张量故障。上限是累计 86,400 秒，未要求耗满。正式训练的末步完整恢复点是 checkpoint-375；按唯一一次周期 dev 检查选出的 adapter 是 checkpoint-250，输出根目录 adapter 与其字节完全相同。

本文件验收训练、恢复、计时与制品身份，不用训练 loss 宣称生成效果改善。正式终态制品已获独立分项批准；基座API身份、实际贪心准备与鉴权中性调用也另获分项批准，不是质量结论。LoRA实际加载/调用、两组完整给定证据/真实RAG对照及普通任务退化仍待后续证据。任务保持 `in_progress`，功能尚未合入权威 main。

## 源码、模型与环境

| 项目 | 实际身份 |
|---|---|
| GPU 运行与统一代码检查提交 | `9a1e1d3a310c58a07aa03962af4d07cc1a07d8fb` |
| 后续纯文档提交 | `f7f8d512c841fd0682626c0b514ba5822b6ef636`；未改变训练源码/配置/数据 |
| run_training.py SHA256 | `13605adff21880929bcf05e9a57abb2bc3fd9c06b298e624f6a49504973be4f3` |
| 原始基座 | `Qwen/Qwen3-8B` |
| 固定 revision / 许可 | `b968826d9c46dd6066d109eabc6255188de91218` / Apache-2.0 |
| 原始加载文件 | 14 文件、16,397,459,696 字节；独立逐文件 SHA256 核验 |
| 原始基座参数 | 8,190,735,360 |
| 实际加载 / 可训练参数 | 基座+LoRA 8,234,382,336 / LoRA 43,646,976；实际 bitsandbytes 4-bit |
| 训练身份 model_hash | `1a7067c94aced88c301774de0f1ce202d11fa130f2b5adb8ccc8e2b41d2d6336` |
| 训练身份 data_hash | `f666f68fac1e6b5a04a8450b089760ca22f00a0c4511d6a230a7f9dad4b2d866` |

实际环境为 WSL2 Linux 6.6.87.2、Python 3.12.3、PyTorch 2.9.1+cu128 / CUDA runtime 12.8、Transformers 4.57.6、LLaMAFactory 0.9.5、bitsandbytes 0.50.2、PEFT 0.18.1、Accelerate 1.11.0、datasets 4.0.0。GPU 为 RTX 5070 Ti，整卡总量 16,303 MiB。沿用已安装训练环境，业务后端使用自己的冻结 CPU 依赖；本轮未升级共享依赖。

源码 SHA、原始基座修订、全部文件身份、语义 recipe 与具体 YAML 的 SHA 分开保存。调用者提供的推理清单只能作制品旁证，不能证明 HTTP 服务自动认证这些哈希；基座已核验的有效模式与尚待核验的LoRA模式分别留证，不把一组证明当成另一组或全部评测调用的逐token证明。

## 数据规模、审核与实际 token

数据为原创、明确虚构的校园/客服教学材料，`synthetic=true`、`human_reviewed=false`，不包含真实业务质量承诺。7,200 候选题产生 14,400 个回答/改写候选投影，经同上下文变体与质量筛选保留 1,800 题；不重复编号来补规模或耗时。

| 划分 | 保留题目 | 回答/改写监督投影 | 实际完整非 padding tokens | 最长序列 |
|---|---:|---:|---:|---:|
| train | 1,000 | 2,000 | 742,392 | 534 |
| dev | 300 | 600 | 224,178 | 534 |
| test | 500 | 1,000 | 370,960 | 536 |
| 普通任务回归 | 100 | 100 | 5,540 | 75 |

36 个 family 按 train20/dev6/test10 隔离。每 split 各有 direct/multi_evidence/no_answer/clarify/injection 五类，train 每类200题、dev60题、test100题。5,400 条原始来源去标识归一后为 2,016 种文本；共享收尾、干扰资料与有限模板使它们不等于 5,400 个独立政策。来源示例 ID 仍代表各自实体，不用归一文本把不同来源等同评分。

独立代理覆盖全部 1,800 题的结构与问题/证据关系、36 个 family 规则阅读、100 普通任务核验，并对 train 五类各20题做语义抽查。初稿发现五个条件/动作不匹配，在 r2 修正后复核通过。跨 split 归一文本/近重复筛查和旧013的60题/20来源泄漏筛查无命中；自动筛查与非人工代理审核不能证明广泛语义新颖性或真实业务可靠性。r1 保留但不用于训练，参考答案不进入模型 user 输入。

冻结字节身份如下；原始数据和标签只保存在忽略目录。

| 文件身份 | SHA256 |
|---|---|
| r2 原始输入 | `c0eda2cfc12bcf8d4475370763fe64d7664f8b0ddf8575ec1cd7ffcb9af56cad` |
| preparation manifest-v2.json | `d28984112c49aa6d0c0a8199ffedaf9e8711532929d26a582d82c7d06a321ac3` |
| train.json | `5253f93cb564d169a233b668e25b9915065bca70629912c89651bbeee045c61c` |
| validation.json | `618f4f6bf0a4de11ba8b0fa59cd0d4bcc5dd726265ff73f31bdb84fab17c42a0` |
| dataset_info.json | `24e1f260c76df52ff64f6c1348f62a672b1db23616ebfd903f06585fff539262` |
| 新 dev/test evaluation-v2.json | `358242c445fd22c2e0867522c6207383aa815f0158f0a30d61ffd4195bebcfd0` |
| general-regression.json | `9d83d5c27912d90d341f164f14c469cb8fe4b75648020027ac30da4976189b45` |
| 独立 Factory 模板 token 审计 | `f0831137f1831e577726877c97e13429b562a3ce46ee51a3a9ea2341299b5141` |
| 实际 Factory 数据处理/CPU collator 审计 | `f7d038a7f74dc8ced44bc57f4be2451e8fe0d345c5d40583d70914be82f3edac` |

实际 Factory qwen3_nothink 模板检查全部3,700行，无零目标或截断，完整最大536tokens，小于 cutoff2048，也小于1024；本轮未降低 cutoff。实际 Factory loader/preprocessor/collator 再逐行检查全部2,600个 train/dev 投影：train source687,556/target54,836、padding6,784；dev source207,536/target16,642、padding2,102。完整源/目标与模板编码一致，源标签及 padding 为 -100，padding attention为0。

真实 8B/PEFT 训练 forward hook 在正式125步（一个epoch/2,000 micro-batches）观测输入742,392/目标54,836，精确匹配上述 CPU 全行数据；正式375步观测输入2,227,176/目标164,508，精确等于三遍。计数只含训练 forward 的 attention-mask 非 padding 与 `labels != -100`，不把 dev 推理或 padding 计入训练 token。这是实际 GPU 数据/监督掩码验收，区别于仅模板长度检查。

## 配方与正式训练的停止边界

全程固定 NF4/double quantization、BF16计算、LoRA rank16/alpha32/all（七种线性投影）、dropout0、SDPA、明确启用 gradient checkpointing、micro-batch1/累积16、seed42、LR5e-5/cosine/warmup3%、qwen3_nothink、train_on_prompt=false、cutoff2048、无packing。冻结 raw train/dev 文件，runner拒绝 `tokenized_path` 缓存旁路；本轮不启用远程代码、分布式/卸载或 Hub 发布。

| 配置 | preflight | formal |
|---|---|---|
| 固定 max_steps | 200 | 375，最多3epochs |
| 首次操作 | 原始基座，暂停100 | 原始基座，独立空正式输出，无resume/预跑adapter |
| 恢复 | 完整checkpoint100→200，同一配置/schedule | 本轮无需正式恢复；完整375末步状态留档，不延长冻结schedule |
| save/eval_steps | 100 | 250 |
| warmup steps | 6 | 12 |
| YAML SHA256 | `0f31e898b3e674b372a0a781a068967f0528c46f45d132a5452252326beb21b4` | `82cc53eb038d75292c37ad2197f26d0a06a96abab753412c80b183494937a516` |
| 语义 recipe_hash | `eb4c6425faf26813399986ed9a6529b94f3cfed7e6d5c7f59e2762d92fad3139` | `dc86ba5001c55f55cec698607702cbd9618cec8ac68879e2fdc68ae05732cc80` |

预跑测得保守折算7.242648秒/更新，1800秒约248.53步，按十步取整为250（预计30.18分钟，不承诺精确墙钟周期）。2,000行/有效batch16=125步/epoch，正式上限375保持三遍数据曝光。冻结的执行+保存余量估算5,233.086秒只是计划边界，真实累计账本和外部截止优先。

正式 runner 装入一个原生 Transformers EarlyStoppingCallback：patience3，`eval_loss` 越低越好，改善严格大于0.001；相等算未充分改善。`restore_callback_states_from_checkpoint=true` 保留 counter，CPU真实Trainer证明了保存counter2后继续一次失败于step5停止。正式375/250只有step250一次周期选择，不能在上限前出现三次连续失败；实际结束原因是 `completed`，没有宣称实际早停或正式恢复被触发。保存的原生counter为0。

## 累计预算与三次真实尝试

权威账本是 Git common directory 内的 `codex-coordination/training-budgets/todo-019.json`，对照 task claim核验路径；已初始化一次，账本与 `.initialized` 标记未重建或删除。模型/数据文件哈希在加载前准备；真实模型导入、加载、训练中验证、保存和退出都在尝试开始后计费。结束后的最终离线生成对照不占训练额度。

| 尝试 | UTC开始→结束（2026-10-14） | 实际新增优化步 | 训练输入 / 监督目标 tokens | 计费秒数 | 退出原因 / code |
|---|---|---:|---:|---:|---|
| 1 preflight暂停 | 10:22:54→10:37:59 | 100 | 591,599 / 43,734 | 905.0259321815392 | planned_pause / 0 |
| 2 preflight完整恢复 | 10:41:34→10:58:14 | 100（global100→200） | 595,427 / 44,059 | 1,000.2678483191266 | completed / 0 |
| 3 fresh formal | 11:12:12→12:01:46 | 375 | 2,227,176 / 164,508 | 2,973.50402484605 | completed / 0 |

预跑两次小计1,905.293780500666秒，正式2,973.50402484605秒，三次计费合计4,878.797805346716秒；预算86,400秒，剩余81,521.20219465328秒。无未闭合训练尝试、OOM尝试或失败训练需要隐藏；准备期间一个缓慢CPU审计 helper曾退出15，未加载模型/占GPU/开启训练尝试，不计成训练失败。预跑100→200之间暂停215.5539799秒在确认原父/子进程退出、GPU释放后未收费；未用保存边界冒充退出边界。

账本保守取 monotonic/UTC非负差值的较大值；异常恢复确认原拥有进程均退出后计入未观测间隔。保存余量取max(600秒,2×最慢完整保存计时)，实际仍为600秒。外部watchdog只终止本次拥有的worker；不信任任意PID、不停止未知GPU用户，UTC倒退/身份无法核验/账本损坏需调查，不能退款或重置。实际退出耗时不裁剪成虚假的达标数。

## 实际 loss、吞吐和保存计时范围

| 阶段 | native train_runtime秒 | 实际新增步数 | mean train_loss | dev检查 |
|---|---:|---:|---:|---|
| 暂停100 | 718.8813 | 100 | 0.26612564877344996 | posttrain600行：loss0.005370217375457287，87.70秒（pretty log精度0.01秒） |
| 恢复100→200 | 813.2945 | 100 | 0.0015898911930162284 | 周期600行：loss0.004522998817265034，89.0297秒；postbest600行：同loss，88.7976秒 |
| 正式375 | 2789.9039 | 375 | 0.08791322911312939 | step250周期600行：loss0.01013548020273447，87.1454秒；postbest600行：同loss，88.4145秒 |

这些loss来自有限教学资料上的teacher-forcing训练/dev验证，不是实际生成对照。native逐步loss经过显示舍入，出现0.0000不代表数学上的零loss；末条回调日志loss0.0002，张量与完整状态有限。独立正式run与pilot的不同schedule不能凭loss比较生成效果。

预跑首段真正是100/718.8813=0.139105steps/s或7.188813秒/更新，Factory显示0.278使用名义max200分子，不采纳。恢复段813.2945含周期dev/save，正式2789.9039/375=7.4397437秒/更新同样含周期dev/save。正式回调阶段计时2803.573433775秒、794.40615793输入tokens/s含阶段验证/保存开销；与计费2973.504秒（还含加载/postbest验证/退出）分开报告。

| checkpoint | complete-marker计时秒 | 计时范围 |
|---|---:|---|
| pilot100 | 3.954005099 | 暂停无周期验证，完整保存+文件哈希 |
| pilot200 | 92.074137894 | 周期dev验证+完整保存/哈希复合计时；减去89.0297秒验证后的约3.0444秒仅为估算 |
| formal250 | 88.346280480 | 周期87.1454秒dev验证+完整保存/哈希复合计时 |
| formal375 | 3.957388871 | 非周期末步强制完整保存+哈希，未增加最终周期dev选择 |

## GPU与进程资源

| 尝试 | 10秒资源样本数 | Torch allocated/reserved峰值 bytes | 整卡采样最大MiB / 温度°C / 功率W | worker RSS峰值 bytes |
|---|---:|---:|---:|---:|
| 暂停100 | 91 | 7,934,873,600 / 8,547,991,552 | 9,168 / 63 / 235.59 | 4,709,814,272 |
| 恢复100→200 | 101 | 7,935,535,104 / 8,550,088,704 | 9,159 / 64 / 233.44 | 4,950,761,472 |
| 正式375 | 291 | 7,934,879,744 / 8,547,991,552 | 9,168 / 63 / 235.65 | 5,074,706,432 |

Torch是训练进程分配器峰值；nvidia-smi是整卡采样，包含桌面/其他进程，温度/功率是各自独立的采样最大值，不保证同一时刻或捕获所有瞬时峰值。RSS是worker进程，不是整机内存。短尝试和结束均有最终采样。正式退出后，在任何模型API启动前测得GPU721MiB、利用率0%、45°C且所属父/子进程均已退出，证明该训练已释放GPU；不是最终服务运行中的占用快照。

## 实际恢复与制品身份

预跑checkpoint100完整保留Adam504项step100、scheduler100/固定200cosine/warmup6、Python/NumPy/CPU/CUDA RNG、有限LoRA张量及完整文件哈希。恢复日志实际global100/跳过1600已训练micro-batches，已安装Trainer路径在首个恢复batch前加载optimizer/scheduler/RNG；endpoint200的Adam504项step200、scheduler200/LR0与新张量变化共同证明完整恢复，不是adapter-only重新编号。全部504张量100→200变化，43,643,452/43,646,976元素改变，有限delta L2=0.24048142845817586；不宣称与未中断200-step运行逐bit一致。

正式checkpoint375有完整optimizer/scheduler/RNG/trainer状态，504个Adam状态均step375且有限；scheduler375/step_count376/LR[0,0]对应固定375cosine/warmup12。504个adapter FP32张量、43,646,976元素有限，252个LoRA-B全部非零（absmax0.005815695505589247），标准PEFT零初始化与optimizer moments/steps共同支持真实参数更新。checkpoint250同样完整且有限。CPU检查在训练进程退出后运行，未初始化CUDA。

唯一周期dev在250，最低已观测周期loss0.01013548020273447；选择在任何heldout评估前冻结。末步375完整checkpoint先保存，再加载best250，Factory随后保存输出根目录adapter；根目录weights/config分别与250字节完全相同，与375weights不同。末步global_step375不会把根目录adapter变成375。实际保留完整checkpoint250/375两份（recent2已包含best），另保留根目录推理adapter，不虚构第三个不同checkpoint。

| 实际制品 | SHA256 |
|---|---|
| 所选best250与根目录 adapter_model.safetensors | `46b2b53189c21b7ae5df206ad4aaae45136ae07cb3df1c282a0c17f8e324498b` |
| 所选best250、根目录及last375 adapter_config.json | `43292c5dc94801f6606732bc8513045cf0fb5f9a3bf377b6725cf0ac1828a027` |
| last375 adapter_model.safetensors | `0be0eca7e70e96b9152bcecb8df14d709886ddbcea7425591f90d2cac1e79617` |
| last375 optimizer.pt | `a94345ed4b7fc2cf15bfba493f2075cab8b2522a1c49f4ec3a0cf2751876385e` |
| last375 scheduler.pt | `bb8f758a4cf0cbdb1690c9f4923f033d5184d5b8882c372c87d2ddf9211f49ef` |
| last375 rng_state.pth | `a8e2011629d8bed3ef560fa11175cac55684c4e12a72634bb24abf767b6c7399` |
| last375 trainer_state.json | `0fb93c50ac84ef1eb5bd9766d670e3918f31a3d933f07e594f51ebdd0b6056e5` |
| last375 complete.json | `536f0ad9c0ddbb22bfa9ab5712402c6b6f9461e13b2caf7823a24c62a9833fd9` |
| best250 complete.json | `68b39d9fdf0c6d4a81c7c6dd28c050452fab43c3b60bcdb792c0ad07f51709af` |
| last375 CPU状态检查JSON | `d0020c6a8f7b90fa9194953ea16b9c551a9eff15dff7eb8ac51a371bfd19e66f` |
| best250 CPU状态检查JSON | `50bb20f5120de63f14404ea21b38de51a5c1d5b908f99deba71552d6f778d7dc` |
| 所选adapter检查JSON | `c31434914e6e21bf7d7df7db7f6c9ccfe73c823f7bf6ec113194b55500e3651b` |

本机资料位于保留制品的019独立worktree中，均为忽略路径：原始基座 `.local/models/qwen3-8b/`，准备/评测投影 `.local/corpus-019/projection-preview-v2-r2/`，实际训练数据 `.local/finetuning-019/frozen-data/`，预跑输出 `.local/finetuning-019/preflight-output/`，正式所选adapter `.local/finetuning-019/formal-output/`，完整恢复点为其 `checkpoint-375/`，best为`checkpoint-250/`。主工作区没有这些本机权重；恢复操作见 [README](../README.md)。原始源资料、参考答案、模型输出、checkpoint字节、密钥和机器绝对路径不写入公开元信息。

## 已核验代码与保留的限制

`node scripts/dev.mjs check` 在9a1e1d3实际exit0：8Node、741后端、9评测、165微调+2Windows跳过、114Vitest、23Playwright，Ruff/迁移/构建通过。两项跳过行为在现有WSL CPU环境单独实测：真实Trainer100→200与原生early-stop counter恢复、Linux父进程死亡守卫。统一检查不隐式启动GPU或最终评测。Task1数据/代码、Task2预算修复、early-stop/config、Task3隐私修复、实际pilot连续性和正式终态制品均获独立分项评审批准；LoRA最终加载/完整对照及全任务最终评审仍待完成。专项独立命令与最终流程证据按 [任务记录](../../../docs/tasks/todo-019.md) 收尾，不把本次纯文档静态核对说成重复业务测试。

训练结束后的基座API首次startup在忽略的witness中因错误的32层架构断言失败于endpoint绑定前；改为逐项核验原始config的8项实际架构后重试通过，原失败保留。此为推理阶段失败，不添加或隐藏为训练attempt；已批准的中性HTTP调用仅证明可达/真实生成，token上限结束不能当作benchmark正确。最终结果须保留实际评测时的代码commit与working_tree_dirty值；仅文档变化且运行源码SHA不变，不伪写成当时工作区干净或重做推理来改变元数据。

保留已知基线Starlette/AnyIO弃用、Node FORCE_COLOR/DEP0190和构建体积提示，以及快速CPU fixture checkpoint的mtime数值排序回退警告（EVIDENCE-03/ESC-01，非训练故障）。此前冻结source-map-js1.2.1的high audit发现未由本任务改依赖解决。警告存在不伪写检查失败，也不声称无告警。

| 已采用决定 | 边界与代价 |
|---|---|
| claim先绑定唯一budget路径，CLI获评审后只初始化一次 | 若顺序不符需修正设置；不伪造空账本、不返还已占用时间 |
| 原创虚构教学数据，非付费生成/真实业务抓取 | 需换业务资料时重新准备；本次结果无真实业务外推承诺 |
| 数据与预算工具按独立文件并行，提交串行 | 错误协调会冲突/返工；真实GPU前必须完成集成验收 |
| 代码/schema gate与最终语料QA分开，评测器先消费稳定接口 | 若schema变化需评测适配返工；实际训练不得越过最终QA/token gate |
| 不做重复来源归一等价评分 | 实体敏感引用/检索指标可更严；保留真实失败与重复措辞限制 |
| 拒绝tokenized cache而非新增缓存身份平台 | 重复预处理较慢；避免绕过冻结raw数据身份 |
| 使用原生strict>0.001 / ExportableState | 相等边界算不改善，可能早一个验证间隔停止；报告实际语义 |
| 保持3epochs/约30分钟目标，即375/250 | 仅一次周期dev选择，实际不能触发三次失败早停；保留last375和best250分开 |

后续对照将分别报告给定证据、真实检索/权限/RAG、旧013回归及普通100题的实际分母、失败和负结果；精确参考匹配不等于语义正确，不承诺零幻觉或广泛泛化。020未领取/运行，不启用018或公开模型端口，不改变业务provider及016的本地停止边界。[PR36](https://github.com/cdzdd/aiServerAndModelTraining/pull/36)仍按最终证据评审/合并；云端CI未运行，不冒称main已经合并或任务done。
