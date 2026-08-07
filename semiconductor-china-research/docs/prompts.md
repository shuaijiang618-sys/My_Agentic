# Block 7 · 提示词与输出规范

> 单一真相源: `backend/prompts/*.md` · 加载器: `backend/prompts.py`

## 文件清单

| 文件 | 用途 |
|------|------|
| `supervisor.md` | 编排总管 `SUP_INSTRUCTIONS` |
| `synthesizer.md` | 兜底综合器 `SYNTHESIZER_INSTRUCTIONS` |
| `report_template.md` | 报告 Markdown 结构参考 |
| `policy_expert.md` | 政策与监管专家 |
| `manufacturing_expert.md` | 制造与产能专家 |
| `design_ip_expert.md` | 设计 / IP / EDA 专家 |
| `equipment_materials_expert.md` | 设备与材料专家 |
| `competitor_expert.md` | 竞争格局专家 |
| `tech_roadmap_expert.md` | 技术路线专家 |
| `risk_supply_expert.md` | 供应链与地缘专家 |
| `investment_expert.md` | 投资与产业政策专家 |

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/prompts` | 提示词索引 |
| GET | `/api/prompts/{name}` | 单个提示词全文 |
| GET | `/api/agents` | 前端点节点展示 instructions |

## 合规要点

- 股价 / PE / 市值 / 基金规模 **必须带日期或报告期**
- 禁止编造 URL、持仓、政策文号
- 投资类禁止买卖建议；须含「不构成投资建议」
- 参考来源由系统 `SEARCH_LOG` 追加，模型不编链接

## 修改方式

1. 编辑 `backend/prompts/*.md`
2. 重启 uvicorn（启动时加载进 agent）
3. 前端点专家节点可预览最新 instructions

## 报告结构（按需裁剪）

见 `report_template.md`：

- 核心结论
- 政策与监管
- 产业链分环节
- 竞争格局 / 技术路线
- 投资与资本市场（含免责）
- 风险与展望
- 参考来源（系统追加）
