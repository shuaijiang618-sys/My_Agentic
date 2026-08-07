# 8 专家体系 · 职责边界与选派规则

> Block 1 定稿 · 中国半导体产业研究编排

## 协作模式

- **模式**: supervisor-as-tools
- **总管**: `research_supervisor` 把 8 位专家当 **tools** 并行调用
- **控制权**: 总管决定派谁、派什么任务、如何综合

## 专家一览

| tool | label | agent | 分析维度 |
|------|-------|-------|----------|
| `policy_expert` | 政策监管 | `policy_analyst` | 国产化政策 / 出口管制 / 信创 / 合规与制裁规则 |
| `manufacturing_expert` | 制造产能 | `manufacturing_analyst` | 晶圆制造 / 产能 / 制程节点 / Foundry·OSAT |
| `design_ip_expert` | 设计IP | `design_ip_analyst` | Fabless / SoC / IP核 / EDA 工具国产化 |
| `equipment_materials_expert` | 设备材料 | `equipment_materials_analyst` | 半导体设备 / 材料 / 国产化率 / 供应链瓶颈 |
| `competitor_expert` | 竞争格局 | `competitor_analyst` | 头部企业 / 市场份额 / 商业模式 / 并购整合 |
| `tech_roadmap_expert` | 技术路线 | `tech_roadmap_analyst` | 先进制程 / Chiplet / AI 芯片 / SiC·GaN |
| `risk_supply_expert` | 供应链 | `risk_supply_analyst` | 断供风险 / 国产替代 / 制裁影响 / 供应链韧性 |
| `investment_expert` | 投资政策 | `investment_analyst` | 大基金三期 / 地方补贴 / IPO / 估值 / 个股 |

## 职责边界（防重叠）

| 专家 | 负责 | 不负责 |
|------|------|--------|
| **investment** | 钱、大基金、补贴、IPO、估值、股价 | 技术细节、制裁法规条文 |
| **policy** | 法规、制裁规则、信创目录、合规框架 | 企业商业模式、股价 |
| **competitor** | 业务、份额、竞争格局、并购 | 制程技术细节、投资估值 |
| **manufacturing** | 晶圆厂、产能、制程、Foundry/OSAT | EDA 工具、设备零部件 |
| **design_ip** | Fabless、SoC、IP、EDA 国产化 | 设备材料、产能数字 |
| **equipment_materials** | 光刻机、刻蚀、材料、国产化率 | 设计工具、政策文件 |
| **tech_roadmap** | 技术演进、新架构、长期路线 | 短期股价、具体政策文号 |
| **risk_supply** | 断供、替代、地缘、韧性 | 投资估值、企业战略 |

## 选派规则（总管）

| 问题类型 | 建议专家数 | 必含 / 主派 |
|----------|------------|-------------|
| 产业链全景 / 发展现状 | 6~8 | policy + competitor；视题含 investment |
| 单点环节（EDA / 光刻 / 某制程） | 2~4 | 对口 1~2 个 + policy 或 risk_supply |
| 大基金 / 补贴 / IPO / 股价 / 估值 | 2~4 | **investment_expert**（主）+ competitor 或 policy |
| 概念解释 | 0~2 | 总管知识为主，必要时补 1~2 对口专家 |

## 示例问题 → 预期选派

| 用户问题 | 预期主派专家 |
|----------|--------------|
| 中国半导体产业链发展现状 | policy, manufacturing, design_ip, equipment_materials, competitor, tech_roadmap, risk_supply, investment（6~8） |
| 大基金三期投向哪些环节？ | investment（主）, policy |
| 北方华创估值贵不贵？ | investment（主）, competitor |
| EDA 国产化进展如何？ | design_ip（主）, policy |
| 光刻机供应链风险？ | equipment_materials（主）, risk_supply, policy |
| 追问：刚才提到的设备公司谁上市了？ | investment, competitor（结合多轮记忆） |

## 代码位置

- `backend/agent.py` → `WORKERS[]`, `TOOL_DESC{}`, `SUP_INSTRUCTIONS`
- `frontend/index.html` → `W[]`（tool 名须与 WORKERS 一致）
- `/api/agents` → 返回 8 专家元数据

## 后续 Block

- **Block 3B**: investment 知识库 lookup（Phase 2）
- **Block 7**: 各专家完整 system prompt（附录 A）

编排层详见 [orchestration.md](orchestration.md)（Block 2 ✅）
