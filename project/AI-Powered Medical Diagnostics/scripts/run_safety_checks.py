#!/usr/bin/env python3
"""运行安全门禁回归测试（不调用 LLM）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.prompt_regression import run_prompt_engineering_suite
from evaluation.safety_runner import run_security_suite


def main() -> int:
    security_cases = run_security_suite()
    prompt_cases = run_prompt_engineering_suite()
    cases = security_cases + prompt_cases
    passed = sum(1 for c in cases if c.passed)
    report = {
        "total": len(cases),
        "passed": passed,
        "pass_rate": round(passed / len(cases), 4) if cases else 0.0,
        "all_passed": passed == len(cases),
        "suites": {
            "security": {
                "total": len(security_cases),
                "passed": sum(1 for c in security_cases if c.passed),
            },
            "prompt_engineering_v2": {
                "total": len(prompt_cases),
                "passed": sum(1 for c in prompt_cases if c.passed),
            },
        },
        "cases": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in cases],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_passed"]:
        failed = [c for c in report["cases"] if not c["passed"]]
        print(f"\n失败 {len(failed)} 项:", file=sys.stderr)
        for c in failed:
            print(f"  - {c['name']}: {c['detail']}", file=sys.stderr)
        return 1
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
