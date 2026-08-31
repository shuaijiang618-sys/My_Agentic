# CLAUDE.md — AI-Powered Medical Diagnostics

医疗导诊与报告解释助手（端口 **8010**）。  
用户文档：[README.md](./README.md) · 验收清单：[boundary-checklist.md](./boundary-checklist.md)

---

## 产品边界

| 做 | 不做 |
|----|------|
| 症状导诊（建议可能就诊科室） | 确诊（「你就是 XX 病」） |
| 检查指标科普解释 | 处方、剂量、推荐具体药物 |
| 就诊流程说明、RAG 引用展示 | 替代 ER / 线下就医 |
| 紧急症状 → 120 / 急诊模板 | 处理非医疗话题 |

本 POC **非医疗器械**；上线前须隐私政策、日志脱敏、人工复核、属地监管评估。

---

## 主链路（不可改顺序）

```
POST /chat
  → require_chat_auth (AUTH_ENABLED 时)           # Bearer API Key 或 JWT
  → validate_client_user_id + effective_user_id   # {tenant}:{user} 记忆分桶
  → reset_token_tracker()
  → core.medical_security.check_question_async
  → _build_knowledge_context(tenant_id=auth.tenant)  # RAG 按租户 + shared 过滤
  → core.medical_security.check_knowledge_gate
  → agents.AgentOrchestrator.run
  → check_empty_agent_response
  → core.safety_judge.SafetyJudge.judge
  → append_disclaimer
  → observability.log_run
  → monitor.metrics record_chat_*
```

**Evidence-first**：需要知识依据的问题，检索不到或 Top-1 分数 `< MIN_RETRIEVAL_SCORE`（当前 **0.4**）时，必须在 RAG 门禁处拒答，**不得**调用 Agent 编造。

**默认 POC**：`AUTH_ENABLED=false` 时不要求 Token，行为与改造前一致。

---

## 近期架构与修改点（Agent 须知晓）

### 1. RAG 成本优化

| 模式 | 环境变量 | 行为 |
|------|----------|------|
| **预检**（默认） | `RAG_PREFLIGHT_ENABLED=true` | 全量 rewrite/rerank 前先 Top-1 向量预检；低分跳过改写+重排（约省 2 次 LLM） |
| **LITE** | `RAG_LITE=true` | 始终仅向量检索，无改写/重排；与预检互斥 |
| **阈值** | `MIN_RETRIEVAL_SCORE=0.4`（`core/medical_security.py`） | 预检、LITE、门禁共用；标定见 `scripts/run_retrieval_eval.sh` |

实现入口：`api/main.py` → `_build_knowledge_context`、`_rag_lite_enabled`、`_rag_preflight_enabled`。

### 2. Token 用量与 LLM 容错

- **模块**：`core/token_usage.py`（ContextVar 按请求累加）
- **统一 LLM 入口**：`core/llm_utils.create_message`  
  - `asyncio.wait_for` 超时：`LLM_TIMEOUT_S`（默认 60s）  
  - 可配置重试：`LLM_MAX_RETRIES`（默认 1）、`LLM_RETRY_ENABLED`、`LLM_RETRY_BACKOFF_S`  
  - 重试条件：timeout / 429 / 5xx / 网络错误；**4xx（除 429）不重试**  
  **禁止**直接 `client.messages.create`
- **Stage 命名**：`rag_rewrite` / `rag_rerank` / `intent` / `intent_entities` / `agent_{type}` / `agent_{type}_retry` / `judge`  
  后台记忆设 `request_scoped=False`
- **JSONL 字段**：Token 字段 + `llm_errors[]`、`llm_retry_count`
- **Prometheus**：`medical_llm_errors_total{stage,reason}`、`medical_llm_retries_total{stage}`、Token/Chat 指标  
  告警：`LlmErrorRateHigh`（见 `prometheus/alerts/medical-diagnostics.yml`）

### 3. 外置 Prompt 与 Skills

