# AI-Powered Medical Diagnostics

医疗**导诊**与**报告解释**助手（端口 **8010**）

> **定位**：辅助解释症状与检查指标、建议可能就诊科室。**不能**替代医生诊断，**不能**开方。  
> 本 POC **非医疗器械**；上线前须隐私政策、日志脱敏、人工复核与属地监管评估。

## 能力

| 模块 | 说明 |
|------|------|
| IntentRecognizer | 导诊 / 报告解释 / 紧急症状 / 寒暄 / 泛医学 |
| RAG | 医学科普、科室说明、检查项、就诊流程；**多租户**（`shared` + 租户私有） |
| Multi-Agent | Triage / Report / General / Greeting / Emergency |
| Security | 输入预检 + RAG 门禁（Evidence-first）+ 紧急 120 模板 |
| Safety Judge | 输出后检：越权确诊 / 开方 / 敏感内容 |
| Memory | 三级记忆（Redis + ChromaDB）；鉴权开启时按 `{tenant}:{user_id}` 分桶 |
| Auth（可选） | Bearer **API Key** 或 **JWT/OIDC**；角色 `chat` / `readonly` / `admin` |
| Observability | `logs/runs.jsonl` 审计 + Prometheus 业务 KPI |

**主链路**：鉴权（可选）→ 安全预检 → RAG + 知识门禁 → Agent → Safety Judge → 免责声明。  
细节见 [CLAUDE.md](./CLAUDE.md)。

---

## 快速启动

```bash
cd "AI-Powered Medical Diagnostics"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # 含 PyJWT（JWT 鉴权）
cp .env.example .env                     # 填入 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY
chmod +x scripts/*.sh
./scripts/start.sh
# → http://127.0.0.1:8010/docs
```

### 依赖服务（可选）

| 服务 | 用途 | 未连接时 |
|------|------|----------|
| **Redis** | 工作记忆 | 部分记忆功能降级 |
| **ChromaDB** | RAG + 情景记忆 | 回退本地 `./data/chroma` |
| **Keycloak** | OIDC 联调（内测） | 见下文；POC 可不开 |

### DeepSeek 配置提示

`DEEPSEEK_BASE_URL` 须为 Anthropic 兼容路径：

```bash
DEEPSEEK_BASE_URL=https://api.deepseek.com/anthropic
```

勿写 `…/v1` 或 OpenAI 地址，否则 LLM 会 404。详见 [CLAUDE.md §常见陷阱](./CLAUDE.md)。

---

## API 示例

### POC 模式（默认，无需 Token）

```bash
curl -s http://127.0.0.1:8010/health | python3 -m json.tool

curl -s -X POST http://127.0.0.1:8010/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"ALT 52 偏高是什么意思？","user_id":"u1"}' | python3 -m json.tool
```

### 内测鉴权（API Key）

`.env` 中设置 `AUTH_ENABLED=true`：

```bash
AUTH_ENABLED=true
AUTH_API_KEYS=chat-key:chat:hospital_a,admin-key:admin:*
```

```bash
curl -s -X POST http://127.0.0.1:8010/chat \
  -H "Authorization: Bearer chat-key" \
  -H "Content-Type: application/json" \
  -d '{"message":"你好","user_id":"u1"}'
```

| 角色 | 典型接口 |
|------|----------|
| `chat` | `POST /chat`、`POST /search` |
| `readonly` | `GET /knowledge/stats`、`/monitor`、`/eval/safety` |
| `admin` | `POST /knowledge/add`、`/knowledge/import`、`/prompts/reload`、`/skills/reload` |

RAG 按 Key 的 **tenant** 过滤（可见 `shared` 公共库 + 本租户私有库）。完整说明见 [`.env.example`](./.env.example) 与 [`core/auth.py`](./core/auth.py)。

---

## Keycloak 本地联调（JWT / OIDC）

```bash
# 1. 启动 Keycloak（Docker）
./scripts/keycloak_up.sh

# 2. 合并鉴权配置（首次）
cat docker/keycloak/.env.example >> .env

# 3. 多租户知识库：回填旧片段 tenant + 导入 ALT 等文档
./scripts/backfill_kb_tenant_shared.sh --tenant hospital_a

# 4. 启动 API（若 8010 被占用先 kill 旧进程）
lsof -ti:8010 | xargs kill 2>/dev/null
./scripts/start.sh

# 5. 端到端 smoke
./scripts/keycloak_smoke.sh

# 6. 医疗问题 + RAG（doctor 用户）
TOKEN=$(./scripts/keycloak_token.sh doctor doctor123)
curl -s -X POST http://127.0.0.1:8010/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"ALT 52 偏高是什么意思？"}' | python3 -m json.tool
```

| 测试用户 | 密码 | 角色 |
|----------|------|------|
| `doctor` | `doctor123` | md-chat → `/chat` |
| `kbadmin` | `kbadmin123` | md-admin → 知识库管理 |
| `viewer` | `viewer123` | md-readonly → 只读运维 |

详细配置、Claims 映射与故障排查：[docker/keycloak/README.md](./docker/keycloak/README.md)。

**HS256 内测 JWT**（不启 Keycloak 时）：

