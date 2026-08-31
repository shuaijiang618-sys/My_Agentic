#!/usr/bin/env python3
"""批量调用 /chat，输出可人工评分的 Markdown + JSON 报告。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.chat_sample_runner import load_chat_sample_cases, run_chat_sample_eval


def _chat_http(base_url: str, timeout: float):
    base = base_url.rstrip("/")

    def chat(message: str, user_id: str = "eval-bot") -> dict:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(
                f"{base}/chat",
                json={"message": message, "user_id": user_id},
            )
            r.raise_for_status()
            return r.json()

    return chat


def _render_markdown(report: dict, base_url: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Chat 采样评测报告",
        "",
        f"- 时间: {ts}",
        f"- 服务: `{base_url}`",
        f"- 通过: **{report['passed']}/{report['total']}** "
        f"({report['pass_rate']:.0%})",
        "",
        "> 自动校验仅覆盖 `expect` 中声明的字段；医学内容是否正确需人工阅读 `full_response` 与 `sources`。",
        "",
    ]

    for i, case in enumerate(report["cases"], start=1):
        status = "PASS" if case["passed"] else "FAIL"
        lines.extend([
            f"## {i}. [{status}] {case['name']}",
            "",
            f"**问题**: {case['message']}",
            "",
            f"| 字段 | 值 |",
            f"|------|-----|",
            f"| blocked | {case.get('blocked')} |",
            f"| emergency | {case.get('emergency')} |",
            f"| safety_passed | {case.get('safety_passed')} |",
            f"| knowledge_used | {case.get('knowledge_used')} |",
            f"| intent | {case.get('intent')} |",
            f"| agent_type | {case.get('agent_type')} |",
            f"| source_count | {case.get('source_count')} |",
            f"| latency_ms | {case.get('latency_ms')} |",
            f"| request_id | `{case.get('request_id')}` |",
            "",
        ])
        if case.get("checks"):
            lines.append("**自动检查**:")
            for c in case["checks"]:
                lines.append(f"- {c}")
            lines.append("")

        if case.get("sources"):
            lines.append("**引用 sources**:")
            for j, src in enumerate(case["sources"][:3], start=1):
                title = src.get("title", "")
                score = src.get("score", "")
                snippet = (src.get("content") or "")[:120]
                lines.append(f"{j}. `{title}` (score={score}) — {snippet}…")
            lines.append("")

        lines.extend([
            "**回答**",
            "",
            "```",
            (case.get("full_response") or case.get("response_preview") or "(空)").strip(),
            "```",
            "",
            "---",
            "",
        ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="批量 /chat 采样评测")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8010",
        help="Medical API 地址",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "logs" / "eval",
        help="报告输出目录",
    )
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    try:
        httpx.get(f"{args.base_url.rstrip('/')}/health", timeout=5.0).raise_for_status()
    except Exception as ex:
        print(f"无法连接 {args.base_url}/health — 请先 ./scripts/start.sh\n  {ex}", file=sys.stderr)
        return 2

    cases = load_chat_sample_cases(args.cases)
    if not cases:
        print("无评测用例", file=sys.stderr)
        return 1

    chat_fn = _chat_http(args.base_url, args.timeout)
    report = run_chat_sample_eval(chat_fn, cases=cases)
    report["base_url"] = args.base_url

    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["all_passed"] else 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = args.output_dir / f"chat_eval_{stamp}.json"
    md_path = args.output_dir / f"chat_eval_{stamp}.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report, args.base_url), encoding="utf-8")

    print(json.dumps({
        "total": report["total"],
        "passed": report["passed"],
        "pass_rate": report["pass_rate"],
        "json": str(json_path),
        "markdown": str(md_path),
    }, ensure_ascii=False, indent=2))

    failed = [c for c in report["cases"] if not c["passed"]]
    if failed:
        print(f"\n未通过 {len(failed)} 项:", file=sys.stderr)
        for c in failed:
            print(f"  - {c['name']}: {', '.join(c['checks'][:2])}", file=sys.stderr)
        return 1

    print("\n全部通过自动检查 ✓ — 请仍阅读 Markdown 做人工医学质量评审")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
