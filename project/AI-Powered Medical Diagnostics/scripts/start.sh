#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then PYTHON=python; fi

# JWT 鉴权依赖 PyJWT（requirements.txt 已声明，旧 venv 可能未安装）
if [[ "${AUTH_ENABLED:-false}" == "true" ]] && {
  [[ "${AUTH_JWT_ENABLED:-false}" == "true" ]] || [[ -n "${AUTH_JWT_JWKS_URL:-}" ]] || [[ -n "${AUTH_JWT_SECRET:-}" ]];
}; then
  if ! "$PYTHON" -c "import jwt" 2>/dev/null; then
    echo "▶ 安装 JWT 依赖 PyJWT ..."
    "$PYTHON" -m pip install -q 'PyJWT[crypto]==2.10.1'
  fi
fi

exec "$PYTHON" -m uvicorn api.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8010}"
