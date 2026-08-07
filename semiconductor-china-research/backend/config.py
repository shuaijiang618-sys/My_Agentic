"""配置(单一真相源):路径 + LLM 连接参数。

全部来自项目根 .env(python-dotenv 读),不依赖系统环境变量、不读外部 creds。
本文件只提供"值"(MODEL / BASE_URL / KEY / 路径),不实例化任何客户端 ——
MAF 客户端由 agent 层按这些值来建(见 agent.py)。

- 密钥绝不硬编码;.env 不入库(见 .gitignore),仓库里只放 .env.example 模板
- 存储统一 backend/data/,日志统一 backend/logs/
- LLM: DeepSeek 官方 API · deepseek-v4-pro(全项目统一)
"""
import pathlib
from dotenv import load_dotenv, dotenv_values

BACKEND = pathlib.Path(__file__).resolve().parent   # backend/
ROOT = BACKEND.parent                                # semiconductor-china-research/
FRONTEND = ROOT / "frontend"
DATA = BACKEND / "data"                              # 存储统一放这
LOGS = BACKEND / "logs"                              # 日志统一放这
PROMPTS = BACKEND / "prompts"
SEED = BACKEND / "seed"
DATA.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)
PROMPTS.mkdir(exist_ok=True)
SEED.mkdir(exist_ok=True)
RUNS_DB = str(DATA / "runs.db")
INDUSTRY_KB_DB = str(DATA / "industry_kb.db")

# 读项目根 .env(override=True:.env 为准);dotenv_values 直接取值,不依赖系统环境变量
load_dotenv(ROOT / ".env", override=True)
_cfg = dotenv_values(ROOT / ".env")

MODEL = _cfg.get("MODEL") or "deepseek-v4-pro"
BASE_URL = (_cfg.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
KEY = _cfg.get("DEEPSEEK_API_KEY") or ""
HOST = _cfg.get("HOST") or "127.0.0.1"
PORT = int(_cfg.get("PORT") or "8093")

# Block 3B · 本地产业知识库(默认开启;设 false 可仅走 ddgs)
ENABLE_INDUSTRY_KB = (_cfg.get("ENABLE_INDUSTRY_KB") or "true").lower() in ("1", "true", "yes", "on")

# Block 3C · 行情快照 akshare(默认开启;需 pip install akshare)
ENABLE_STOCK_SNAPSHOT = (_cfg.get("ENABLE_STOCK_SNAPSHOT") or "true").lower() in ("1", "true", "yes", "on")

# Phase 3 · 质量与退避
ENABLE_FACT_CHECK = (_cfg.get("ENABLE_FACT_CHECK") or "true").lower() in ("1", "true", "yes", "on")
ENABLE_COMPLIANCE_FILTER = (_cfg.get("ENABLE_COMPLIANCE_FILTER") or "true").lower() in ("1", "true", "yes", "on")
ENABLE_COMPLIANCE_RESCAN = (_cfg.get("ENABLE_COMPLIANCE_RESCAN") or "true").lower() in ("1", "true", "yes", "on")
ENABLE_PDF_EXPORT = (_cfg.get("ENABLE_PDF_EXPORT") or "true").lower() in ("1", "true", "yes", "on")
ENABLE_OBSERVABILITY_LOG = (_cfg.get("ENABLE_OBSERVABILITY_LOG") or "true").lower() in ("1", "true", "yes", "on")
LLM_RETRY_MAX = int(_cfg.get("LLM_RETRY_MAX") or "3")
LLM_RETRY_BASE_SEC = float(_cfg.get("LLM_RETRY_BASE_SEC") or "1.0")

if not KEY:
    raise RuntimeError(
        "缺少 DEEPSEEK_API_KEY —— 请先 `cp .env.example .env` 并在 .env 里填入你的 key"
        "（申请: https://platform.deepseek.com）"
    )
