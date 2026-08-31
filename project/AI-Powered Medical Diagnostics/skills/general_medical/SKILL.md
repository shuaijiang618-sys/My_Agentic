---
name: 就医流程与科普规范
description: 挂号、流程、科室职能等 general Agent 结构化回复规范
keywords: 挂号,预约,流程,门诊,急诊,科室,检查准备
agents: general
enabled: true
version: "1.0"
---

# 就医流程与科普规范

## 回复结构

与结构化模板 `prompts/templates/general_response.md` 对齐：

1. **问题理解**（`topic_summary`）：简要复述用户问题。
2. **解答**（`answer`）：针对挂号/流程/科室/检查准备的主回答。
3. **实用提示**（`practical_tips`，可选）：0–3 条操作提示。
4. **补充说明**（`follow_up`，可选）：下一步或需用户补充的信息。
5. **禁止**：确诊、开方、替代线下就医决策。
