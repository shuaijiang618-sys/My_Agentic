#!/usr/bin/env bash
# Block 8 · 仓库合规检查：确认无 OpenRouter / 旧模型 ID 残留
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAIL=0
TARGETS=(backend/*.py frontend/index.html .env.example)

scan() {
  local label="$1" pattern="$2"
  local hits
  hits=$(grep -iE "$pattern" "${TARGETS[@]}" 2>/dev/null || true)
  if [[ -n "$hits" ]]; then
    echo "❌ $label"
    echo "$hits"
    FAIL=1
  else
    echo "✅ $label"
  fi
}

echo "=== semiconductor-china-research · repo check ==="
scan "无 openrouter 业务代码" 'openrouter|OPENROUTER'
scan "无 deepseek/deepseek 前缀" 'deepseek/deepseek'

if grep -q 'DEEPSEEK_API_KEY' backend/config.py && grep -q 'DEEPSEEK_BASE_URL' backend/config.py; then
  echo "✅ config.py 使用 DEEPSEEK_* 单一真相源"
else
  echo "❌ config.py 未配置 DEEPSEEK_*"
  FAIL=1
fi

exit $FAIL
