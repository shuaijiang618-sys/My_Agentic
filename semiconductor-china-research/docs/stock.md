# Block 3C · 行情快照 stock_snapshot

> **目标**：为 `investment_expert` 提供带 **as_of 时间戳** 的最新价/PE/市值，降低股价幻觉；失败时静默跳过，由 ddgs 兜底。

---

## 1. 能力

| 项 | 说明 |
|----|------|
| 函数 | `stock_snapshot(symbols)` · `stock_snapshot_for_task(task)` |
| 数据源 | [akshare](https://github.com/akfamily/akshare) `stock_zh_a_spot_em` / `stock_hk_spot_em` |
| 开关 | `.env` → `ENABLE_STOCK_SNAPSHOT=true` |
| 依赖 | `pip install akshare`（已在 requirements.txt） |

### 返回字段

| 字段 | 说明 |
|------|------|
| `code` | 6 位 A 股代码 |
| `name` | 简称 |
| `price` | 最新价 |
| `pe` | 市盈率(动态) |
| `market_cap` | 总市值 |
| `change_pct` | 涨跌幅 % |
| `as_of` | 拉取时间 `YYYY-MM-DD HH:MM` |
| `market` | `A` / `HK` |

---

## 2. 集成流程

```text
fetch_for_expert("investment_expert", task)
    │
    ├─ kb_hit          (Block 3B)
    ├─ stock_snapshot  (Block 3C) ← 命中 6 位代码或 KB 公司名 + 估值关键词
    └─ ddgs 双 query   (Block 3A)
```

**触发条件**（满足其一）：

- task 含 `估值/股价/PE/市值/贵不贵` 等关键词
- task 含 6 位股票代码
- task 命中 KB 公司名（如「北方华创」→ `002371`）

**不计入** `SEARCH_BUDGET`（非 ddgs 检索）。

### SSE 事件

```json
event: stock_snapshot
data: {"expert":"investment_expert","symbols":["002371"],"count":1,"as_of":"2026-07-08 14:30","provider":"akshare","t":150}
```

---

## 3. API

```bash
curl -s 'http://127.0.0.1:8093/api/stock-snapshot?symbols=002371,688012' | python3 -m json.tool
```

`/api/health` 扩展：

```json
{
  "stock_snapshot": true,
  "stock_provider": "akshare"
}
```

---

## 4. 验收标准

- [ ] `pip install akshare` 后 `/api/stock-snapshot?symbols=002371` 返回 `ok: true`
- [ ] 问「北方华创估值贵不贵」时 SSE 含 `stock_snapshot` + 仍含 `search`
- [ ] 快照文本含 `as_of:` 日期时间
- [ ] `ENABLE_STOCK_SNAPSHOT=false` 时不注入、不报错
- [ ] akshare 未安装时 health 中 `stock_provider: null`，走 ddgs 兜底

---

## 5. 故障排查

| 现象 | 处理 |
|------|------|
| `akshare 未安装` | `pip install akshare` |
| 返回空 snapshots | 非交易时段/网络限制；依赖 ddgs 补充 |
| 港股无数据 | 当前优先 A 股 spot；HK 依赖 KB exchange 标注 |
| 拉取慢 | 单次请求内缓存全市场 spot,多代码只拉一次 |

Phase 3 可扩展：历史 K 线、财报 EPS、Block 3B KB 联动 `stock_snapshot` 缓存表。
