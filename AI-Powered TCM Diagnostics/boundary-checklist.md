# AI-Powered TCM Diagnostics — 业务验收口径 & 风险边界清单 v2.0

> 与 [`new_zhongyi_agent.py`](new_zhongyi_agent.py)、[`project-blueprint.md`](project-blueprint.md)、[`项目说明.md`](项目说明.md) 对齐。  
> 标注 **【POC】** = 当前可验收；**【目标态】** = API/治理阶段（见 `.cursor/skills/tcm-diagnostics-platform/SKILL.md`）。

---

## 0. 文档适用范围

| 阶段 | 范围 | 典型交付 |
|------|------|----------|
| POC（当前） | 单用户本地；Gradio + LlamaIndex RAG + RAGAS | `python new_zhongyi_agent.py` |
| Week01+ | 可选 FastAPI `/api/v1`、JSONL 审计、安全门禁 | `backend/` 骨架 |
| Week08+ | citations 暴露、RAGAS 门禁、request_id 全链路 | 评估 CI + UI/API 一致 |
| Week14+ | release manifest、索引回滚、安全扫描 CI | `release_manifest.json` |

---

## 1. 系统边界（做什么 / 不做什么）

### ✅ 系统做

| 类别 | 具体能力 | 状态 |
|------|----------|------|
| 知识问答 | 基于 `doc_emb/` 检索 Top-5，回答**中医证候/辨证**问题；Prompt 要求严格依据上下文（`new_zhongyi_agent.py`） | 【POC】已实现 |
| 证据引用 | 回答附检索片段 `sources[]`（snippet / score / doc_ref） | 【POC】Gradio/API 需展示 |
| 文本检索 | 当前索引来源为 `data/*.txt`（如 `demo.txt`） | 【POC】已实现 |
| 多格式检索 | PDF / FAQ / Word / CSV 扩展入库 | 【目标态】Phase 2 |
| 人工介入（HITL） | 个体化处方、用药剂量、确诊类请求 → 免责声明 + `hitl_required` | 【POC】规则拦截 |
| 审计追踪 | 每次问答写入 JSONL（request_id、query 截断、blocked、duration_ms） | 【POC】`backend/logs/runs.jsonl` |
| 版本与回滚 | `release_id` 绑定 data / index / prompt；可回滚索引快照 | 【目标态】Week14 |

### ❌ 系统不做

| 类别 | 说明 |
|------|------|
| 正式临床诊断 | 不提供替代执业医师的 diagnosis / 处方决策；仅辅助学习、知识查询 |
| 开放式聊天 | 不回答与中医证候知识库无关的问题（天气、编程、闲聊等） |
| 具体用药剂量 | 不主动给出剂量、方剂加减；知识库原文涉及也须附带免责声明 |
| 无限制自动执行 | 不调用外部 HTTP 工具、不写外部系统状态；POC 无工具层 |
| 自动学习 / RLHF | 不做在线学习或模型微调 |
| 跨租户数据访问 | 未来多租户须按 `org_id` 隔离索引；**【POC】单用户 N/A** |

### UI / 响应强制项

- [x] Gradio 页顶展示**非医疗建议**免责声明（【POC】）
- [x] 越界 / 高风险问题返回固定拒答文案，不调用 LLM（【POC】）

---

## 2. 数据边界

### 2.1 PII 处理规则

| 数据类型 | PII 级别 | 处理要求 |
|----------|----------|----------|
| 用户问答中的姓名 / 手机 / 身份证 | high | 不入检索索引；JSONL / 日志脱敏；不写入 RAGAS 导出 |
| 用户描述的症状文本 | medium | 可进审计 JSONL（截断 200 字）；评估集匿名化 |
| `data/*.txt` 证候知识 | none / low | 可入 `doc_emb/` 索引 |
| `DASHSCOPE_API_KEY` | secret | 仅环境变量；禁止日志、响应、错误堆栈泄露 |

### 2.2 版权与分发规则

