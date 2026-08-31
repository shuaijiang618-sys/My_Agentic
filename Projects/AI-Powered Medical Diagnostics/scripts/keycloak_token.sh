#!/usr/bin/env bash
# 从 Keycloak 获取 access_token（Resource Owner Password，仅本地联调）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then set -a; source .env; set +a; fi

KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
REALM="${KEYCLOAK_REALM:-medical}"
CLIENT_ID="${KEYCLOAK_CLIENT_ID:-medical-api}"
USERNAME="${1:-doctor}"
PASSWORD="${2:-doctor123}"

TOKEN_URL="${KEYCLOAK_URL%/}/realms/${REALM}/protocol/openid-connect/token"

RESP=$(curl -sf -X POST "$TOKEN_URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=${CLIENT_ID}" \
  -d "username=${USERNAME}" \
  -d "password=${PASSWORD}" \
  -d "grant_type=password") || {
  echo "获取 Token 失败。Keycloak 是否已启动？ ./scripts/keycloak_up.sh" >&2
  exit 1
}

if command -v python3 >/dev/null 2>&1; then
  python3 -c "import json,sys; print(json.loads(sys.argv[1])['access_token'])" "$RESP"
else
  echo "$RESP" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p'
fi
