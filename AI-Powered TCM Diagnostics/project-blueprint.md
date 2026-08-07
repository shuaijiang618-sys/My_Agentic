# AI-Powered TCM Diagnostics — 项目蓝图 v2.0

> 业务边界见 [`boundary-checklist.md`](boundary-checklist.md)；运行说明见 [`项目说明.md`](项目说明.md)。

---

## 1. 一句话定义

面向**中医证候 / 辨证论治**领域的 RAG 知识问答 POC：本地向量检索 + DashScope 生成，附证据引用，带 RAGAS 评估与边界门禁，**不提供正式临床诊断**。

---

## 2. 业务世界观

### 核心业务对象

| 对象 | 说明 | 存储 |
|------|------|------|
| 证候知识块 | 从 `data/*.txt` 分块后的检索单元 | `doc_emb/` |
| 用户问题 | Gradio / API 输入的问答 | `backend/logs/runs.jsonl`（审计） |
| RAG 响应 | answer + sources[] + metadata | 契约见 §6 |
| 评估集 | question / ground_truth / context | `rag_eval_dataset.csv` |
| Release | data + index + prompt + eval 版本绑定 | `release_manifest.json`（Week14） |

---

## 3. 系统结构（七层）

| 层 | POC 实现 | 目标态 |
|----|----------|--------|
| 1. 接入层 | Gradio Web UI（7860） | + FastAPI `/api/v1` |
| 2. 编排层 | 单轮 QueryEngine | 多轮 session（可选） |
| 3. 检索层 | LlamaIndex VectorStore Top-5 | + 多格式 ingest |
| 4. 生成层 | DashScope Qwen-Max + QA/Refine Prompt | 同左 |
| 5. 安全层 | `backend/security.py` 主题 / HITL 拦截 | + API 限流 |
| 6. 观测层 | `backend/observability.py` JSONL + `--debug` | + `GET /api/v1/stats` |
| 7. 评估层 | RAGAS `--eval` / `--eval-only` | CI 阈值门禁 |

---

## 4. 技术选型

| 类别 | 技术 |
|------|------|
| RAG | LlamaIndex |
| LLM / Embedding | DashScope Qwen-Max + text-embedding-v1 |
| Web UI | Gradio 4.x+ |
| 评估 | RAGAS + pandas |
| HTTP（目标态） | FastAPI + uvicorn |
| 密钥 | 环境变量 `DASHSCOPE_API_KEY` |

---

## 5. 数据模型概览

### Bronze（保真落盘）

- `data/*.txt`、未来 PDF 原文
- 评估 CSV、RAGAS 结果 CSV

### Silver（规范化）

- `doc_emb/` 向量索引与 docstore
- `backend/logs/runs.jsonl` 审计行（JSON）

### Gold（服务消费）

- RAG 响应 JSON（见 §6）
- Gradio 展示：answer + 引用片段

---

## 6. 核心接口契约

### RAG 响应结构

与 [`contracts/rag_response.schema.json`](contracts/rag_response.schema.json) 一致：

```json
{
  "answer": "……",
  "sources": [
    {
      "chunk_id": "optional-node-id",
      "snippet": "检索片段文本",
      "score": 0.87,
      "doc_ref": "data/demo.txt"
    }
  ],
  "metadata": {
    "model": "qwen-max",
    "duration_ms": 2340,
    "release_id": "doc_emb@v1",
    "request_id": "a1b2c3d4e5f6",
    "blocked": false,
    "hitl_required": false
  }
}
```

### 工具调用必须字段（Phase 2+）

审计 JSONL 或 API 扩展时，每次工具调用须含：

`tool_name`, `tool_call_id`, `arguments_hash`, `status`, `idempotency_key`（可选）

---

## 7. 逐周实现计划

| 周 | 目标 |
|----|------|
| Week01 | Gradio + RAG + 免责声明 + citations 展示 + JSONL 审计 + security 拦截 |
| Week08 | RAGAS 门禁（faithfulness ≥0.75, context_recall ≥0.70）+ request_id 全链路 |
| Week14 | release_manifest + 索引回滚 + security_check CI |

---

## 8. 实施原则

1. **Evidence-first**：无可靠检索时不生成诊疗建议。
2. **边界优先**：越界 / 高风险先拦截，再考虑调用 LLM。
3. **单代码路径**：POC 与 API 共用 `get_query_engine()` / `backend/rag.py` / `backend/security.py` / `backend/observability.py`。
4. **可复现评估**：固定 `rag_eval_dataset.csv` + `--eval-only`。
5. **密钥零入库**：仅环境变量。

---

## 9. Week01 交付物清单

- [x] `new_zhongyi_agent.py` — Gradio + RAG + RAGAS
- [x] `boundary-checklist.md` v2.0
- [x] `backend/` FastAPI — `app.py` / `server.py` / `rag.py` / `config.py`
- [x] `backend/security.py` — 主题 / HITL / PII 脱敏
- [x] `backend/observability.py` — request_id + `backend/logs/runs.jsonl`
- [x] `contracts/rag_response.schema.json`
- [ ] `release_manifest.json`（Week14）

交叉引用：工程质量门禁详见 [`boundary-checklist.md`](boundary-checklist.md) §4。
