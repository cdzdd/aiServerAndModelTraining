# 真机验收报告

这里仅提交实际执行后的脱敏报告。开发阶段尚未执行真实Ollama/GPU，不提供虚构成功记录。

建议保存`ollama-short-cold.json`、`ollama-short-warm.json`和`ollama-rag.json`，并附环境说明：日期/commit、GPU/驱动、Ollama版本、模型精确标签/digest、量化、4096上下文、冷/热前置状态、首文本/总耗时、实际usage、显存采样间隔/峰值、成功与失败样本。不得把未测显存填0、缺失total按输入输出相加，或把协议stop数量当质量正确率。
