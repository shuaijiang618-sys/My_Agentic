# -*- coding: utf-8 -*-
"""环境变量与路径（对齐 tcm-diagnostics-platform SKILL §一 / reference.md）。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_EMB_DIR = ROOT / "doc_emb"
DATA_DIR = ROOT / "data"
LOGS_DIR = Path(__file__).resolve().parent / "logs"

VERSION = "0.1.0"
SERVICE_NAME = "tcm-diagnostics"
MODEL = "qwen-max"
EMBEDDING = "text-embedding-v1"
SIMILARITY_TOP_K = 5

HOST = os.getenv("TCM_HOST", "127.0.0.1")
PORT = int(os.getenv("TCM_PORT", "8090"))
ENABLE_OBSERVABILITY_LOG = os.getenv("TCM_ENABLE_OBSERVABILITY_LOG", "true").lower() not in (
    "0",
    "false",
    "no",
)
DISABLE_DOCS = os.getenv("TCM_DISABLE_DOCS", "false").lower() in ("1", "true", "yes")
LOG_JSON = os.getenv("TCM_LOG_JSON", "false").lower() in ("1", "true", "yes")
RATE_LIMIT_PER_MIN = int(os.getenv("TCM_RATE_LIMIT_PER_MIN", "60"))

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "TCM_CORS_ORIGINS",
        "http://127.0.0.1:7860,http://localhost:7860,http://127.0.0.1:8090,http://localhost:8090",
    ).split(",")
    if o.strip()
]