| 数据来源 | 许可策略 | 分发方式 |
|----------|----------|----------|
| `data/demo.txt` 等证候条目 | 课程 / POC 内部使用 | 随 repo 分发；注明非医疗建议 |
| `中医临床诊疗智能助手.pdf` | 待确认 | 仅作索引原料；不对外提供原始 PDF 下载 API |

### 2.3 数据包规模边界

| 数据包 | 当前规模 | 用途 |
|--------|----------|------|
| POC Core | `demo.txt` ~7600 行；本地 `doc_emb/` | Gradio 问答 + RAGAS |
| 扩展包（规划） | 多 PDF/FAQ，chunk 上限待 Phase 2 定义 | 需更大磁盘 / 可选容器化时再定 |

---

## 3. 工具与 HITL 边界

### 3.1 当前工具清单（Week01 / POC）

| 工具 | 状态 | 说明 |
|------|------|------|
| RAG retrieve（LlamaIndex） | 内置 | `similarity_top_k=5`，非 HTTP 工具 |
| 外部 HTTP 工具 | **禁止** | POC 阶段不允许 |

### 3.2 规划工具（Phase 2+）

| 工具 | 角色 | HITL |
|------|------|------|
| `knowledge_search` | 只读检索 | 否 |
| `escalate_clinician` | 升级执业医师 | 是 |

### 3.3 必须触发 HITL / 拒答的场景

- 用户要求**确诊、开方、具体用药剂量**
- 问题含高风险意图词：如「帮我治」「吃什么药」「开方」「剂量多少」
- 检索 Top-1 相似度 **< 0.4**（向量分数，可配置）且问题涉及诊疗建议
- 主题明显越界（非中医证候 / 辨证领域）

触发后：返回固定免责声明 + `hitl_required: true`；**不**调用 LLM 生成诊疗建议。

### 3.4 幂等性要求（【目标态】API）

- `POST /api/v1/queries` 支持 `idempotency_key`
- 同一 key 在 24 小时内重复调用返回原结果，不重复计费 / 写审计

Gradio 本地 UI **不适用**幂等键。

---

## 4. 工程质量门禁

### 4.1 最低可接受（Week01 / POC）

- [ ] `python new_zhongyi_agent.py` 启动 Gradio，`http://127.0.0.1:7860` 可访问
- [x] `DASHSCOPE_API_KEY` 缺失时有明确报错（`require_api_key()`）
- [ ] `doc_emb/` 存在且 QueryEngine 可加载
- [x] [`项目说明.md`](项目说明.md) 可指导安装、`--eval`、`--eval-only`
- [x] Gradio 展示免责声明 Banner
- [x] 问答结果展示或附带 `sources[]` 证据引用
- [x] 每次问答追加 `backend/logs/runs.jsonl` 审计行
- [x] `backend/` FastAPI + `GET /api/v1/health` + `POST /api/v1/queries`
- [x] `scripts/security_check.sh` 可执行
- [x] 1 份 RAG 响应契约样板：[`contracts/rag_response.schema.json`](contracts/rag_response.schema.json)

### 4.2 Week08 前必须满足（RAG 上线门禁）

- [ ] 响应含 `sources[]`（`snippet` + `score` + `doc_ref`）与 `release_id`
- [ ] RAGAS `faithfulness` ≥ **0.75**（POC 基线，可调）
- [ ] RAGAS `context_recall` ≥ **0.70**
- [ ] 固定 `rag_eval_dataset.csv` 可 `python new_zhongyi_agent.py --eval-only` 复现
- [ ] 100% 对外请求携带 `request_id`（JSONL 或响应头 `X-Request-Id`）
- [ ] 至少 1 条 bad case 可通过 `--debug` / `ZHONGYI_DEBUG=1` LlamaIndex trace 定位

### 4.3 Week14 前必须满足（治理门禁）

- [ ] `release_manifest.json` 绑定 data / index / prompt / eval 四版本
- [ ] 可回滚到上一 `doc_emb/` 索引快照（≤30 分钟操作）
- [ ] CI 跑 RAGAS 阈值 + `security_check.sh`（pip-audit + bandit）

