#!/usr/bin/env bash
# Block 3B · 初始化 industry_kb.db
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VENV="${ROOT}/.venv/bin/python"
if [[ ! -x "$VENV" ]]; then
  python3.12 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
  VENV="${ROOT}/.venv/bin/python"
fi
"$VENV" -m backend.seed.industry_kb
echo "验证:"
curl -sf "http://127.0.0.1:${PORT:-8093}/api/knowledge" 2>/dev/null | python3 -m json.tool || \
  "$VENV" -c "from backend.kb import kb_stats; import json; print(json.dumps(kb_stats(), ensure_ascii=False, indent=2))"
