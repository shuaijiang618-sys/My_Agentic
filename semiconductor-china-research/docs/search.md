# Block 3A · 检索策略（tool.py）

> 单一真相源: `backend/tool.py` → `SEARCH_STRATEGY`

## 设计原则

- 专家 **不 agentic 自主搜** —— wrapper 调用 `fetch_for_expert` / `retry_for_expert`
- 底层 `web_search()` 负责: ddgs 线程池、SSE 事件、SEARCH_LOG、预算控制
- 每专家每轮真检索 **≤ 3 次**（`MAX_SEARCH_PER_EXPERT`），超限回放 `last` 结果

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/search-strategies` | 8 专家策略摘要 |
| GET | `/api/agents` | 每个 worker 含 `search_strategy` 字段 |

## SSE 事件（检索相关）

| event | 字段 |
|-------|------|
| `search_start` | expert, query, region, timelimit, t |
| `search` | expert, query, n, region, items, t |

## 各专家策略

| 专家 | region | timelimit | 模式 |
|------|--------|-----------|------|
| policy_expert | cn-zh | y | 单 query，政策关键词 |
| manufacturing_expert | cn-zh | y | 单 query，产能/制程 |
| design_ip_expert | cn-zh → wt-wt 重搜 | y | 首轮中文；无效时英文 EDA/IP |
| equipment_materials_expert | cn-zh → wt-wt 重搜 | y | 首轮中文；无效时英文设备/材料 |
| competitor_expert | cn-zh | y | 单 query，竞争格局 |
| tech_roadmap_expert | cn-zh | **不限** | 长期技术演变 |
| risk_supply_expert | cn-zh + wt-wt | y | 首轮双区域（国内+全球） |
| investment_expert | cn-zh | y | **双 query**（见下） |

## investment 双 query

**触发**（task 含任一）: 股、上市、估值、PE、市值、股价、ipo、财报、贵不贵…

1. **政策/资金**: `大基金 / 补贴 / IPO / 产业政策`
2. **个股/估值**（触发时）: `市值 / PE / 估值 / 财报 / A股`

**无效重搜**:

- 含个股词 → `PE / 市值 / 财报 2025 2026`
- 否则 → `国家集成电路产业投资基金 三期 投向`

## 代码入口

```python
from backend.tool import fetch_for_expert, retry_for_expert, web_search

data = await fetch_for_expert("policy_expert", task)
more = await retry_for_expert("design_ip_expert", task)
```

## 与 Block 2 关系

- `agent.py` → `make_expert_tool` 只调用 `fetch_for_expert` / `retry_for_expert`
- 检索 query 构建、区域、时效全部在 `SEARCH_STRATEGY` 配置
