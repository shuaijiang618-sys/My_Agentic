#!/usr/bin/env bash
# Keycloak → 医疗 API 端到端联调（需 Keycloak + API 均已启动且 .env 已配置 AUTH_*）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then set -a; source .env; set +a; fi

API="${MEDICAL_API_URL:-http://127.0.0.1:${PORT:-8010}}"
USER="${1:-doctor}"
PASS="${2:-doctor123}"

echo "▶ 1/3 Keycloak Token (${USER})..."
TOKEN=$("$ROOT/scripts/keycloak_token.sh" "$USER" "$PASS")
echo "   token 前缀: ${TOKEN:0:24}..."

echo "▶ 2/3 GET ${API}/health (公开)..."
curl -sf "${API}/health" | head -c 200
echo ""

echo "▶ 3/3 POST ${API}/chat (Bearer JWT)..."
HTTP=$(curl -s -o /tmp/medical_chat_resp.json -w "%{http_code}" \
  -X POST "${API}/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message":"你好"}')

if [[ "$HTTP" != "200" ]]; then
  echo "HTTP $HTTP — 响应:" >&2
  cat /tmp/medical_chat_resp.json >&2
  echo "" >&2
  echo "检查 .env 是否已 merge docker/keycloak/.env.example 中的 AUTH_JWT_*" >&2
  exit 1
fi

python3 -m json.tool </tmp/medical_chat_resp.json | head -20
echo ""
echo "✓ Keycloak 联调通过 (user=${USER}, HTTP ${HTTP})"
