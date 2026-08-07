# Block 4 · API 与 SSE 事件流

## 接口一览

| 方法 | 路径 | Block | 说明 |
|------|------|-------|------|
| GET | `/` | 6 | 前端 SPA |
| GET | `/api/health` | 4 | 健康检查 + 模型/专家/SSE 元数据 |
| GET | `/api/agents` | 1/3A | 总管 + 8 专家（含 search_strategy） |
| GET | `/api/search-strategies` | 3A | 检索策略摘要 |
| GET | `/api/knowledge` | 3B | 本地 KB 查询（segment / q） |
| GET | `/api/stock-snapshot` | 3C | 行情快照 `?symbols=002371,688012` |
| GET | `/api/run?query=&session=` | 4 | **SSE 主流程** |
| GET | `/api/conversations` | 5 | 历史会话列表 |
| GET | `/api/conversation/{session}` | 5 | 会话回放（含 events） |
| DELETE | `/api/conversation/{session}` | 5 | 删除会话 |

## SSE 协议

连接: `GET /api/run?query=...&session=s-xxx`

```
event: start
data: {"query":"...","workers":[...],"session":"...","t":0}

event: tool_call
data: {"name":"policy_expert","arguments":"...","t":120}

event: kb_hit
data: {"expert":"investment_expert","chars":420,"t":130}

event: stock_snapshot
data: {"expert":"investment_expert","symbols":["002371"],"count":1,"as_of":"2026-07-08 14:30","provider":"akshare","t":145}

event: search_start
data: {"expert":"policy_expert","query":"...","region":"cn-zh","timelimit":"y","t":150}

event: search
data: {"expert":"policy_expert","query":"...","n":4,"region":"cn-zh","items":[...],"t":890}

event: tool_done
data: {"name":"policy_expert","output":"...","t":12000}

event: final
data: {"brief":"...","t":45000}

event: error
data: {"message":"DeepSeek API 限流(429)...","t":1000}
```

## 生产者-消费者（server.py）

1. 初始化 `EVENT_Q` / `SEARCH_LOG` / `SEARCH_BUDGET` / `EXPERT_RESULTS`
2. `asyncio.create_task(producer())` 跑 supervisor
3. 消费者 loop `yield sse(...)` 实时推送
4. 结束后 `store.save_run`

## Block 5 多轮记忆

- `session` 相同 → `load_history` 带入最近 5 轮摘要
- 每轮摘要截断 400 字（`store.brief_summary`）
- 追问示例：「刚才提到的设备公司谁上市了？」

## Block 6 前端

- 8 节点星形动画 + 并行甘特图
- 示例问题 chips、历史下拉、步进/播放/放大
- Markdown 简报渲染 + 下载 .md