```bash
python scripts/gen_test_jwt.py --sub u1 --tenant hospital_a --roles chat --print-curl
```

---

## 知识库

知识文件目录：`data/medical_knowledge/`（含 `lab_item/ALT.md` 等），详见 [data/medical_knowledge/README.md](./data/medical_knowledge/README.md)。

```bash
# 本地导入 Chroma
./scripts/import_knowledge.sh

# 经 API 导入（鉴权开启时需 Bearer）
TOKEN=$(./scripts/keycloak_token.sh kbadmin kbadmin123)
./scripts/import_knowledge.sh --via-api http://127.0.0.1:8010 \
  --api-key "$TOKEN" --tenant-id hospital_a

# 启用多租户后：旧片段补 tenant_id=shared + 租户导入（一行命令，勿在行尾写 # 注释）
./scripts/backfill_kb_tenant_shared.sh --tenant hospital_a
```

**Evidence-first**：需要依据的问题若检索 Top-1 分数 `< 0.4`（`MIN_RETRIEVAL_SCORE`），系统拒答而不调用 Agent。

### RAG 成本优化

| 环境变量 | 作用 |
|----------|------|
| `RAG_PREFLIGHT_ENABLED=true`（默认） | 全量 RAG 前 Top-1 预检；低分跳过改写+重排 |
| `RAG_LITE=true` | 仅向量检索，无改写/重排 |

---

## 目录结构

```
AI-Powered Medical Diagnostics/
├── api/main.py              # FastAPI 入口、鉴权 Depends、/chat 主链路
├── core/
│   ├── auth.py              # API Key + 角色 + tenant
│   ├── jwt_auth.py          # JWT / OIDC JWKS
│   ├── knowledge_acl.py     # 租户 RAG filter
│   └── medical_security.py  # 业务门禁
├── agents/
├── mcp/knowledge_base.py    # Chroma + tenant + backfill
├── memory/
├── skills/
├── prompts/
├── data/medical_knowledge/
├── docker/keycloak/         # Keycloak compose + realm 导入
├── evaluation/              # 安全/检索/鉴权回归
├── prometheus/
├── scripts/
│   ├── start.sh
│   ├── start_frontend.sh
│   ├── keycloak_*.sh
│   ├── backfill_kb_tenant_shared.sh
│   └── run_*_checks.sh
├── boundary-checklist.md
├── frontend/                # Vue 3 调试台（EchoMind 风格）
└── CLAUDE.md                # Agent 开发手册（架构与约束）
```

---

## 测试与回归

```bash
# 规则层安全（无需 LLM）
./scripts/run_safety_checks.sh

# 鉴权模块（API Key / JWT / tenant where）
./scripts/run_auth_checks.sh

# RAG 阈值标定
./scripts/run_retrieval_eval.sh

# 端到端 Chat 采样（需 LLM Key + 服务已启动）
./scripts/run_chat_eval.sh
```

HTTP：`GET /eval/safety` · Prometheus：`GET /metrics` · 审计：`logs/runs.jsonl`

---

## Prometheus 监控（可选）

```bash
./scripts/start.sh                    # 终端 1
./scripts/start_prometheus.sh           # 终端 2，需 Docker
# Prometheus → http://127.0.0.1:9090
curl -sL http://127.0.0.1:8010/metrics | grep medical_chat
```

关键指标：Token 用量、`medical_chat_rag_hits_total`（RAG 命中）、`medical_chat_effective_answers_total`（有效回答）、`medical_llm_errors_total`。  
告警与 Runbook：[prometheus/README.md](./prometheus/README.md)。

---

## 外置 Prompt 与 Skills A/B

- **Prompt**：[`prompts/`](./prompts/) — `agents.yaml`、RAG 模板、`security/*.md`；热加载 `POST /prompts/reload`
- **Skills A/B**：`SKILL.md` frontmatter 的 `experiment` / `variant` / `weight`，按 `user_id` 分桶

详见 [prompts/README.md](./prompts/README.md)。

---

## 前端（Vue 3）

参照 EchoMindFrontend，Medical 专用调试台：

```bash
# 终端 1
./scripts/start.sh

# 终端 2
chmod +x scripts/start_frontend.sh
./scripts/start_frontend.sh
# → http://localhost:5173  （/api 代理到 8010）
```

- 侧栏支持 **Keycloak 获取 JWT** 或粘贴 Bearer Token
- 对话、RAG 检索、知识库导入（admin + 租户 ID）
- 详见 [frontend/README.md](./frontend/README.md)

---

## 文档

| 文档 | 内容 |
|------|------|
| [CLAUDE.md](./CLAUDE.md) | 主链路、鉴权/多租户、开发约束、环境变量、陷阱 |
| [boundary-checklist.md](./boundary-checklist.md) | 验收清单 |
| [docker/keycloak/README.md](./docker/keycloak/README.md) | Keycloak 联调 |
| [.env.example](./.env.example) | 完整环境变量 |
| [frontend/README.md](./frontend/README.md) | Vue 3 调试台 |

---

## 相关项目

| 项目 | 说明 |
|------|------|
| AI-Powered TCM Diagnostics | 中医证候 RAG |
| EchoMindFrontend-main | 统一前端（Medical 模式对接 8010） |
