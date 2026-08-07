#!/usr/bin/env bash
# Block 8 · 部署冒烟：DeepSeek API + 本地 /api/health
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "❌ 缺少 .env —— 请先: cp .env.example .env 并填入 DEEPSEEK_API_KEY"
  exit 1
fi

# shellcheck disable=SC1091
set -a && source .env && set +a

: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY 未设置}"
MODEL="${MODEL:-deepseek-v4-pro}"
BASE="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
PORT="${PORT:-8093}"
HOST="${HOST:-127.0.0.1}"

# 兼容带/不带 /v1 的 base_url
API="${BASE%/}/chat/completions"

echo "=== 1/2 DeepSeek API ==="
HTTP=$(curl -sS -o /tmp/scr-smoke-ds.json -w "%{http_code}" \
  "$API" \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":16}")

if [[ "$HTTP" != "200" ]]; then
  echo "❌ DeepSeek 返回 HTTP $HTTP"
  head -c 500 /tmp/scr-smoke-ds.json; echo
  exit 1
fi
echo "✅ DeepSeek chat/completions HTTP 200 (model=$MODEL)"

echo "=== 2/2 本地 health ==="
HEALTH_URL="http://${HOST}:${PORT}/api/health"
HTTP=$(curl -sS -o /tmp/scr-smoke-health.json -w "%{http_code}" "$HEALTH_URL" || true)
if [[ "$HTTP" == "200" ]]; then
  echo "✅ $HEALTH_URL"
  python3 -c "import json; d=json.load(open('/tmp/scr-smoke-health.json')); assert d.get('provider')=='deepseek' and d.get('experts')==8, d; print('   provider=', d['provider'], 'model=', d['model'], 'experts=', d['experts'])"
else
  echo "⚠️  服务未启动 (HTTP ${HTTP:-000}) —— 先运行 scripts/start.sh"
  echo "   DeepSeek 链路已通过，本地 health 跳过"
fi

echo "=== smoke 完成 ==="
