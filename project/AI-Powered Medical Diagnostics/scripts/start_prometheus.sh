#!/usr/bin/env bash
# 本地启动 Prometheus + Alertmanager（需 Docker）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROM_DIR="$ROOT/prometheus"

if ! command -v docker >/dev/null 2>&1; then
  echo "需要 Docker。请安装后重试，或手动加载 $PROM_DIR/prometheus.yml"
  exit 1
fi

"$ROOT/scripts/render_alertmanager.sh"
ALERTMANAGER_CFG="$PROM_DIR/alertmanager.generated.yml"

docker network inspect medical-prom >/dev/null 2>&1 || docker network create medical-prom >/dev/null

echo "启动 Alertmanager → http://127.0.0.1:9093"
docker rm -f medical-alertmanager >/dev/null 2>&1 || true
docker run -d --name medical-alertmanager --network medical-prom \
  -p 9093:9093 \
  -v "$ALERTMANAGER_CFG:/etc/alertmanager/alertmanager.yml:ro" \
  prom/alertmanager:latest \
  --config.file=/etc/alertmanager/alertmanager.yml \
  --web.listen-address=:9093

echo "启动 Prometheus → http://127.0.0.1:9090"
docker rm -f medical-prometheus >/dev/null 2>&1 || true
docker run -d --name medical-prometheus --network medical-prom \
  -p 9090:9090 \
  -v "$PROM_DIR:/etc/prometheus:ro" \
  --add-host=host.docker.internal:host-gateway \
  prom/prometheus:latest \
  --config.file=/etc/prometheus/prometheus.yml \
  --web.enable-lifecycle

echo "完成。请确保 Medical API 已在 host 上监听 8010（./scripts/start.sh）"
echo "Mac/Windows 下 Prometheus 通过 host.docker.internal:8010 抓取；"
echo "若抓取失败，将 prometheus.yml 中 target 改为 host.docker.internal:8010"
