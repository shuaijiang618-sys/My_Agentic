# CLAUDE.md — AI-Powered TCM Diagnostics

本文件为 AI 编码助手提供项目上下文。详细说明见 [`项目说明.md`](项目说明.md)；业务边界见 [`boundary-checklist.md`](boundary-checklist.md)；架构与契约见 [`project-blueprint.md`](project-blueprint.md)；平台工程规范见 [`.cursor/skills/tcm-diagnostics-platform/SKILL.md`](.cursor/skills/tcm-diagnostics-platform/SKILL.md)。

---

## 项目说明

这是一个面向**中医证候 / 辨证论治**领域的 **RAG（检索增强生成）** 智能问答系统，帮助用户查询证候定义、临床表现、辨证要点等知识。

**核心流程**：用户提问 → 从本地向量索引 `doc_emb/` 检索 Top-5 相关片段 → DashScope Qwen-Max 基于上下文生成回答 → 返回答案并附**检索证据引用**（`sources[]`）。

**双入口**：

| 入口 | 端口 | 用途 |
|------|------|------|
| Gradio Web UI | 7860 | 本地聊天式交互（`python new_zhongyi_agent.py`） |
| FastAPI HTTP API | 8090 | REST 接口（`./scripts/start.sh`） |

**重要定位**：本系统仅供**知识辅助学习**，**不能替代执业医师**的诊断、处方或治疗决策。页顶有免责声明；高风险医疗意图（开方、剂量、确诊）会被规则拦截。

**主程序**：[`new_zhongyi_agent.py`](new_zhongyi_agent.py)（推荐）。旧版 [`zhongyi_agent.py`](zhongyi_agent.py) 勿再扩展。

**关键目录**：

```
new_zhongyi_agent.py    # RAG 核心 + Gradio + RAGAS CLI
backend/
  rag.py                # 统一 RAG 网关（安全 + 证据 + 审计）
  security.py           # 主题边界 / HITL / PII 脱敏
  observability.py      # request_id + backend/logs/runs.jsonl
  server.py             # /api/v1/* 路由
data/demo.txt           # 证候知识原文
doc_emb/                # 向量索引（运行前必须存在，由 index_api.ipynb 构建）
contracts/rag_response.schema.json
```

修改 RAG 逻辑时：**Gradio 与 API 必须共用** `backend/rag.py`，不得在路由里直接写 LlamaIndex 调用。

---

## 技术栈

| 类别 | 技术 | 说明 |
|------|------|------|
| RAG 框架 | LlamaIndex | VectorStoreIndex、QueryEngine、`similarity_top_k=5` |
| 大模型 | DashScope **Qwen-Max** | 问答生成、评估 QA 生成、RAGAS 判分 |
| 向量模型 | DashScope **text-embedding-v1** | 文档与问题嵌入 |
| Web UI | Gradio 4.x+ | 默认 `127.0.0.1:7860` |
| HTTP API | FastAPI + uvicorn | 前缀 `/api/v1`，默认 `8090` |
| 评估 | RAGAS + pandas + datasets | `--eval` / `--eval-only` |
| LLM 适配 | langchain-core | RAGAS 所需接口 |
| 密钥 | 环境变量 `DASHSCOPE_API_KEY` | 禁止硬编码、禁止写入日志 |

**Python**：3.10+（推荐 3.11）

**索引构建**（离线，非运行时）：[`index_api.ipynb`](index_api.ipynb) — 将 `data/*.txt` 向量化并 persist 到 `doc_emb/`。

---

## 重要约束

### 业务边界（必须遵守）

**系统做**：

- 基于 `doc_emb/` 回答中医证候 / 辨证相关问题，严格依据检索上下文（Evidence-first）
- 回答附 `sources[]`（snippet、score、doc_ref）
- 越界 / 高风险问题规则拦截 + 审计 JSONL

**系统不做**：

- 正式临床诊断、个体化开方、用药剂量建议
- 与证候知识库无关的开放式聊天（编程、天气等）
- 外部 HTTP 工具调用、在线微调 / RLHF
- POC 阶段跨租户 / 多 org 数据访问

完整清单见 [`boundary-checklist.md`](boundary-checklist.md) §1–§3。

### 工程约束

1. **单代码路径**：POC 与 API 共用 `get_query_engine()`、`backend/rag.py`、`backend/security.py`、`backend/observability.py`。
2. **密钥零入库**：`DASHSCOPE_API_KEY` 仅来自环境变量或 `.env`（`.env` 不入库）。
3. **API 契约**：成功响应 `ApiResponse`（code/message/data/timestamp/request_id）；失败 `ErrorBody`（errorCode/message）。RAG 响应结构见 [`contracts/rag_response.schema.json`](contracts/rag_response.schema.json) 与 SKILL §5。
4. **审计**：每次问答写入 `backend/logs/runs.jsonl`（含 request_id、blocked、hitl_required、release_id）；日志不得含 API Key 或完整 PII。
5. **安全门禁**：问题长度 1–2000 字；`top_k` 1–20；拦截逻辑在 `backend/security.py`，新增 errorCode 须在 SKILL 登记。
6. **默认网络**：监听 `127.0.0.1`；公网暴露须反向代理 + 鉴权。
7. **旧版勿动**：优先改 `new_zhongyi_agent.py` 与 `backend/`，不扩展 `zhongyi_agent.py`。

