#!/usr/bin/env bash
# Block 9 · 在线验收：对运行中服务发 SSE 请求，校验 5 功能用例结构
# 兼容 macOS 自带 bash 3.2（不用 declare -A）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "❌ 缺少 .env"
  exit 1
fi
# shellcheck disable=SC1091
set -a && source .env && set +a

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8093}"
BASE="http://${HOST}:${PORT}"

CASE=""
SESSION=""
TIMEOUT=600

while [[ $# -gt 0 ]]; do
  case "$1" in
    --case) CASE="$2"; shift 2 ;;
    --session) SESSION="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "用法: $0 [--case 1|2|3|4|5] [--session id] [--timeout sec]"; exit 1 ;;
  esac
done

query_for_case() {
  case "$1" in
    1) echo "中国半导体发展现状" ;;
    2) echo "大基金三期投向" ;;
    3) echo "北方华创估值贵不贵" ;;
    4) echo "EDA 国产化" ;;
    5) echo "中国半导体设备国产化现状" ;;
    *) echo "" ;;
  esac
}

default_session_for_case() {
  case "$1" in
    1) echo "accept-u1" ;;
    2) echo "accept-u2" ;;
    3) echo "accept-u3" ;;
    4) echo "accept-u4" ;;
    5) echo "accept-u5" ;;
    *) echo "accept-u0" ;;
  esac
}

required_for_case() {
  case "$1" in
    2) echo "investment_expert,policy_expert" ;;
    3) echo "investment_expert" ;;
    4) echo "design_ip_expert,policy_expert" ;;
    5) echo "investment_expert,competitor_expert" ;;
    *) echo "" ;;
  esac
}

run_sse() {
  local query="$1" session="$2" label="$3" required="$4"
  local encoded
  encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''${query}'''))")
  local url="${BASE}/api/run?query=${encoded}&session=${session}"
  echo ""
  echo ">>> ${label}: ${query} (session=${session})"
  local out="/tmp/scr-accept-${session}-$$.sse"
  curl -sS -N --max-time "$TIMEOUT" "$url" > "$out" || true

  REQUIRED="$required" QUERY="$query" OUT="$out" python3 << 'PY'
import json, os, re, sys
path = os.environ["OUT"]
required = [x for x in os.environ.get("REQUIRED", "").split(",") if x]
query = os.environ.get("QUERY", "")
text = open(path, encoding="utf-8", errors="replace").read()
events = []
for block in re.split(r"\n\n", text.strip()):
    if not block.strip():
        continue
    ev, d = None, {}
    for line in block.split("\n"):
        if line.startswith("event:"):
            ev = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            d = json.loads(line.split(":", 1)[1].strip())
    if ev:
        events.append((ev, d))

names = [d.get("name") for ev, d in events if ev == "tool_call"]
ts = [d.get("t") for ev, d in events if ev == "tool_call" if d.get("t") is not None]
parallel_ok = len(ts) >= 2 and (max(ts) - min(ts) < 30000) if len(ts) >= 2 else len(ts) <= 1

final = next((d for ev, d in events if ev == "final"), None)
err = next((d for ev, d in events if ev == "error"), None)
brief = (final or {}).get("brief", "") if final else ""

print(f"   events: {len(events)} | tool_calls: {len(names)} | experts: {sorted(set(n for n in names if n))}")
if err:
    print(f"   ❌ error: {err.get('message','')[:200]}")
    sys.exit(1)
if not final:
    print("   ❌ 无 final 事件")
    sys.exit(1)

checks = [("final", True), ("参考来源", "## 📎 参考来源" in brief or "参考来源" in brief), ("parallel_ok", parallel_ok)]
for t in required:
    checks.append((f"含 {t}", t in names))
if any(k in query for k in ("估值", "贵不贵", "股价", "PE", "大基金")):
    checks.append(("免责", "不构成投资建议" in brief))

failed = False
for label, ok in checks:
    print(f"   {'✅' if ok else '⚠️ '} {label}")
    if not ok and label.startswith("含 "):
        failed = True
    if not ok and label in ("final", "免责"):
        failed = True

if failed:
    sys.exit(2)
PY
}

if ! curl -sf "${BASE}/api/health" >/dev/null; then
  echo "❌ 服务未启动 —— 请先 ./scripts/start.sh"
  exit 1
fi

echo "=== Block 9 · 在线验收 (base=${BASE}) ==="

if [[ -n "$CASE" ]]; then
  cases="$CASE"
else
  cases="1 2 3 4 5"
fi

for c in $cases; do
  sess="${SESSION:-$(default_session_for_case "$c")}"
  if [[ "$c" == "5" ]]; then
    run_sse "$(query_for_case 5)" "$sess" "用例5·轮1" ""
    run_sse "刚才设备公司谁上市了" "$sess" "用例5·轮2" "$(required_for_case 5)"
  else
    run_sse "$(query_for_case "$c")" "$sess" "用例${c}" "$(required_for_case "$c")"
  fi
done

echo ""
echo "✅ 在线验收结构检查通过（内容质量需人工复核，见 docs/acceptance.md）"
