# Phase 3 · 质量与合规（M3.1–M3.3）

> **模块**: `quality.py` · `llm_retry.py` · `export.py` · `observability.py`

---

## 能力概览

| 能力 | 文件 | SSE 事件 |
|------|------|----------|
| 429/503 指数退避 | `llm_retry.py` | —（透明重试） |
| 事实校验（启发式） | `quality.py` | `fact_check` |
| 合规过滤 + 投资免责 | `quality.py` | `compliance` |
| Markdown 导出 | `export.py` | —（REST） |
| PDF 导出 | `export.py` + reportlab | —（REST） |
| 合规二次扫描 | `quality.py` | `compliance_rescan` |
| 运行观测 | `observability.py` | `request_id` in start/final |

---

## 11A · 事实校验

在 `final` 之前对简报做确定性检查（不额外调用 LLM）：

1. **未收录 URL**：正文中的 `http(s)://` 链接须出现在本轮 `SEARCH_LOG` 检索记录中，否则警告「可能编造」。
2. **检索覆盖不足**：有检索记录但 snippet  corpus 过短（< 80 字符）时警告。
3. **估值缺日期**：含 PE/市值/股价等表述但未见 `20xx` 或报告期关键词时警告。

`fact_check` 事件示例：

```json
{
  "enabled": true,
  "passed": false,
  "warnings": ["含估值/股价表述但未见明确日期或报告期"],
  "rogue_urls": [],
  "search_refs": 5
}
```

关闭：`ENABLE_FACT_CHECK=false`

---

## 11B · 合规过滤

1. **禁止买卖建议**：命中「建议买入」「目标价」「必涨」等短语 → 替换为 `【表述已合规处理】`。
2. **投资免责**：问题或正文含估值/股价/IPO 等关键词，且尚无免责句时，追加：

   > 以上内容基于公开资料整理，不构成投资建议。

`compliance` 事件示例：

```json
{
  "enabled": true,
  "flags": ["建议买入"],
  "disclaimer_appended": true
}
```

关闭：`ENABLE_COMPLIANCE_FILTER=false`

---

## 11D · LLM 退避

`run_with_retry()` 包裹 supervisor / synthesizer / 专家 wrapper 调用：

- 识别 429、503、502、timeout 类错误
- 指数退避：`LLM_RETRY_BASE_SEC × 2^attempt`
- 默认最多 3 次（`LLM_RETRY_MAX`）

---

## M3.2 · 合规二次扫描

在短语替换之后，用正则做更宽的兜底：

- 收益承诺（「保证…涨/赚/翻倍」）
- 零风险表述
- 内幕消息暗示
- 敏感信息暗示

`compliance_rescan` 事件示例：

```json
{
  "enabled": true,
  "hits": ["收益承诺"],
  "passed": false
}
```

关闭：`ENABLE_COMPLIANCE_RESCAN=false`

---

## 11C · PDF 导出（M3.2）

```bash
# Markdown（默认）
curl -OJ "http://127.0.0.1:8093/api/export?session=default&format=md"

# PDF（reportlab + STSong-Light 中文）
curl -OJ "http://127.0.0.1:8093/api/export?session=default&format=pdf"
```

前端简报区提供 **⬇ MD** / **⬇ PDF** 按钮（走服务端已落库版本）。

关闭：`ENABLE_PDF_EXPORT=false`

---

## M3.3 · 运维观测

每轮 `/api/run` 分配 `request_id`（12 位 hex），写入：

- SSE `start` / `final` / `error` 帧
- `runs.db` 新列 `request_id`、`duration_ms`
- `backend/logs/runs.jsonl`（JSONL，一行一轮）

```bash
curl -s http://127.0.0.1:8093/api/stats | jq
```

关闭 JSONL：`ENABLE_OBSERVABILITY_LOG=false`

---

## 11C · Markdown 导出（M3.1 基础版）

```bash
curl -OJ "http://127.0.0.1:8093/api/export?session=default"
```

返回会话**最新一轮**已落库简报的 `.md` 附件。

---

## 处理流水线（server.py）

```
supervisor.run → (synthesizer 兜底) → 追加参考来源 → postprocess_brief
  → fact_check → compliance → compliance_rescan → final (+ request_id, duration_ms)
```

检索摘要由 `tool.py` 写入 `SEARCH_SNIPPETS` ContextVar，供事实校验使用。

---

## 配置项

| 变量 | 默认 | 说明 |
|------|------|------|
| `ENABLE_FACT_CHECK` | `true` | 启发式事实校验 |
| `ENABLE_COMPLIANCE_FILTER` | `true` | 合规短语 + 免责 |
| `ENABLE_COMPLIANCE_RESCAN` | `true` | 正则二次合规 |
| `ENABLE_PDF_EXPORT` | `true` | PDF 导出 |
| `ENABLE_OBSERVABILITY_LOG` | `true` | JSONL 运行日志 |
| `LLM_RETRY_MAX` | `3` | 最大重试次数 |
| `LLM_RETRY_BASE_SEC` | `1.0` | 退避基数（秒） |

---

## 测试

```bash
./scripts/acceptance.sh   # 含 test_quality.py / test_llm_retry.py
```
