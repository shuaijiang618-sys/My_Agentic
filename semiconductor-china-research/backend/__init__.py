"""semiconductor-china-research · supervisor-as-tool 多轮研究编排 —— 后端(模块化)。

模块职责:
  config.py   LLM 连接(DeepSeek 凭证 / 模型 / 路径 data/ logs/ prompts/ seed/)
  runtime.py  per-request 事件管道(contextvars + 时间戳 + SSE 序列化)
  tool.py     工具层:web_search(ddgs 联网检索,发实时事件)
  agent.py    智能体层:8 专家(规划) + supervisor(supervisor-as-tools)
  store.py    持久层:data/runs.db(对话历史 / 多轮记忆重建 / 删除)
  server.py   接口层:所有 /api/* 路由(APIRouter)
  app.py      主入口:组装应用(中间件 + 挂路由 + 前端) → uvicorn backend.app:app

数据 → backend/data/   日志 → backend/logs/
提示词 → backend/prompts/   种子 → backend/seed/
"""
