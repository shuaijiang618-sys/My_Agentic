# Block 3B · 本地产业知识库

> **目标**：为专家 Wrapper 提供结构化产业数据前缀，降低公司名/代码/大基金幻觉；**仍走 ddgs** 补充时效信息。

---

## 1. 数据库

| 项 | 值 |
|----|-----|
| 文件 | `backend/data/industry_kb.db` |
| 初始化 | `python -m backend.seed.industry_kb` |
| 开关 | `.env` → `ENABLE_INDUSTRY_KB=true`（默认开启） |

### 四表

| 表 | 用途 | 种子规模 |
|----|------|----------|
| `listed_semiconductor` | A/H 股代码、板块、segment | **30** 只 |
| `fund_events` | 大基金/地方基金事件 | 3 条 |
| `facilities` | 晶圆厂/封测产线(示例) | 5 条 |
| `policy_events` | 政策/制裁事件(示例) | 3 条 |

### segment 枚举

`foundry` · `osat` · `equipment` · `material` · `eda` · `fabless` · `fabless_ai` · `ip` · `idm` · `power_idm` · `power` · `sic` · `power_module`

---

## 2. 检索注入流程

```text
fetch_for_expert(expert, task)
    │
    ├─ kb_lookup_for_expert()     ← Block 3B（静态 KB）
    │     emit SSE: kb_hit
    │
    └─ web_search / dual_query    ← Block 3A（ddgs 时效）
```

**原则**：KB 是「结构化前缀」，不是替代联网；数字/股价/政策动态仍以 ddgs 为准。

### 专家 ↔ KB 映射

| 专家 | KB 内容 |
|------|---------|
| `investment_expert` | 代码/公司名、大基金事件、segment 同业 |
| `competitor_expert` | 命中公司、segment 列表 |
| `policy_expert` | policy_events |
| `manufacturing_expert` | facilities、foundry/osat 标的 |
| `equipment_materials_expert` | equipment/material segment |
| `design_ip_expert` | eda/fabless/ip segment |

---

## 3. API

### `GET /api/knowledge`

| 参数 | 说明 |
|------|------|
| （无） | stats + segments 列表 |
| `segment=equipment` | 该环节上市标的 |
| `q=北方华创` | 公司名模糊 |
| `q=002371` | 6 位代码 |
| `q=大基金` | fund_events |

示例：

```bash
curl -s 'http://127.0.0.1:8093/api/knowledge' | python3 -m json.tool
curl -s 'http://127.0.0.1:8093/api/knowledge?segment=equipment'
curl -s 'http://127.0.0.1:8093/api/knowledge?q=002371'
```

### `/api/health` 扩展

```json
{
  "knowledge_base": true,
  "kb_stats": {
    "listed_semiconductor": 30,
    "fund_events": 3,
    "facilities": 5,
    "policy_events": 3
  }
}
```

### SSE 新事件

| event | 含义 |
|-------|------|
| `kb_hit` | 专家检索前命中本地 KB · 字段: `expert`, `chars`, `t` |

---

## 4. 验收标准（Block 3B）

- [ ] `python -m backend.seed.industry_kb` 成功，30 只标的
- [ ] `GET /api/knowledge?segment=equipment` 返回北方华创等
- [ ] 问「大基金三期」时 investment 资料前缀含 fund_events
- [ ] 问「北方华创估值」时 KB 命中 002371 + 仍发 `search` 事件
- [ ] `ENABLE_INDUSTRY_KB=false` 时不注入、health 显示 false

---

## 5. 维护

1. 编辑 `backend/seed/industry_kb.py` 中 `LISTED` / `FUND_EVENTS` 等
2. 重新运行 `python -m backend.seed.industry_kb`（会清空并重灌）
3. 生产环境建议定期人工更新大基金/政策条目并标注 `source_url`

Phase 2 后续：**Block 3C** `stock_snapshot`（akshare 实时 PE/市值）
