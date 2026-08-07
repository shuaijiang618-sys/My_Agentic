#!/usr/bin/env bash
# Block 9 · 离线验收（unittest，不调用 DeepSeek）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="${ROOT}/.venv/bin/python"
if [[ ! -x "$VENV" ]]; then
  echo "❌ 未找到 .venv —— 请先: python3.12 -m venv .venv && pip install -r requirements.txt"
  exit 1
fi

echo "=== Block 9 · 离线验收 ==="
"$VENV" -m unittest discover -s tests -p 'test_*.py' -v

echo ""
echo "=== 仓库合规 ==="
./scripts/check-repo.sh

echo ""
echo "✅ 离线验收通过"
echo "   在线 5 用例: ./scripts/start.sh && ./scripts/acceptance-live.sh"