- **外置**：`prompts/`（`agents.yaml`、RAG 模板、`security/*.md` 拒答文案）  
  加载：`core/prompt_registry.py` · 热加载：`POST /prompts/reload`
- **结构化输出**（triage / report / general）：  
  - `prompts/output_schemas.yaml` — JSON 字段与 system 追加说明  
  - `prompts/templates/*.md` — 固定段落标题渲染  
  - `core/structured_response.py` — 解析 / 校验 / 渲染；失败时 **自动重试 1 次**（stage `agent_*_retry`），仍失败则回退原文  
  - `emergency` 仍为固定模板拒答
- **仍硬编码**：`core/safety_judge.py` 中 Judge prompt（**不外置**）
- **Skills A/B**：`skills/*/SKILL.md` frontmatter 支持 `version`、`experiment`、`variant`、`weight`，按 `user_id` 分桶；话术须与模板段落（如「建议咨询科室」）一致

### 4. LLM 配置（DeepSeek / Anthropic）

- `.env` 二选一：`DEEPSEEK_API_KEY` 或 `ANTHROPIC_API_KEY`
- **Base URL**：`DEEPSEEK_BASE_URL=https://api.deepseek.com`（**不要**写 `…/v1`）  
  Anthropic SDK 自行追加 `/v1/messages`；重复 `/v1` 会导致 `…/v1/v1/messages` → **404**
- 归一化：`core/llm_utils.normalize_anthropic_base_url()`（`api/main.py` `_llm_cfg` 已调用）
- 超时/重试：见 §2；Judge LLM/JSON 失败 → **仅规则通过**（规则已拦越权/敏感）；内容安全 API 命中仍拒答

### 5. Prometheus 监控

- 应用内：`monitor/metrics.py` · 端点：`GET /metrics`（与 FastAPI 同端口）
- 可选 Docker 栈：`scripts/start_prometheus.sh` → `prometheus/` + Alertmanager
- Chat 指标：`medical_chat_requests_total{outcome}`、`medical_knowledge_gate_blocks_total`、`medical_safety_judge_blocks_total`
- **业务 KPI 原始计数**：`medical_chat_rag_queries_total` / `medical_chat_rag_hits_total`（命中率）、`medical_chat_effective_answers_total`（有效回答）、`medical_chat_hitl_total`（人工转接）、`medical_llm_attempts_total`（模型失败率/超时率分母）
- **预聚合比率**（Prometheus recording rules）：`medical:rag_hit_rate:5m`、`medical:effective_answer_rate:5m`、`medical:hitl_rate:5m`、`medical:answer_success_rate:5m`、`medical:llm_failure_rate:5m`、`medical:llm_timeout_rate:5m`、`medical:chat_latency_avg_seconds:5m`
- `/health` → `audit` 字段含近 500 条 JSONL 汇总的 KPI 比率

### 6. 评测脚本

| 脚本 | 用途 |
|------|------|
| `scripts/run_safety_checks.sh` | 规则层回归（无需 LLM） |
| `scripts/run_auth_checks.sh` | 鉴权模块回归（API Key / JWT / tenant where，无需 LLM） |
| `scripts/run_retrieval_eval.sh` | RAG 阈值标定（`evaluation/retrieval_cases.json`） |
| `scripts/run_chat_eval.sh` | 端到端 `/chat` 采样（需 API + Key） |

### 7. 身份鉴权与多租户 RAG（2026-08 内测/生产）

内测/生产启用 `AUTH_ENABLED=true` 后，Bearer Token 在业务门禁**之前**校验；业务安全门禁（`medical_security`）与身份鉴权是两套机制，勿混淆。

#### 7.1 两层「权限」

| 类型 | 控制什么 | 模块 |
|------|----------|------|
| **身份/接口/资源** | 谁在调用、能否调管理 API、看哪份知识库 | `core/auth.py`、`core/jwt_auth.py` |
| **业务/内容** | 能否回答、有无 RAG 依据、输出是否越权 | `core/medical_security.py`、`SafetyJudge` |

