#!/usr/bin/env bash
# TCM Diagnostics — 依赖 CVE + Python 代码安全扫描（SKILL §6.5）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> pip-audit (dependencies)"
if command -v pip-audit >/dev/null 2>&1; then
  pip-audit -r requirements.txt
else
  echo "WARN: pip-audit not installed — pip install pip-audit"
  exit 1
fi

echo "==> bandit (backend + main agent)"
if command -v bandit >/dev/null 2>&1; then
  bandit -r backend/ new_zhongyi_agent.py -ll
else
  echo "WARN: bandit not installed — pip install bandit"
  exit 1
fi

echo "==> security_check OK"
