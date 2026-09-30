# 数据说明

本实验只演示检索问答输出格式的少量样本微调。训练集消费 todo-013 中经独立代理复核的 `experiments/evaluation/training.json`：停车、打印、艺术展览、包裹四个主题，每主题两条，共八条。验证集在 `prepare_data.py` 中原创一个校报投稿主题、两条问题；邮箱采用 `.invalid` 保留域，所有政策和地点均属虚构。

准备脚本把真实生产 `rag-extractive-v2` 的 system 提示词及 question/retrieval_query/evidence JSON 用作输入，助手只输出连续原文选择 JSON。生成的 manifest、ShareGPT 数据和配置位于忽略目录 `.local/finetuning/`；不导入聊天、用户反馈或实际业务材料。已有 013 公开的虚构 fixture 作为输入来源保留，本任务不提交新的原始训练文件和模型制品。

校验器检查非空有效 Unicode、角色顺序、重复 ID、规范化问题/来源、来源哈希、组和来源跨集隔离、证据一致性及连续引文。与 013 的完整开发/测试集检查问题、来源 ID、组、规范化原文；另由独立代理逐条检查近义重复。代理审核不等于人工审核，所有数据与报告保留 `human_reviewed=false`。纯格式教学不代表真实业务泛化效果。
