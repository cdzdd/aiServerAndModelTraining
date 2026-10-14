# 数据说明

本实验只演示检索问答输出格式的少量样本微调。训练集消费 todo-013 中经独立代理复核的 `experiments/evaluation/training.json`：停车、打印、艺术展览、包裹四个主题，每主题两条，共八条。验证集在 `prepare_data.py` 中原创一个校报投稿主题、两条问题；邮箱采用 `.invalid` 保留域，所有政策和地点均属虚构。

准备脚本把真实生产 `rag-extractive-v2` 的 system 提示词及 question/retrieval_query/evidence JSON 用作输入，助手只输出连续原文选择 JSON。生成的 manifest、ShareGPT 数据和配置位于忽略目录 `.local/finetuning/`；不导入聊天、用户反馈或实际业务材料。已有 013 公开的虚构 fixture 作为输入来源保留，本任务不提交新的原始训练文件和模型制品。

校验器检查非空有效 Unicode、角色顺序、重复 ID、规范化问题/来源、来源哈希、组和来源跨集隔离、证据一致性及连续引文。与 013 的完整开发/测试集检查问题、来源 ID、组、规范化原文；另由独立代理逐条检查近义重复。代理审核不等于人工审核，所有数据与报告保留 `human_reviewed=false`。纯格式教学不代表真实业务泛化效果。

## todo-019 原创语料 v2

旧入口不传 `manifest_path`、`recipe_path` 时保留固定 8+2 数据及原有内容哈希。新入口必须同时显式提供两项；输出目录非空时拒绝覆盖，训练、验证与最终测试的标签都只保存在忽略目录。原文许可标注 `original-synthetic-project-use`，依据用户对本项目本机训练的授权，不声明公开放弃原文权利。

原始规则是私有 JSON 数组，各项带 `family`、`split`、`topic`、`conditions`、`actions`、`wrapup`、`counter_rule`，并可明确记录该主题的原文句式、问题句式、缺失信息问题及资料/历史中的攻击文字。`prepare_corpus.py` 不读取旧 60 题或其参考答案。完整条件、动作、收尾规则先归入来源和语义 family，再整组分配 train/dev/test；同语境的四种候选问法只保留一种。修改规则后的数据应写到新的版本路径。

```text
python -m experiments.finetuning.prepare_corpus --rules .local/corpus-019/rules.json --output .local/corpus-019/candidate-input.json --candidates .local/corpus-019/candidate-pool.json
python -m experiments.finetuning.prepare_data --manifest .local/corpus-019/candidate-input.json --recipe PATH_TO_FROZEN_RECIPE --output NEW_EMPTY_DIRECTORY --model-path PATH_TO_MODEL --runtime-root PATH_AS_SEEN_IN_WSL
```

v2 的 `sources` 保留许可、授权、来源 SHA256、group/family/semantic_group/split；`cases` 保留真实检索评测器的 `allowed_kbs`、`reference_sources`、`reference_answer`、`answer_terms`、`expected_refusal`、`history`，新增显式 `answer`、`rewrite` 与 evidence 来源编号。answer 的输入使用生产 `ANSWER_SYSTEM` 和 question/retrieval_query/evidence；rewrite 使用生产 `REWRITE_SYSTEM` 和 question/history。两项投影跟随同一 case 分割。改写只能补充历史已有指代，历史助手文字不得成为答案证据。

输出为 `manifest-v2.json`、`train.json`、`validation.json`（dev）、`dataset_info.json`、`evaluation-v2.json`（dev/test）、`general-regression.json`、显式 recipe 配置及 `data-summary.json`。`dataset_info.json` 只有 train/dev；测试和 100 道普通指令、整数算术、严格 JSON 通用回归均不进入训练。通用回归必须使用独立普通指令提示词，参考标签不送入模型。

校验要求证据编号按生产顺序为 1..N、最多 5 候选；answered 最多 3 条、总长最多 800 字符的连续原文，并验证参考标签对应同一来源。clarify/no_answer 必须没有引用。改写的 `needs_clarification` 必须为布尔值，非澄清 query 与逐题 retrieval_query 一致。ASCII 编号/数字去除后用完整原文和问题/历史/证据的字符四元组 Jaccard≥0.88 筛查跨集近重复，另检查整来源、family、semantic_group 不跨集。该筛查不能证明不存在语义重复；仍需独立逐题审查 dev/test、每个 family 的规则及每类至少 20 道 train。

样本清单记录实际 UTF-8 字节数和哈希，token 字段在真实冻结 tokenizer 审计之前保持 null，不能把字符数当作 token 数。候选规模、去重后投影数、归一化独立来源数和独立审核分母须分开记录；相同 family 中复用的收尾/对照资料不算新独立政策。作者规则校验不等于独立代理审核，代理审核也不等于人工业务验收。当前生成方法涵盖有限教学模板，不能据此宣称广泛业务泛化。