#### 7.2 Bearer Token 解析（`verify_bearer_token`）

1. Token 含两个 `.` → 优先 **JWT**（`core/jwt_auth.py`）
2. 否则 → **API Key**（`AUTH_API_KEYS`）
3. JWT 校验失败且形如 JWT 时 **不回退** 到 API Key

| 模式 | 配置 |
|------|------|
| API Key | `AUTH_API_KEYS=secret:role:tenant[:user_id]`（角色 `chat` / `readonly` / `admin`） |
| HS256 内测 JWT | `AUTH_JWT_SECRET` + `scripts/gen_test_jwt.py` |
| OIDC / Keycloak RS256 | `AUTH_JWT_JWKS_URL`、`AUTH_JWT_ISSUER`、`AUTH_JWT_AUDIENCE` |

Claims 映射（env 可覆盖 claim 名）：

| Claim | 用途 |
|-------|------|
| `sub` / `preferred_username` | `user_id`；JWT 下 body 可省略或传 `anonymous` |
| `tenant_id`（Keycloak 可为数组 `["hospital_a"]`） | RAG 租户隔离 |
| `realm_access.roles` | 经 `AUTH_JWT_ROLE_MAP` 映射为 chat/readonly/admin |

#### 7.3 接口权限矩阵

| 接口 | 最低角色 | 说明 |
|------|----------|------|
| `GET /health`、`/metrics`、`/docs` | 公开 | 探针与文档 |
| `POST /chat`、`/search` | `chat` | 主链路 |
| `GET /knowledge/stats`、`/monitor`、`/eval/safety` | `readonly` | 只读运维 |
| `POST /knowledge/add`、`/import`、`/prompts/reload`、`/skills/reload` | `admin` | 管理写操作；admin 通配 `*` 可用 `X-Tenant-ID` 指定写入租户 |

#### 7.4 知识库租户

- 片段 metadata：`tenant_id` = `shared`（全员可读）或租户私有（如 `hospital_a`）
- 检索 filter：`core/knowledge_acl.build_tenant_where` → `$or: [本 tenant, shared]`
- 实现：`mcp/knowledge_base.search(..., tenant_id=)`；`/chat` 传入 `auth.tenant_id`
- **记忆分桶**：`AuthContext.effective_user_id()` → `{tenant_id}:{user_id}`，避免跨租户碰撞

**历史数据**：早期 Chroma 片段无 `tenant_id` 时，启用多租户后对 tenant 过滤不可见 → 运行：

```bash
./scripts/backfill_kb_tenant_shared.sh --tenant hospital_a
```

会为缺 `tenant_id` 的片段补打 `shared`，并导入 `data/medical_knowledge/`（含 `lab_item/ALT.md`）到指定租户。

#### 7.5 Keycloak 本地联调

| 项 | 值 |
|----|-----|
| 启动 | `./scripts/keycloak_up.sh` |
| Realm / Client | `medical` / `medical-api` |
| Admin Console | http://localhost:8080/admin（`admin` / `admin`） |
| 测试用户 | `doctor`/`doctor123`（md-chat）、`kbadmin`/`kbadmin123`（md-admin）、`viewer`/`viewer123`（md-readonly） |
| 文档 | [docker/keycloak/README.md](./docker/keycloak/README.md) |

联调 env 模板：`docker/keycloak/.env.example`（merge 到项目根 `.env`）。

```bash
cat docker/keycloak/.env.example >> .env
./scripts/start.sh                    # AUTH 开启时自动补装 PyJWT
./scripts/keycloak_smoke.sh           # Token + 寒暄 /chat
./scripts/keycloak_token.sh doctor doctor123
```

带 JWT 导入知识库：

```bash
TOKEN=$(./scripts/keycloak_token.sh kbadmin kbadmin123)
./scripts/import_knowledge.sh --via-api http://127.0.0.1:8010 \
  --api-key "$TOKEN" --tenant-id hospital_a
```

