# 外置 Prompt 目录

## 工程化契约（v2.0.0）

| 路径 | 说明 |
|------|------|
| `manifest.json` | Prompt 包名称、版本、变更记录 |
| `CHANGELOG.md` | 版本变更与最小回归清单 |
| `shared/system_rules.txt` | 共享角色、目标、边界、输出风格 |
| `shared/few_shot.txt` | 正常 / 无证据 / 边界 Few-shot |
| `shared/workflow.txt` | 分析 → 执行 → 检查 三段式 |
| `shared/injection_guard.txt` | 间接注入防护声明 |
| `agents/triage_role.txt` 等 | 各 Agent 可观察职责 |
| `agents.yaml` | `engineering_pack: true` 启用工程化组装 |
| `rag/context.yaml` | RAG 不可信数据区模板 |

启用后 `core/prompt_registry.agent_system()` 按固定规则组装 system prompt；`format_rag_context()` 包裹不可信数据区。

## 其他资产

| 路径 | 说明 |
|------|------|
| `output_schemas.yaml` | triage/report 结构化 JSON 字段说明 |
| `templates/*.md` | 结构化 JSON 渲染为用户可见 Markdown |
| `security/*.md` | 拒答/免责/紧急模板（支持 `{{disclaimer}}`） |
| `security/sensitive_words.yaml` | 泛化敏感词正则（输入/输出） |

**不外置**：`core/safety_judge.py`（Judge 规则 + LLM 审核仍硬编码）。

## 热加载

```bash
curl -X POST http://127.0.0.1:8010/prompts/reload
curl http://127.0.0.1:8010/prompts
```

响应含 `prompt_id`、`prompt_release_tag`、`engineering_pack`。

## Skills A/B

在 `skills/*/SKILL.md` frontmatter 中设置：

```yaml
version: "1.0"
experiment: triage_reply
variant: A
weight: 70
```

同一 `experiment` 下按 `user_id` 稳定分桶选 variant。

## 结构化输出（triage / report / general）

1. Agent 按 `output_schemas.yaml` 返回 **JSON**
2. `core/structured_response.py` 校验必填字段并渲染 `templates/*.md`
3. 解析/缺字段失败 → 同请求内 **自动重试 1 次**（`agent_{type}_retry` Token stage）
4. 重试仍失败 → 回退 LLM 原文

关闭某 Agent 结构化：在 `output_schemas.yaml` 设 `enabled: false`。