> **非 POC 范围**（见附录 B）：lakeFS、OpenLineage、OTel 全链路、9 服务 Docker Compose。

---

## 5. 已知风险与缓解策略

| 风险 | 影响 | 缓解 |
|------|------|------|
| 模型输出被误当作临床诊断 | 法律 / 伦理 | UI 免责声明 + 高风险意图拦截 + Evidence-first |
| 证候知识库覆盖不足 | 答非所问 | 低检索分时拒答；监控 RAGAS `context_recall` |
| 模型生成无证据支撑 | 幻觉 | Prompt 约束 + 展示 `sources[]` + 无上下文时拒答 |
| DashScope 限流 / 余额不足 | 服务不可用 | 友好错误文案；API 层 `LLM_UNAVAILABLE` |
| Gradio `--host 0.0.0.0` 暴露 | 未授权访问 | 默认 `127.0.0.1`；公网须反向代理 + 鉴权 |
| API Key 写入日志 | 泄露 | 禁止记录；bandit 扫描 |
| 版本漂移（data / index / prompt 不同步） | 评测不可重复 | `release_manifest.json` 强制绑定 |

---

## 6. 非功能性标准（分阶段）

| 维度 | POC 最低（当前可验收） | 目标态（API 上线后） |
|------|------------------------|----------------------|
| 可重复 | 同 `doc_emb` + 固定 CSV → `--eval-only` 可复现 | + `release_manifest.json` 四版本绑定 |
| 可观测 | `--debug` / `ZHONGYI_DEBUG` trace + `request_id` JSONL | + `GET /api/v1/stats` |
| 可回滚 | 手动恢复 `doc_emb/` 备份 | + manifest 一键切换索引 |
| 可审计 | `backend/logs/runs.jsonl` | + 工具调用 args_hash（Phase 2） |
| 可切换 | N/A（单 POC 数据包） | 多数据包共用同一 `/api/v1` 契约 |

---

## 附录 A：与项目说明 / 命令行映射

| boundary 能力 | 命令 / 入口 |
|---------------|-------------|
| Web 问答（Gradio） | `python new_zhongyi_agent.py` |
| HTTP API | `./scripts/start.sh` 或 `uvicorn backend.app:app` |
| 健康检查 | `GET /api/v1/health` |
| RAG 问答 API | `POST /api/v1/queries` |
| 调试 trace | `python new_zhongyi_agent.py --debug` |
| RAGAS 完整评估 | `python new_zhongyi_agent.py --eval` |
| RAGAS 复测 | `python new_zhongyi_agent.py --eval-only` |
| 局域网访问 | `python new_zhongyi_agent.py --host 0.0.0.0 --port 8080` |
| 索引构建 | `index_api.ipynb`（非本清单范围） |

---

## 附录 B：Enterprise 演进（非 POC，可选）

以下能力来自通用 RAG 平台模板，**当前 TCM POC 不实施**；若未来企业化可单独立项：

- Docker Compose 多服务（9 服务）
- lakeFS 数据分支 / merge
- OpenLineage 血缘（dataset → job → run）
- OTel 100% trace + span
- RBAC 工具矩阵（end_user / support_agent / admin）
- Student / Instructor 多数据包切换

---

## 代码缺口跟踪（实现状态）

| 要求 | 优先级 | 状态 |
|------|--------|------|
| Gradio 展示 citations | P0 | 已实现（`format_answer_with_citations`） |
| 主题 / 高风险拦截 | P0 | 已实现（`security.py`） |
| 免责声明 Banner | P0 | 已实现（Gradio 页顶） |
| JSONL 审计 | P1 | 已实现（`observability.py` → `logs/runs.jsonl`） |
| `release_id` | P1 | 已实现（索引目录 hash） |
| FastAPI `/api/v1` | P1 | 已实现（`backend/server.py`） |
| RAGAS CI 阈值 | P2 | 未实现 |
| PII 脱敏 | P2 | 已实现（`backend/security.redact_pii`） |
| pip-audit / bandit CI | P2 | `scripts/security_check.sh` 可执行，CI 待接 |
