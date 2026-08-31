# Prometheus 监控与告警

## 前置条件

1. 应用已启动：`./scripts/start.sh`（默认 `http://127.0.0.1:8010`）
2. 指标端点：`GET http://127.0.0.1:8010/metrics`
3. 可选独立 metrics 端口：`.env` 中设置 `PROMETHEUS_PORT=9091`

## 快速启动（Docker）

```bash
# 终端 1：Medical API
./scripts/start.sh

# 终端 2：Prometheus + Alertmanager
./scripts/start_prometheus.sh
```

- Prometheus UI: http://127.0.0.1:9090
- Alertmanager UI: http://127.0.0.1:9093
- 规则文件：`prometheus/alerts/medical-diagnostics.yml`

## 主要指标

| 指标 | 说明 |
|------|------|
| `medical_chat_requests_total{outcome}` | Chat 请求（success / blocked_* / llm_failed / error）→ **回答成功率** |
| `medical_chat_rag_queries_total` / `medical_chat_rag_hits_total` | RAG 检索次数 / 命中次数 → **命中率** |
| `medical_chat_effective_answers_total` | Agent 成功 + Safety 通过 → **有效回答率** 分子 |
| `medical_chat_hitl_total` | hitl / escalated / emergency → **人工转接率** 分子 |
| `medical_llm_attempts_total{stage}` | LLM 尝试次数（含重试）→ 失败率/超时率分母 |
| `medical_llm_errors_total{stage,reason}` | LLM 错误 → **模型接入失败率** / **超时率** 分子 |
| `medical_chat_latency_seconds` | Chat 延迟 → **平均响应时间** / P99 |
| `medical:rag_hit_rate:5m` 等 | recording rules 预聚合比率（见 `recording_rules/medical-kpi.yml`） |
| `agent_success_rate` / `agent_latency_ms` | Agent 在线表现（Monitor 周期写入） |
| `tool_success_rate{tool="knowledge_search"}` | 检索工具成功率 |

### 业务 KPI PromQL 速查

```promql
# 命中率
medical:rag_hit_rate:5m

# 有效回答率
medical:effective_answer_rate:5m

# 人工转接率
medical:hitl_rate:5m

# 回答成功率
medical:answer_success_rate:5m

# 模型接入失败率
medical:llm_failure_rate:5m

# 超时率（LLM 调用维度）
medical:llm_timeout_rate:5m

# 平均响应时间
medical:chat_latency_avg_seconds:5m
```

本地 JSONL 汇总：`curl -s http://127.0.0.1:8010/health | python -m json.tool` → `audit.rag_hit_rate` 等。

## Runbook 摘要

### MedicalApiDown

1. `curl -s http://127.0.0.1:8010/health`
2. 重启 `./scripts/start.sh`
3. 确认 Prometheus `scrape_configs` 中 target 与 `PORT` 一致

### KnowledgeBaseEmpty

1. `./scripts/import_knowledge.sh`
2. 确认 `medical_knowledge_chunks` > 0

### KnowledgeGateMayBeBypassed

1. 跑 `./scripts/run_safety_checks.sh`
2. 检查 `api/main.py` 中 `check_knowledge_gate` 是否在 Agent 之前执行
3. 查看 `logs/runs.jsonl` 中 `blocked_reason`

### KnowledgeSearchToolDegraded

1. 检查 ChromaDB / `CHROMA_PERSIST_DIRECTORY`
2. 调用 `POST /search` 验证检索

### LlmErrorRateHigh

1. `curl -sL http://127.0.0.1:8010/metrics | grep medical_llm_errors`
2. 确认 `DEEPSEEK_BASE_URL=https://api.deepseek.com`（无 `/v1` 后缀）
3. 调整 `.env` 中 `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES`
4. 查看 `logs/runs.jsonl` 字段 `llm_errors`

## 校验规则语法

```bash
docker run --rm -v "$(pwd)/prometheus:/etc/prometheus" prom/prometheus:latest \
  promtool check rules /etc/prometheus/alerts/medical-diagnostics.yml
```

## Slack 告警（可选）

1. 在 Slack 创建 **Incoming Webhook**（Apps → Incoming Webhooks → 选频道）
2. 将 URL 写入项目根目录 `.env`（勿提交 Git）：

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
SLACK_CHANNEL=#medical-alerts
```

3. 渲染并启动：

```bash
./scripts/render_alertmanager.sh   # 生成 prometheus/alertmanager.generated.yml
./scripts/start_prometheus.sh
```

4. 在 Prometheus UI 手动触发测试告警，或等待规则 firing，确认 Slack 频道收到消息。

未配置 `SLACK_WEBHOOK_URL` 时，告警仅在 http://127.0.0.1:9093 可见。

模板文件：`prometheus/alertmanager.slack.yml.template`（占位符由脚本替换，避免密钥进仓库）。

