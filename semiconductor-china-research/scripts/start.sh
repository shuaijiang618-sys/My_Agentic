#!/usr/bin/env bash
# Block 8 · 启动服务（后台 + 日志重定向到 backend/logs/server.log）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "❌ 缺少 .env —— 请先: cp .env.example .env 并填入 DEEPSEEK_API_KEY"
  exit 1
fi

# shellcheck disable=SC1091
set -a && source .env && set +a
PORT="${PORT:-8093}"
HOST="${HOST:-127.0.0.1}"

VENV="${ROOT}/.venv/bin/python"
if [[ ! -x "$VENV" ]]; then
  echo "❌ 未找到 .venv —— 请先: python3.12 -m venv .venv && pip install -r requirements.txt"
  exit 1
fi

mkdir -p backend/logs
LOG="${ROOT}/backend/logs/server.log"
PIDFILE="${ROOT}/backend/logs/server.pid"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "⚠️  服务已在运行 (pid=$(cat "$PIDFILE")) · http://${HOST}:${PORT}"
  exit 0
fi

nohup "$VENV" -m uvicorn backend.app:app --host "$HOST" --port "$PORT" \
  >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"

# 等待 health 就绪（最多 10s）
HEALTH_URL="http://${HOST}:${PORT}/api/health"
for _ in $(seq 1 20); do
  if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
    echo "✅ 已启动 pid=$(cat "$PIDFILE")"
    echo "   前端: http://${HOST}:${PORT}"
    echo "   健康: $HEALTH_URL"
    echo "   日志: backend/logs/server.log"
    echo "   停止: ./scripts/stop.sh"
    exit 0
  fi
  sleep 0.5
done

if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "⚠️  进程已启动但 health 未就绪，请查看 backend/logs/server.log"
  exit 0
else
  echo "❌ 启动失败，查看 backend/logs/server.log"
  tail -20 "$LOG"
  exit 1
fi
