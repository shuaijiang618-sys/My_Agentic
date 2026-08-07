# Block 9 · 测试与验收

> **目标**：DeepSeek 链路 + 8 专家 + `investment_expert` 场景可回归。  
> **依赖**：Block 2–8 已完成。  
> **自动化**：`./scripts/acceptance.sh`（离线）· `./scripts/acceptance-live.sh`（需有效 Key + 运行中服务）

---

## 9A · 前置条件

| # | 检查项 | 命令 / 动作 | 通过标准 |
|---|--------|-------------|----------|
| A1 | DeepSeek Key 有效 | `./scripts/smoke.sh` 第 1 步 | HTTP 200 |
| A2 | 账户有余额 | [platform.deepseek.com](https://platform.deepseek.com) | 控制台无欠费 |
| A3 | 服务健康 | `curl -s http://127.0.0.1:8093/api/health \| python3 -m json.tool` | `"ok": true` |
| A4 | 模型与提供商 | 同上 | `provider=deepseek`, `model=deepseek-v4-pro`, `experts=8` |
| A5 | 无 OpenRouter 残留 | `./scripts/check-repo.sh` | 全部 ✅ |
| A6 | 离线自动化 | `./scripts/acceptance.sh` | pytest 全绿 |

---

## 9B · 功能用例（5 场景）

> **说明**：每条用例需在浏览器 http://127.0.0.1:8093 或 SSE 脚本中执行。  
> 记录模板见文末「验收记录表」。

### 用例 1 · 产业链全景

| 项 | 内容 |
|----|------|
| **输入** | `中国半导体发展现状` |
| **session** | `accept-u1`（新会话） |
| **预期专家** | 6~8 个（含 `policy_expert`、`competitor_expert`，视题可含 `investment_expert`） |
| **预期输出** | 有 Markdown 综合简报；文末有 `## 📎 参考来源`；SSE 含 `start` → 多个 `tool_call` → `final` |
| **SSE 检查** | `tool_call` 的 `t` 存在；多专家 `t` 差值 < 总耗时（体现并行） |

```bash
./scripts/acceptance-live.sh --case 1 --session accept-u1
```

---

### 用例 2 · 大基金三期

| 项 | 内容 |
|----|------|
| **输入** | `大基金三期投向` |
| **session** | `accept-u2` |
| **预期专家** | 必含 `investment_expert` + `policy_expert` |
| **预期输出** | 简报提及大基金/产业政策/投资方向等事实；参考来源非空 |
| **检索** | `investment_expert` 应有 `search` / `search_start` 事件 |

---

### 用例 3 · 个股估值（合规）

| 项 | 内容 |
|----|------|
| **输入** | `北方华创估值贵不贵` |
| **session** | `accept-u3` |
| **预期专家** | `investment_expert` 为主；可能含 `equipment_materials_expert` / `competitor_expert` |
| **预期输出** | 若涉及 PE/市值/股价，须带**日期或报告期**；文末含 **「不构成投资建议」** |
| **合规** | 禁止出现具体买卖建议（如「建议买入/卖出」） |

---

### 用例 4 · EDA 国产化（单点环节）

| 项 | 内容 |
|----|------|
| **输入** | `EDA 国产化` |
| **session** | `accept-u4` |
| **预期专家** | `design_ip_expert` + `policy_expert`；通常**不必须** `investment_expert` |
| **预期输出** | 聚焦 EDA/IP/国产化政策；专家数 2~4 为宜 |
| **边界** | 不出现大段无关股价分析 |

---

### 用例 5 · 多轮追问（记忆）

| 项 | 内容 |
|----|------|
| **前置** | 在同一会话先跑用例 1 或任意含「设备公司」的问答 |
| **第 1 轮** | `中国半导体设备国产化现状` · session=`accept-u5` |
| **第 2 轮** | `刚才设备公司谁上市了` · **同一** session=`accept-u5` |
| **预期专家** | 第 2 轮应补派 `investment_expert` + `competitor_expert`（或相关） |
| **记忆** | 第 2 轮总管输入含前几轮摘要（`load_history`）；回答能承接「刚才」语境 |
| **存储** | `GET /api/conversation/accept-u5` 返回 2 条 run |

```bash
# 连续两轮
./scripts/acceptance-live.sh --case 5 --session accept-u5
```

---

## 9C · 非功能验收

| 项 | 标准 | 验证方式 |
|----|------|----------|
| **SSE 并行** | 多个 `tool_call` 的 `t` 重叠或接近 | live 脚本输出 `parallel_ok` |
| **单一模型** | 全链路 `deepseek-v4-pro` | `/api/health` · 日志无其它 model |
| **兜底综合** | supervisor 正文 <200 字时触发 synthesizer | 偶发；日志/专家结果可见 |
| **参考来源** | 来自 `SEARCH_LOG` 真实 href，非模型编造 | `final.brief` 中链接与 `search` 事件一致 |
| **投资免责** | 投资类 query 必含「不构成投资建议」 | server 确定性追加 + prompt 约束 |
| **错误友好** | 401/429/402 → SSE `error` 事件，可读中文 | 故意错 Key 或限流时验证 |
| **空 query** | 返回 `error`，不 silent fail | `GET /api/run?query=` |
| **多轮记忆** | 同 session 第 2 轮带历史摘要 | store.load_history + 用例 5 |

---

## 9D · DeepSeek 特有关注

| 风险 | 验收动作 | 通过标准 |
|------|----------|----------|
| **429 限流** | 连续跑用例 1 + 3 | 若失败，SSE 含友好 `error`，不白屏 |
| **输出截断** | 用例 1 专家 `tool_done` | 单专家 output 不应无故截断在句中（展示限 700 字，完整在综合里） |
| **base_url** | `.env` 用 `https://api.deepseek.com` | smoke 200；文档见 deployment.md |
| **余额** | 跑 5 用例前查余额 | 5 轮完整 `final` 无 402 |

---

## 自动化测试

### 离线（无需 DeepSeek 调用）

```bash
./scripts/acceptance.sh
```

覆盖：health / agents / 空 query / 免责逻辑 / 友好错误 / store 记忆 / 8 专家定义 / 检索策略索引。

### 在线（需有效 Key + 服务）

```bash
./scripts/start.sh
./scripts/acceptance-live.sh              # 跑全部 5 用例（耗时 ~10–20 min）
./scripts/acceptance-live.sh --case 3   # 只跑用例 3
./scripts/stop.sh
```

---

## 验收记录表

| 用例 | 日期 | 执行人 | 专家派发（实际） | final | 参考来源 | 免责 | 并行 | 备注 |
|------|------|--------|------------------|-------|----------|------|------|------|
| 1 | | | | ☐ | ☐ | N/A | ☐ | |
| 2 | | | | ☐ | ☐ | N/A | ☐ | |
| 3 | | | | ☐ | ☐ | ☐ | ☐ | |
| 4 | | | | ☐ | ☐ | N/A | ☐ | |
| 5 轮1 | | | | ☐ | ☐ | N/A | ☐ | |
| 5 轮2 | | | | ☐ | ☐ | ☐ | ☐ | 记忆 ☐ |

**签字**：____________　**版本**：Block 9 · Phase 1 MVP

---

## 故障排查

| 现象 | 见 |
|------|-----|
| smoke 401 | [deployment.md](deployment.md) §7 |
| SSE 无 final | `backend/logs/server.log` · DeepSeek 429/超时 |
| 专家全派 8 个 | 正常（全景题）；单点题应 2~4，可调 supervisor prompt |
| 无参考来源 | ddgs 未返回结果；检查网络 |
