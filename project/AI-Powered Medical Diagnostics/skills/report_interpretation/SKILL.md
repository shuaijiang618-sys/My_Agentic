---
name: 报告解释规范
description: 体检与化验指标解释模板
keywords: 报告,指标,ALT,AST,偏高,偏低,体检,化验,血常规,血压,mmol
agents: report
enabled: true
version: "1.0"
---

# 报告解释规范

## 回复结构

与结构化模板 `prompts/templates/report_response.md` 对齐：

1. **指标含义**（`indicator_meaning`）：该指标测量什么、一般如何理解。
2. **常见影响因素**（`common_factors`）：非诊断性的常见因素（1–4 条）。
3. **建议下一步**（`next_steps`）：复查或咨询科室。
4. **禁止**：单次异常不得推导疾病名称；不得给出治疗方案。

## 引用要求

优先引用 `[医学知识库检索结果]` 中的内容；无检索结果时明确说明信息不足并建议面诊。
