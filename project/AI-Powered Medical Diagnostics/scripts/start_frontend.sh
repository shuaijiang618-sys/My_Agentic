#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  echo "▶ npm install …"
  npm install
fi
if [[ -f .env ]]; then set -a; source .env; set +a; fi
echo "▶ http://localhost:5173  →  API ${VITE_API_URL:-/api → 8010}"
exec npm run dev