依赖：`PyJWT[crypto]==2.10.1`（`requirements.txt`；`start.sh` 在 JWT 开启时会 `python -m pip install`）。

---

## 开发约束（P0）

1. **安全优先**：不得跳过 `check_question` / `check_question_async`、`check_knowledge_gate`、`SafetyJudge`；**空 Agent 正文强制拒答**；Judge LLM 失败 **降级为仅规则通过**（规则仍拦截越权/敏感）。
2. **Evidence-first**：无检索 / 低分不得调 Agent；不得为「能回答」而降低 `MIN_RETRIEVAL_SCORE` 除非有评测数据支撑。
3. **单代码路径**：新增 UI / CLI / 评测须复用 `api/main.py` 同一套门禁与 RAG 逻辑，禁止旁路。
4. **LLM 调用规范**：新增 LLM 调用须走 `create_message` 并指定 `stage`；后台任务用 `request_scoped=False`。
5. **结构化输出**：triage/report/general 改 JSON 或模板时，同步改 `output_schemas.yaml` + `templates/*.md` + 对应 Skill；解析失败会重试 1 次（`_retry` stage），不得绕过 `structured_response`。
6. **Prompt 变更**：Agent / 拒答文案改 `prompts/` + `POST /prompts/reload`；Judge 改 `safety_judge.py` 并跑安全回归。
7. **架构对齐**：与 EchoMind Python 保持 Orchestrator / Memory / MCP 模式；Skills 目录 `ECHOMIND_SKILLS_DIR`。
8. **观测不静默失败**：改 `log_run` / metrics 时勿吞掉 Token 字段；改完须重启 `./scripts/start.sh` 再验 `logs/runs.jsonl`。
9. **密钥与合规**：勿提交 `.env`；日志 query 经 `redact_pii`；勿移除 `DISCLAIMER`。
10. **鉴权不旁路**：`AUTH_ENABLED=true` 时不得跳过 `require_*_auth`；管理接口不得对公网裸奔；`user_id` 在 Key/API 绑定时不得由客户端伪造（`AUTH_BIND_USER_ID`）。
11. **多租户 RAG**：新增/导入知识须带 `tenant_id`；改 filter 逻辑时同步 `core/knowledge_acl.py` 与 `backfill_kb_tenant_shared` 文档。

---

## 关键文件

| 路径 | 职责 |
|------|------|
| `api/main.py` | HTTP 入口、`/chat` 主链路、RAG 策略、Token tracker 重置 |
| `core/medical_security.py` | 输入预检、RAG 门禁、空内容拒答 |
| `core/content_safety.py` | 敏感词 + 可选内容安全 API |
| `core/off_topic_classifier.py` | 偏题 LLM 分类 |
| `core/safety_judge.py` | 规则 + LLM Judge（硬编码 prompt） |
| `core/prompt_registry.py` | 外置 Prompt 加载与热更新 |
| `core/structured_response.py` | triage/report JSON 解析与 Markdown 模板渲染 |
| `core/token_usage.py` | 请求级 Token 统计 |
| `core/llm_utils.py` | `create_message`、`normalize_anthropic_base_url` |
| `core/auth.py` | Bearer API Key 鉴权、角色、租户、user_id 绑定 |
| `core/jwt_auth.py` | JWT/OIDC（HS256、JWKS RS256）校验与 claims 映射 |
| `core/knowledge_acl.py` | 知识库 tenant Chroma `where` 条件（纯逻辑，无 Chroma 依赖） |
| `agents/agent_orchestrator.py` | Intent → Agent 路由 |
| `core/intent_recognizer.py` | 意图识别（LLM + embedding + 规则投票） |
| `mcp/tool_manager.py` | RAG 改写 / 重排 / 工具链 |
| `mcp/knowledge_base.py` | Chroma 向量检索、`tenant_id` 写入/过滤、`backfill_tenant_shared()` |
| `memory/conversation_memory.py` | Redis 工作记忆 + Chroma 情景记忆 |
| `observability.py` | `logs/runs.jsonl` 审计（query/Token/outcome/response_preview/timeout/异常） |
| `monitor/metrics.py` | Prometheus 指标定义 |
| `prompts/` | 外置 Agent / RAG / security / output_schemas / templates |
| `skills/` | 业务 Skills（A/B） |
| `prometheus/` | 告警规则与 Alertmanager 模板 |
| `evaluation/` | 检索与 Chat 评测；`evaluation/auth_runner.py` 鉴权回归 |
| `docker/keycloak/` | Keycloak docker-compose、realm 导入、联调 README |
| `data/medical_knowledge/lab_item/ALT.md` | ALT 指标科普（多租户导入用例） |
| `scripts/keycloak_*.sh` | Keycloak 启动 / 取 Token / smoke |
| `scripts/backfill_kb_tenant_shared.sh` | 旧库 tenant 回填 + 目录导入 |
| `scripts/import_knowledge.py` | 支持 `--api-key`、`--tenant-id`（`MEDICAL_API_KEY`） |
| `scripts/gen_test_jwt.py` | 内测 HS256 JWT 签发 |
| `frontend/` | Vue 3 调试台（`scripts/start_frontend.sh` → :5173） |

