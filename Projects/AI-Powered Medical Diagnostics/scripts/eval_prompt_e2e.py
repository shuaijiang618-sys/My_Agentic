#!/usr/bin/env python3
"""工程化 Prompt 端到端回归：mock（无 API）或 live（真实 LLM）。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

from evaluation.prompt_e2e_runner import (
    load_prompt_e2e_cases,
    run_inprocess_prompt_e2e,
    run_prompt_e2e_http,
)


def _has_llm_key() -> bool:
    return bool(
        os.getenv("DEEPSEEK_API_KEY", "").strip()
        or os.getenv("ANTHROPIC_API_KEY", "").strip()
    )


def _chat_http(base_url: str, timeout: float):
    base = base_url.rstrip("/")

    def chat(message: str, user_id: str = "prompt-e2e") -> dict:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(
                f"{base}/chat",
                json={"message": message, "user_id": user_id},
            )
            r.raise_for_status()
            data = r.json()
            return {
                "response": data.get("response"),
                "blocked": data.get("blocked"),
                "emergency": data.get("emergency"),
                "agent_type": data.get("agent_type"),
                "knowledge_used": data.get("knowledge_used"),
                "intent": data.get("intent"),
                "sources": data.get("sources"),
            }

    return chat


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 工程化 E2E 回归")
    parser.add_argument(
        "--mode",
        choices=("auto", "mock", "live", "http"),
        default="auto",
        help="mock=无 LLM；live=进程内真实 LLM；http=调用 /chat",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "logs" / "eval")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    cases, fixture_doc = load_prompt_e2e_cases(args.cases)
    if not cases:
        print("无 E2E 用例", file=sys.stderr)
        return 1

    mode = args.mode
    if mode == "auto":
        mode = "live" if _has_llm_key() else "mock"

    if mode == "http":
        try:
            httpx.get(f"{args.base_url.rstrip('/')}/health", timeout=5.0).raise_for_status()
        except Exception as ex:
            print(f"无法连接 {args.base_url}/health — 请先启动服务\n  {ex}", file=sys.stderr)
            return 2
        report = run_prompt_e2e_http(_chat_http(args.base_url, args.timeout), cases=cases)
    elif mode == "mock":
        report = asyncio.run(
            run_inprocess_prompt_e2e(mock_llm=True, cases=cases, fixture_doc=fixture_doc)
        )
    else:
        if not _has_llm_key():
            print("live 模式需要 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY", file=sys.stderr)
            return 2
        report = asyncio.run(
            run_inprocess_prompt_e2e(mock_llm=False, cases=cases, fixture_doc=fixture_doc)
        )

    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["all_passed"] else 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = args.output_dir / f"prompt_e2e_{report['mode']}_{stamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "mode": report["mode"],
        "total": report["total"],
        "passed": report["passed"],
        "pass_rate": report["pass_rate"],
        "json": str(json_path),
    }, ensure_ascii=False, indent=2))

    failed = [c for c in report["cases"] if not c["passed"]]
    if failed:
        print(f"\n未通过 {len(failed)} 项:", file=sys.stderr)
        for c in failed:
            print(f"  - {c['name']}: {', '.join(c['checks'][:3])}", file=sys.stderr)
        return 1

    print(f"\n全部通过 ✓（mode={report['mode']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
