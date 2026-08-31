#!/usr/bin/env bash
# 回填 shared tenant + 导入 data/medical_knowledge（含 ALT.md）到 hospital_a
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then PYTHON=python3; fi
exec "$PYTHON" scripts/backfill_kb_tenant_shared.py "$@"