### HITL / 拒答触发条件

- 含「开方」「剂量」「帮我治」「吃什么药」「确诊」等高风险意图
- 主题明显越界（非中医证候领域）
- 检索 Top-1 相似度 < 0.4 且涉及诊疗建议（阈值见 `backend/security.py`）

触发后返回固定免责声明，`hitl_required: true`，**不调用 LLM**。

### 质量门禁（参考）

| 阶段 | 关键指标 |
|------|----------|
| Week08 | RAGAS faithfulness ≥ 0.75，context_recall ≥ 0.70；固定 CSV `--eval-only` 可复现 |
| Week14 | `release_manifest.json`；索引回滚；`scripts/security_check.sh` 进 CI |

---

## 构建和测试

### 环境准备

```bash
cd "AI-Powered TCM Diagnostics"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DASHSCOPE_API_KEY='你的密钥'
```

**前置**：`doc_emb/` 必须存在。若缺失，先运行 `index_api.ipynb` 构建索引。

### 启动服务

```bash
# Gradio 问答（默认）
python new_zhongyi_agent.py
# → http://127.0.0.1:7860

# FastAPI
./scripts/start.sh
# 或: python -m uvicorn backend.app:app --host 127.0.0.1 --port 8090
# → GET  /api/v1/health
# → POST /api/v1/queries  {"question":"血热挟湿证的临床表现有哪些？"}
# → http://127.0.0.1:8090/docs
```

### 命令行参数（`new_zhongyi_agent.py`）

| 参数 | 说明 |
|------|------|
| （无参数） | 启动 Gradio Web UI |
| `--eval` | 完整 RAGAS 评估（生成 QA + 评估） |
| `--eval-only` | 使用已有 `rag_eval_dataset.csv` 复测 |
| `--eval-only --dataset PATH` | 指定测试集 CSV |
| `--num-questions N` | `--eval` 时生成 QA 对数量（默认 10） |
| `--debug` | 开启 LlamaIndex trace |
| `--host` / `--port` | Gradio 监听地址（默认 127.0.0.1:7860） |

### RAGAS 评估

```bash
# 首次：生成测试集并评估
python new_zhongyi_agent.py --eval --num-questions 10

# 调参后复测（省 API 费用）
python new_zhongyi_agent.py --eval-only

# 调试单条链路
python new_zhongyi_agent.py --eval-only --debug
# 或: export ZHONGYI_DEBUG=1
```

**输出文件**：

- `rag_eval_dataset.csv` — 测试集
- `ragas_evaluation_results.csv` — 逐题分数与明细

**五项指标**（0–1，越高越好）：faithfulness、answer_relevancy、context_precision、context_recall、answer_correctness。

### 安全扫描

```bash
pip install pip-audit bandit   # 首次需安装
./scripts/security_check.sh
```

### 快速验证清单

```bash
# 语法与模块
python -m py_compile new_zhongyi_agent.py backend/*.py

# 安全规则
python -c "from backend.security import check_question; assert not check_question('写python代码').allowed"

# FastAPI 路由
python -c "from backend.app import app; print([r.path for r in app.routes if hasattr(r,'path')])"

# 健康检查（需 API Key + doc_emb）
curl -s http://127.0.0.1:8090/api/v1/health | python -m json.tool
```

### 常见问题

| 现象 | 处理 |
|------|------|
| 未设置 `DASHSCOPE_API_KEY` | `export DASHSCOPE_API_KEY='...'` |
| 索引目录不存在 | 运行 `index_api.ipynb` 生成 `doc_emb/` |
| Gradio 代理报错 | 项目已设 `NO_PROXY`；或 `unset HTTP_PROXY HTTPS_PROXY` |
| RAGAS 很慢 / 费 API | 先用 `--num-questions 5`；调参阶段用 `--eval-only` |

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [`项目说明.md`](项目说明.md) | 安装、架构、RAGAS 详解、FAQ |
| [`boundary-checklist.md`](boundary-checklist.md) | 业务边界、PII、HITL、质量门禁 |
| [`project-blueprint.md`](project-blueprint.md) | 七层架构、数据模型、接口契约、周计划 |
| [`.cursor/skills/tcm-diagnostics-platform/SKILL.md`](.cursor/skills/tcm-diagnostics-platform/SKILL.md) | 日志、监控、HTTP/API、安全检查、验收清单 |
| [`contracts/rag_response.schema.json`](contracts/rag_response.schema.json) | RAG 响应 JSON Schema |

---

## 实施原则（改代码前必读）

1. **Evidence-first** — 无可靠检索不生成诊疗建议。
2. **边界优先** — 先过 `backend/security.py`，再调 LLM。
3. **最小 diff** — 复用现有模块，不另起 RAG / 安全 / 审计实现。
4. **可复现** — 评估变更后用固定 `rag_eval_dataset.csv` + `--eval-only` 对比。
