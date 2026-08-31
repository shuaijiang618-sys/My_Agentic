#!/usr/bin/env bash
# 鉴权模块回归（无需 LLM / 无需启动 API）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
python -m py_compile core/auth.py api/main.py mcp/knowledge_base.py
python -m evaluation.auth_runner
