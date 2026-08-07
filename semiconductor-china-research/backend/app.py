"""主入口:组装 FastAPI 应用(中间件 + 挂接口路由 + 前端页面)。

启动:
    cd semiconductor-china-research
    python -m uvicorn backend.app:app --host 127.0.0.1 --port 8093
    # 或: ./scripts/start.sh（见 docs/deployment.md）
"""
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import FRONTEND
from .server import router

app = FastAPI(title="semiconductor-china-research · 中国半导体产业研究编排")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)            # /api/* 接口在 server.py


@app.get("/")
async def index():                    # 前端单页
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
