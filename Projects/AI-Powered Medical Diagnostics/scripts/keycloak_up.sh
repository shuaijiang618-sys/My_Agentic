#!/usr/bin/env bash
# 启动本地 Keycloak（realm medical 自动导入）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KC_DIR="$ROOT/docker/keycloak"
cd "$KC_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "需要 Docker。请安装 Docker Desktop 后重试。" >&2
  exit 1
fi

echo "▶ 启动 Keycloak (realm=medical, port=8080)..."
docker compose up -d

echo "⏳ 等待 Keycloak 就绪..."
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:8080/realms/medical/.well-known/openid-configuration" >/dev/null 2>&1; then
    echo "✓ Keycloak 已就绪"
    echo ""
    echo "  Admin Console : http://localhost:8080/admin  (admin / admin)"
    echo "  Realm         : medical"
    echo "  OIDC Discovery: http://localhost:8080/realms/medical/.well-known/openid-configuration"
    echo ""
    echo "  测试账号:"
    echo "    doctor  / doctor123   → md-chat"
    echo "    kbadmin / kbadmin123  → md-admin"
    echo "    viewer  / viewer123   → md-readonly"
    echo ""
    echo "  下一步:"
    echo "    1. cat docker/keycloak/.env.example >> .env   # 或手动合并 AUTH_* 变量"
    echo "    2. ./scripts/start.sh"
    echo "    3. ./scripts/keycloak_smoke.sh"
    exit 0
  fi
  sleep 2
done

echo "Keycloak 启动超时。查看日志: docker compose -f docker/keycloak/docker-compose.yml logs" >&2
exit 1
