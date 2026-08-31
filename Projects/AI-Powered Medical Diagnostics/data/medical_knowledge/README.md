# 医疗知识库批量导入目录

将公开医学科普、科室说明、检查项目解释、就诊流程放在对应子目录下，然后运行：

```bash
./scripts/import_knowledge.sh
# 或
python scripts/import_knowledge.py
```

## 目录约定

| 子目录 | doc_type | 说明 |
|--------|----------|------|
| `department/` | department | 科室导诊 |
| `lab_item/` | lab_item | 检查/化验指标 |
| `hospital_flow/` | hospital_flow | 挂号、分诊流程 |
| `popular_science/` | popular_science | 通用科普 |

## 文件格式

### Markdown（推荐）

```markdown
---
title: 文档标题
doc_type: lab_item
source: 来源说明
---

正文内容……
```

### 纯文本 `.txt`

文件名作为标题，所在文件夹决定 `doc_type`。

### 批量 JSON

- `batch.json` — 文档数组
- `batch.jsonl` — 每行一篇 JSON

```json
{"title":"标题","content":"正文","doc_type":"department","source":"来源"}
```

## API 导入（服务运行中）

```bash
# 未开鉴权
curl -X POST http://127.0.0.1:8010/knowledge/import \
  -H 'Content-Type: application/json' \
  -d '{"directory":"data/medical_knowledge"}'

# 已开 AUTH_ENABLED（admin Key 或 JWT）
./scripts/import_knowledge.sh --via-api http://127.0.0.1:8010 \
  --api-key "$MEDICAL_API_KEY" --tenant-id hospital_a
```

## 多租户：回填 shared + 导入（Keycloak 联调）

启用 `AUTH_ENABLED` 后，旧 Chroma 片段若无 `tenant_id` 会对 tenant 过滤不可见。运行：

```bash
# 本地 Chroma：回填 11 条 shared + 导入本目录（含 lab_item/ALT.md）到 hospital_a
./scripts/backfill_kb_tenant_shared.sh --tenant hospital_a

# 或通过 API（服务运行中，需 kbadmin JWT）
TOKEN=$(./scripts/keycloak_token.sh kbadmin kbadmin123)
./scripts/backfill_kb_tenant_shared.sh --skip-backfill \
  --via-api http://127.0.0.1:8010 --api-key "$TOKEN" --tenant hospital_a
```

完成后 **重启 `./scripts/start.sh`**（清除 RAG 工具缓存），再用 doctor Token 问「ALT 52 偏高是什么意思？」。
