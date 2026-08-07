# Block 8 · 配置、部署与运维（DeepSeek 专版）

> **定稿约束**：全项目仅使用 DeepSeek 官方 API，统一模型 `deepseek-v4-pro`，**禁止** OpenRouter。

---

## 1. 配置单一真相源

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `DEEPSEEK_API_KEY` | ✅ | — | [platform.deepseek.com](https://platform.deepseek.com) 申请 |
| `MODEL` | — | `deepseek-v4-pro` | 总管 + 8 专家 + 综合器 |
| `DEEPSEEK_BASE_URL` | — | `https://api.deepseek.com` | OpenAI 兼容端点；也可写 `.../v1` |
| `HOST` | — | `127.0.0.1` | Uvicorn 绑定地址 |
| `PORT` | — | `8093` | 与 flagship `8088` 错开 |

读取逻辑见 `backend/config.py`：

- 缺失 `DEEPSEEK_API_KEY` → 启动时 `RuntimeError`（提示复制 `.env.example`）
- 路径常量：`DATA` / `LOGS` / `PROMPTS` / `RUNS_DB` 均在此定义

---

## 2. 安装

```bash
cd semiconductor-china-research
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

**依赖清单**（`requirements.txt`）：

| 包 | 版本 | 用途 |
|----|------|------|
| agent-framework-core | 1.8.0 | MAF 编排 |
| agent-framework-openai | 1.8.0 | OpenAI 兼容客户端 |
| ddgs | 9.14.4 | DuckDuckGo 联网检索 |
| fastapi | 0.136.3 | HTTP API |
| uvicorn[standard] | 0.49.0 | ASGI 服务 |
| python-dotenv | 1.2.2 | 读 `.env` |

> 若与课件环境冲突，可尝试 `pip install -r requirements.txt --no-deps` 后手动补装缺失包。

---

## 3. 启动方式

### 3.1 前台（开发）

```bash
source .venv/bin/activate
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8093 --reload
```

浏览器打开：http://127.0.0.1:8093

### 3.2 后台 + 日志（演示/运维）

```bash
chmod +x scripts/*.sh
./scripts/start.sh      # 日志 → backend/logs/server.log
./scripts/stop.sh       # 停止
```

或手动重定向（与 flagship 一致）：

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8093 \
  >> backend/logs/server.log 2>&1 &
```

---

## 4. 部署前冒烟

### 4.1 一键脚本

```bash
./scripts/smoke.sh
```

步骤：

1. `curl` DeepSeek `/chat/completions`（验证 Key + 模型）
2. `curl` 本地 `/api/health`（若服务已启动）

### 4.2 手动 DeepSeek 冒烟

```bash
source .env
curl "${DEEPSEEK_BASE_URL%/}/chat/completions" \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"ping"}],"max_tokens":16}'
```

期望：**HTTP 200**，响应含 `choices[0].message.content`。

### 4.3 本地 health

```bash
curl -s http://127.0.0.1:8093/api/health | python3 -m json.tool
```

期望字段：

```json
{
  "ok": true,
  "provider": "deepseek",
  "model": "deepseek-v4-pro",
  "experts": 8,
  "port": 8093
}
```

---

## 5. 仓库合规检查

确认无 OpenRouter / 旧模型 ID 残留：

```bash
./scripts/check-repo.sh
```

等价手动命令：

```bash
grep -ri 'openrouter\|OPENROUTER' --include='*.py' --include='*.md' .
grep -r 'deepseek/deepseek' --include='*.py' --include='*.md' .
```

允许在文档中**说明禁止 OpenRouter**（如 README 命名约定），但业务代码与 `.env.example` 不得引用。

---

## 6. 运维 checklist

| 步骤 | 命令 / 动作 |
|------|-------------|
| Key 有效 | `./scripts/smoke.sh` 第 1 步通过 |
| 账户余额 | platform.deepseek.com 控制台 |
| 服务存活 | `curl /api/health` → `"ok": true` |
| 端口占用 | `lsof -i :8093` 或改 `PORT` |
| 日志 | `tail -f backend/logs/server.log` |
| 数据备份 | 复制 `backend/data/runs.db` |
| 密钥安全 | `.env` 不入库；生产用密钥管理 |

---

## 7. 常见故障

| 现象 | 原因 | 处理 |
|------|------|------|
| 启动报 `缺少 DEEPSEEK_API_KEY` | 无 `.env` 或未填 Key | `cp .env.example .env` |
| smoke HTTP 401 | Key 无效或过期 | 重新生成 Key |
| smoke HTTP 402 / balance | 余额不足 | 充值 |
| SSE `error` 含 429 | 并行专家过多触发限流 | 稍后重试；问题拆小 |
| SSE `error` 含 401 | 运行时 Key 错误 | 检查 `.env` 与进程是否重启 |
| `/api/health` 连不上 | 服务未启动或端口错 | `./scripts/start.sh` 或核对 `PORT` |
| `ModuleNotFoundError: agent_framework` | 未装依赖 | `pip install -r requirements.txt` |
| base_url 404 | URL 写错 | 用 `https://api.deepseek.com` 或带 `/v1` |

友好错误映射见 `backend/server.py` → `_friendly_api_error()`。

---

## 8. DeepSeek 特有说明

- **单一客户端**：`agent.py` 只建一个 `OpenAIChatClient(model=MODEL, api_key=KEY, base_url=BASE_URL)`
- **模型 ID**：官方为 `deepseek-v4-pro`（**无** `deepseek/` 前缀）
- **端点**：MAF 会在 base_url 后拼 `/chat/completions`；`https://api.deepseek.com` 与 `https://api.deepseek.com/v1` 均可
- **并行成本**：一次研究可能触发 3~7 个专家 ×（检索 + 总结）+ supervisor 综合，注意 Token 与 QPS

---

## 9. 生产部署提示（可选）

本项目为 **本地/demo 编排**，生产化时可考虑：

- 反向代理（Nginx）+ HTTPS
- `HOST=0.0.0.0` + 防火墙限制来源
- 进程管理（systemd / supervisord）替代 `nohup`
- 日志轮转（logrotate）
- 限流与超时（网关层）

Phase 2/3（KB、行情）见 Block 10 路线图。
