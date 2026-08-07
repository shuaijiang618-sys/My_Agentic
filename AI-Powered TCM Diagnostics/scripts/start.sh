#!/usr/bin/env bash
# 启动 FastAPI（SKILL §四）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec python -m uvicorn backend.app:app \
  --host "${TCM_HOST:-127.0.0.1}" \
  --port "${TCM_PORT:-8090}"
