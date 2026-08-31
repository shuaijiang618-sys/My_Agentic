# AI-Powered Medical Diagnostics — 边界与验收清单

## 1. 业务边界

| 允许 | 禁止 |
|------|------|
| 建议可能就诊科室 | 确诊（「你就是 XX 病」） |
| 解释检查指标一般含义 | 处方、剂量、推荐具体药物 |
| 引用公开医学科普 | 替代 ER / 线下就医 |
| 紧急症状 → 120/急诊 | 处理非医疗话题 |

## 2. 安全门禁（P0）

- [x] `core/medical_security.py` — 输入预检
- [x] 紧急症状规则 → `EMERGENCY_RESPONSE`
- [x] 高危医疗意图拦截（确诊/开方/剂量）
- [x] `check_knowledge_gate` — 无检索 / 低分拒答（Evidence-first）
- [x] `check_retrieval_score` — Top-1 < 0.4 拒答
- [x] `core/safety_judge.py` — 输出后检（规则 + 可选 API + LLM；LLM 失败降级仅规则）
- [x] Agent 空内容强制拒答（`check_empty_agent_response`）
- [x] 泛化敏感词 + 可选 `CONTENT_SAFETY_API_URL`
- [x] 偏题 LLM 分类（`OFF_TOPIC_LLM_ENABLED`）
- [x] 每条正常回复附加 `DISCLAIMER`

## 3. RAG（P0）

- [x] 默认医疗知识库（科室/检查项/流程/科普）
- [x] `POST /knowledge/add` / `POST /knowledge/import` 批量导入
- [x] `/chat` 返回 `sources[]`
- [x] 需要依据的问题：**检索不到 → 不调 Agent**

## 4. Agent（P0）

- [x] TriageAgent / ReportInterpretationAgent / GeneralMedicalAgent / EmergencyAgent
- [x] Intent → Agent 路由表
- [x] system prompt 禁止确诊/开方

## 5. 评测与观测

- [x] `logs/runs.jsonl` 审计（含 Token、`outcome`、`response_preview`、`timeout`、`llm_errors`）
- [x] Prometheus Token 指标（`medical_llm_tokens_total`、`medical_chat_estimated_tokens`）
- [x] 业务 KPI 指标（RAG 命中率、有效回答率、人工转接率、LLM 失败率/超时率、Chat 延迟）
- [x] `prometheus/recording_rules/medical-kpi.yml` 预聚合比率 + 告警
- [x] LLM 统一超时/重试（`create_message`）+ `medical_llm_errors_total` / `LlmErrorRateHigh`
- [x] `scripts/run_safety_checks.sh` — 规则层回归（无需 LLM）
- [x] `GET /eval/safety` — 同上，HTTP 入口
- [x] Prometheus 指标（`/metrics`）+ `prometheus/alerts/medical-diagnostics.yml`
- [ ] 端到端 LLM 评测 CI（可选）

## 6. 主链路（当前）

```
check_question → RAG + check_knowledge_gate → Agent → SafetyJudge(fail-closed) → disclaimer
```

## 6.1 身份与接口鉴权（内测/生产）

- [x] `core/auth.py` — Bearer API Key + 角色（chat / readonly / admin）
- [x] `AUTH_ENABLED=false` 默认 — POC 与现有 curl 兼容
- [x] `/chat`、`/search` — chat 角色；Key 可选绑定 `user_id`（`AUTH_BIND_USER_ID`）
- [x] `/knowledge/add`、`/knowledge/import`、`/prompts/reload`、`/skills/reload` — admin
- [x] 知识库 tenant：`shared`（全员可见）+ 租户私有；RAG 按 Key 的 tenant 过滤
- [x] 记忆分桶：`{tenant_id}:{user_id}`，避免跨租户碰撞
- [x] JWT/OIDC：`core/jwt_auth.py`（HS256 + JWKS RS256），与 API Key 并存
- [x] Keycloak 本地联调：`docker/keycloak/` + `scripts/keycloak_*.sh`
- [ ] 细粒度 RBAC、审计按用户查日志（后续）

```bash
./scripts/run_auth_checks.sh
```

## 7. 合规说明

本 POC **非医疗器械**。上线前须：隐私政策、日志脱敏、人工复核流程、属地监管评估。

## 8. 本地验收命令

```bash
./scripts/run_safety_checks.sh
python -c "from core.medical_security import check_knowledge_gate; assert not check_knowledge_gate('ALT偏高', evidence_required=True, source_count=0, top_score=None).allowed"
curl -s http://127.0.0.1:8010/eval/safety | python -m json.tool
```
