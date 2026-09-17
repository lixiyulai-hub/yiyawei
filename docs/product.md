# Yiyawei（咿呀喂） - 产品说明

## 核心原则

不要让 ASR 决定最终表达质量。ASR 只是原材料，真正的 Typeless 感来自 LLM 审计层。

当前 ASR 主链路固定为 FunASR Paraformer。优化目标不是堆多套 ASR 或词典补丁，而是让 Paraformer 提供稳定中文原文，再由 LLM harness 根据上下文做语义重建。

产品质量看 `final_text`，不是看 `raw_asr_text`。评估标准是：最终文本是否能直接发给 AI 执行工作。

本文件与 `README.md` 一起描述当前公开的产品定位；内部决策记录不随此快照分发。

## 定位

**Yiyawei（咿呀喂）** 将中文口语整理为适合 AI 工具输入的专业文本。

## 用户价值

- 说话可以口语化、重复、改口
- 输出适合 Cursor / ChatGPT / 终端等场景
- 全程本地，隐私可控

## 非目标（第一版）

- 不是代码生成器
- 不是自动执行 Agent
- 不是云端 SaaS

## 核心差异化

**口语审计器（Auditor）**：理解改口、撤销、约束保留，而非简单 ASR。

## 默认模型建议

| 用途 | 模型 | 说明 |
|------|------|------|
| 主力 | Qwen3.5 9B 或同级 9B 中文通用模型 | 中文整理能力强 |
| 极速 | Gemma4 E4B | 低延迟场景 |

不要使用 Coder 专用模型作为默认——本项目是语言整理，不是写代码。

不要将 Qwen3 系列作为默认建议；模型路线以已定的 Qwen3.5 9B / 同级 9B 中文通用模型为准。

## ASR 第一版决策

当前产品主链路只保留 FunASR Paraformer：

```text
热键录音 -> FunASR Paraformer -> LLM 语义审计 -> final_text -> 粘贴
```

不在默认软件中保留 ASR 对比模式、SenseVoice、Whisper fallback 或音译纠错词典，避免给产品增加噪音和重量。
