#!/usr/bin/env bash
# Block 8 · 停止后台服务
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="${ROOT}/backend/logs/server.pid"

if [[ ! -f "$PIDFILE" ]]; then
  echo "无 pid 文件，服务可能未通过 scripts/start.sh 启动"
  exit 0
fi

PID=$(cat "$PIDFILE")
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  rm -f "$PIDFILE"
  echo "✅ 已停止 pid=$PID"
else
  rm -f "$PIDFILE"
  echo "进程 $PID 不存在，已清理 pid 文件"
fi
