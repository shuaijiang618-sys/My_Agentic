"""AI-Powered Medical Diagnostics 运行时配置。"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_NAME = "AI-Powered Medical Diagnostics"
PROJECT_SLUG = "ai-powered-medical-diagnostics"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
KNOWLEDGE_DIR = DATA_DIR / "medical_knowledge"
PROMPTS_DIR = Path(os.getenv("PROMPTS_DIR", str(ROOT / "prompts")))

ENABLE_OBSERVABILITY_LOG = os.getenv("ENABLE_OBSERVABILITY_LOG", "true").lower() not in {
    "0", "false", "no",
}