---

## 环境变量速查

| 变量 | 默认 | 说明 |
|------|------|------|
| `PORT` | `8010` | API 端口 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/anthropic` | DeepSeek 须用 Anthropic 兼容路径；写根域名会自动补 `/anthropic` |
| `RAG_PREFLIGHT_ENABLED` | `true` | RAG 预检 |
| `RAG_LITE` | `false` | 仅向量检索 |
| `ENABLE_OBSERVABILITY_LOG` | `true` | 写 `runs.jsonl` |
| `LOG_RESPONSE_PREVIEW_MAX` | `500` | 审计日志回复摘要长度（0=关闭） |
| `PROMPTS_DIR` | `./prompts` | 外置 Prompt |
| `PROMETHEUS_PORT` | — | 可选独立 metrics 端口 |
| `LLM_TIMEOUT_S` | `60` | 单次 LLM 调用超时（秒） |
| `LLM_MAX_RETRIES` | `1` | 失败后额外重试次数 |
| `LLM_RETRY_ENABLED` | `true` | 是否启用 API 重试 |
| `LLM_RETRY_BACKOFF_S` | `0.5` | 重试基础退避（含随机 jitter） |
| `MIN_AGENT_RESPONSE_CHARS` | `8` | Agent 正文最小长度 |
| `OFF_TOPIC_LLM_ENABLED` | `false` | 偏题 LLM 分类 |
| `CONTENT_SAFETY_API_URL` | — | 可选内容安全 HTTP API |
| `AUTH_ENABLED` | `false` | 启用 Bearer API Key 鉴权 |
| `AUTH_API_KEYS` | — | `secret:role:tenant[:user_id]` 逗号分隔 |
| `AUTH_BIND_USER_ID` | `true` | Key 绑定 user 时拒绝伪造 |
| `AUTH_DEFAULT_TENANT` | `default` | admin 通配 `*` 时的默认租户 |
| `AUTH_JWT_SECRET` | — | HS256 对称密钥（内测） |
| `AUTH_JWT_JWKS_URL` | — | OIDC JWKS（RS256） |
| `AUTH_JWT_ISSUER` / `AUTH_JWT_AUDIENCE` | — | JWT 发行方/受众校验 |
| `AUTH_JWT_ROLE_MAP` | — | IdP 角色 → chat/readonly/admin（如 `md-chat:chat,md-admin:admin`） |
| `AUTH_JWT_ENABLED` | 自动 | 显式开关；或凭 `AUTH_JWT_SECRET` / `JWKS_URL` 推断 |
| `MEDICAL_API_KEY` | — | `import_knowledge.sh --via-api` 用 Bearer |
| `KEYCLOAK_URL` / `KEYCLOAK_REALM` | localhost:8080 / medical | `keycloak_token.sh` |

完整列表见 [.env.example](./.env.example)。

---

## 本地验证

```bash
# 语法 + 规则层 + 鉴权（无需 LLM）
python -m py_compile api/main.py core/*.py agents/*.py
./scripts/run_safety_checks.sh
./scripts/run_auth_checks.sh

# POC 模式（AUTH_ENABLED=false）
./scripts/start.sh
curl -s http://127.0.0.1:8010/health | python -m json.tool
curl -s -X POST http://127.0.0.1:8010/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好","user_id":"u1"}' > /dev/null
tail -1 logs/runs.jsonl | python -m json.tool

# Keycloak + JWT 联调（AUTH_ENABLED=true，见 docker/keycloak/.env.example）
./scripts/keycloak_up.sh
cat docker/keycloak/.env.example >> .env   # 首次；勿在行尾写 shell 注释
./scripts/backfill_kb_tenant_shared.sh --tenant hospital_a
lsof -ti:8010 | xargs kill 2>/dev/null; ./scripts/start.sh
./scripts/keycloak_smoke.sh

TOKEN=$(./scripts/keycloak_token.sh doctor doctor123)
curl -s -X POST http://127.0.0.1:8010/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"ALT 52 偏高是什么意思？"}' | python3 -m json.tool
# 期望：blocked=false, knowledge_used=true, sources 含 ALT

# Prometheus
curl -sL http://127.0.0.1:8010/metrics | grep medical_chat_estimated
```

---

## 常见陷阱

| 现象 | 原因 | 处理 |
|------|------|------|
| `runs.jsonl` 无 Token 字段 | 旧进程 / 旧日志行 | 重启 `./scripts/start.sh` 后再发请求 |
| `runs.jsonl` 无 `response_preview` | `LOG_RESPONSE_PREVIEW_MAX=0` 或旧进程 | 确认 env 并重启 |
| LLM 全部 404 | DeepSeek 用了根域名或 `/v1` | 改为 `https://api.deepseek.com/anthropic`（或根域名由 `normalize_anthropic_base_url` 自动补 `/anthropic`） |
| `grep medical_chat_*` 无输出 | 服务未启 / 未跟重定向 | `curl -sL`；至少完成一次 `/chat` 才有 histogram 样本 |
| LLM 全 404 且 `llm_errors` 含 `client_error` | DeepSeek base_url 未指向 Anthropic 兼容面 | 见上 |
| `LlmErrorRateHigh` 告警 | 超时/限流/5xx 过多 | 查 `medical_llm_errors_total` 与 `logs/runs.jsonl` 的 `llm_errors` |
| RAG 全被 `low_retrieval` 拦截 | 知识库未导入或阈值过高 | `./scripts/import_knowledge.sh`；跑 `run_retrieval_eval.sh` 标定 |
| `AUTH_ENABLED` 下 ALT 等 `no_retrieval` | 旧片段无 `tenant_id` 或租户库无对应文档 | `./scripts/backfill_kb_tenant_shared.sh --tenant hospital_a`；确认 `lab_item/ALT.md` |
| `ModuleNotFoundError: jwt` | 未装 PyJWT | `.venv/bin/python -m pip install 'PyJWT[crypto]==2.10.1'` 或重启 `start.sh`（自动补装） |
| `address already in use :8010` | 旧 uvicorn 未退出 | `lsof -ti:8010 \| xargs kill` 后再 `start.sh` |
| backfill 脚本报 unrecognized arguments | 命令行写了 `# 注释` | 注释单独一行；勿 `./script.sh --x  # 说明` |
| Keycloak `/chat` 401 | `.env` 未 merge JWT 配置或 issuer 不匹配 | 对照 `docker/keycloak/.env.example` 与 realm `medical` |
