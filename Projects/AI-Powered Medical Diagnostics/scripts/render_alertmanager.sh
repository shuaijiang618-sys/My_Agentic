#!/usr/bin/env bash
# 从 .env 读取 SLACK_*，生成 prometheus/alertmanager.generated.yml（不提交 Git）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROM_DIR="$ROOT/prometheus"
TEMPLATE="$PROM_DIR/alertmanager.slack.yml.template"
LOCAL="$PROM_DIR/alertmanager.local.yml"
OUT="$PROM_DIR/alertmanager.generated.yml"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
SLACK_CHANNEL="${SLACK_CHANNEL:-#medical-alerts}"

if [[ -n "$SLACK_WEBHOOK_URL" ]]; then
  python3 - "$TEMPLATE" "$OUT" "$SLACK_WEBHOOK_URL" "$SLACK_CHANNEL" <<'PY'
import sys
from pathlib import Path

template_path, out_path, webhook_url, channel = sys.argv[1:5]
text = Path(template_path).read_text(encoding="utf-8")
text = text.replace("__SLACK_WEBHOOK_URL__", webhook_url)
text = text.replace("__SLACK_CHANNEL__", channel)
Path(out_path).write_text(text, encoding="utf-8")
PY
  echo "Alertmanager 已渲染（Slack → ${SLACK_CHANNEL}）"
else
  cp "$LOCAL" "$OUT"
  echo "Alertmanager 已渲染（未设置 SLACK_WEBHOOK_URL，仅本地 UI）"
fi
