# semiconductor-china-research · 中国半导体产业多轮研究编排

基于 **supervisor-as-tools** 模式的多智能体研究系统：一个 `research_supervisor` 把 **8 位半导体领域专家**当工具并行调用，每位专家先联网检索再总结，最后 supervisor 综合成带「参考来源」的研究简报。

- **框架**: Microsoft Agent Framework 1.8 (`agent-framework-core` / `-openai`)
- **LLM 客户端**: `OpenAIChatCompletionClient`（走 `/chat/completions`；DeepSeek **不支持** MAF 默认的 Responses API）
- **模型**: DeepSeek 官方 **`deepseek-v4-pro`**（总管 + 8 专家 + 综合器，单一模型）
- **API**: [DeepSeek 官方](https://platform.deepseek.com) · `https://api.deepseek.com`
- **特性**: 实时 SSE 动画 / 真并行 fan-out / 联网检索 (ddgs) / 多轮记忆 / 历史复现 / 事实校验与合规 / Markdown·PDF 导出

> **进度**: Block 0–10 ✅ · Phase 1/2/3 已交付 · 在线 5 用例验收 ✅ · [质量文档](docs/quality.md)

## 8 专家体系

详见 [docs/experts.md](docs/experts.md)

| tool | 领域 |
|------|------|
| `policy_expert` | 政策与监管 |
| `manufacturing_expert` | 制造与产能 |
| `design_ip_expert` | 设计 / IP / EDA |
| `equipment_materials_expert` | 设备与材料 |
| `competitor_expert` | 竞争格局 |
| `tech_roadmap_expert` | 技术路线 |
| `risk_supply_expert` | 供应链与地缘 |
| `investment_expert` | 投资与产业政策（大基金 / IPO / 估值） |

## 目录结构

```
semiconductor-china-research/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── scripts/                 # Block 8 · 启动 / 冒烟 / 合规检查
│   ├── start.sh
│   ├── stop.sh
│   ├── smoke.sh
│   ├── check-repo.sh
│   ├── acceptance.sh          # Block 9 · 离线验收（45 tests）
│   ├── acceptance-live.sh     # Block 9 · 在线 5 用例（兼容 macOS bash 3.2）
│   └── seed-kb.sh             # Block 3B · 初始化知识库
├── .github/workflows/
│   └── acceptance.yml         # CI · 离线 acceptance
├── docs/                    # 设计文档（Block 0–10）
│   ├── roadmap.md           # Block 10 · Phase 1/2/3 路线图
│   ├── deployment.md        # Block 8 · 部署运维
│   ├── acceptance.md        # Block 9 · 测试验收
│   ├── quality.md           # Phase 3 · 质量 / 合规 / 导出
│   ├── knowledge.md         # Block 3B · 知识库
│   ├── stock.md             # Block 3C · 行情
│   └── …                    # experts / api / search / prompts / orchestration
├── frontend/
│   └── index.html           # 前端单页（Block 6 改为 8 节点星形）
└── backend/
    ├── app.py               # 主入口
    ├── server.py            # /api/* 路由
    ├── agent.py             # 专家 + supervisor（Block 1/2/7；OpenAIChatCompletionClient）
    ├── tool.py              # web_search + KB 注入（Block 3A/3B）
    ├── kb.py                # industry_kb 查询（Block 3B）
    ├── stock.py             # 行情快照 akshare（Block 3C）
    ├── quality.py           # 事实校验 + 合规（Phase 3）
    ├── llm_retry.py         # 429/503 指数退避（Phase 3）
    ├── export.py            # Markdown / PDF 导出（Phase 3）
    ├── observability.py     # request_id + JSONL 日志（Phase 3）
    ├── store.py             # runs.db 多轮记忆（Block 5）
    ├── runtime.py           # SSE 事件管道
    ├── config.py            # DeepSeek 配置（Block 8）
    ├── prompts/             # 提示词外置（可选，Block 7）
    ├── seed/
    │   └── industry_kb.py   # KB 种子与初始化（Block 3B）
    ├── data/
    │   ├── runs.db
    │   └── industry_kb.db   # Block 3B · 30 只标的 + 大基金/产线/政策
    └── logs/
```

## 命名约定

| 类型 | 规范 |
|------|------|
| 专家 tool 名 | `{domain}_expert`，如 `investment_expert` |
| Agent 名 | `{domain}_analyst` |
| 环境变量 | `DEEPSEEK_*`、`MODEL`（禁止 `OPENROUTER_*`） |
| 模型 ID | `deepseek-v4-pro`（无 provider 前缀） |
| MAF 客户端 | `OpenAIChatCompletionClient`（DeepSeek 专用；勿用 `OpenAIChatClient`） |

## 安装 & 启动

详见 [docs/deployment.md](docs/deployment.md)

```bash
cd semiconductor-china-research
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # 填入真实 DEEPSEEK_API_KEY（占位符会导致在线 401/404）

# 开发：前台 + 热重载
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8093 --reload

# 运维：后台 + 日志
chmod +x scripts/*.sh
./scripts/smoke.sh     # 部署前冒烟（DeepSeek chat/completions + /api/health）
./scripts/start.sh     # 日志 → backend/logs/server.log
# 修改 .env 后须 ./scripts/stop.sh && ./scripts/start.sh 重启，否则仍用旧 Key

# 浏览器打开 http://127.0.0.1:8093
```

### 环境变量（`.env`）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | 必填 · DeepSeek 官方 Key |
| `MODEL` | 默认 `deepseek-v4-pro` |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com`（MAF 拼 `/chat/completions`） |
| `HOST` / `PORT` | 默认 `127.0.0.1` / `8093` |
| `ENABLE_INDUSTRY_KB` | 默认 `true` · Block 3B 本地知识库 |
| `ENABLE_STOCK_SNAPSHOT` | 默认 `true` · Block 3C akshare 行情 |
| `ENABLE_FACT_CHECK` | 默认 `true` · Phase 3 启发式事实校验 |
| `ENABLE_COMPLIANCE_FILTER` | 默认 `true` · 投资免责 + 禁止买卖建议 |
| `ENABLE_COMPLIANCE_RESCAN` | 默认 `true` · Phase 3 正则二次合规 |
| `ENABLE_PDF_EXPORT` | 默认 `true` · 简报 PDF 导出（reportlab） |
| `ENABLE_OBSERVABILITY_LOG` | 默认 `true` · `backend/logs/runs.jsonl` |
| `LLM_RETRY_MAX` / `LLM_RETRY_BASE_SEC` | 默认 `3` / `1.0` · DeepSeek 429 退避 |

## 分块路线图（Block 0–10）

| Block | 内容 | 状态 |
|-------|------|------|
| 0 | 项目基座与约定 | ✅ |
| 1 | 8 专家体系 | ✅ |
| 2 | Supervisor + Wrapper 编排 | ✅ |
| 3A | ddgs 检索策略细化 | ✅ |
| 3B | 本地知识库 industry_kb.db | ✅ |
| 3C | 行情 stock_snapshot (akshare) | ✅ |
| 4 | API + SSE | ✅ |
| 5 | runs.db 多轮记忆 | ✅ |
| 6 | 8 节点星形前端 | ✅ |
| 7 | 提示词与输出规范 | ✅ |
| 8 | DeepSeek 部署与运维 | ✅ |
| 9 | 测试与验收 | ✅ |
| 10 | Phase 1/2/3 路线图 | ✅ |

## Phase 路线图（Block 10）

详见 [docs/roadmap.md](docs/roadmap.md)

| 阶段 | 目标 | 状态 |
|------|------|------|
| **Phase 1** | 8 专家 + DeepSeek + SSE MVP | ✅ |
| **Phase 2** | KB + akshare 行情 + 验收 | ✅ |
| **Phase 3** | 事实校验 / 合规 / PDF / 429 退避 / 观测 / CI | ✅ 在线 5 用例已通过 |

## 部署与运维（Block 8）

详见 [docs/deployment.md](docs/deployment.md)

- 配置单一真相源：`backend/config.py` + `.env`
- 脚本：`scripts/smoke.sh` · `scripts/start.sh` · `scripts/check-repo.sh`
- 日志：`backend/logs/server.log`
- 验收：`curl /api/health` → `provider=deepseek`, `experts=8`

## 测试与验收（Block 9）

详见 [docs/acceptance.md](docs/acceptance.md)

```bash
./scripts/acceptance.sh              # 离线 unittest（45 tests，无需 DeepSeek 调用）
./scripts/smoke.sh                   # DeepSeek Key + /api/health
./scripts/start.sh
./scripts/acceptance-live.sh         # 在线 5 用例 SSE 结构验收（需有效 Key + 运行中服务）
./scripts/acceptance-live.sh --case 3 --timeout 600
```

| 步骤 | 说明 |
|------|------|
| 离线 | `./scripts/acceptance.sh` → 45/45 通过 |
| 冒烟 | `./scripts/smoke.sh` → DeepSeek `chat/completions` HTTP 200 |
| 在线 | 全套 5 用例约 **30–40 分钟**（每轮多专家检索 + LLM）；日志 `backend/logs/acceptance-live.log` |

**5 功能用例**（session `accept-u1`～`accept-u5`）：

| # | 输入 | 必检项 |
|---|------|--------|
| 1 | 中国半导体发展现状 | `final`、参考来源、多专家派发 |
| 2 | 大基金三期投向 | `investment_expert` + `policy_expert`、免责 |
| 3 | 北方华创估值贵不贵 | `investment_expert`、**不构成投资建议** |
| 4 | EDA 国产化 | `design_ip_expert` + `policy_expert` |
| 5 | 设备国产化 → 追问「刚才设备公司谁上市了」 | 同 session 多轮、`investment_expert` + `competitor_expert` |

**常见问题**

- `401` / Key 无效 → 检查 `.env` 中 `DEEPSEEK_API_KEY`，并 **重启服务**
- `404` on `/api/run` → 确认 `agent.py` 使用 `OpenAIChatCompletionClient`（非 `OpenAIChatClient`）
- `acceptance-live.sh: declare -A invalid` → 已修复，需 bash 3.2+（macOS 自带即可）

## 提示词（Block 7）

详见 [docs/prompts.md](docs/prompts.md) · API: `GET /api/prompts` · `GET /api/prompts/{name}`

## API 与 SSE（Block 4/5/6）

详见 [docs/api.md](docs/api.md)

- SSE: `GET /api/run?query=&session=`
- 多轮记忆: 同 session 追问，最近 5 轮摘要
- 导出: `GET /api/export?session=&format=md|pdf`
- 观测: `GET /api/stats`（DB 汇总 + JSONL 最近运行）
- SSE 事件: `start` · `tool_call` · `kb_hit` · `stock_snapshot` · `search_*` · `fact_check` · `compliance` · `compliance_rescan` · `final` · `error`
- 前端: 8 节点星形 + 甘特图 + 示例问题 + 历史回放 + **⬇ MD / ⬇ PDF** 下载

## 检索策略（Block 3A）

详见 [docs/search.md](docs/search.md) · API: `GET /api/search-strategies`

## 本地知识库（Block 3B）

详见 [docs/knowledge.md](docs/knowledge.md) · API: `GET /api/knowledge`

```bash
./scripts/seed-kb.sh                   # 初始化 30 只标的 + 大基金/产线/政策种子
curl -s 'http://127.0.0.1:8093/api/knowledge?segment=equipment'
curl -s 'http://127.0.0.1:8093/api/knowledge?q=002371'
```

- 检索前注入 KB 前缀（SSE `kb_hit`），仍走 ddgs 补充时效
- 开关：`.env` → `ENABLE_INDUSTRY_KB=true`

## 行情快照（Block 3C）

详见 [docs/stock.md](docs/stock.md) · API: `GET /api/stock-snapshot`

```bash
pip install akshare   # 或 pip install -r requirements.txt
curl -s 'http://127.0.0.1:8093/api/stock-snapshot?symbols=002371,688012'
```

- `investment_expert` 问估值/股价时：KB → **akshare 快照** → ddgs
- SSE 事件：`stock_snapshot`（含 `as_of`）
- 开关：`.env` → `ENABLE_STOCK_SNAPSHOT=true`

## 质量与合规（Phase 3）

详见 [docs/quality.md](docs/quality.md)

- 简报后处理：合规过滤 → 二次扫描 → 事实校验（SSE `fact_check` / `compliance_rescan`）
- LLM 429/503：`llm_retry.py` 指数退避
- 导出：`/api/export?format=md|pdf`；前端简报区 **⬇ MD / ⬇ PDF**
- 观测：每轮 `request_id` → `runs.db` + `backend/logs/runs.jsonl`；`GET /api/stats`

## 参考

- DeepSeek API: https://api-docs.deepseek.com/
