# Block 2 · 编排层（Supervisor + Wrapper）

## 架构

```
research_supervisor (deepseek-v4-pro)
    ├── policy_expert          ─┐
    ├── manufacturing_expert   │
    ├── design_ip_expert       │ 并行 tool_call
    ├── equipment_materials_expert
    ├── competitor_expert      │
    ├── tech_roadmap_expert    │
    ├── risk_supply_expert     │
    └── investment_expert      ─┘
              ↓ 综合
         研究简报 + 参考来源
              ↓ (正文 <200 字)
    research_synthesizer 兜底
```

## Wrapper 标准流程

每个 `make_expert_tool(w)` 返回的 async 函数:

1. `tool_call` SSE 事件
2. `_fetch_materials()` 确定性检索
3. `_summarize()` → `expert.run` (temperature=0.3, max_tokens=16000)
4. 结论无效 → `_retry_materials()` 聚焦重搜 → 再总结
5. 写入 `EXPERT_RESULTS` + `tool_done` 事件

## 检索策略（按专家）

| 专家 | 首轮检索 | 无效重搜 |
|------|----------|----------|
| 默认 | cn-zh, timelimit=y | wt-wt |
| tech_roadmap_expert | cn-zh, 不限时 | wt-wt |
| risk_supply_expert | cn-zh + wt-wt 双视角 | wt-wt 聚焦 |
| investment_expert | 双 query（见下） | 大基金三期 或 PE/市值 |

## investment_expert 特殊分支

**双 query 触发**（task 含 股/上市/估值/PE/市值/ipo 等）:

1. 第 1 次: `大基金 / 补贴 / IPO / 产业政策`
2. 第 2 次: `市值 / PE / 估值 / 财报`

**无效重搜**:

- 含个股关键词 → `半导体 {task} PE 市值 财报`
- 否则 → `国家集成电路产业投资基金 三期 投向`

**输出约束**: 数据须带日期;文末含「不构成投资建议」

## 兜底机制

| 层级 | 触发 | 实现 |
|------|------|------|
| 专家级 | 资料无效 | wrapper 内 `_retry_materials` |
| 总管级 | 专家结论空 | supervisor 重派 1 次 (`max_iterations=3`) |
| 综合级 | 正文 <200 字 | `synthesizer.run(EXPERT_RESULTS)` |
| 溯源级 | 参考来源 | `SEARCH_LOG` 去重后确定性追加 |
| 合规级 | 投资类问题 | server 追加免责声明 |
| 错误级 | DeepSeek 401/429 | 友好 `error` SSE 事件 |

## LLM 调用参数

| 组件 | temperature | max_tokens | 其它 |
|------|-------------|------------|------|
| 专家 `_summarize` | 0.3 | 16000 | 单一 client |
| supervisor | 0.5 | 默认 | max_iterations=3 |
| synthesizer | 0.5 | 默认 | 无 tools |

## 代码位置

- `backend/tool.py` — `SEARCH_STRATEGY`, `fetch_for_expert`, `retry_for_expert`, `web_search`
- `backend/agent.py` — wrapper 调用 tool 层（不再内嵌 query 逻辑）
- `backend/server.py` — producer 流程、兜底综合、参考来源、免责、错误处理
